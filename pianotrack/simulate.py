"""Synthetic practice generator, so the pipeline can run without a piano.

Produces [(seconds, msg)] streams that look like real practice: scales,
arpeggios, chord work with pedal, and a "piece" with phrasing. Beginner mode
plays a small fixed repertoire instead, with the wrong and missed notes, stops,
restarts and slow tempos of someone still learning it, and can log what was
played when, so the pieces matcher can be scored against the truth. They can be
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


# --- Repertoire and beginner mode -------------------------------------------

_NAMES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7,
          "G#": 8, "A": 9, "A#": 10, "B": 11}


def _pitch(name):
    return 12 * (int(name[-1]) + 1) + _NAMES[name[:-1]]


def _tune(melody, bass):
    """'E5 D5:0.5 | ...' (duration in beats, default 1) and one bass root per bar."""
    bars = []
    for bar in melody.split("|"):
        notes = []
        for tok in bar.split():
            name, _, dur = tok.partition(":")
            notes.append((_pitch(name), float(dur or 1)))
        bars.append(notes)
    roots = [_pitch(r) for r in bass.split()]
    assert len(roots) == len(bars)
    return {"bars": bars, "bass": roots}


# Public-domain beginner pieces, melody plus a broken-chord left hand.
REPERTOIRE = {
    "Twinkle": dict(bpm=100, **_tune(
        "C5 C5 G5 G5 | A5 A5 G5:2 | F5 F5 E5 E5 | D5 D5 C5:2 | G5 G5 F5 F5 | E5 E5 D5:2 |"
        "G5 G5 F5 F5 | E5 E5 D5:2 | C5 C5 G5 G5 | A5 A5 G5:2 | F5 F5 E5 E5 | D5 D5 C5:2",
        "C3 F3 F3 C3 C3 G2 C3 G2 C3 F3 F3 C3")),
    "Ode to Joy": dict(bpm=110, **_tune(
        "E5 E5 F5 G5 | G5 F5 E5 D5 | C5 C5 D5 E5 | E5:1.5 D5:0.5 D5:2 |"
        "E5 E5 F5 G5 | G5 F5 E5 D5 | C5 C5 D5 E5 | D5:1.5 C5:0.5 C5:2 |"
        "D5 D5 E5 C5 | D5 E5:0.5 F5:0.5 E5 C5 | D5 E5:0.5 F5:0.5 E5 D5 | C5 D5 G4:2 |"
        "E5 E5 F5 G5 | G5 F5 E5 D5 | C5 C5 D5 E5 | D5:1.5 C5:0.5 C5:2",
        "C3 G2 C3 G2 C3 G2 C3 C3 G2 C3 C3 G2 C3 G2 C3 C3")),
    "Minuet in G": dict(bpm=100, **_tune(
        "D5 G4:0.5 A4:0.5 B4:0.5 C5:0.5 | D5 G4 G4 | E5 C5:0.5 D5:0.5 E5:0.5 F#5:0.5 | G5 G4 G4 |"
        "C5 D5:0.5 C5:0.5 B4:0.5 A4:0.5 | B4 C5:0.5 B4:0.5 A4:0.5 G4:0.5 |"
        "F#4 G4:0.5 A4:0.5 B4:0.5 G4:0.5 | A4:3 |"
        "D5 G4:0.5 A4:0.5 B4:0.5 C5:0.5 | D5 G4 G4 | E5 C5:0.5 D5:0.5 E5:0.5 F#5:0.5 | G5 G4 G4 |"
        "C5 D5:0.5 C5:0.5 B4:0.5 A4:0.5 | B4 C5:0.5 B4:0.5 A4:0.5 G4:0.5 |"
        "A4 B4:0.5 A4:0.5 G4:0.5 F#4:0.5 | G4:3",
        "G2 G2 C3 G2 C3 G2 D3 D3 G2 G2 C3 G2 C3 G2 D3 G2")),
    "Fur Elise": dict(bpm=70, **_tune(
        "E5:0.5 D#5:0.5 E5:0.5 D#5:0.5 E5:0.5 B4:0.5 | D5:0.5 C5:0.5 A4:2 |"
        "C4:0.5 E4:0.5 A4:0.5 B4:1.5 | E4:0.5 G#4:0.5 B4:0.5 C5:1.5 |"
        "E4:0.5 E5:0.5 D#5:0.5 E5:0.5 D#5:0.5 E5:0.5 | B4:0.5 D5:0.5 C5:0.5 A4:1.5 |"
        "C4:0.5 E4:0.5 A4:0.5 B4:1.5 | E4:0.5 C5:0.5 B4:0.5 A4:1.5 |"
        "E5:0.5 D#5:0.5 E5:0.5 D#5:0.5 E5:0.5 B4:0.5 | D5:0.5 C5:0.5 A4:2 |"
        "C4:0.5 E4:0.5 A4:0.5 B4:1.5 | E4:0.5 G#4:0.5 B4:0.5 C5:1.5 |"
        "E4:0.5 E5:0.5 D#5:0.5 E5:0.5 D#5:0.5 E5:0.5 | B4:0.5 D5:0.5 C5:0.5 A4:1.5 |"
        "C4:0.5 E4:0.5 A4:0.5 B4:1.5 | E4:0.5 C5:0.5 B4:0.5 A4:3",
        "A2 A2 A2 E2 A2 A2 A2 E2 A2 A2 A2 E2 A2 A2 A2 E2")),
}


BEGINNER_ERRORS = (0.10, 0.15)  # share of written notes played wrong, missed or corrected


def _slip(rng, pitch, errors):
    """The pitches actually played for one written note: [] if missed."""
    r = rng.random() / errors if errors else 1.0
    wrong = pitch + rng.choice([-2, -1, 1, 2])
    if r < 0.35:
        return []  # missed
    if r < 0.75:
        return [wrong]  # wrong key, not corrected
    if r < 1.0:
        return [wrong, pitch]  # wrong key, then corrected
    return [pitch]


def perform(rng, t, tune, tempo=1.0, transpose=0, beginner=False, bars=None, left_hand=True):
    """Play a REPERTOIRE tune from bar bars[0] to bars[1] (exclusive).

    Clean by default. A beginner gets 10 to 15% wrong, missed or corrected
    notes, hesitations, timing wobble, and stops that restart a few bars back.
    """
    events = []
    first, last = bars or (0, len(tune["bars"]))
    errors = rng.uniform(*BEGINNER_ERRORS) if beginner else 0.0
    jitter = 0.035 if beginner else 0.01
    beat = 60.0 / (tune["bpm"] * tempo)
    restarts, i = 0, first
    while i < last:
        bar_beat = beat * (rng.uniform(0.92, 1.1) if beginner else 1.0)
        bar_start = t
        root = tune["bass"][i] + transpose
        notes = tune["bars"][i]
        stop_at = len(notes)
        if beginner and i > first and restarts < 3 and rng.random() < 0.12:
            stop_at = rng.randrange(len(notes))  # stumble partway through the bar
        for pitch, beats in notes[:stop_at]:
            if beginner and rng.random() < 0.05:
                t += rng.uniform(0.3, 1.2)  # hesitation: looking for the next key
            played = _slip(rng, pitch + transpose, errors)
            for j, p in enumerate(played):
                last_one = j == len(played) - 1
                dur = beats * bar_beat if last_one else rng.uniform(0.12, 0.35)
                _note(events, t + rng.gauss(0, jitter), p, 72 + rng.gauss(0, 8),
                      dur * rng.uniform(0.75, 0.95))
                t += dur
            if not played:
                t += beats * bar_beat
        if left_hand:
            bar_len = sum(b for _, b in notes[:stop_at]) * bar_beat
            for k in range(int(round(sum(b for _, b in notes[:stop_at]) * 2))):
                p = root + (0, 7, 12, 7)[k % 4]
                if beginner and rng.random() < errors:
                    continue
                _note(events, bar_start + k * bar_beat / 2 + rng.gauss(0, jitter), p,
                      58 + rng.gauss(0, 6), bar_beat / 2 * 0.9)
            t = max(t, bar_start + bar_len)
        if stop_at < len(notes):
            restarts += 1
            t += rng.uniform(1.0, 3.5)
            i = max(first, i - rng.randint(1, 3))  # go back a few bars
            continue
        i += 1
    return events, t


def beginner_piece(rng, t, name=None):
    """One attempt at a repertoire piece, the way a learner practises it."""
    name = name or rng.choice(sorted(REPERTOIRE))
    tune = REPERTOIRE[name]
    n = len(tune["bars"])
    bars = (0, n)
    if rng.random() < 0.3:  # work on one half only
        bars = (0, n // 2) if rng.random() < 0.5 else (n // 2, n)
    ev, t = perform(rng, t, tune, tempo=rng.uniform(0.5, 1.0), beginner=True, bars=bars,
                    left_hand=rng.random() < 0.7)
    return name, ev, t


def practice_session(rng, minutes=20.0, skill=0.5, beginner=False, log=None):
    """[(seconds_from_start, msg)] for one session of roughly `minutes`.

    With `beginner`, the pieces come from REPERTOIRE, played with mistakes.
    `log` collects (start, end, what) for every exercise or piece played.
    """
    events, t = [], 0.0
    target = minutes * 60
    tempo = 70 + 50 * skill
    jitter = 0.03 - 0.024 * skill
    while t < target:
        kind = rng.choices(["scale", "arp", "chords", "piece"], [3, 2, 2, 4])[0]
        bpm = tempo * rng.uniform(0.85, 1.15)
        root = rng.choice([48, 50, 53, 55, 57, 60])
        start = t
        if beginner and kind == "piece" and rng.random() < 0.8:
            kind, ev, t = beginner_piece(rng, t)
        elif beginner and kind == "piece":  # sight-reading something new
            kind = "new"
            ev, t = piece(rng, t, bpm * 0.7, bars=rng.randint(8, 16), jitter=0.03)
        elif kind == "scale":
            ev, t = scale(rng, t, bpm, root=root + 12, jitter=jitter)
        elif kind == "arp":
            ev, t = arpeggio(rng, t, bpm, root=root, jitter=jitter)
        elif kind == "chords":
            ev, t = chords(rng, t, bpm, root=root)
        else:
            ev, t = piece(rng, t, bpm, bars=rng.randint(12, 32), jitter=jitter)
        if log is not None:
            log.append((start, t, kind))
        events += ev
        t += rng.uniform(4, 40)  # rest between exercises, under the idle gap
    events.sort(key=lambda e: e[0])
    return events


def feed(recorder, events, t0):
    for dt, msg in events:
        recorder.handle(t0 + dt, msg)
        recorder.tick(t0 + dt)
    return recorder.close_session()


def backfill(store, days=30, seed=None, now=None, beginner=False, log=None):
    """Write `days` of plausible practice history ending today.

    `log` collects (start, end, what) in unix seconds, see practice_session.
    """
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
            spans = []
            ev = practice_session(rng, minutes, skill=0.3 + 0.5 * progress,
                                  beginner=beginner, log=spans)
            t0 = start.timestamp()
            if log is not None:
                log += [(t0 + a, t0 + b, what) for a, b, what in spans]
            sid = feed(rec, ev, t0)
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
