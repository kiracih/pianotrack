import json
import os
import random
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from pianotrack import metrics, simulate
from pianotrack.collector import Collector
from pianotrack.midi import StreamParser, read_smf, write_smf
from pianotrack.recorder import Recorder
from pianotrack.server import Api, make_server
from pianotrack.store import Store


class TmpStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, "t.db"))

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()


class ParserTest(unittest.TestCase):
    def test_running_status_realtime_and_sysex(self):
        p = StreamParser()
        data = bytes([0xFE, 0x90, 60, 100, 0xF8, 62, 90, 0xF0, 0x41, 0x10, 0xF7,
                      0x80, 60, 0, 0xB0, 64, 127, 0xFE])
        self.assertEqual(p.feed(data[:3]) + p.feed(data[3:]),
                         [(0x90, 60, 100), (0x90, 62, 90), (0x80, 60, 0), (0xB0, 64, 127)])

    def test_smf_roundtrip(self):
        events = [(0.0, (0x90, 60, 80)), (0.5, (0x80, 60, 0)), (0.75, (0xB0, 64, 100))]
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            write_smf(events, path)
            back = read_smf(path)
        finally:
            os.unlink(path)
        self.assertEqual([m for _, m in back], [m for _, m in events])
        for (a, _), (b, _) in zip(back, events):
            self.assertAlmostEqual(a, b, places=2)


class MetricsTest(unittest.TestCase):
    def test_metronomic_scale_is_steady(self):
        onsets = [i * 0.25 for i in range(64)]
        m = metrics.tempo_metrics(onsets)
        self.assertEqual(m["steadiness"], 100)
        self.assertEqual(m["tempo_bpm"], 120)

    def test_sloppy_timing_scores_lower(self):
        rng = random.Random(0)
        steady = metrics.tempo_metrics([i * 0.25 + rng.gauss(0, 0.005) for i in range(64)])
        sloppy = metrics.tempo_metrics([i * 0.25 + rng.gauss(0, 0.04) for i in range(64)])
        self.assertGreater(steady["steadiness"], sloppy["steadiness"] + 20)

    def test_steadiness_is_fair_to_slow_practice(self):
        # The same 3.5% unevenness scores alike at 60, 100 and 140 bpm.
        scores = []
        for bpm in (60, 100, 140):
            beat, rng = 60 / bpm, random.Random(1)
            t, onsets = 0.0, []
            for _ in range(200):
                onsets.append(t)
                t += beat * (1 + rng.choice((-1, 1)) * 0.035)
            scores.append(metrics.tempo_metrics(onsets)["steadiness"])
        self.assertLessEqual(max(scores) - min(scores), 6, scores)
        self.assertTrue(60 <= scores[0] <= 90, scores)

    def test_session_metrics_basics(self):
        notes = [{"t_on": i * 0.5, "t_off": i * 0.5 + 0.4, "pitch": 60 + i % 12, "velocity": 40 + i}
                 for i in range(40)]
        m = metrics.session_metrics(notes, [{"t": 0, "cc": 64, "value": 127},
                                            {"t": 10, "cc": 64, "value": 0},
                                            {"t": 2, "cc": 67, "value": 127},
                                            {"t": 6, "cc": 67, "value": 0}])
        self.assertEqual(m["soft_presses"], 1)
        self.assertAlmostEqual(m["soft_fraction"], 4 / 19.9, places=2)
        self.assertEqual(m["note_count"], 40)
        self.assertAlmostEqual(m["active_seconds"], 39 * 0.5 + 0.4, places=1)
        self.assertEqual(m["sustain_presses"], 1)
        self.assertEqual(sum(m["key_histogram"]), 40)
        self.assertEqual(m["lowest_pitch"], 60)

    def test_streaks(self):
        from datetime import date, timedelta
        today = date(2026, 10, 20)
        days = {today - timedelta(days=i): {"active_seconds": 600} for i in (1, 2, 3, 6, 7)}
        self.assertEqual(metrics.streaks(days, 300, today), {"current": 3, "longest": 3})

    def test_week_days_counts_monday_to_today(self):
        from datetime import date, timedelta
        thu = date(2026, 10, 22)  # a Thursday
        days = {thu - timedelta(days=i): {"active_seconds": s} for i, s in
                [(0, 600), (1, 100), (2, 400), (3, 900), (4, 900)]}  # Sunday before doesn't count
        self.assertEqual(metrics.week_days(days, 300, thu), 3)
        self.assertEqual(metrics.week_days({}, 300, thu), 0)

    def test_last_week_counts_monday_to_sunday(self):
        from datetime import date, timedelta
        monday = date(2026, 10, 26)
        days = {monday - timedelta(days=i): {"active_seconds": s}
                for i, s in [(1, 600), (2, 60), (3, 400), (7, 900), (8, 900)]}
        lw = metrics.last_week(days, 300, 2, monday)
        self.assertEqual(lw, {"start": "2026-10-19", "played": 3, "target": 2, "met": True,
                              "active_seconds": 1960})
        # The same week seen from Sunday is "this week", so last week is the one before.
        self.assertEqual(metrics.last_week(days, 300, 2, monday - timedelta(days=1))["start"], "2026-10-12")
        self.assertFalse(metrics.last_week({}, 300, 2, monday)["met"])

    def test_invite_offers_the_next_small_step(self):
        inv = metrics.invite
        self.assertEqual(inv(0, 1800, 300, 9), "5 min keeps your 9-day run going")
        self.assertEqual(inv(130, 1800, 300, 9), "3 min keeps your 9-day run going")
        self.assertEqual(inv(0, 1800, 300, 0), "5 min starts a new run")
        self.assertEqual(inv(400, 1800, 300, 10), "23 min to your 30 min goal")  # ring shows 7
        self.assertEqual(inv(1795, 1800, 300, 10), "Goal met today")  # ring shows 100%
        self.assertEqual(inv(1800, 1800, 300, 10), "Goal met today")
        # After a break: a welcome back, not a zero.
        self.assertEqual(inv(0, 1800, 300, 0, 2), "One day off doesn't undo a habit. 5 min picks it back up.")
        self.assertEqual(inv(0, 1800, 300, 0, 6), "Welcome back. 5 min is a good start.")
        self.assertEqual(inv(0, 1800, 300, 0, None), "5 min starts a new run")
        self.assertEqual(inv(0, 1800, 300, 4, 1), "5 min keeps your 4-day run going")
        for args in [(0, 1800, 300, 0), (0, 1800, 300, 40), (60, 1800, 300, 0), (1000, 1800, 300, 3),
                     (0, 1800, 300, 0, 2), (0, 1800, 300, 0, 30)]:
            line = inv(*args)
            self.assertNotIn("!", line)
            self.assertNotIn("lose", line.lower())


