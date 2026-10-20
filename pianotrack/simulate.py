"""Synthetic practice generator, so the pipeline can run without a piano.

Produces [(seconds, msg)] streams that look like real practice: scales,
arpeggios, chord work with pedal, and a "piece" with phrasing. They can be
written straight into the database (backfill), streamed as raw MIDI bytes into
a FIFO the collector reads (true end-to-end), or saved as a .mid file.
"""

import os
import random
import time
from datetime import datetime, timedelta

from .midi import write_smf
from .recorder import Recorder

MAJOR = [0, 2, 4, 5, 7, 9, 11]


def _note(events, t, pitch, vel, dur, ch=0):
    pitch = max(21, min(108, pitch))
    vel = max(1, min(127, int(vel)))
    events.append((t, (0x90 | ch, pitch, vel)))
    events.append((t + dur, (0x80 | ch, pitch, 0)))


def scale(rng, t, bpm, root=60, octaves=2, base_vel=70, jitter=0.012):
    events = []
    step = 60.0 / bpm / 2  # eighth notes
    degrees = [root + 12 * (i // 7) + MAJOR[i % 7] for i in range(7 * octaves + 1)]
    seq = degrees + degrees[-2::-1]
    for i, p in enumerate(seq):
        vel = base_vel + 18 * (1 - abs(i - len(seq) / 2) / (len(seq) / 2)) + rng.gauss(0, 5)
        _note(events, t + rng.gauss(0, jitter), p, vel, step * 0.9)
        _note(events, t + rng.gauss(0, jitter), p - 12, vel - 8, step * 0.9)
        t += step
    return events, t


def arpeggio(rng, t, bpm, root=48, base_vel=65, reps=4, jitter=0.01):
    events = []
    step = 60.0 / bpm / 4  # sixteenths
    for _ in range(reps):
        for chord in ([0, 4, 7, 12], [5, 9, 12, 17], [7, 11, 14, 19], [0, 4, 7, 12]):
            for o in (0, 12):
                for c in chord:
                    _note(events, t + rng.gauss(0, jitter), root + o + c,
                          base_vel + rng.gauss(0, 7), step * 1.5)
                    t += step
    return events, t


def chords(rng, t, bpm, root=48, base_vel=60, bars=8):
    events = []
    beat = 60.0 / bpm
    prog = [[0, 4, 7], [9, 12, 16], [5, 9, 12], [7, 11, 14]]
    for bar in range(bars):
        tri = prog[bar % 4]
        events.append((t - 0.02, (0xB0, 64, 0)))
        events.append((t + 0.03, (0xB0, 64, 100)))
        for b in range(4):
            vel = base_vel + (15 if b == 0 else 0) + rng.gauss(0, 4)
            for c in tri:
                _note(events, t + rng.gauss(0, 0.008), root + c, vel, beat * 0.95)
            _note(events, t, root - 12 + tri[0], vel + 5, beat * 0.95)
            if b % 2 == 0:
                melody = root + 24 + rng.choice(tri) + rng.choice([0, 12])
                _note(events, t + rng.gauss(0, 0.01), melody, vel + 10, beat * 1.8)
            t += beat
    events.append((t, (0xB0, 64, 0)))
    return events, t


def piece(rng, t, bpm, bars=24, base_vel=64, jitter=0.012):
    """A random-walk melody over an Alberti bass, with crescendo phrases."""
    events = []
    beat = 60.0 / bpm
    melody = 72
    for bar in range(bars):
        phrase = (bar % 4) / 3.0
        dyn = base_vel + 25 * phrase + rng.gauss(0, 3)
        root = 48 + [0, 5, 7, 0][bar % 4]
        events.append((t, (0xB0, 64, 90 if bar % 2 == 0 else 0)))
        events.append((t, (0xB0, 67, 100 if phrase == 0 else 0)))  # soft pedal on quiet bars
        for b in range(4):
            for i, c in enumerate([0, 7, 4, 7]):
                tt = t + b * beat + i * beat / 4 + rng.gauss(0, jitter)
                _note(events, tt, root + c, dyn - 15 + rng.gauss(0, 4), beat / 4)
            for half in (0, 1):
                melody += rng.choice([-2, -1, 0, 1, 2, 2, -3, 4])
                melody = max(64, min(88, melody))
                tt = t + b * beat + half * beat / 2 + rng.gauss(0, jitter)
                _note(events, tt, melody, dyn + rng.gauss(0, 6), beat / 2 * 0.9)
        t += 4 * beat
        if rng.random() < 0.1:  # a stumble: hesitation then restart
            t += rng.uniform(0.8, 2.5)
    events.append((t, (0xB0, 64, 0)))
    events.append((t, (0xB0, 67, 0)))
    return events, t


def practice_session(rng, minutes=20.0, skill=0.5):
    """[(seconds_from_start, msg)] for one session of roughly `minutes`."""
    events, t = [], 0.0
    target = minutes * 60
    tempo = 70 + 50 * skill
    jitter = 0.03 - 0.024 * skill
    while t < target:
        kind = rng.choices(["scale", "arp", "chords", "piece"], [3, 2, 2, 4])[0]
        bpm = tempo * rng.uniform(0.85, 1.15)
        root = rng.choice([48, 50, 53, 55, 57, 60])
        if kind == "scale":
            ev, t = scale(rng, t, bpm, root=root + 12, jitter=jitter)
        elif kind == "arp":
            ev, t = arpeggio(rng, t, bpm, root=root, jitter=jitter)
        elif kind == "chords":
            ev, t = chords(rng, t, bpm, root=root)
        else:
            ev, t = piece(rng, t, bpm, bars=rng.randint(12, 32), jitter=jitter)
        events += ev
        t += rng.uniform(4, 40)  # rest between exercises, under the idle gap
    events.sort(key=lambda e: e[0])
    return events


def feed(recorder, events, t0):
    for dt, msg in events:
        recorder.handle(t0 + dt, msg)
        recorder.tick(t0 + dt)
    return recorder.close_session()


def backfill(store, days=30, seed=None, now=None):
    """Write `days` of plausible practice history ending today."""
    rng = random.Random(seed)
    now = now or datetime.now()
    rec = Recorder(store, source="simulator")
    created = []
    for i in range(days, -1, -1):
        day = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        if rng.random() < 0.18:
            continue  # rest day
        progress = 1 - i / max(days, 1)
        for start_hour in rng.sample([7, 12, 18, 20, 21], rng.choice([1, 1, 1, 2])):
            start = day + timedelta(hours=start_hour, minutes=rng.randint(0, 50))
            if start > now:
                continue
            minutes = rng.uniform(8, 45)
            ev = practice_session(rng, minutes, skill=0.3 + 0.5 * progress)
            sid = feed(rec, ev, start.timestamp())
            if sid:
                created.append(sid)
    return created


def stream_to_fifo(path, events, speed=1.0, loops=1):
    """Write raw MIDI bytes into a FIFO in real time, like a USB device would."""
    if not os.path.exists(path):
        os.mkfifo(path)
    with open(path, "wb", buffering=0) as f:
        for _ in range(loops):
            start = time.monotonic()
            for dt, msg in events:
                wait = start + dt / speed - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                f.write(bytes(msg))
                f.write(b"\xfe")  # active sensing, as the FP-30X sends


def save_mid(path, events):
    write_smf(events, path)
