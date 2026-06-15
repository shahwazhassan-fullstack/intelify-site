"""Recruitee ATS — public offers API."""

from __future__ import annotations

import re
from typing import Optional

import requests

from ..models import JobOpening
from ..utils.logger import get_logger
from .base import ATSProvider, classify_function, classify_seniority

log = get_logger("ats.recruitee")

API = "https://{token}.recruitee.com/api/offers/"


class RecruiteeATS(ATSProvider):
    name = "recruitee"

    _PATTERNS = [
        r"([A-Za-z0-9_-]+)\.recruitee\.com",
        r"careers\.recruitee\.com/([A-Za-z0-9_-]+)",
    ]

    def detect(self, careers_url, page_html, domain) -> Optional[str]:
        for hay in (careers_url or "", page_html or ""):
            for pat in self._PATTERNS:
                m = re.search(pat, hay)
                if m and m.group(1) not in {"careers", "www"}:
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
            log.warning(f"Recruitee fetch failed for {token}: {e}")
            return []

        openings: list[JobOpening] = []
        for job in data.get("offers", []):
            title = job.get("title", "").strip()
            dept = job.get("department", "") or ""
            location = job.get("location", "") or job.get("city", "")
            openings.append(
                JobOpening(
                    title=title,
                    function=classify_function(title, dept),
                    location=location,
                    seniority=classify_seniority(title),
                    posted_date=(job.get("published_at") or "")[:10] or None,
                    url=job.get("careers_url", "") or job.get("url", ""),
                )
            )
        return openings
