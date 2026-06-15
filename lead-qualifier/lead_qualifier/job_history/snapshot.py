"""Snapshot-and-track history provider (free, default).

Each run stores the company's current openings into a local SQLite datastore
keyed by (domain, date). History accrues from the first run onward — there is
no retroactive backfill. The ~6-month "trend" compares the earliest snapshot
within a 180-day window to the latest.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from ..models import JobOpening, dataclass_to_dict
from ..utils.logger import get_logger
from .base import HistoryResult, JobHistoryProvider

log = get_logger("history.snapshot")


class SnapshotHistory(JobHistoryProvider):
    name = "snapshot"

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    domain      TEXT NOT NULL,
                    snap_date   TEXT NOT NULL,
                    total_open  INTEGER NOT NULL,
                    by_function TEXT NOT NULL,
                    openings    TEXT NOT NULL,
                    created     TEXT NOT NULL,
                    PRIMARY KEY (domain, snap_date)
                )
                """
            )

    def record_and_summarize(self, domain: str, current: list[JobOpening]) -> HistoryResult:
        today = date.today().isoformat()
        by_function: dict[str, int] = {}
        for o in current:
            by_function[o.function] = by_function.get(o.function, 0) + 1

        # Upsert today's snapshot (idempotent within a day → safe re-runs).
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO snapshots
                (domain, snap_date, total_open, by_function, openings, created)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    domain, today, len(current),
                    json.dumps(by_function),
                    json.dumps([dataclass_to_dict(o) for o in current]),
                    datetime.utcnow().isoformat(),
                ),
            )

        return self._summarize(domain, len(current), by_function)

    def _summarize(self, domain: str, today_total: int, today_by_fn: dict[str, int]) -> HistoryResult:
        cutoff = (date.today() - timedelta(days=180)).isoformat()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT snap_date, total_open, by_function FROM snapshots
                WHERE domain=? AND snap_date>=? ORDER BY snap_date ASC
                """,
                (domain, cutoff),
            ).fetchall()

        if len(rows) <= 1:
            return HistoryResult(
                summary=(
                    f"First snapshot recorded today: {today_total} open role(s). "
                    "Hiring history will accumulate from future runs (snapshot mode "
                    "has no retroactive backfill)."
                ),
                trend="new",
            )

        first_date, first_total, _ = rows[0]
        last_date, last_total, _ = rows[-1]
        delta = last_total - first_total

        if delta > 0:
            trend = "growing"
            momentum = f"up {delta} role(s)"
        elif delta < 0:
            trend = "shrinking"
            momentum = f"down {abs(delta)} role(s)"
        else:
            trend = "steady"
            momentum = "flat"

        summary = (
            f"Tracked since {first_date}: {first_total} → {last_total} open roles "
            f"({momentum}) across {len(rows)} snapshots. Current mix: "
            + ", ".join(f"{fn} {n}" for fn, n in sorted(today_by_fn.items(), key=lambda kv: -kv[1]))
        )
        return HistoryResult(summary=summary, trend=trend)
