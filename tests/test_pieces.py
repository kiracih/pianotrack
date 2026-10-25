import random
import unittest
from datetime import datetime

from pianotrack import pieces, simulate
from pianotrack.recorder import Recorder
from pianotrack.store import Store


def stored(events):
    """Store one performance as a session; returns (store, session id)."""
    store = Store(":memory:")
    return store, simulate.feed(Recorder(store), sorted(events, key=lambda e: e[0]), 1_700_000_000.0)


def played(events):
    return pieces.session_segments(*stored(events))


class MatcherTest(unittest.TestCase):
    def play(self, name, seed, **kw):
        rng = random.Random(seed)
        ev, _ = simulate.perform(rng, 0.0, simulate.REPERTOIRE[name], **kw)
        segs = played(ev)
        self.assertEqual(len(segs), 1)
        return segs[0]

    def test_transposed_or_faster_still_matches(self):
        for kw in ({"transpose": 5}, {"transpose": -3}, {"tempo": 1.2},
                   {"tempo": 1.2, "beginner": True}):
            m = pieces.Matcher()
            first = m.add(self.play("Minuet in G", 1, beginner=True))
            self.assertEqual(m.add(self.play("Minuet in G", 2, **kw)), first, kw)

    def test_different_pieces_do_not_match(self):
        names = sorted(simulate.REPERTOIRE)
        m = pieces.Matcher()
        got = [m.add(self.play(n, i, beginner=True)) for i, n in enumerate(names)]
        self.assertEqual(len(set(got)), len(names))

    def test_fingerprint_ignores_key(self):
        a = [60, 62, 64, 65, 67, 65, 64]
        self.assertEqual(pieces.fingerprint(a), pieces.fingerprint([p + 7 for p in a]))

    def test_top_voice_drops_left_hand(self):
        rng = random.Random(0)
        tune = simulate.REPERTOIRE["Twinkle"]
        ev, _ = simulate.perform(rng, 0.0, tune)
        melody = [p for bar in tune["bars"] for p, _ in bar]
        store, sid = stored(ev)
        self.assertEqual([n["pitch"] for n in pieces.top_voice(store.notes(sid))], melody)


class GateTest(unittest.TestCase):
    """Step 1 gate from docs/ROADMAP.md, on simulated beginner practice."""

    def check(self, seed):
        store, log = Store(":memory:"), []
        simulate.backfill(store, days=30, seed=seed, beginner=True, log=log,
                          now=datetime(2026, 1, 1, 22))
        before = store._db.total_changes
        matcher, segs = pieces.group(store)
        self.assertEqual(store._db.total_changes, before, "matching must not write")
        r = pieces.evaluate(matcher, segs, log, simulate.REPERTOIRE)
        self.assertGreater(r["piece_segments"], 200)
        self.assertGreaterEqual(r["right"], 0.9, r)
        self.assertLess(r["wrong"], 0.05, r)
        return matcher, segs

    def test_beginner_gate(self):
        for seed in (1, 4):
            self.check(seed)

    def test_report_lists_the_repertoire(self):
        matcher, segs = self.check(2)
        busy = [r for r in pieces.pieces_report(matcher) if r["segments"] >= 10]
        self.assertGreaterEqual(len(busy), len(simulate.REPERTOIRE))
        text = pieces.format_report(matcher, segs)
        self.assertIn("Piece A", text)


class SimulatorTest(unittest.TestCase):
    def test_default_backfill_is_unchanged_by_beginner_mode(self):
        a, b = Store(":memory:"), Store(":memory:")
        simulate.backfill(a, days=3, seed=5, now=datetime(2026, 1, 1, 22))
        simulate.backfill(b, days=3, seed=5, now=datetime(2026, 1, 1, 22), log=[])
        self.assertEqual([s["metrics"] for s in a.sessions()], [s["metrics"] for s in b.sessions()])

    def test_beginner_makes_mistakes(self):
        tune = simulate.REPERTOIRE["Ode to Joy"]
        written = sum(len(bar) for bar in tune["bars"])
        rng = random.Random(3)
        ev, t = simulate.perform(rng, 0.0, tune, beginner=True, left_hand=False)
        clean, t_clean = simulate.perform(random.Random(3), 0.0, tune, left_hand=False)
        self.assertEqual(sum(1 for _, m in clean if m[0] == 0x90), written)
        self.assertNotEqual(sorted(m for _, m in ev), sorted(m for _, m in clean))
        self.assertGreater(t, t_clean * 0.9)



