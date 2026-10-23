import os
import sqlite3
import tempfile
import unittest

from pianotrack.store import SCHEMA, SCHEMA_VERSION, Store, migrate


class SchemaTest(unittest.TestCase):
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
        Store(self.path).close()
        steps = [SCHEMA, "ALTER TABLE sessions ADD COLUMN mood TEXT",
                 "UPDATE sessions SET mood = 'calm'"]
        db = sqlite3.connect(self.path)
        self.assertEqual(migrate(db, steps), 1)
        self.assertEqual(migrate(db, steps), 3)  # nothing left to do
        cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)")]
        self.assertIn("mood", cols)
        db.close()

    def test_failed_step_changes_nothing(self):
        Store(self.path).close()
        db = sqlite3.connect(self.path)
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
