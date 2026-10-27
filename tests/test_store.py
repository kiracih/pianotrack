import os
import shutil
import sqlite3
import tempfile
import unittest

from pianotrack.store import SCHEMA, SCHEMA_VERSION, Store, migrate


class SchemaTest(unittest.TestCase):
    def test_version_1_database_gains_session_ids_and_device(self):
        path = os.path.join(self.dir.name, "v1.db")
        db = sqlite3.connect(path)
        migrate(db, [SCHEMA])
        db.executemany("INSERT INTO sessions(start, end, closed) VALUES (?, ?, 1)", [(1, 2), (3, 4)])
        db.commit()
        db.close()
        copy = os.path.join(self.dir.name, "v1-backup.db")
        shutil.copy(path, copy)
        store = Store(path)
        rows = store.sessions()
        uids = {r["uid"] for r in rows}
        self.assertEqual(len(uids), 2)
        self.assertTrue(all(len(u) == 36 for u in uids))
        # A backup from before the upgrade gives the same recordings the same uids.
        restored = Store(copy)
        self.assertEqual({r["uid"] for r in restored.sessions()}, uids)
        restored.close()
        self.assertEqual({r["device"] for r in rows}, {store.device})
        new = store.open_session(5)
        self.assertEqual(store.session(new)["device"], store.device)
        store.close()
        again = Store(path)  # reopening changes nothing
        self.assertEqual({r["uid"] for r in again.sessions() if r["id"] != new}, uids)
        self.assertEqual(again.device, store.device)
        again.close()

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "t.db")

    def tearDown(self):
        self.dir.cleanup()

    def version(self):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()

    def test_new_database_is_current(self):
        Store(self.path).close()
        self.assertEqual(self.version(), SCHEMA_VERSION)

    def test_database_from_before_versioning_is_adopted(self):
        db = sqlite3.connect(self.path)
        db.executescript(SCHEMA)
        db.execute("INSERT INTO sessions(start, end) VALUES (1, 2)")
        db.commit()
        db.close()
        store = Store(self.path)
        self.assertEqual(len(store.sessions()), 1)
        store.close()
        self.assertEqual(self.version(), SCHEMA_VERSION)

    def test_steps_run_once_in_order(self):
        db = sqlite3.connect(self.path)
        migrate(db, [SCHEMA])
        steps = [SCHEMA, "ALTER TABLE sessions ADD COLUMN mood TEXT",
                 "UPDATE sessions SET mood = 'calm'"]
        self.assertEqual(migrate(db, steps), 1)
        self.assertEqual(migrate(db, steps), 3)  # nothing left to do
        cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)")]
        self.assertIn("mood", cols)
        db.close()

    def test_failed_step_changes_nothing(self):
        db = sqlite3.connect(self.path)
        migrate(db, [SCHEMA])
        with self.assertRaises(sqlite3.Error):
            migrate(db, [SCHEMA, "ALTER TABLE sessions ADD COLUMN a TEXT; SELECT * FROM missing"])
        cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)")]
        self.assertNotIn("a", cols)
        db.close()
        self.assertEqual(self.version(), 1)

    def test_newer_database_is_refused(self):
        db = sqlite3.connect(self.path)
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        db.close()
        with self.assertRaises(RuntimeError):
            Store(self.path)
        with self.assertRaises(RuntimeError):
            Store(self.path, readonly=True)


if __name__ == "__main__":
    unittest.main()
