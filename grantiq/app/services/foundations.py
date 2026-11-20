"""Load 990-PF foundation prospects produced by analysis/irs990/report.py.

The research pipeline is offline and slow (it downloads IRS archives and runs the
embedding model over thousands of grant purposes), so the app does not run it.
It reads the JSON the pipeline writes and mirrors it into foundation_prospects.
Each import replaces the previous one: the filing is the source of truth. The
table is therefore a pure mirror of the file, and is rebuilt when a new version
of GrantIQ adds columns to it (SQLite cannot add them to an existing table).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from sqlalchemy import delete, inspect, select
from sqlalchemy.orm import Session

from ..config import ROOT
from ..models import FoundationProspect, ResearchImport

IMPORT_PREFIX = "irs990:"
RELEVANT_AT = 0.45  # default; each import uses the threshold the pipeline wrote


def prospects_file() -> Path:
    return Path(os.getenv("GRANTIQ_IRS990_FILE", str(ROOT / "analysis" / "irs990_prospects.json")))


def import_prospects(session: Session, path: Path) -> int:
    """Replace all foundation prospects with the contents of one pipeline run."""
    data = json.loads(path.read_text(encoding="utf-8"))
    year = int(data["year"])
    _rebuild_if_outdated(session)
    session.execute(delete(FoundationProspect))
    for item in data["prospects"]:
        best = item.get("best_match") or {}
        session.add(FoundationProspect(
            ein=str(item["ein"]).zfill(9), name=item["name"], city=item.get("city") or "",
            assets=item.get("assets") or 0, total_paid=item.get("total_paid") or 0,
            paid_count=item.get("paid_count") or 0, relevant_total=item.get("relevant_total") or 0,
            relevant_count=item.get("relevant_count") or 0, best_score=best.get("score") or 0,
            already_funder=bool(item.get("already_funder")), known_as=item.get("known_as") or "",
            funded_us=bool(item.get("funded_us")), filing_year=year,
            received=item.get("received") or [], received_total=item.get("received_total") or 0,
            grants_in_attachment=bool(item.get("grants_in_attachment")),
            tier=item.get("tier") or 1, nefl_count=item.get("nefl_count") or 0,
            nefl_total=item.get("nefl_total") or 0, declined=item.get("declined") or "",
            tax_period=item.get("tax_period") or "", object_id=item.get("object_id") or "",
            gifts=item.get("gifts") or ([best] if best else []),
        ))
    session.execute(delete(ResearchImport).where(ResearchImport.id.startswith(IMPORT_PREFIX)))
    session.add(ResearchImport(id=f"{IMPORT_PREFIX}{path.stat().st_mtime_ns}"))
    session.commit()
    return len(data["prospects"])


def _rebuild_if_outdated(session: Session) -> None:
    table = FoundationProspect.__table__
    have = {column["name"] for column in inspect(session.connection()).get_columns(table.name)}
    if not {column.name for column in table.columns} <= have:
        table.drop(session.connection())
        table.create(session.connection())


def method_note(path: Path | None = None) -> dict:
    """The threshold and focus phrases of the pipeline run that produced the data."""
    path = path or prospects_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"threshold": RELEVANT_AT, "focus_phrases": [], "method": ""}
    return {"threshold": data.get("relevance_threshold", RELEVANT_AT),
            "focus_phrases": data.get("focus_phrases", []), "method": data.get("method", "")}


def sync_prospects(session: Session, path: Path | None = None) -> int | None:
    """Import only when the pipeline has written a file this database has not seen."""
    path = path or prospects_file()
    if not path.is_file():
        return None
    if session.get(ResearchImport, f"{IMPORT_PREFIX}{path.stat().st_mtime_ns}"):
        return None
    return import_prospects(session, path)


def last_import(session: Session):
    row = session.scalar(select(ResearchImport).where(ResearchImport.id.startswith(IMPORT_PREFIX)))
    return row.imported_at if row else None


def filter_prospects(session: Session, filters: dict) -> list[FoundationProspect]:
    try:
        min_score = float(filters.get("min_score") or 0) / 100
        min_assets = float(filters.get("amount_min") or 0)
    except ValueError:
        min_score, min_assets = 0, 0
    terms = re.findall(r"\w+", filters.get("q", "").casefold())
    relationship = filters.get("relationship", "")
    result = []
    for row in session.scalars(select(FoundationProspect)):
        if row.best_score < min_score or row.assets < min_assets:
            continue
        if filters.get("city") and row.city != filters["city"]:
            continue
        if filters.get("area") == "local" and row.tier != 1:
            continue
        if filters.get("area") == "florida" and row.tier != 2:
            continue
        if relationship == "new" and (row.already_funder or row.funded_us or row.declined):
            continue
        if relationship == "declined" and not row.declined:
            continue
        if relationship == "known" and not (row.already_funder or row.funded_us):
            continue
        if relationship == "unscorable" and not row.grants_in_attachment:
            continue
        if relationship == "relevant" and not row.relevant_count:
            continue
        if terms:
            haystack = " ".join([row.name, row.city, *(f"{g.get('recipient', '')} {g.get('purpose', '')}" for g in row.gifts)]).casefold()
            if any(term not in haystack for term in terms):
                continue
        result.append(row)
    return sorted(result, key=lambda r: (-r.best_score, -r.relevant_total, r.name))


def main(argv: list[str] | None = None) -> int:
    """python -m grantiq.app.services.foundations [path] - import on demand."""
    import sys
    from ..database import SessionLocal, initialize
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else prospects_file()
    if not path.is_file():
        print(f"No 990 prospects file at {path}. Run analysis/irs990/report.py first.")
        return 1
    initialize()
    with SessionLocal() as session:
        count = import_prospects(session, path)
    print(f"Imported {count} foundation prospects from {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
