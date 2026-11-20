"""Step 7: run the whole pipeline and print who to call.

    ./.venv/bin/python analysis/irs990/report.py [year]

With no year, the previous and current index years are read and each
foundation's newest filing is used. The first run downloads roughly
2GB and takes a few minutes. Archives are cached under data/cache/irs990/ for
good; the directory and indexes are re-checked weekly, so a later run downloads
only archives the IRS has published since.

GrantIQ runs this monthly (see grantiq/app/services/irs990_schedule.py) and
imports the JSON it writes.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import grantiq.app.config  # noqa: F401,E402  - points the model cache at data/models

from irs990 import fetch, match, parse  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "analysis" / "irs990_prospects.json"
RULE = "-" * 108


def money(value: float | None) -> str:
    return f"${value:,.0f}" if value else "-"


def main() -> None:
    years = [int(sys.argv[1])] if len(sys.argv) > 1 else fetch.default_years()

    # Tier 1: foundations based in Northeast Florida. Tier 2: foundations based
    # elsewhere in Florida that already give to Northeast Florida recipients
    # (the Grant Watch document's statewide tier). Both start from every Florida
    # private foundation; tier 2 is narrowed in step 4, once grants are readable.
    print(f"\nSTEP 1  Find Florida private foundations")
    directory = fetch.local_foundations(zip_prefixes=None)
    local = {ein for ein, row in directory.items() if fetch.in_northeast_florida(row.get("ZIP", ""))}
    print(f"  {len(local):,} of them are based in Northeast Florida")

    print(f"\nSTEP 2  Find their filings ({', '.join(map(str, years))} indexes)")
    filings_index = fetch.filings_for(set(directory), years)
    if not filings_index:
        print("  No filings found. Nothing to do.")
        return

    print(f"\nSTEP 3  Download the archives holding those filings")
    archives, downloaded = fetch.ensure_archives(filings_index)

    print(f"\nSTEP 4  Read the grant lists")
    filings = parse.read_filings(archives, filings_index)
    statewide = len(filings)
    filings = [f for f in filings if fetch.normalize_ein(f.ein) in local
               or any(fetch.in_northeast_florida(g.zip) for g in f.gifts)]
    tier2 = sum(1 for f in filings if fetch.normalize_ein(f.ein) not in local)
    print(f"  kept {len(filings) - tier2:,} Northeast Florida foundations and {tier2:,} elsewhere in Florida "
          f"that gave to Northeast Florida recipients (of {statewide:,} Florida filings read)")
    gifts = sum(len(f.gifts) for f in filings)
    paid = sum(f.total_paid for f in filings)
    print(f"  {gifts:,} grant records, {money(paid)} paid in total")

    print(f"\nSTEP 5  Score each grant against Vision Is Priceless's focus areas")
    profile = match.load_profile()
    matches = match.score_gifts(filings, profile)

    print(f"\nSTEP 6  Flag funders already known")
    prospects = match.build_prospects(filings, directory, matches, local)
    known = [p for p in prospects if p.already_funder or p.funded_us]
    declined = [p for p in prospects if p.declined]
    fresh = [p for p in prospects if not (p.already_funder or p.funded_us or p.declined) and p.best]
    print(f"  {len(known)} known or past funders found in these filings")
    print(f"  {len(declined)} on the 'said no' list, kept out of new prospects: "
          + (", ".join(p.declined for p in declined) or "none"))

    print(f"\nSTEP 7  Report\n{RULE}")
    print("NEW PROSPECTS - foundations never approached, ranked by how closely their")
    print(f"giving matches the mission. 'Relevant' means a purpose scoring >= {match.RELEVANT_AT:.2f}.\n")
    print(f"  {'MATCH':>5}  {'FOUNDATION':<34}{'CITY':<14}{'ASSETS':>13}{'GAVE':>12}{'RELEVANT':>11}  BEST-MATCHING GRANT")
    for prospect in fresh[:25]:
        best = prospect.best
        label = f"{best.recipient[:30]} - {best.purpose[:40]}" if best else ""
        print(f"  {best.score:>5.2f}  {prospect.name[:32]:<34}{prospect.city[:12]:<14}"
              f"{money(prospect.assets):>13}{money(prospect.total_paid):>12}"
              f"{money(prospect.relevant_total):>11}  {label}")

    if known:
        print(f"\n{RULE}\nKNOWN FUNDERS - and where their OTHER giving would rank them among all "
              f"{len(prospects)} (gift to VIP hidden):\n")
        others = {p.ein: max((g.score for g in p.gifts if not g.to_us), default=0) for p in prospects}
        order = sorted(others, key=lambda e: -others[e])
        for prospect in known:
            note = " (grant list is in an attachment; not scorable)" if prospect.grants_in_attachment else ""
            print(f"  rank {order.index(prospect.ein) + 1:>3}  {prospect.name[:40]:<42}"
                  f"{money(sum(r['amount'] for r in prospect.received)):>10} received"
                  f"{'  · filing lists VIP' if prospect.funded_us else ''}{note}")

    OUTPUT.write_text(json.dumps({
        "year": max(int(row["YEAR"]) for row in filings_index.values()), "years": years,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "filings_indexed": len(filings_index), "filings_parsed": len(filings),
            "with_grants": sum(1 for f in filings if f.paid_count),
            "archives": len(archives), "archives_downloaded": downloaded,
            "new_prospects": len(fresh), "known_rediscovered": len(known), "declined": len(declined),
            "florida_filings_read": statewide, "elsewhere_in_florida": tier2,
        },
        "generated_for": profile.name,
        "foundations_in_directory": len(directory), "filings_parsed": len(filings),
        "relevance_threshold": match.RELEVANT_AT,
        "method": "closest of the VIP focus phrases (local MiniLM embeddings)",
        "focus_phrases": match.VIP_FOCUS,
        "prospects": [p.as_dict() for p in prospects],
    }, indent=2))
    print(f"\n{RULE}")
    print(f"  {len(fresh)} new prospects, {len(known)} existing funders rediscovered")
    print(f"  Full detail written to {OUTPUT.relative_to(ROOT)}")
    print(f"{RULE}\n")


if __name__ == "__main__":
    from filelock import FileLock, Timeout
    from grantiq.app.config import DATA_DIR
    try:
        # One run at a time, including one left running by a stopped GrantIQ server.
        with FileLock(str(DATA_DIR / "irs990-pipeline.lock"), timeout=0):
            main()
    except Timeout:
        sys.exit("Another IRS 990 refresh is already running; try again when it finishes.")
