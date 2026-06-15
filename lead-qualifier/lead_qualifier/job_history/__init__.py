"""Job-history provider selection."""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from .base import HistoryResult, JobHistoryProvider
from .snapshot import SnapshotHistory
from .theirstack import TheirStackHistory


def get_history_provider(
    kind: str, settings: Settings, *, snapshots_db: str | Path
) -> JobHistoryProvider:
    """Factory: 'none' (snapshot-only) or 'api' (paid provider + snapshot ledger)."""
    snapshot = SnapshotHistory(snapshots_db)
    if kind == "api":
        settings.require_history_api()
        return TheirStackHistory(settings.theirstack_api_key, snapshot_fallback=snapshot)
    return snapshot
