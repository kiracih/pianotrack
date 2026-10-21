"""Nightly copies of the database: 7 daily plus 4 weekly, and restore.

Copies use SQLite's online backup API, so they are consistent even while the
collector is writing. Each copy is written to a temporary name, checked with
PRAGMA quick_check and only then renamed into place, so a file in the backup
folder is always a good one.
"""

import logging
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime

log = logging.getLogger(__name__)

KEEP_DAILY = 7
KEEP_WEEKLY = 4
STALE_SECONDS = 2 * 86400
OFFSITE_STALE_SECONDS = 3 * 86400
OFFSITE_MARK = "offsite"  # written over SSH by deploy/mac/pull-backup.sh after each good pull
DAILY = re.compile(r"daily-(\d{4}-\d{2}-\d{2})\.db$")
WEEKLY = re.compile(r"weekly-(\d{4}-W\d{2})\.db$")


def snapshot(src_path, dest_path):
    """Copy the database at src_path to dest_path, consistent and verified."""
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"no database at {src_path}")
    tmp = dest_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")  # one self-contained file
            check = dst.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    if check != "ok":
        os.remove(tmp)
        raise RuntimeError(f"backup failed its integrity check: {check}")
    os.replace(tmp, dest_path)
    return dest_path


def verify(path):
    """Raise ValueError unless path is a sound pianotrack database. Returns its session count."""
    if not os.path.isfile(path):
        raise ValueError(f"{path} does not exist")
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            check = db.execute("PRAGMA quick_check").fetchone()[0]
            if check != "ok":
                raise ValueError(f"{path} is damaged: {check}")
            return db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        finally:
            db.close()
    except sqlite3.DatabaseError as e:
        raise ValueError(f"{path} is not a pianotrack database ({e})")


def restore(backup_path, db_path, force=False):
    """Replace the database at db_path with the backup. Returns (sessions, saved_copy)."""
    sessions = verify(backup_path)
    saved = None
    if os.path.exists(db_path):
        try:
            existing = verify(db_path)
        except ValueError:
            existing = None  # damaged: restoring over it is the point
        if existing and not force:
            raise ValueError(f"{db_path} already holds {existing} sessions; "
                             "pass --force to replace them (a copy is kept)")
        saved = f"{db_path}.before-restore-{datetime.now():%Y%m%d-%H%M%S}"
        snapshot(db_path, saved)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    # Copying through a connection (not a file copy) also clears any -wal file.
    src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return sessions, saved


class Backups:
    """Keeps the rotated copies in one folder and runs the nightly job."""

    def __init__(self, db_path, backup_dir=None, at="03:30"):
        self.db_path = os.path.abspath(db_path)
        self.configured = bool(backup_dir)
        self.dir = os.path.abspath(backup_dir or os.path.join(os.path.dirname(self.db_path), "backups"))
        self.at = datetime.strptime(at, "%H:%M").time()
        self.error = None
        self._lock = threading.Lock()

    def _files(self):
        try:
            names = os.listdir(self.dir)
        except OSError:
            return [], []
        daily = sorted((n for n in names if DAILY.match(n)), reverse=True)
        weekly = sorted((n for n in names if WEEKLY.match(n)), reverse=True)
        return daily, weekly

    def off_card(self):
        """True when the backup folder is on another disk than the database."""
        try:
            return os.stat(self.dir).st_dev != os.stat(os.path.dirname(self.db_path)).st_dev
        except OSError:
            return False

    def last_backup(self):
        daily, weekly = self._files()
        times = [os.path.getmtime(os.path.join(self.dir, n)) for n in daily + weekly]
        return max(times) if times else None

    def run(self, today=None):
        """Make today's copy, refresh this week's copy and prune old ones."""
        today = today or date.today()
        with self._lock:
            try:
                os.makedirs(self.dir, exist_ok=True)
                daily = os.path.join(self.dir, f"daily-{today.isoformat()}.db")
                snapshot(self.db_path, daily)
                y, w, _ = today.isocalendar()
                snapshot(daily, os.path.join(self.dir, f"weekly-{y}-W{w:02d}.db"))
                d, wk = self._files()
                for n in d[KEEP_DAILY:] + wk[KEEP_WEEKLY:]:
                    os.remove(os.path.join(self.dir, n))
                self.error = None
                log.info("backup written to %s", daily)
                return daily
            except Exception as e:
                self.error = f"{e.__class__.__name__}: {e}"
                log.error("backup to %s failed: %s", self.dir, self.error)
                raise

    def due(self, now=None):
        """A copy is due once a day after the backup time, or at once if the last one is over a day old."""
        now = now or datetime.now()
        last = self.last_backup()
        if last is None:
            return True
        if now.timestamp() - last > 86400:
            return True
        made_today = os.path.exists(os.path.join(self.dir, f"daily-{now.date().isoformat()}.db"))
        return not made_today and now.time() >= self.at

    def loop(self, stop, interval=300):
        """Run until stop is set; the Pi may sleep through 03:30, so check every few minutes."""
        while not stop.wait(interval if self.last_backup() else 60):
            if self.due():
                try:
                    self.run()
                except Exception:
                    pass  # recorded in self.error; try again next round
            if self.error:
                stop.wait(3600)  # do not hammer a missing USB stick

    def offsite(self):
        """When another machine last pulled a copy, from the mark it leaves in the folder."""
        path = os.path.join(self.dir, OFFSITE_MARK)
        try:
            with open(path) as f:
                words = f.read().split()
            return {"time": os.path.getmtime(path), "host": words[0] if words else None,
                    "file": words[1] if len(words) > 1 else None}
        except OSError:
            return None

    def status(self, now=None):
        now = now or time.time()
        daily, weekly = self._files()
        last = self.last_backup()
        offsite = self.offsite()
        return {
            "dir": self.dir,
            "configured": self.configured,
            "off_card": self.off_card(),
            "last_backup": last,
            "stale": last is None or now - last > STALE_SECONDS,
            "daily": len(daily),
            "weekly": len(weekly),
            "files": [{"name": n, "size": os.path.getsize(os.path.join(self.dir, n)),
                       "time": os.path.getmtime(os.path.join(self.dir, n))} for n in daily + weekly],
            "offsite": offsite,
            "offsite_stale": offsite is None or now - offsite["time"] > OFFSITE_STALE_SECONDS,
            "error": self.error,
            "at": self.at.strftime("%H:%M"),
        }
