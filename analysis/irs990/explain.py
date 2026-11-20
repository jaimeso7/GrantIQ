"""Show exactly how each relevant grant earned its score, from the last report run.

    ./.venv/bin/python analysis/irs990/explain.py [--threshold 0.45] [--ein 123456789]

Each grant's score is its similarity (0-1) to the closest of the focus phrases in
match.VIP_FOCUS; the phrase is printed beside it, so you can see which part of
Vision Is Priceless's work the grant resembles. Shared words are context only and
do not change the score. A CSV of every scored grant is written to
analysis/irs990_scoring.csv for sorting and filtering in a spreadsheet.

Reads analysis/irs990_prospects.json; run report.py first.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "analysis" / "irs990_prospects.json"
CSV_OUTPUT = ROOT / "analysis" / "irs990_scoring.csv"
RULE = "-" * 108


def main() -> None:
    data = json.loads(SOURCE.read_text())
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--threshold", type=float, default=data["relevance_threshold"])
    parser.add_argument("--ein", help="explain one foundation, every grant regardless of threshold")
    args = parser.parse_args()

    rows = []
    for prospect in data["prospects"]:
        if args.ein and prospect["ein"].zfill(9) != args.ein.replace("-", "").zfill(9):
            continue
        for gift in prospect["gifts"]:
            rows.append({"ein": prospect["ein"], "foundation": prospect["name"], **{
                key: gift.get(key, "") for key in ("score", "focus", "recipient", "purpose", "amount", "status")},
                "to_vip": gift.get("to_us", False), "shared": " ".join(gift.get("shared_subjects", []))})

    print(f"\nScores are similarity to the closest of {len(data.get('focus_phrases', []))} focus phrases "
          f"(method: {data.get('method', 'unknown')}).")
    shown = rows if args.ein else [r for r in rows if r["score"] >= args.threshold]
    current = None
    for row in sorted(shown, key=lambda r: (r["foundation"], -r["score"])):
        if row["foundation"] != current:
            current = row["foundation"]
            print(f"{RULE}\n{current}  (EIN {row['ein']})")
        amount = f"${row['amount']:,.0f}" if row["amount"] else "-"
        print(f"  {row['score']:.2f}  {amount:>10}  {row['recipient'][:30]} - {row['purpose'][:36]}"
              f"{'  [VIP]' if row['to_vip'] else ''}\n        closest VIP focus: {row['focus']}")
    print(f"{RULE}\n  {len(shown)} grants from {len({r['ein'] for r in shown})} foundations")
    if rows:
        with CSV_OUTPUT.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda r: -r["score"]))
        print(f"  All {len(rows):,} scored grants written to {CSV_OUTPUT.relative_to(ROOT)}\n")


if __name__ == "__main__":
    main()