class ReadOnlyTest(unittest.TestCase):
    def test_report_cannot_write_the_live_database(self):
        import contextlib
        import io
        import os
        import sqlite3
        import tempfile
        from pianotrack.__main__ import main
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "live.db")
            live = Store(path)  # the running service keeps its connection open
            simulate.backfill(live, days=2, seed=1, beginner=True, now=datetime(2026, 1, 1, 22))
            before = live.sessions()
            with contextlib.redirect_stdout(io.StringIO()) as out:
                main(["--db", path, "pieces", "--sessions"])
            self.assertIn("segments in", out.getvalue())
            ro = Store(path, readonly=True)
            with self.assertRaises(sqlite3.OperationalError):
                ro.set_setting("daily_goal_minutes", 1)
            ro.close()
            self.assertEqual(live.sessions(), before)
            live.close()



class PiecesApiTest(unittest.TestCase):
    def test_view_names_stick_and_recordings_are_untouched(self):
        from pianotrack.server import Api
        store = Store(":memory:")
        simulate.backfill(store, days=20, seed=2, beginner=True, now=datetime(2026, 1, 1, 22))
        api = Api(store)
        notes_before = {s["id"]: store.notes(s["id"]) for s in store.sessions()}
        view = api.pieces()
        self.assertGreaterEqual(len(view), len(simulate.REPERTOIRE))
        top = max(view, key=lambda r: r["active_seconds"])
        self.assertTrue(all(h["active_seconds"] > 0 for h in top["history"]))
        self.assertIn(top["label"], [r["label"] for r in view])

        view = api.name_piece({"key": top["key"], "name": "  My   waltz "})
        named = [r for r in view if r["name"]]
        self.assertEqual([r["label"] for r in named], ["My waltz"])
        sid = named[0]["history"][-1]["session"]
        self.assertIn("My waltz", [p["label"] for p in api.session(sid)["pieces"]])

        # More practice later: the name follows the music into new sessions.
        simulate.backfill(store, days=10, seed=9, beginner=True, now=datetime(2026, 1, 12, 22))
        later = [r for r in api.pieces() if r["name"] == "My waltz"]
        self.assertEqual(len(later), 1)
        self.assertGreater(later[0]["last"], named[0]["last"])

        view = api.name_piece({"key": later[0]["key"], "name": ""})
        self.assertFalse(any(r["name"] for r in view))
        for sid, notes in notes_before.items():
            self.assertEqual(store.notes(sid), notes)
        with self.assertRaises(ValueError):
            api.name_piece({"key": "nope", "name": "x"})

    def test_new_sessions_are_added_without_regrouping(self):
        from pianotrack.server import Api
        store = Store(":memory:")
        simulate.backfill(store, days=20, seed=4, beginner=True, now=datetime(2026, 1, 1, 22))
        api = Api(store)
        api.pieces()
        kept = api._matcher[1]
        simulate.backfill(store, days=6, seed=8, beginner=True, now=datetime(2026, 1, 8, 22))
        grown = api.pieces()
        self.assertIs(api._matcher[1], kept)  # grown in place, not regrouped
        self.assertEqual(grown, Api(store).pieces())  # same as grouping from scratch

        # A deleted session regroups from scratch, and still matches a fresh grouping.
        store.delete_session(grown[0]["history"][0]["session"])
        after = api.pieces()
        self.assertIsNot(api._matcher[1], kept)
        self.assertEqual(after, Api(store).pieces())

    def test_a_failed_update_regroups_instead_of_counting_twice(self):
        from unittest import mock
        from pianotrack.server import Api
        store = Store(":memory:")
        simulate.backfill(store, days=12, seed=4, beginner=True, now=datetime(2026, 1, 1, 22))
        api = Api(store)
        api.pieces()
        simulate.backfill(store, days=3, seed=8, beginner=True, now=datetime(2026, 1, 5, 22))
        real = pieces.add_sessions

        def half(matcher, st, sessions, cache=None):
            real(matcher, st, sessions[:1], cache)
            raise OSError("database is locked")
        with mock.patch.object(pieces, "add_sessions", half):
            with self.assertRaises(OSError):
                api.pieces()
        self.assertEqual(api.pieces(), Api(store).pieces())


if __name__ == "__main__":
    unittest.main()
