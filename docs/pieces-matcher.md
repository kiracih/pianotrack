# Pieces matcher (trial)

The goal of Pieces is to see time, tempo and steadiness per piece without logging
anything. Step 1 was the matcher and a report, to find out whether a beginner's
playing (wrong notes, restarts, slow tempos) can be grouped reliably. On the
owner's first real session it found the Chopin waltz played last (2026-10-21), and
step 2, the Pieces view on the dashboard, followed. Both use the same matcher.

```
python3 -m pianotrack --db /var/lib/pianotrack/pianotrack.db pieces            # report
python3 -m pianotrack --db /var/lib/pianotrack/pianotrack.db pieces --sessions # plus every segment
python3 -m pianotrack pieces --check --seed 1                                 # score it on simulated practice
```

The report opens the database read-only, so SQLite refuses any write. The dashboard
stores only the names you give pieces (with the n-grams that identify each named
piece, so the name follows the music); grouping is recomputed from the raw notes, and
sessions, replay, `.mid` and `.csv` downloads are untouched.

## How it works (`pianotrack/pieces.py`)

1. **Segments.** Each session is cut at pauses of more than 3.5 s (and every
   4 minutes at most). A restart a few bars back usually comes after a shorter
   pause, so it stays inside the segment. Segments with fewer than 24 melody notes
   are skipped.
2. **Melody.** The top voice: a note counts if no higher note is struck with it or
   held over it. Left-hand notes that show through a legato gap (an octave or
   more below a note just released, or far below both neighbours) are dropped.
3. **Fingerprint.** The pitch intervals between melody notes, taken five notes at a
   time (4-interval n-grams). Intervals don't change with key or tempo, so a piece
   played transposed or slower looks the same. Plain scale runs and mostly
   repeated notes are left out, because every piece has some and they made pieces
   look like scale exercises.
4. **Grouping.** Segments are taken oldest first. A segment joins the group whose
   n-grams cover at least 20% of its own (and at least 6 of them). A wrong note
   spoils the five n-grams around it, so even a 15% error rate leaves roughly half
   of a segment's n-grams intact. Once a group has 5 segments it only uses n-grams
   heard at least twice, so one-off slips don't pile up. Two settled groups whose
   n-grams overlap by 60% or more are joined, which repairs a piece that started
   as two groups.

## Simulated beginner (`simulate.py`, `--beginner`)

A small repertoire of four public-domain pieces (Twinkle, Ode to Joy, Minuet in G,
Für Elise opening), each with a broken-chord left hand, played the way a learner
plays them:

* 10 to 15% of written notes missed, played wrong, or played wrong then corrected
* stops partway through a bar and restarts 1 to 3 bars back
* 50 to 100% of the written tempo, with bar-to-bar drift and hesitations
* sometimes only one half of the piece, sometimes right hand alone
* scales, arpeggios and chord work between pieces, and 20% of "piece" time spent
  sight-reading new music that should match nothing

The simulator logs what it played and when, so every segment has a true answer.

## Results

Gate from the roadmap: at least 9 in 10 segments of a piece on the right piece,
fewer than 1 in 20 of all segments on a wrong one. "Right" means the piece's main
group (its biggest); a segment in a smaller second group of the same piece counts
as not right. "Wrong" means the segment sits in a group of something else, or is
new music grouped with anything.

30 days of simulated beginner practice, 10 different seeds (about 300 piece
segments and 800 segments in all per run):

| Error rate | Right (min / avg) | Wrong (max) | Result |
|---|---|---|---|
| 10 to 15% (the spec) | 95.2% / 97.0% | 2.4% | passes on all 10 |
| 15% always (5 seeds) | 93.2% / 96.9% | 4.6% | passes |
| 20% (5 seeds) | 77.9% / 84.5% | 8.0% | fails: pieces split into 2 to 5 groups |
| 25% (5 seeds) | 34.5% / 54.9% | 12.4% | fails |

Also tested: the same piece transposed (+5, -3 semitones) or 20% faster still
matches; the four pieces never match each other.

## What this does not prove yet

* The simulator was written alongside the matcher, so passing it is necessary but
  not enough. The real test is the owner's own history: run the report on the Pi
  and check whether the groups are the pieces actually played.
* Above about 20% wrong notes (a piece in its first days) a piece tends to split
  into several groups rather than mix with another piece. Splits are joined later
  once both halves have been heard five times.
* Scales and arpeggios form their own groups. They show in the report as pieces
  until a later step names them.
* Hands-separate practice of the left hand alone will form its own group.
