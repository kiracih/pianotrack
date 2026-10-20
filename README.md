# pianotrack

A headless practice tracker for a digital piano, built for a Roland FP-30X plugged
into a Raspberry Pi over USB. The Pi records every note you play, splits it into
practice sessions, and serves a fitness-band style dashboard on your home network.
No phone app, no cloud, no extra Python packages.

![Dashboard](docs/dashboard.png)

<p>
  <img src="docs/phone.png" alt="Dashboard on a phone, dark mode" width="260">
  <img src="docs/session.png" alt="Session detail with replay, effort zones, dynamics and keys played" width="520">
</p>

## What it tracks

| Metric | What it means |
|---|---|
| Active time | Time actually playing. Pauses longer than 3 s stop the clock, so reading the score doesn't count. |
| Daily goal ring, streak, consistency | Minutes against your goal, consecutive days with at least 5 min, and the share of the last 28 days you played. |
| Notes, notes per minute | Volume of playing and how dense it was while playing. |
| Effort zones | Like heart-rate zones: time spent at Rest / Light / Moderate / Vigorous / Peak note density. |
| Intensity and load | A 0 to 100 effort figure from density and loudness, and load = active minutes × intensity / 50. |
| Steadiness, est. tempo | How evenly notes land on a rhythmic grid (100 = metronomic; about 70 means a typical ±10 ms wobble), plus the dominant tempo. |
| Dynamics | Mean velocity, pp to ff distribution, and dynamic range (spread between the quiet and loud 10%). |
| Keys | 88-key heatmap per session and across the last 7, 30 or 90 days or all time, top keys, lowest and highest note, share of notes below middle C. |
| Pedal | Sustain presses and share of time on sustain, soft pedal presses and share of time. |

Tempo, steadiness and intensity are heuristics for following trends over weeks,
the same way a band's calorie count is. They are not a teacher's grade.

![Most used keys](docs/keys.png)

![Session replay](docs/replay.png)

**Session replay:** open any session and press play to hear it back with a grand piano
sound while the keyboard lights up the keys as you pressed them. Sustain and soft pedal
are honoured, playback speed goes from 0.5× to 2×, and "skip pauses" squeezes long
silences so you hear only the playing. The piano samples ship with the app, so replay
works without internet.

Every session can be downloaded as a `.mid` file (handy for replaying what you
played) or as a CSV of notes. `/api/sessions.csv` exports the session list.

## How it works

```
FP-30X ──USB──▶ /dev/snd/midiC1D0 ──▶ collector ──▶ recorder ──▶ SQLite
                                                                   │
                     phone / laptop on wifi ◀── dashboard + API ◀──┘
```

* **Collector** (`collector.py`) reads the ALSA raw MIDI device directly and parses
  the byte stream itself (`midi.py`). If the piano is switched off, it waits and
  reconnects when it comes back.
* **Recorder** (`recorder.py`) opens a session on the first note and closes it after
  3 minutes of silence. Sessions with fewer than 8 notes are discarded. Notes are
  written in batches every 2 s to spare the SD card.
* **Metrics** (`metrics.py`) are computed when a session closes and stored with it.
* **Server** (`server.py`) serves the dashboard and a JSON API on port 8080.

Data never leaves the Pi. The SQLite file lives at `/var/lib/pianotrack/pianotrack.db`
when installed as a service.

## Install on the Raspberry Pi

Needs Raspberry Pi OS (Bookworm or newer, Python 3.9+). Nothing to `pip install`.

```bash
sudo apt install -y git
git clone https://github.com/kiracih/pianotrack.git
cd pianotrack
python3 -m pianotrack devices      # the FP-30X should be listed
./deploy/install.sh                # installs and starts the systemd service
```

Then open `http://<pi-hostname>.local:8080` (for example `http://raspberrypi.local:8080`)
on any device on the same wifi. Add it to your phone's home screen and it opens full screen with its own icon.

Useful commands:

```bash
journalctl -u pianotrack -f        # live log: "opened session", "closed session"
sudo systemctl restart pianotrack
git pull && sudo systemctl restart pianotrack    # update
```

If `devices` shows nothing, check `aconnect -l` and `cat /proc/asound/cards`. The
FP-30X needs to be connected with its **USB to Host** port. Only one program can
open a raw MIDI port at a time, so stop anything else reading the piano.

## Try it without a piano

```bash
# 60 days of realistic simulated history, then the dashboard
python3 -m pianotrack --db /tmp/demo.db backfill --days 60
python3 -m pianotrack --db /tmp/demo.db run --no-collector

# full pipeline: the collector reads a FIFO that the simulator plays into
python3 -m pianotrack --db /tmp/demo.db run --device /tmp/piano.fifo --idle-gap 20 &
python3 -m pianotrack simulate --fifo /tmp/piano.fifo --minutes 3 --speed 2

# import or stream an existing .mid file
python3 -m pianotrack --db /tmp/demo.db replay song.mid
python3 -m pianotrack replay song.mid --fifo /tmp/piano.fifo
```

Run the tests with `python3 -m unittest discover -v tests`.

The screenshots in `docs/` are generated from the simulated data with
`tools/screenshots.mjs` (instructions at the top of that file). Regenerate them
whenever the dashboard changes.

## Options

`python3 -m pianotrack run --help`:

* `--device` a regex for the ALSA card name (default: first non-virtual device, preferring Roland), or a path
* `--port` (8080), `--host` (0.0.0.0)
* `--idle-gap` seconds of silence that end a session (180)
* `--db` or `PIANOTRACK_DB` for the database path

The daily goal is set from the dashboard.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/summary` | today, week, streak, records, totals, live session, collector status |
| `GET /api/status` | collector state: piano connected, device, last MIDI event |
| `GET /api/days?days=365` | active seconds and notes per day |
| `GET /api/trends?days=60` | daily steadiness, notes/min, velocity, dynamic range, tempo |
| `GET /api/keys?days=30` | key usage summed over the period (`days=0` for all time) |
| `GET /api/sessions?limit=50` | session list with headline metrics |
| `GET /api/sessions/<id>` | full metrics, timeline, key histogram |
| `GET /api/sessions/<id>/events` | the session as a time series for replay: notes `[on, off, pitch, velocity]` and pedals `[t, cc, value]`, seconds from start |
| `GET /api/sessions/<id>.mid` / `.csv` | the session as MIDI or notes CSV |
| `GET /api/sessions.csv` | all sessions as CSV |
| `GET/POST /api/settings` | `{"daily_goal_minutes": 30, "streak_min_minutes": 5}` |

## License

Code: MIT. Piano samples in `pianotrack/static/piano/`: Salamander Grand Piano V3 by
Alexander Holm, CC-BY 3.0 (see `ATTRIBUTION.md` there).
