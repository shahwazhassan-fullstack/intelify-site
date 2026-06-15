"""Ashby ATS — public posting API (GraphQL-style JSON endpoint)."""

from __future__ import annotations

import re
from typing import Optional

import requests

from ..models import JobOpening
from ..utils.logger import get_logger
from .base import ATSProvider, classify_function, classify_seniority

log = get_logger("ats.ashby")

# Public posting board API used by jobs.ashbyhq.com front-ends.
API = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"


class AshbyATS(ATSProvider):
    name = "ashby"

    _PATTERNS = [
        r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)",
        r"([A-Za-z0-9_-]+)\.ashbyhq\.com",
        r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.-]+)",
    ]

    def detect(self, careers_url, page_html, domain) -> Optional[str]:
        for hay in (careers_url or "", page_html or ""):
            for pat in self._PATTERNS:
                m = re.search(pat, hay)
                if m and m.group(1) not in {"jobs", "api", "www"}:
                    return m.group(1)
        return None

    def fetch_openings(self, token: str) -> list[JobOpening]:
        try:
            resp = requests.get(
                API.format(token=token),
                timeout=20,
                headers={"User-Agent": self.fetcher.user_agent},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"Ashby fetch failed for {token}: {e}")
            return []

        openings: list[JobOpening] = []
        for job in data.get("jobs", []):
            title = job.get("title", "").strip()
            dept = job.get("department", "") or job.get("team", "")
            location = job.get("location", "")
            openings.append(
                JobOpening(
                    title=title,
                    function=classify_function(title, dept),
                    location=location,
                    seniority=classify_seniority(title),
                    posted_date=(job.get("publishedAt") or "")[:10] or None,
                    url=job.get("jobUrl", "") or job.get("applyUrl", ""),
                )
            )
        return openings
