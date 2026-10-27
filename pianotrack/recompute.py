"""Bring stored session metrics up to the current formulas.

Session metrics are computed once, when a session closes, and stored. When a
formula changes (metrics.METRICS_VERSION goes up) the older sessions are
recomputed from their notes, which never change: a checked copy of the database
is taken first, every session is written in one transaction, and running it
again does nothing.
"""
import json
import logging
import os

from . import backup, metrics

log = logging.getLogger(__name__)


def stale(store) -> list:
    """Ids of closed sessions whose stored metrics come from an older formula."""
    out = []
    for s in store.sessions(closed_only=True):
        m = s["metrics"]
        if isinstance(m, str):
            m = json.loads(m)
        if m and m.get("note_count") and m.get("v", 1) < metrics.METRICS_VERSION:
            out.append(s["id"])
    return out


def recompute(store, db_path: str, dry_run: bool = False):
    """Recompute stale sessions. Returns (how many, the copy taken before or None)."""
    ids = stale(store)
    if not ids or dry_run:
        return len(ids), None
    copy = f"{db_path}.pre-metrics-v{metrics.METRICS_VERSION}.db"
    if not os.path.exists(copy):
        backup.snapshot(db_path, copy)  # verified with quick_check
    rows = [(sid, metrics.session_metrics(store.notes(sid), store.pedals(sid))) for sid in ids]
    store.set_metrics_many(rows)
    log.info("recomputed the metrics of %d sessions (formula v%d); copy from before: %s",
             len(rows), metrics.METRICS_VERSION, copy)
    return len(rows), copy
