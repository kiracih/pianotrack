# Engine test vectors

The planned iOS app needs the same engine as the Pi: the recorder that turns MIDI into
sessions, the per-session and daily metrics, and the pieces matcher. The files in
`tests/vectors/` pin down what the Python engine does, so a port (Swift or anything
else) can be checked against them and give the same minutes, streaks and pieces.

`python3 -m pianotrack vectors` rewrites them from `pianotrack/vectors.py`.
`tests/test_vectors.py` re-runs the engine and fails if its output no longer matches,
so after an intended engine change, regenerate the files and commit them with it.

## The cases

| File | What it covers |
|---|---|
| `clean-session.json` | One 6-minute session of scales, arpeggios, chords with pedal and a piece, played cleanly. All session metrics. |
| `beginner-session.json` | One beginner session: wrong and missed notes, stops, restarts, slow tempos. |
| `recorder-edges.json` | Small, hand-made: sustain pressed before the first note (ignored), note-on with velocity 0 as a release, a retriggered key, the drum channel, All Notes Off, a 5-note session (discarded), a stuck key, sessions split by the 180 s idle gap. |
| `two-weeks-beginner.json` | Two weeks of beginner practice with two rest days and a session starting at 23:56: daily totals, current and longest streak, 28-day consistency and pieces. |

## Format (version 1)

Each file is one JSON object:

```json
{
  "format": 1,
  "name": "recorder-edges",
  "description": "...",
  "settings": {"timezone": "Europe/Istanbul", "today": "2026-10-03",
               "idle_gap_seconds": 180.0, "min_notes": 8, "streak_min_minutes": 5},
  "input": [[1791039599.0, [176, 64, 127]], [1791039600.0, [144, 60, 60]], ...],
  "expected": {"sessions": [...], "days": {...}, "streak": {...},
               "consistency_28d": 43, "pieces": [...]}
}
```

**input** is every MIDI channel message in order: unix time in seconds (3 decimals)
and the message bytes (status, data1, data2). Active sensing and clock bytes are
already removed, as the MIDI parser does.

**How to replay it.** For each message, first `tick(t)` (close the session if it has
been idle for `idle_gap_seconds`, or twice that while a key is still held), then
`handle(t, message)`. After the last message, close the open session. This is what
the Pi's collector does, since it ticks every half second between messages.

Rules the recorder follows (see `pianotrack/recorder.py`):
- A session opens on the first note-on with velocity above 0. Pedal messages
  (CC 64, 66, 67) only count while a session is open.
- A note is stored when released: `[t_on, t_off, pitch, velocity, channel]`.
  A note-on for a held key releases it first. CC 120 or 123 releases everything.
- A session with fewer than `min_notes` notes is discarded.
- Times are local in `settings.timezone`; a session belongs to the day it starts.

**expected**:
- `sessions`: closed sessions, oldest first, each with `start`, `end`, `notes`,
  `pedals` (`[t, cc, value]`) and `metrics` (as `pianotrack/metrics.py`
  `session_metrics` returns them, including the key histogram and timeline, and `v`, the
  formula version, now 2). Since v2 steadiness is `round(100·exp(−mean(rel)/0.12))`, where
  `rel = min(|x − r·local| / local, 0.6)` for each inter-onset interval `x`, its local beat
  `local` (median of the 4 intervals on each side) and nearest simple ratio `r`;
  `timing_error_ms` is still the mean of `min(|x − r·local|, 0.15 s)` in milliseconds.
- `days`: per local date, `active_seconds`, `notes`, `sessions`, `load`.
- `streak`: `current` and `longest` run of days with at least `streak_min_minutes`,
  as of `settings.today`. `consistency_28d`: share of the 28 days up to today with
  any practice.
- `pieces`: as `/api/pieces` returns them, except that sessions are referred to by
  their index in `sessions` and the internal `key` is left out. A piece's per-session
  `tempo_bpm` comes from `pieces.piece_tempo`: five-note melody phrases are timed against
  the same phrases in the piece's other plays (relative speed), times one beat per piece
  (its typical melody note, folded into 60–180 once). Each history entry's `offset` is
  where to play that recording from: 1 s before the piece's first stretch in that session (never before
  the session start), in seconds from its start. Since 2026-10-25; before, it was
  the session tempo of each segment, which often read the left hand's double beat.
  Stumbles (since 2026-10-28) come from `pieces.piece_stumbles`: for each gap between
  melody notes, its spot is the four intervals up to and across it; the usual gap at a
  spot is the 30th percentile of that spot's gaps over all plays of the piece (spots seen
  3+ times), each play scaled by its median ratio to those (when it has 8+ known gaps).
  A gap is a stumble when it is over 2× the usual and 0.4 s longer (at an unknown spot:
  3× the play's median gap; a spot whose usual gap is 0 counts as unknown); stumbling gaps
  within 2 notes of the previous one count as one stumble. `clean_run` is the longest
  melody stretch between stumbling gaps; it and `best_run` play from 1 s before that
  stretch (`clean_run_offset`, `best_run.offset`); `trouble` counts the five melody notes up to each stumble
  over the piece's last 10 sessions (3+ stumbles, at most 3 spots, `passes` = times
  those five notes were played), `offset` 2 s before the latest stumble's first note.

## Matching

Integers and strings should match exactly. Metrics are already rounded (mostly to
0.1); allow a difference of one unit in the last decimal for floats, since
floating-point summation order can differ between languages. Pieces should match
exactly in grouping, labels and per-session history; offsets within 0.01 s.
