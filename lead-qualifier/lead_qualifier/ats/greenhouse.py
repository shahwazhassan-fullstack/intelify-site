"""Greenhouse ATS — public boards API."""

from __future__ import annotations

import re
from typing import Optional

import requests

from ..models import JobOpening
from ..utils.logger import get_logger
from .base import ATSProvider, classify_function, classify_seniority

log = get_logger("ats.greenhouse")

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


class GreenhouseATS(ATSProvider):
    name = "greenhouse"

    _PATTERNS = [
        r"boards\.greenhouse\.io/([A-Za-z0-9_-]+)",
        r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)",
        r"job-boards\.greenhouse\.io/([A-Za-z0-9_-]+)",
        r"greenhouse\.io/embed/job_board\?for=([A-Za-z0-9_-]+)",
    ]

    def detect(self, careers_url, page_html, domain) -> Optional[str]:
        for hay in (careers_url or "", page_html or ""):
            for pat in self._PATTERNS:
                m = re.search(pat, hay)
                if m:
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
            log.warning(f"Greenhouse fetch failed for {token}: {e}")
            return []

        openings: list[JobOpening] = []
        for job in data.get("jobs", []):
            title = job.get("title", "").strip()
            dept = ""
            depts = job.get("departments") or []
            if depts:
                dept = depts[0].get("name", "")
            location = (job.get("location") or {}).get("name", "")
            openings.append(
                JobOpening(
                    title=title,
                    function=classify_function(title, dept),
                    location=location,
                    seniority=classify_seniority(title),
                    posted_date=(job.get("updated_at") or "")[:10] or None,
                    url=job.get("absolute_url", ""),
                )
            )
        return openings
