"""Pluggable job-history interface.

Two implementations ship:
  * SnapshotHistory (free, default) — stores current openings each run and
    derives a trend from accumulated snapshots.
  * TheirStackHistory (paid, optional) — pulls real ~6-month posting history.

The pipeline depends only on this interface, so the source is swappable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import JobOpening


@dataclass
class HistoryResult:
    summary: str        # human-readable momentum description
    trend: str          # growing / steady / shrinking / new / unknown


class JobHistoryProvider(ABC):
    name: str = "base"

    @abstractmethod
    def record_and_summarize(
        self, domain: str, current: list[JobOpening]
    ) -> HistoryResult:
        """Record the current snapshot (if applicable) and return a ~6-mo summary."""
