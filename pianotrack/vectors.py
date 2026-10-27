"""Engine test vectors: fixed MIDI input and what the Python engine makes of it.

A port of the engine (recorder, metrics, pieces) to another language, such as
the planned iOS app, replays each vector's input and must produce the same
output. See docs/engine-vectors.md for the format. `python3 -m pianotrack
vectors` rewrites the files; tests/test_vectors.py fails when the engine's
output drifts from them.
"""

import json
import os
import random
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from . import metrics, pieces, simulate
from .recorder import Recorder
from .store import Store

FORMAT = 1
TIMEZONE = "Europe/Istanbul"  # days split at local midnight; the vectors fix the zone
IDLE_GAP = 180.0
MIN_NOTES = 8
STREAK_MIN_MINUTES = 5
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "vectors")


@contextmanager
def timezone(name=TIMEZONE):
    old = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def _ts(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute).timestamp()


def _absolute(events, t0):
    # Millisecond timestamps, so the JSON input is exactly what the engine saw.
    return [(round(t0 + dt, 3), tuple(msg)) for dt, msg in events]


# --- cases --------------------------------------------------------------------

def case_clean_session():
    rng = random.Random(1)
    events = simulate.practice_session(rng, 6, skill=0.8)
    return ("One session of scales, arpeggios, chords and a piece, played cleanly.",
            date(2026, 10, 1), _absolute(events, _ts(date(2026, 10, 1), 19, 5)))


def case_beginner_session():
    rng = random.Random(2)
    events = simulate.practice_session(rng, 6, skill=0.3, beginner=True)
    return ("One beginner session: repertoire pieces with wrong and missed notes, "
            "stops, restarts and slow tempos.",
            date(2026, 10, 2), _absolute(events, _ts(date(2026, 10, 2), 20, 30)))


def case_recorder_edges():
    t = _ts(date(2026, 10, 3), 18, 0)
    ev = []
    # Sustain pressed before the first note: no session is open, so it is ignored.
    ev.append((t - 1.0, (0xB0, 64, 127)))
    # Session 1: ten notes, one ended by note-on velocity 0, one retriggered
    # without a release, pedals during it, a note on channel 10 (drums).
    for i in range(10):
        on = t + i * 0.5
        ev.append((on, (0x90, 60 + i, 60 + 3 * i)))
        if i == 3:
            ev.append((on + 0.3, (0x90, 60 + i, 0)))
        elif i == 5:
            ev.append((on + 0.2, (0x90, 60 + i, 90)))  # retrigger
            ev.append((on + 0.4, (0x80, 60 + i, 0)))
        else:
            ev.append((on + 0.4, (0x80, 60 + i, 0)))
    ev += [(t + 1.0, (0xB0, 64, 127)), (t + 3.0, (0xB0, 64, 0)),
           (t + 2.0, (0xB0, 67, 100)), (t + 2.5, (0xB0, 67, 0))]
    ev += [(t + 5.2, (0x99, 36, 100)), (t + 5.3, (0x89, 36, 0))]
    # All notes off releases what is held.
    ev += [(t + 6.0, (0x90, 48, 70)), (t + 6.0, (0x90, 52, 70)), (t + 7.0, (0xB0, 123, 0))]
    # Session 2 starts after more than the idle gap. Five notes only: discarded.
    t2 = t + 7.0 + IDLE_GAP + 20
    for i in range(5):
        ev += [(t2 + i * 0.3, (0x90, 72, 80)), (t2 + i * 0.3 + 0.2, (0x80, 72, 0))]
    # Session 3: twelve notes and a stuck key (no note-off). It closes only after
    # twice the idle gap, when the next session starts.
    t3 = t2 + 2 + IDLE_GAP + 30
    for i in range(12):
        ev += [(t3 + i * 0.25, (0x90, 64, 75)), (t3 + i * 0.25 + 0.2, (0x80, 64, 0))]
    ev.append((t3 + 3.5, (0x90, 40, 50)))
    # Session 4, after more than twice the idle gap: its first notes close session 3.
    t4 = t3 + 3.5 + 2 * IDLE_GAP + 10
    for i in range(9):
        ev += [(t4 + i * 0.4, (0x90, 67 + i % 3, 85)), (t4 + i * 0.4 + 0.3, (0x80, 67 + i % 3, 0))]
    ev.sort(key=lambda e: e[0])
    return ("Hand-made edge cases for the recorder: pedal before the first note, "
            "note-on velocity 0, retrigger, drum channel, All Notes Off, a session under "
            "8 notes (discarded), a stuck key and the idle gap.",
            date(2026, 10, 3), [(round(a, 3), m) for a, m in ev])