class RecomputeTest(TmpStore):
    def test_old_sessions_recomputed_once_after_a_copy(self):
        from pianotrack import recompute
        simulate.backfill(self.store, days=3, seed=2)
        old = self.store.sessions(closed_only=True)
        for s in old:  # as stored by the previous formula
            m = json.loads(s["metrics"]); m.pop("v"); m["steadiness"] = -1
            self.store.set_metrics(s["id"], m)
        db = os.path.join(self.dir.name, "t.db")
        n, copy = recompute.recompute(self.store, db)
        self.assertEqual(n, len(old))
        self.assertTrue(os.path.exists(copy))
        for s in self.store.sessions(closed_only=True):
            m = json.loads(s["metrics"])
            self.assertEqual(m["v"], metrics.METRICS_VERSION)
            self.assertNotEqual(m["steadiness"], -1)
        self.assertEqual(recompute.recompute(self.store, db), (0, None))


class RecorderTest(TmpStore):
    def test_idle_gap_splits_sessions_and_short_ones_are_dropped(self):
        rec = Recorder(self.store, idle_gap=60)
        t = 1000.0
        for i in range(20):
            rec.handle(t + i * 0.3, (0x90, 60, 80))
            rec.handle(t + i * 0.3 + 0.2, (0x80, 60, 0))
        rec.tick(t + 30)
        self.assertTrue(rec.active)
        rec.tick(t + 100)
        self.assertFalse(rec.active)
        rec.handle(t + 200, (0x90, 61, 80))  # a single stray note
        rec.handle(t + 200.1, (0x90, 61, 0))
        rec.tick(t + 400)
        sessions = self.store.sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(json.loads(sessions[0]["metrics"])["note_count"], 20)

    def test_stuck_key_still_closes(self):
        rec = Recorder(self.store, idle_gap=60, min_notes=1)
        rec.handle(0, (0x90, 60, 80))
        rec.tick(100)
        self.assertTrue(rec.active)
        rec.tick(130)
        self.assertFalse(rec.active)


