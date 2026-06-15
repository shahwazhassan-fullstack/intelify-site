"""TheirStack historical-jobs provider (paid, optional).

Returns real posting history over the last ~6 months so the full window is
available immediately, without waiting for snapshots to accrue. Requires
THEIRSTACK_API_KEY. This is a thin, defensive integration — if the API shape
changes or the key is missing, it degrades gracefully.

NOTE: kept behind the JobHistoryProvider interface so the rest of the pipeline
is unaffected by which source is used.
"""

from __future__ import annotations

from datetime import date, timedelta

import requests

from ..models import JobOpening
from ..utils.logger import get_logger
from .base import HistoryResult, JobHistoryProvider

log = get_logger("history.theirstack")

API = "https://api.theirstack.com/v1/jobs/search"


class TheirStackHistory(JobHistoryProvider):
    name = "theirstack"

    def __init__(self, api_key: str, snapshot_fallback: JobHistoryProvider | None = None):
        self.api_key = api_key
        # Still record snapshots so we own the data over time.
        self.snapshot_fallback = snapshot_fallback

    def record_and_summarize(self, domain: str, current: list[JobOpening]) -> HistoryResult:
        # Always keep our own snapshot ledger up to date if available.
        if self.snapshot_fallback:
            self.snapshot_fallback.record_and_summarize(domain, current)

        posted_after = (date.today() - timedelta(days=180)).isoformat()
        try:
            resp = requests.post(
                API,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "company_domain_or": [domain],
                    "posted_at_gte": posted_after,
                    "page": 0,
                    "limit": 100,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                log.warning(f"TheirStack {resp.status_code} for {domain}; "
                            "falling back to snapshot summary.")
                return self._fallback(domain, current)
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            log.warning(f"TheirStack error for {domain}: {e}; using snapshot summary.")
            return self._fallback(domain, current)

        jobs = data.get("data", data.get("results", []))
        total = len(jobs)
        if total == 0:
            return HistoryResult(
                summary=f"No postings found in TheirStack for {domain} in the last 180 days.",
                trend="unknown",
            )

        # Bucket by month to describe momentum.
        by_month: dict[str, int] = {}
        for j in jobs:
            posted = (j.get("date_posted") or j.get("posted_at") or "")[:7]
            if posted:
                by_month[posted] = by_month.get(posted, 0) + 1
        months = sorted(by_month)
        trend = "unknown"
        if len(months) >= 2:
            first_half = sum(by_month[m] for m in months[: len(months) // 2])
            second_half = sum(by_month[m] for m in months[len(months) // 2:])
            trend = ("growing" if second_half > first_half
                     else "shrinking" if second_half < first_half else "steady")

        summary = (
            f"TheirStack: {total} posting(s) in the last 180 days. "
            "Monthly volume: " + ", ".join(f"{m}:{by_month[m]}" for m in months)
        )
        return HistoryResult(summary=summary, trend=trend)

    def _fallback(self, domain: str, current: list[JobOpening]) -> HistoryResult:
        if self.snapshot_fallback:
            return self.snapshot_fallback.record_and_summarize(domain, current)
        return HistoryResult(
            summary=f"{len(current)} current openings (no history available).",
            trend="unknown",
        )