def case_two_weeks():
    rng = random.Random(4)
    first = date(2026, 10, 1)
    out = []
    for i in range(14):
        day = first + timedelta(days=i)
        if i in (4, 9):
            continue  # rest days break the streak
        start = _ts(day, rng.choice([7, 19, 21]), rng.randint(0, 50))
        events = simulate.practice_session(rng, rng.uniform(7, 10), skill=0.3 + 0.03 * i, beginner=True)
        out += _absolute(events, start)
    # One session just before local midnight, so day splitting is in the vectors.
    late = _ts(first + timedelta(days=13), 23, 56)
    out += _absolute(simulate.practice_session(rng, 6, skill=0.6, beginner=True), late)
    out.sort(key=lambda e: e[0])
    return ("Two weeks of short beginner sessions with two rest days and one session that "
            "crosses local midnight: daily totals, streaks, consistency and pieces.",
            first + timedelta(days=14), out)


CASES = {
    "clean-session": case_clean_session,
    "beginner-session": case_beginner_session,
    "recorder-edges": case_recorder_edges,
    "two-weeks-beginner": case_two_weeks,
}


# --- running the engine -------------------------------------------------------

def run(events, today):
    """Feed the messages through the engine the way the collector does and
    return everything a port must reproduce."""
    store = Store(":memory:")
    rec = Recorder(store, idle_gap=IDLE_GAP, min_notes=MIN_NOTES)
    for t, msg in events:
        rec.tick(t)  # the collector ticks between messages, so idle sessions close first
        rec.handle(t, msg)
    rec.close_session()  # end of input

    sessions = []
    for s in sorted(store.sessions(closed_only=True), key=lambda s: s["start"]):
        m = json.loads(s["metrics"])
        sessions.append({
            "start": s["start"], "end": s["end"],
            "notes": [[n["t_on"], n["t_off"], n["pitch"], n["velocity"], n["channel"]]
                      for n in store.notes(s["id"])],
            "pedals": [[p["t"], p["cc"], p["value"]] for p in store.pedals(s["id"])],
            "metrics": m,
        })
    days = metrics.daily_totals([{"start": s["start"], "metrics": s["metrics"]} for s in sessions])
    matcher, _ = pieces.group(store)
    starts = {s["id"]: s["start"] for s in store.sessions(closed_only=True)}
    order = {sid: i for i, sid in enumerate(sorted(starts, key=starts.get))}
    found = []
    for p in pieces.pieces_view(matcher, (), starts):
        p = {k: v for k, v in p.items() if not k.startswith("_") and k != "key"}
        # Session ids are storage details; refer to sessions by their index above.
        p["opening"]["session"] = order[p["opening"]["session"]]
        p["best_run"]["session"] = order[p["best_run"]["session"]]
        for x in p["history"] + p["trouble"]:
            x["session"] = order[x["session"]]
        found.append(p)
    store.close()
    return {
        "sessions": sessions,
        "days": {d.isoformat(): {k: round(v, 1) if isinstance(v, float) else v for k, v in agg.items()}
                 for d, agg in sorted(days.items())},
        "streak": metrics.streaks(days, STREAK_MIN_MINUTES * 60, today),
        "consistency_28d": metrics.consistency(days, today),
        "pieces": found,
    }


def build(name):
    with timezone():
        description, today, events = CASES[name]()
        return {
            "format": FORMAT,
            "name": name,
            "description": description,
            "settings": {"timezone": TIMEZONE, "today": today.isoformat(), "idle_gap_seconds": IDLE_GAP,
                         "min_notes": MIN_NOTES, "streak_min_minutes": STREAK_MIN_MINUTES},
            "input": [[t, list(msg)] for t, msg in events],
            "expected": run(events, today),
        }


def dumps(vector):
    return json.dumps(vector, separators=(",", ":"), sort_keys=True) + "\n"


def write_all(out_dir=None):
    out_dir = out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name in CASES:
        path = os.path.join(out_dir, name + ".json")
        with open(path, "w") as f:
            f.write(dumps(build(name)))
        written.append(path)
    return written
