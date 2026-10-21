import json
import os
import shutil
import subprocess
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from pianotrack import backup, simulate
from pianotrack.server import Api, make_server
from pianotrack.store import Store

TUNNEL = {"Cf-Ray": "abc123-AMS", "Cf-Connecting-Ip": "203.0.113.7"}


def summary(path):
    store = Store(path)
    try:
        s = Api(store).summary()
    finally:
        store.close()
    s.pop("now")
    return s


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "data", "t.db")
        os.makedirs(os.path.dirname(self.db))
        self.store = Store(self.db)
        simulate.backfill(self.store, days=6, seed=4)
        self.bdir = os.path.join(self.dir.name, "usb")

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def test_restore_gives_the_same_history(self):
        b = backup.Backups(self.db, self.bdir)
        path = b.run()
        before = summary(self.db)
        target = os.path.join(self.dir.name, "new", "restored.db")
        sessions, saved = backup.restore(path, target)
        self.assertIsNone(saved)
        self.assertEqual(sessions, len(self.store.sessions()))
        self.assertEqual(summary(target), before)

    def test_restore_keeps_the_replaced_database(self):
        path = backup.Backups(self.db, self.bdir).run()
        other = os.path.join(self.dir.name, "other.db")
        s = Store(other)
        simulate.backfill(s, days=2, seed=9)
        s.close()
        with self.assertRaises(ValueError):
            backup.restore(path, other)
        _, saved = backup.restore(path, other, force=True)
        self.assertTrue(os.path.exists(saved))
        self.assertEqual(summary(other), summary(self.db))

    def test_restore_refuses_a_file_that_is_not_a_backup(self):
        junk = os.path.join(self.dir.name, "junk.db")
        with open(junk, "wb") as f:
            f.write(b"not a database" * 100)
        with self.assertRaises(ValueError):
            backup.restore(junk, os.path.join(self.dir.name, "x.db"))

    def test_copy_is_consistent_while_writing(self):
        stop = threading.Event()
        sid = self.store.open_session(time.time())

        def writer():
            t = time.time()
            while not stop.is_set():
                self.store.add_batch([(sid, t, t + 0.1, 60, 80, 0)] * 50, [])

        th = threading.Thread(target=writer)
        th.start()
        try:
            for i in range(5):
                dest = os.path.join(self.dir.name, f"c{i}.db")
                backup.snapshot(self.db, dest)
                db = sqlite3.connect(dest)
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                db.close()
        finally:
            stop.set()
            th.join()

    def test_rotation_keeps_seven_daily_and_four_weekly(self):
        b = backup.Backups(self.db, self.bdir)
        start = date(2026, 1, 1)
        for i in range(40):
            b.run(today=start + timedelta(days=i))
        names = sorted(os.listdir(self.bdir))
        daily = [n for n in names if n.startswith("daily-")]
        weekly = [n for n in names if n.startswith("weekly-")]
        self.assertEqual(daily, [f"daily-{start + timedelta(days=i)}.db" for i in range(33, 40)])
        self.assertEqual(weekly, ["weekly-2026-W04.db", "weekly-2026-W05.db",
                                  "weekly-2026-W06.db", "weekly-2026-W07.db"])  # Feb 9 is W07
        self.assertFalse([n for n in names if n.endswith(".tmp")])

    def test_due_and_stale(self):
        b = backup.Backups(self.db, self.bdir, at="03:30")
        self.assertTrue(b.due())
        st = b.status()
        self.assertTrue(st["stale"])
        self.assertIsNone(st["last_backup"])
        b.run()
        now = datetime.now()
        self.assertFalse(b.due(now))
        self.assertFalse(b.status()["stale"])
        self.assertTrue(b.status(now=time.time() + 3 * 86400)["stale"])
        # A day later it is due again once the clock passes the backup time.
        tomorrow = now + timedelta(days=1)
        self.assertTrue(b.due(tomorrow.replace(hour=4, minute=0)))
        early = tomorrow.replace(hour=3, minute=0)
        if early.timestamp() - b.last_backup() < 86400:
            self.assertFalse(b.due(early))

    def test_failure_is_reported(self):
        blocker = os.path.join(self.dir.name, "file")
        open(blocker, "w").close()
        b = backup.Backups(self.db, os.path.join(blocker, "sub"))
        with self.assertRaises(Exception):
            b.run()
        self.assertTrue(b.status()["error"])

    def test_default_folder_is_on_the_same_disk(self):
        b = backup.Backups(self.db)
        b.run()
        self.assertEqual(b.dir, os.path.join(os.path.dirname(self.db), "backups"))
        st = b.status()
        self.assertFalse(st["configured"])
        self.assertFalse(st["off_card"])
        self.assertEqual((st["daily"], st["weekly"]), (1, 1))


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE_SSH = """#!/bin/sh
# Stands in for ssh: drop the options and the host, run the command here.
[ -e "$FAKE_SSH_DOWN" ] && exit 255
while [ "$1" = -o ]; do shift 2; done
shift
exec sh -c "$*"
"""
FAKE_SQLITE = """#!/usr/bin/env python3
import sqlite3, sys
try:
    for row in sqlite3.connect(sys.argv[1]).execute(sys.argv[2]):
        print("|".join(str(v) for v in row))
except sqlite3.Error as e:
    sys.exit(f"Error: {e}")
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class MacPullTest(unittest.TestCase):
    """deploy/mac/pull-backup.sh, with ssh replaced by a local shell."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        self.db = os.path.join(d, "pi", "t.db")
        os.makedirs(os.path.dirname(self.db))
        store = Store(self.db)
        simulate.backfill(store, days=2, seed=5)
        store.close()
        self.pi = backup.Backups(self.db)
        self.mac = os.path.join(d, "mac")
        bin_ = os.path.join(d, "bin")
        os.makedirs(bin_)
        for name, body in (("ssh", FAKE_SSH), ("sqlite3", FAKE_SQLITE)):
            if name == "sqlite3" and shutil.which("sqlite3"):
                continue
            with open(os.path.join(bin_, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(bin_, name), 0o755)
        self.down = os.path.join(d, "down")
        self.env = dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"],
                        PIANOTRACK_REMOTE_DIR=self.pi.dir, PIANOTRACK_DEST=self.mac,
                        FAKE_SSH_DOWN=self.down)

    def tearDown(self):
        self.dir.cleanup()

    def pull(self):
        return subprocess.run(["bash", os.path.join(ROOT, "deploy", "mac", "pull-backup.sh")],
                              env=self.env, capture_output=True, text=True)

    def mac_files(self):
        return sorted(n for n in os.listdir(self.mac) if not n.startswith("."))

    def test_pulls_checks_rotates_and_tells_the_pi(self):
        self.assertIsNone(self.pi.status()["offsite"])
        start = date(2026, 3, 2)  # a Monday
        for i in range(12):
            self.pi.run(today=start + timedelta(days=i))
            r = self.pull()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        files = self.mac_files()
        self.assertEqual([n for n in files if n.startswith("daily-")],
                         [f"daily-{start + timedelta(days=i)}.db" for i in range(5, 12)])
        self.assertEqual([n for n in files if n.startswith("weekly-")],
                         ["weekly-2026-W10.db", "weekly-2026-W11.db"])
        self.assertEqual(summary(os.path.join(self.mac, "daily-2026-03-13.db")), summary(self.db))
        st = self.pi.status()
        self.assertEqual(st["offsite"]["file"], "daily-2026-03-13.db")
        self.assertFalse(st["offsite_stale"])
        # Nothing new: no copy and no log line.
        r = self.pull()
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_unreachable_pi_is_quiet_and_caught_up_later(self):
        self.pi.run()
        open(self.down, "w").close()
        r = self.pull()
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(self.mac) and self.mac_files())
        os.remove(self.down)
        self.assertEqual(self.pull().returncode, 0)
        self.assertEqual(len(self.mac_files()), 2)

    def test_damaged_copy_keeps_previous_ones(self):
        self.pi.run(today=date(2026, 3, 2))
        self.assertEqual(self.pull().returncode, 0)
        with open(os.path.join(self.pi.dir, "daily-2026-03-03.db"), "wb") as f:
            f.write(b"SQLite format 3\x00" + b"\x00" * 4000)
        r = self.pull()
        self.assertEqual(r.returncode, 1)
        self.assertIn("failed its check", r.stdout)
        self.assertEqual(self.mac_files(), ["daily-2026-03-02.db", "weekly-2026-W10.db"])
        self.assertEqual(self.pi.status()["offsite"]["file"], "daily-2026-03-02.db")


class BackupHttpTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "t.db")
        self.store = Store(self.db)
        simulate.backfill(self.store, days=3, seed=2)
        self.backups = backup.Backups(self.db, os.path.join(self.dir.name, "bk"))
        self.httpd = make_server(Api(self.store, backups=self.backups), "127.0.0.1", 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()
        self.dir.cleanup()

    def req(self, path, headers=None, data=None):
        r = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_download_is_a_restorable_copy(self):
        code, headers, body = self.req("/api/backup")
        self.assertEqual(code, 200)
        self.assertIn("attachment; filename=pianotrack-", headers["Content-Disposition"])
        self.assertTrue(body.startswith(b"SQLite format 3\x00"))
        dl = os.path.join(self.dir.name, "download.db")
        with open(dl, "wb") as f:
            f.write(body)
        target = os.path.join(self.dir.name, "restored.db")
        backup.restore(dl, target)
        self.assertEqual(summary(target), summary(self.db))

    def test_home_network_only(self):
        self.assertEqual(self.req("/api/backup", TUNNEL)[0], 403)
        self.assertEqual(self.req("/api/backup", TUNNEL, data=b"")[0], 403)

    def test_back_up_now_and_status(self):
        st = json.loads(self.req("/api/backups")[2])
        self.assertIsNone(st["last_backup"])
        code, _, body = self.req("/api/backup", data=b"")
        self.assertEqual(code, 200)
        st = json.loads(body)
        self.assertFalse(st["stale"])
        self.assertEqual((st["daily"], st["weekly"]), (1, 1))
        self.assertEqual(json.loads(self.req("/api/backups")[2])["daily"], 1)


if __name__ == "__main__":
    unittest.main()
