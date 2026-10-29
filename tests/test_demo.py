import logging
import os
import tempfile
import threading
import unittest
import urllib.request

from pianotrack import demo
from pianotrack.server import Api, make_server
from pianotrack.store import Store
from tests import test_auth

TUNNEL, NoRedirect = test_auth.TUNNEL, test_auth.NoRedirect


class DemoTest(unittest.TestCase):
    def setUp(self):
        logging.getLogger("pianotrack").setLevel(logging.WARNING)
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "demo.db")

    def tearDown(self):
        self.dir.cleanup()

    def test_build_names_the_pieces_and_keeps_todays_copy(self):
        self.assertTrue(demo.build(self.db, days=14, seed=3))
        self.assertFalse(demo.build(self.db, days=14, seed=3))  # already built today
        store = Store(self.db, readonly=True)
        try:
            self.assertGreater(len(store.sessions(limit=1000)), 5)
            self.assertTrue(store.piece_names())
        finally:
            store.close()
        self.assertTrue(demo.build(self.db, days=3, seed=1, force=True))

    def test_refuses_a_database_with_real_recordings(self):
        store = Store(self.db)
        store.open_session(1_700_000_000, source="/dev/snd/midiC3D0")
        store.close()
        with self.assertRaises(ValueError):
            demo.build(self.db, days=3)
        # A fresh real database: no recordings yet, but a password and settings.
        fresh = os.path.join(self.dir.name, "fresh.db")
        store = Store(fresh)
        store.set_secret("password_hash", "x")
        store.close()
        with self.assertRaises(ValueError):
            demo.build(fresh, days=3)
        store = Store(fresh, readonly=True)
        self.assertEqual(store.secret("password_hash"), "x")
        store.close()
        with open(self.db + "x", "w") as f:
            f.write("not a database")
        with self.assertRaises(ValueError):
            demo.build(self.db + "x", days=3)


class DemoServerTest(unittest.TestCase):
    """The demo answers anyone without a password and changes nothing."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, "t.db"))
        self.httpd = make_server(Api(self.store, demo=True), "127.0.0.1", 0, tunnel=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.opener = urllib.request.build_opener(NoRedirect)

    tearDown = test_auth.AuthTest.tearDown
    req = test_auth.AuthTest.req

    def test_reads_need_no_password(self):
        for path in ("/", "/api/summary", "/api/pieces", "/api/sessions"):
            self.assertIn(self.req(path, TUNNEL)[0], (200, 503), path)
        self.assertEqual(self.req("/api/summary", {"Host": "evil.example"})[0], 200)

    def test_changes_and_backups_are_refused(self):
        goal = self.store.settings()["daily_goal_minutes"]
        for path, body in (("/api/settings", {"daily_goal_minutes": goal + 1}),
                           ("/api/password", {"password": "x" * 9}),
                           ("/api/pieces/name", {"key": "k", "name": "n"}),
                           ("/api/signout-all", {}), ("/api/backup", {})):
            self.assertEqual(self.req(path, json_body=body)[0], 403, path)
        self.assertEqual(self.req("/api/backup")[0], 403)
        self.assertEqual(self.store.settings()["daily_goal_minutes"], goal)


if __name__ == "__main__":
    unittest.main()