class EndToEndTest(TmpStore):
    def test_fifo_collector_and_http_api(self):
        fifo = os.path.join(self.dir.name, "piano.fifo")
        os.mkfifo(fifo)
        col = Collector(self.store, device=fifo, idle_gap=1.5)
        th = threading.Thread(target=col.run, daemon=True)
        th.start()
        events = simulate.practice_session(random.Random(1), minutes=0.3)
        events = [(t, m) for t, m in events if t < 8] + [(8.0, (0xB0, 123, 0))]
        simulate.stream_to_fifo(fifo, events, speed=8)
        time.sleep(3)  # let the idle gap close the session
        httpd = make_server(Api(self.store, col), "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            summary = json.load(urllib.request.urlopen(base + "/api/summary"))
            sessions = json.load(urllib.request.urlopen(base + "/api/sessions"))
            self.assertEqual(len(sessions), 1)
            self.assertTrue(sessions[0]["closed"])
            sent = sum(1 for _, m in events if m[0] == 0x90 and m[2] > 0)
            self.assertEqual(sessions[0]["note_count"], sent)
            self.assertEqual(summary["totals"]["notes"], sent)
            ev = json.load(urllib.request.urlopen(f"{base}/api/sessions/{sessions[0]['id']}/events"))
            self.assertEqual(len(ev["notes"]), sent)
            self.assertTrue(all(0 <= n[0] <= n[1] for n in ev["notes"]))
            mid = urllib.request.urlopen(f"{base}/api/sessions/{sessions[0]['id']}.mid").read()
            self.assertTrue(mid.startswith(b"MThd"))
            page = urllib.request.urlopen(base + "/").read()
            self.assertIn(b"Piano Practice", page)
        finally:
            col.stop()
            httpd.shutdown()
            th.join(5)


class BackfillTest(TmpStore):
    def test_backfill_and_summary(self):
        ids = simulate.backfill(self.store, days=10, seed=2)
        self.assertGreater(len(ids), 3)
        api = Api(self.store)
        s = api.summary()
        self.assertGreater(s["totals"]["notes"], 1000)
        self.assertEqual(len(api.days(30)), 30)
        self.assertTrue(api.trends(30))
        keys = api.keys(30)
        self.assertEqual(len(keys["histogram"]), 88)
        self.assertEqual(keys["total"], s["totals"]["notes"])
        self.assertEqual(api.keys(0)["total"], keys["total"])

    def test_one_day_off_needs_a_streak_day_before_it(self):
        api, t = Api(self.store), time.time() - 2 * 86400
        sid = self.store.open_session(t)
        self.store.close_session(sid, t + 60, {"active_seconds": 60, "note_count": 10})
        self.assertEqual(api.summary()["today"]["invite"], "5 min starts a new run")
        sid = self.store.open_session(t + 100)
        self.store.close_session(sid, t + 500, {"active_seconds": 400, "note_count": 10})
        self.assertTrue(api.summary()["today"]["invite"].startswith("One day off"))

    def test_assets_served(self):
        httpd = make_server(Api(self.store), "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            for path in ("/manifest.webmanifest", "/icon.svg", "/icon-180.png", "/icon-512.png"):
                with urllib.request.urlopen(base + path) as r:
                    self.assertEqual(r.status, 200)
            for path in ("/replay.js", "/piano/A0.mp3", "/piano/C8.mp3", "/piano/Fs4.mp3"):
                with urllib.request.urlopen(base + path) as r:
                    self.assertEqual(r.status, 200)
            for path in ("/keys3d.js", "/piano3d.js", "/falling3d.js", "/vendor/three-0.180.0/three.module.min.js", "/vendor/three-0.180.0/three.core.min.js"):
                with urllib.request.urlopen(base + path) as r:
                    self.assertEqual(r.status, 200)
                    self.assertIn("javascript", r.headers["Content-Type"])
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/vendor/three-LICENSE")
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/piano/../store.py")
            self.assertIsNone(json.load(urllib.request.urlopen(base + "/api/tunnel"))["url"])
            with open(os.path.join(self.dir.name, "tunnel-url"), "w") as f:
                f.write("https://abc.trycloudflare.com\n")
            self.assertEqual(json.load(urllib.request.urlopen(base + "/api/tunnel"))["url"],
                             "https://abc.trycloudflare.com")
            keys = json.load(urllib.request.urlopen(base + "/api/keys?days=7"))
            self.assertEqual(keys["total"], 0)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
