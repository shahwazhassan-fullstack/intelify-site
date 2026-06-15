"""SQLite-backed cache + checkpoint store.

Two responsibilities:
  1. Cache expensive results (HTTP fetches, LLM responses) keyed by a hash so
     re-runs don't re-fetch or re-spend API credits.
  2. Checkpoint completed company records so an interrupted run can resume.

Thread-safe via a lock + per-thread connections (check_same_thread=False).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional


def make_key(*parts: Any) -> str:
    """Stable hash key from arbitrary parts."""
    blob = json.dumps(parts, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class Cache:
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
                CREATE TABLE IF NOT EXISTS cache (
                    key       TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    value     TEXT NOT NULL,
                    created   REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    domain    TEXT PRIMARY KEY,
                    record    TEXT NOT NULL,
                    updated   REAL NOT NULL
                )
                """
            )

    # ── generic cache ──────────────────────────────────────────────────────
    def get(self, namespace: str, key: str, *, max_age: Optional[float] = None) -> Optional[Any]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT value, created FROM cache WHERE key=? AND namespace=?",
                (key, namespace),
            )
            row = cur.fetchone()
        if not row:
            return None
        value, created = row
        if max_age is not None and (time.time() - created) > max_age:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, namespace, value, created) VALUES (?,?,?,?)",
                (key, namespace, json.dumps(value, default=str), time.time()),
            )

    # ── checkpoints ──────────────────────────────────────────────────────────
    def get_checkpoint(self, domain: str) -> Optional[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT record FROM checkpoints WHERE domain=?", (domain,)
            )
            row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def set_checkpoint(self, domain: str, record: dict) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO checkpoints (domain, record, updated) VALUES (?,?,?)",
                (domain, json.dumps(record, default=str), time.time()),
            )

    def clear_checkpoints(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM checkpoints")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
