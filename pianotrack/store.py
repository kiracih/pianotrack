"""SQLite storage for sessions, notes and pedal events."""

import json
import os
import sqlite3
import threading
import urllib.parse

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id      INTEGER PRIMARY KEY,
    start   REAL NOT NULL,
    end     REAL NOT NULL,
    closed  INTEGER NOT NULL DEFAULT 0,
    source  TEXT,
    metrics TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t_on       REAL NOT NULL,
    t_off      REAL NOT NULL,
    pitch      INTEGER NOT NULL,
    velocity   INTEGER NOT NULL,
    channel    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notes_session ON notes(session_id, t_on);
CREATE TABLE IF NOT EXISTS pedals (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t          REAL NOT NULL,
    cc         INTEGER NOT NULL,
    value      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS pedals_session ON pedals(session_id, t);
CREATE INDEX IF NOT EXISTS sessions_start ON sessions(start);
CREATE TABLE IF NOT EXISTS secrets (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "daily_goal_minutes": 30,
    "streak_min_minutes": 5,
}


class Store:
    """Thin wrapper over one SQLite file. Safe to share across threads."""

    def __init__(self, path, readonly=False):
        self.path = path
        self._lock = threading.RLock()
        if readonly:  # for reports: SQLite itself refuses any write
            uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
            self._db = sqlite3.connect(uri, uri=True, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            return
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    def _q(self, sql, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _x(self, sql, args=()):
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur.lastrowid

    # --- writes ---

    def open_session(self, start, source=None):
        return self._x("INSERT INTO sessions(start, end, source) VALUES (?, ?, ?)",
                       (start, start, source))

    def touch_session(self, sid, end):
        self._x("UPDATE sessions SET end=? WHERE id=?", (end, sid))

    def close_session(self, sid, end, metrics):
        self._x("UPDATE sessions SET end=?, closed=1, metrics=? WHERE id=?",
                (end, json.dumps(metrics), sid))

    def delete_session(self, sid):
        self._x("DELETE FROM sessions WHERE id=?", (sid,))

    def add_note(self, sid, t_on, t_off, pitch, velocity, channel=0):
        self._x("INSERT INTO notes(session_id, t_on, t_off, pitch, velocity, channel)"
                " VALUES (?, ?, ?, ?, ?, ?)", (sid, t_on, t_off, pitch, velocity, channel))

    def add_pedal(self, sid, t, cc, value):
        self._x("INSERT INTO pedals(session_id, t, cc, value) VALUES (?, ?, ?, ?)",
                (sid, t, cc, value))

    def add_batch(self, notes, pedals):
        """Insert many rows in one transaction (fewer SD card writes)."""
        with self._lock:
            self._db.executemany(
                "INSERT INTO notes(session_id, t_on, t_off, pitch, velocity, channel)"
                " VALUES (?, ?, ?, ?, ?, ?)", notes)
            self._db.executemany(
                "INSERT INTO pedals(session_id, t, cc, value) VALUES (?, ?, ?, ?)", pedals)
            self._db.commit()

    def set_metrics(self, sid, metrics):
        self._x("UPDATE sessions SET metrics=? WHERE id=?", (json.dumps(metrics), sid))

    def close_dangling(self):
        """Sessions left open by a crash or reboot are closed at their last event."""
        rows = self._q("SELECT id FROM sessions WHERE closed=0")
        for r in rows:
            self._x("UPDATE sessions SET closed=1, metrics=NULL WHERE id=?", (r["id"],))
        return [r["id"] for r in rows]

    # --- reads ---

    def session(self, sid):
        rows = self._q("SELECT * FROM sessions WHERE id=?", (sid,))
        return dict(rows[0]) if rows else None

    def sessions(self, since=None, until=None, limit=None, closed_only=False):
        sql, args = "SELECT * FROM sessions WHERE 1=1", []
        if since is not None:
            sql += " AND end >= ?"
            args.append(since)
        if until is not None:
            sql += " AND start < ?"
            args.append(until)
        if closed_only:
            sql += " AND closed=1"
        sql += " ORDER BY start DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(int(limit))
        return [dict(r) for r in self._q(sql, args)]

    def open_sessions(self):
        return [dict(r) for r in self._q("SELECT * FROM sessions WHERE closed=0")]

    def notes(self, sid):
        return [dict(r) for r in self._q(
            "SELECT t_on, t_off, pitch, velocity, channel FROM notes"
            " WHERE session_id=? ORDER BY t_on", (sid,))]

    def pedals(self, sid):
        return [dict(r) for r in self._q(
            "SELECT t, cc, value FROM pedals WHERE session_id=? ORDER BY t", (sid,))]

    def settings(self):
        out = dict(DEFAULT_SETTINGS)
        for r in self._q("SELECT key, value FROM settings"):
            out[r["key"]] = json.loads(r["value"])
        return out

    def set_setting(self, key, value):
        self._x("INSERT INTO settings(key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))

    # Kept apart from settings so they never appear in /api/settings.
    def secret(self, key):
        rows = self._q("SELECT value FROM secrets WHERE key=?", (key,))
        return rows[0]["value"] if rows else None

    def set_secret(self, key, value):
        self._x("INSERT INTO secrets(key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
