"""Data models shared across the pipeline.

Plain dataclasses (no pydantic dependency) keep the schema explicit and
serialisable. Every stage of the pipeline consumes and produces these.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


# ──────────────────────────────────────────────────────────────────────────
# Ingest
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class CompanyRow:
    """A single validated input row from the leads file."""

    domain: str                      # normalised bare domain, e.g. "acme.com"
    company_name: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)  # original row, for debugging

    @property
    def website(self) -> str:
        return f"https://{self.domain}"


# ──────────────────────────────────────────────────────────────────────────
# Company research
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class CompanySummary:
    """Result of Step 1 — what the company does."""

    domain: str
    summary: str = ""                # 1–3 paragraph plain-language description
    industry: str = ""
    products_services: list[str] = field(default_factory=list)
    size_stage_signals: str = ""     # e.g. "Series B, ~120 employees (LinkedIn count on site)"
    pages_read: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────
# Hiring signals
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class JobOpening:
    """A single normalised job posting."""

    title: str
    function: str = "Other"          # Engineering, Sales, Marketing, Ops, ...
    location: str = ""
    seniority: str = ""              # Junior / Mid / Senior / Lead / Exec / ""
    posted_date: Optional[str] = None  # ISO date string if available
    url: str = ""


@dataclass
class HiringSignals:
    """Result of Step 2 — current openings + trend."""

    domain: str
    careers_url: Optional[str] = None
    ats: Optional[str] = None        # detected ATS name, e.g. "greenhouse"
    openings: list[JobOpening] = field(default_factory=list)
    by_function: dict[str, int] = field(default_factory=dict)  # {"Sales": 4, ...}
    total_open: int = 0
    history_summary: str = ""        # human text describing ~6-mo momentum
    trend: str = "unknown"           # growing / steady / shrinking / unknown / new
    error: Optional[str] = None

    @property
    def found_careers(self) -> bool:
        return self.careers_url is not None


# ──────────────────────────────────────────────────────────────────────────
# Qualification
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class QualResult:
    """Result of Step 3 — fit decision."""

    domain: str
    score: int = 0                   # 1–10
    qualified: bool = False
    rationale: str = ""              # references hiring signals explicitly
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────
# Assembly
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Brief:
    """Result of Step 4 — outreach-ready brief + email."""

    domain: str
    markdown: str = ""               # full research brief
    outreach_hooks: list[str] = field(default_factory=list)
    email_subject: str = ""
    email_body: str = ""             # AIDA-structured cold email
    brief_path: Optional[str] = None  # filled in by output stage
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────
# Per-company aggregate (what flows through the orchestrator)
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class CompanyRecord:
    """Everything we know about one company after a full run."""

    row: CompanyRow
    summary: Optional[CompanySummary] = None
    hiring: Optional[HiringSignals] = None
    qual: Optional[QualResult] = None
    brief: Optional[Brief] = None
    processed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    errors: list[str] = field(default_factory=list)

    @property
    def domain(self) -> str:
        return self.row.domain

    def to_result_dict(self) -> dict[str, Any]:
        """Flatten to a stable, documented spreadsheet schema."""
        functions = ""
        total_open = 0
        careers = ""
        ats = ""
        if self.hiring:
            functions = ", ".join(
                f"{fn}({n})" for fn, n in sorted(
                    self.hiring.by_function.items(), key=lambda kv: -kv[1]
                )
            )
            total_open = self.hiring.total_open
            careers = self.hiring.careers_url or ""
            ats = self.hiring.ats or ""
        return {
            "domain": self.domain,
            "company_name": self.row.company_name or "",
            "industry": self.summary.industry if self.summary else "",
            "current_openings": total_open,
            "functions_hiring": functions,
            "ats": ats,
            "careers_url": careers,
            "fit_score": self.qual.score if self.qual else "",
            "decision": (
                ("QUALIFIED" if self.qual.qualified else "DISQUALIFIED")
                if self.qual else "ERROR"
            ),
            "rationale": self.qual.rationale if self.qual else "",
            "email_subject": self.brief.email_subject if self.brief else "",
            "brief_path": self.brief.brief_path if (self.brief and self.brief.brief_path) else "",
            "errors": "; ".join(self.errors),
        }


def dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses to plain dicts (for JSON / cache)."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: dataclass_to_dict(v) for k, v in asdict(obj).items()}
    return obj
