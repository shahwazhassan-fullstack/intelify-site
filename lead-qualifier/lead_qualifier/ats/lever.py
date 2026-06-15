"""Lever ATS — public postings API."""

from __future__ import annotations

import re
from typing import Optional

import requests

from ..models import JobOpening
from ..utils.logger import get_logger
from .base import ATSProvider, classify_function, classify_seniority

log = get_logger("ats.lever")

API = "https://api.lever.co/v0/postings/{token}?mode=json"


class LeverATS(ATSProvider):
    name = "lever"

    _PATTERNS = [
        r"jobs\.lever\.co/([A-Za-z0-9_-]+)",
        r"api\.lever\.co/v0/postings/([A-Za-z0-9_-]+)",
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
            log.warning(f"Lever fetch failed for {token}: {e}")
            return []

        openings: list[JobOpening] = []
        for job in data:
            title = job.get("text", "").strip()
            cats = job.get("categories") or {}
            dept = cats.get("team") or cats.get("department") or ""
            location = cats.get("location", "")
            posted = None
            if job.get("createdAt"):
                # epoch ms → ISO date
                from datetime import datetime, timezone
                posted = datetime.fromtimestamp(
                    job["createdAt"] / 1000, tz=timezone.utc
                ).date().isoformat()
            openings.append(
                JobOpening(
                    title=title,
                    function=classify_function(title, dept),
                    location=location,
                    seniority=classify_seniority(title),
                    posted_date=posted,
                    url=job.get("hostedUrl", ""),
                )
            )
        return openings
