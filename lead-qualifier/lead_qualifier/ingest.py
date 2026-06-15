"""Load + validate the leads file (CSV/XLSX) with forgiving column mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from .models import CompanyRow
from .utils.logger import get_logger

log = get_logger("ingest")

# Column aliases, matched case-insensitively after stripping non-alphanumerics.
DOMAIN_ALIASES = {
    "domain", "companydomain", "website", "websiteurl", "url", "companyurl",
    "site", "web", "homepage", "link", "companywebsite",
}
NAME_ALIASES = {
    "companyname", "company", "name", "organization", "organisation",
    "account", "accountname", "business",
}


@dataclass
class IngestReport:
    rows: list[CompanyRow]
    skipped: list[tuple[int, str]]      # (row index, reason)
    domain_column: str
    name_column: str | None

    @property
    def ok(self) -> bool:
        return len(self.rows) > 0


def _norm(col: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(col).lower())


def _pick_column(columns: list[str], aliases: set[str]) -> str | None:
    # Exact normalised alias match first.
    for col in columns:
        if _norm(col) in aliases:
            return col
    # Then substring (e.g. "Company Domain Name").
    for col in columns:
        n = _norm(col)
        if any(alias in n for alias in aliases):
            return col
    return None


_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,}$")


def normalize_domain(raw: str) -> str | None:
    """Normalise a domain or URL to a bare lowercase domain. None if invalid."""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().lower()
    if "@" in s and "/" not in s:           # looks like an email → take the host
        s = s.split("@", 1)[1]
    if "://" not in s:
        s = "https://" + s
    host = urlparse(s).netloc or urlparse(s).path
    host = host.split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not _DOMAIN_RE.match(host):
        return None
    return host


def load_leads(path: str | Path, *, limit: int | None = None) -> IngestReport:
    """Read a CSV/XLSX leads file into validated CompanyRow objects.

    Raises FileNotFoundError / ValueError for unrecoverable problems; per-row
    issues are collected into `skipped` rather than crashing.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Leads file not found: {p}")

    suffix = p.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(p, engine="openpyxl" if suffix == ".xlsx" else None, dtype=str)
    elif suffix == ".csv":
        df = pd.read_csv(p, dtype=str)
    else:
        raise ValueError(f"Unsupported file type {suffix!r}. Use .csv or .xlsx.")

    df = df.fillna("")
    columns = list(df.columns)
    domain_col = _pick_column(columns, DOMAIN_ALIASES)
    name_col = _pick_column(columns, NAME_ALIASES)

    if domain_col is None:
        raise ValueError(
            "Could not find a domain/website column. Expected one of "
            f"(case-insensitive): {sorted(DOMAIN_ALIASES)}. Found columns: {columns}"
        )
    log.info(f"Mapped domain column → '{domain_col}'"
             + (f", name column → '{name_col}'" if name_col else ""))

    rows: list[CompanyRow] = []
    skipped: list[tuple[int, str]] = []
    seen: set[str] = set()

    for idx, record in df.iterrows():
        raw_domain = record[domain_col]
        domain = normalize_domain(raw_domain)
        if not domain:
            skipped.append((int(idx) + 2, f"invalid/empty domain: {raw_domain!r}"))
            continue
        if domain in seen:
            skipped.append((int(idx) + 2, f"duplicate domain: {domain}"))
            continue
        seen.add(domain)
        name = str(record[name_col]).strip() if name_col else ""
        rows.append(
            CompanyRow(
                domain=domain,
                company_name=name or None,
                raw={c: record[c] for c in columns},
            )
        )
        if limit and len(rows) >= limit:
            log.info(f"--limit {limit} reached; stopping ingest.")
            break

    if skipped:
        log.warning(f"Skipped {len(skipped)} row(s):")
        for line, reason in skipped[:20]:
            log.warning(f"  row {line}: {reason}")
        if len(skipped) > 20:
            log.warning(f"  … and {len(skipped) - 20} more")

    log.info(f"Loaded {len(rows)} valid lead(s) from {p.name}")
    return IngestReport(rows=rows, skipped=skipped, domain_column=domain_col, name_column=name_col)
