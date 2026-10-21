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
