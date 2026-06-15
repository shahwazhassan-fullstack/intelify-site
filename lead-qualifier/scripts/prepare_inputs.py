"""Build leads.csv and offer.md from workflow form inputs (passed as env vars).

Used by .github/workflows/lead-qualifier.yml so the GitHub Actions
"Run workflow" form acts as an input dashboard for the lead qualifier:
the operator types companies + an offer, this turns them into the CSV and
markdown files the CLI expects.

Env vars:
  COMPANIES  comma/newline-separated domains; an entry may be "Name|domain".
  OFFER      free-text offer description; if blank, a committed offer.md is used.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path


def parse_companies(raw: str) -> list[tuple[str, str]]:
    """Split the free-form companies box into (name, domain) rows."""
    tokens = [t.strip() for line in raw.splitlines() for t in line.split(",")]
    rows: list[tuple[str, str]] = []
    for token in tokens:
        if not token:
            continue
        if "|" in token:
            name, domain = token.split("|", 1)
        else:
            name, domain = "", token
        rows.append((name.strip(), domain.strip()))
    return rows


def main() -> int:
    rows = parse_companies(os.environ.get("COMPANIES", ""))
    if not rows:
        print("ERROR: No companies provided — enter at least one domain.", file=sys.stderr)
        return 1

    with open("leads.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["company_name", "domain"])
        writer.writerows(rows)
    print(f"Wrote leads.csv ({len(rows)} compan{'y' if len(rows) == 1 else 'ies'}).")

    offer = os.environ.get("OFFER", "").strip()
    if offer:
        Path("offer.md").write_text(offer + "\n", encoding="utf-8")
        print("Wrote offer.md from the form input.")
    elif Path("offer.md").exists():
        print("Using committed lead-qualifier/offer.md.")
    else:
        print(
            "ERROR: No offer text provided and lead-qualifier/offer.md not found.\n"
            "       Type your offer in the form, or commit lead-qualifier/offer.md.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
