"""Abstract ATS provider interface.

Each provider knows how to:
  * recognise whether a given company uses it (from a careers URL / page HTML)
  * fetch and normalise current openings via the public job-board endpoint

Add a new ATS by subclassing ATSProvider and registering it in __init__.py.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional

from ..models import JobOpening
from ..utils.fetcher import Fetcher


# ── shared normalisation helpers ────────────────────────────────────────────
_FUNCTION_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Sales", ("sales", "account executive", "account exec", " ae ", "sdr", "bdr",
               "business development", "revenue", "account manager")),
    ("Marketing", ("marketing", "growth", "demand gen", "content", "seo", "brand",
                   "communications", "pr ", "social media")),
    ("Engineering", ("engineer", "developer", "software", "devops", "sre", "data",
                     "machine learning", "ml ", "ai ", "platform", "backend",
                     "frontend", "full stack", "fullstack", "infrastructure",
                     "security", "qa", "architect")),
    ("Product", ("product manager", "product owner", "product design", " pm ",
                 "head of product")),
    ("Design", ("designer", "design", "ux", "ui ", "creative")),
    ("Customer Success", ("customer success", "support", "customer experience",
                          "csm", "onboarding", "implementation")),
    ("Operations", ("operations", "ops", "logistics", "supply chain", "procurement")),
    ("Finance", ("finance", "accounting", "controller", "fp&a", "treasury", "audit")),
    ("People/HR", ("recruiter", "recruiting", "talent", "people", "hr ", "human resources")),
    ("Legal", ("legal", "counsel", "compliance", "paralegal")),
    ("Executive", ("chief", "ceo", "cfo", "cto", "coo", "vp ", "vice president",
                   "president", "head of")),
]

_SENIORITY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Executive", ("chief", "ceo", "cfo", "cto", "coo", "vp", "vice president",
                   "president", "head of", "director")),
    ("Lead", ("lead", "principal", "staff", "manager", "head")),
    ("Senior", ("senior", "sr.", "sr ", "iii")),
    ("Junior", ("junior", "jr.", "jr ", "entry", "intern", "graduate", "associate", " i ")),
]


def classify_function(title: str, department: str = "") -> str:
    hay = f" {title.lower()} {department.lower()} "
    for fn, kws in _FUNCTION_KEYWORDS:
        if any(kw in hay for kw in kws):
            return fn
    return "Other"


def classify_seniority(title: str) -> str:
    hay = f" {title.lower()} "
    for level, kws in _SENIORITY_KEYWORDS:
        if any(kw in hay for kw in kws):
            return level
    return "Mid"


class ATSProvider(ABC):
    name: str = "base"

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    @abstractmethod
    def detect(self, careers_url: str | None, page_html: str | None, domain: str) -> Optional[str]:
        """Return a provider-specific company slug/token if this ATS is in use, else None."""

    @abstractmethod
    def fetch_openings(self, token: str) -> list[JobOpening]:
        """Fetch + normalise current openings for the given company token."""

    # convenience used by several providers
    @staticmethod
    def _slug_from_url(url: str, host_fragment: str) -> Optional[str]:
        m = re.search(host_fragment, url)
        return m.group(1) if m else None
