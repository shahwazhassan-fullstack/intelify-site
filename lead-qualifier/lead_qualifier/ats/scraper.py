"""Generic HTML careers-page scraper — fallback when no known ATS is detected.

Best-effort: pulls likely job-title links/headings from a careers page. This is
intentionally conservative; structured ATS APIs are always preferred.
"""

from __future__ import annotations

import re

from ..models import JobOpening
from ..utils.fetcher import Fetcher, FetchResult
from ..utils.logger import get_logger
from .base import classify_function, classify_seniority

log = get_logger("ats.scraper")

# Words/abbreviations that strongly suggest a string is a job title.
_TITLE_HINTS = re.compile(
    r"\b(engineer|developer|manager|designer|analyst|specialist|lead|director|"
    r"officer|representative|sales|marketing|recruiter|account|consultant|"
    r"architect|scientist|coordinator|associate|intern|head|vp|president|"
    r"executive|administrator|support|success|operations|product|counsel|"
    r"sdr|bdr|ae|csm|smb|devops|sre|fp&a|gtm|ceo|cfo|cto|coo|cmo|cro)\b",
    re.IGNORECASE,
)

_JUNK = re.compile(r"(cookie|privacy|terms|sign in|log in|apply now|learn more|"
                   r"view all|see all|home|about|contact)", re.IGNORECASE)


def scrape_careers_html(fetcher: Fetcher, result: FetchResult) -> list[JobOpening]:
    """Extract candidate job openings from a careers page's HTML."""
    soup = result.soup()
    candidates: dict[str, str] = {}   # title → url

    # 1. Links whose text looks like a job title.
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(separator=" ").split())
        if 3 <= len(text) <= 90 and _TITLE_HINTS.search(text) and not _JUNK.search(text):
            from urllib.parse import urljoin
            candidates.setdefault(text, urljoin(result.final_url, a["href"]))

    # 2. Headings that look like job titles (some boards render <h3>Role</h3>).
    for tag in soup.find_all(["h2", "h3", "h4", "li"]):
        text = " ".join(tag.get_text(separator=" ").split())
        if 3 <= len(text) <= 90 and _TITLE_HINTS.search(text) and not _JUNK.search(text):
            candidates.setdefault(text, result.final_url)

    openings: list[JobOpening] = []
    seen: set[str] = set()
    for title, url in candidates.items():
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        openings.append(
            JobOpening(
                title=title,
                function=classify_function(title),
                seniority=classify_seniority(title),
                url=url,
            )
        )

    if openings:
        log.info(f"HTML scrape found {len(openings)} candidate opening(s)")
    return openings
