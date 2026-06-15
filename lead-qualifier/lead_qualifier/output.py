"""Output stage — enriched spreadsheets, brief files, and run summary.

Produces TWO separate spreadsheets per the user's spec:
  * qualified_leads.csv   — qualified companies + brief path + email subject
  * unqualified_leads.csv — disqualified companies + reason

Plus one markdown brief per qualified company in output/briefs/, and a
machine- + human-readable run summary.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from .models import CompanyRecord
from .utils.logger import get_logger

log = get_logger("output")

# Stable column order — same every run.
COLUMNS = [
    "domain", "company_name", "industry", "current_openings", "functions_hiring",
    "ats", "careers_url", "fit_score", "decision", "rationale",
    "email_subject", "brief_path", "errors",
]


def _safe_slug(domain: str) -> str:
    return re.sub(r"[^a-z0-9.-]", "_", domain.lower())


class OutputWriter:
    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)
        self.briefs_dir = self.out_dir / "briefs"
        self.briefs_dir.mkdir(parents=True, exist_ok=True)

    def write_brief(self, record: CompanyRecord) -> str | None:
        if not (record.brief and record.brief.markdown):
            return None
        path = self.briefs_dir / f"{_safe_slug(record.domain)}.md"
        path.write_text(record.brief.markdown, encoding="utf-8")
        record.brief.brief_path = str(path)
        log.info(f"[{record.domain}] brief → {path}")
        return str(path)

    def write_spreadsheets(self, records: list[CompanyRecord]) -> dict[str, str]:
        rows = [r.to_result_dict() for r in records]
        df = pd.DataFrame(rows, columns=COLUMNS)

        qualified = df[df["decision"] == "QUALIFIED"].copy()
        unqualified = df[df["decision"] != "QUALIFIED"].copy()

        q_path = self.out_dir / "qualified_leads.csv"
        u_path = self.out_dir / "unqualified_leads.csv"
        all_path = self.out_dir / "all_results.csv"

        qualified.to_csv(q_path, index=False)
        unqualified.to_csv(u_path, index=False)
        df.to_csv(all_path, index=False)

        log.info(f"Wrote {len(qualified)} qualified → {q_path}")
        log.info(f"Wrote {len(unqualified)} unqualified → {u_path}")
        return {
            "qualified": str(q_path),
            "unqualified": str(u_path),
            "all": str(all_path),
        }

    def write_summary(self, records: list[CompanyRecord], meta: dict) -> str:
        qualified = [r for r in records if r.qual and r.qual.qualified]
        disqualified = [r for r in records if r.qual and not r.qual.qualified]
        errored = [r for r in records if r.errors]
        no_careers = [
            r for r in records
            if r.hiring and not r.hiring.found_careers
        ]

        summary = {
            "run_at": datetime.utcnow().isoformat() + "Z",
            "total_companies": len(records),
            "qualified": len(qualified),
            "disqualified": len(disqualified),
            "errored": len(errored),
            "no_careers_page": len(no_careers),
            "no_careers_domains": [r.domain for r in no_careers],
            "errored_domains": {r.domain: r.errors for r in errored},
            **meta,
        }

        json_path = self.out_dir / "run_summary.json"
        json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        # Human-readable version.
        md = [
            "# Run Summary",
            f"- **When:** {summary['run_at']}",
            f"- **Total companies:** {summary['total_companies']}",
            f"- **Qualified:** {summary['qualified']}",
            f"- **Disqualified:** {summary['disqualified']}",
            f"- **Errored:** {summary['errored']}",
            f"- **No careers page found:** {summary['no_careers_page']}",
        ]
        if no_careers:
            md.append("\n## Companies with no careers page")
            md += [f"- {r.domain}" for r in no_careers]
        if errored:
            md.append("\n## Companies with errors")
            md += [f"- {r.domain}: {'; '.join(r.errors)}" for r in errored]
        (self.out_dir / "run_summary.md").write_text("\n".join(md), encoding="utf-8")

        log.info(f"Run summary → {json_path}")
        return str(json_path)
