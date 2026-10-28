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
| Stumbles | A pause in the middle of a piece far longer than the piece has at that spot: at least twice its usual length there and 0.4 s longer, the usual being how the spot goes in your better plays, scaled to each play's speed. So a note the music holds isn't a stumble, slow practice isn't one long stumble, and a spot you stumble at most of the time still counts. Shown per session and per minute of the piece, lower is smoother. Why this instead of a score: in a study of 17 pianists, practice time and repetitions didn't predict how well they played the next day, but the share of plays without mistakes did (Duke, Simmons & Cash 2009). |
| Longest clean run | The longest stretch of a piece played without a stumble, per session, plus your best ever with ▶ to hear it. |
| Trouble spots | The up to three places in a piece where you stumbled most in its last 10 sessions (at least 3 times), named by the five melody notes before the stumble, with how often: "after C5 D5 E5 D5 C5, 8 of 41 times", and ▶ to hear the latest one. |
| Active time | Time actually playing. Pauses longer than 3 s stop the clock, so reading the score doesn't count. |
| This week | The week as an octave: seven white keys, Monday to Sunday, each filling with felt up to the daily goal and brass when it is met; today's key is outlined. Tap a key for its minutes. Plus days played this week against a weekly target (5 by default, set under Goals), which forgives a missed day the streak would not. |
| Daily goal ring, streak, consistency | Minutes against your goal, consecutive days with at least 5 min, and the share of the last 28 days you played. A line above the ring names the next small step: "5 min keeps your 9-day run going", "24 min to your 30 min goal" or "Goal met today"; after one missed day it says "One day off doesn't undo a habit. 5 min picks it back up.", after a longer break "Welcome back. 5 min is a good start.", instead of greeting you with a zero. On Mondays a line under it says how last week went, so a fresh week doesn't start from a blank octave: "Last week: 6 of 5 days, 3h 10m. Target met." |
| Notes, notes per minute | Volume of playing and how dense it was while playing. |
| Effort zones | Like heart-rate zones: time spent at Rest / Light / Moderate / Vigorous / Peak note density. |
| Intensity and load | A 0 to 100 effort figure from density and loudness, and load = active minutes × intensity / 50. |
| Steadiness, est. tempo | How evenly notes land on a rhythmic grid, measured as a share of the beat so slow practice is judged as fairly as fast playing (100 = metronomic; about 75 means notes land 3.5% of a beat early or late, at any tempo), plus the dominant tempo. Since 2026-10-27; past sessions were recomputed once, after a copy of the database was kept. |
| Dynamics | Mean velocity, pp to ff distribution, and dynamic range (spread between the quiet and loud 10%). |
| Keys | Across the last 7, 30 or 90 days or all time, a 3D keyboard (three.js, bundled) where each key grows a column as tall as you played it, rising left to right like a glissando; brass marks the three most played keys, drag to move along the keyboard, tap a key for its count. It loads only when the card scrolls into view and only where WebGL works. Below it, and per session, the flat 88-key map: keys keep their piano colours and a coloured band on each key, white or black, shows how much it was played (tap a key for its count). Top keys, top black keys, lowest and highest note, share of notes below middle C. |
| Pedal | Sustain presses and share of time on sustain, soft pedal presses and share of time. |
| Pieces | Per piece: active time, sessions, last played, and per-session tempo, stumbles, longest clean run and steadiness (tempo and steadiness active-time weighted over the stretches of that piece). A piece's tempo times its melody phrases against the same phrases in its other plays, so the left hand can't make it read double and a session never jumps 2×; it is counted in the piece's typical melody note. |

**On a phone** the page puts what changes day to day first: Today, This week, Pieces and
recent sessions, then the slower views (trends, calendar, keys, records). Steadiness,
notes per minute and dynamic range share one **Trends** card; on a phone, tabs switch
between them, on a wider screen all three show side by side. Pieces fit the phone
width, with time, last played, Listen and Name under each piece's name. Chart and key tips
open on a tap and close when you tap anywhere else or scroll.

**The look** follows [docs/DESIGN.md](docs/DESIGN.md): a practice room rather than a gym.
Felt claret and brass on plaster and ivory (rosewood in dark mode), serif headings and
figures (New York on Apple devices), goal-met days in brass, and a felt focus ring for
keyboard use.

A session's detail leads with active time, notes, stumbles and the longest clean run;
steadiness, tempo, intensity, effort zones, dynamics, pedals and range sit under
**Details**, folded away. Tempo, steadiness and intensity are heuristics for following trends over weeks,
the same way a band's calorie count is. They are not a teacher's grade.

![Most used keys](docs/keys.png)

![Session replay](docs/replay.png)

**Session replay:** open any session and press play to hear it back with a grand piano
sound. With **Falling notes** (on by default where the browser has WebGL) the notes travel
down a lane onto a 3D keyboard, the next four seconds in view, each note as long as you
held it and taller when played louder. A brass line along the back of the keys marks where notes land;
while one sounds it warms towards brass and its key goes down in felt red (light felt on a
black key), and the view frames the range of keys the session used. Untick it for the flat
88-key keyboard that lights up the keys as you pressed them; the choice is remembered on
that device. While paused it redraws only when you seek, resize or switch theme. Sustain and soft pedal
are honoured, playback speed goes from 0.5× to 2×, and "skip pauses" squeezes long
silences so you hear only the playing. The piano samples ship with the app, so replay
works without internet.

Every session can be downloaded as a `.mid` file (handy for replaying what you
played) or as a CSV of notes. `/api/sessions.csv` exports the session list.

**Backups:** the whole history is copied every night (7 daily and 4 weekly copies), can
be pulled onto a Mac automatically, downloaded from the dashboard, and restored with one
command. See [Backups](#backups).

![Pieces](docs/pieces.png)

**Pieces (trial):** the dashboard groups the stretches of playing that are the same
piece, found from the notes alone, with wrong notes, restarts, slow tempos and all.
Nothing to log. Each piece shows its total time, sessions and when you last played it,
and its tempo and stumbles a minute per session (tap a piece for the charts). From 10 sessions
on, a line under the piece compares its first 5 sessions with its last 5 (medians), e.g.
"153 → 109 bpm, stumbles 3.1 → 1.4 a minute: slowed down to clean up". Pieces show as
"Piece A, B…" with their most played phrase; **Listen** jumps the replay to that phrase
so you can recognise it. Tap a piece to open its tempo and
stumbles charts, its longest clean run (your best and last time, ▶ to hear them), its
trouble spots (▶ opens the session and starts playing 2 s before the latest stumble there) and a list of every
recording of it with its stumbles and clean run, newest first; ▶ plays one from
where the piece starts, so you can hear how it sounded weeks ago. **Name** names it once ("Chopin waltz"). The name follows
the music into later sessions. A session's detail lists the pieces played in it.
A session that closes after everything already grouped is added to the existing
pieces instead of regrouping the whole history (under a second instead of about 17 s with 400
days of practice); a deleted or out-of-order session regroups from scratch.
Grouping never changes your recordings: replay, `.mid` and `.csv` stay exactly as
recorded; only the names you give are stored. Scales and exercises can show up as
pieces too. See [docs/pieces-matcher.md](docs/pieces-matcher.md) for how matching works
and how well it does. `python3 -m pianotrack pieces` prints the same grouping as a
read-only report.

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
* **Pieces** (`pieces.py`) cuts sessions into segments at pauses of 3.5 s, takes the
  melody (top voice), and matches segments by shared runs of pitch intervals, then finds
  stumbles in each play against how that spot usually goes. Pieces heard
  3+ times are listed, recomputed from the raw notes after each new session. Each
  session's segments are kept in the database (tagged with the matcher's version), so a
  restart re-matches without re-reading every note; while the first pass runs, the
  dashboard says the pieces are still being found instead of waiting.
* **Store** (`store.py`) keeps everything in one SQLite file. Its schema carries a version
  number (`PRAGMA user_version`); schema changes are added as numbered steps and an older
  database is upgraded when it opens, while a database from a newer version is refused.
  Every session carries a random `uid` and the id of the device that recorded it, so
  sessions from several devices (a second Pi, the iOS app) can be merged later without
  clashes.
* **Server** (`server.py`) serves the dashboard and a JSON API on port 8080, plus a
  localhost-only entrance on 8081 for the remote link (see below).
* **Backups** (`backup.py`) copy the database every night (see below).

Data never leaves your home. The SQLite file lives at `/var/lib/pianotrack/pianotrack.db`
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

At boot the service waits up to 90 seconds for the clock to sync over the network,
because the Pi has no battery-backed clock and session times would otherwise be
wrong just after boot. If the Pi is offline it starts anyway.

Useful commands:

```bash
journalctl -u pianotrack -f        # live log: "opened session", "closed session"
sudo systemctl restart pianotrack
git pull && sudo systemctl restart pianotrack    # update
```

If `devices` shows nothing, check `aconnect -l` and `cat /proc/asound/cards`. The
FP-30X needs to be connected with its **USB to Host** port. Only one program can
open a raw MIDI port at a time, so stop anything else reading the piano.

## Reach it from outside your home

`deploy/install-tunnel.sh` publishes the dashboard through a Cloudflare
[Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/): no
Cloudflare account, domain or router change needed.

```bash
./deploy/install-tunnel.sh
```

Then open the dashboard at home and set a password under **Remote access**. Until a
password exists, anything coming through the tunnel is refused. Visitors through the
tunnel see a sign-in page once per device and stay signed in for 30 days; on the home
network no password is asked. Five wrong attempts lock that visitor out for 15 minutes,
and 20 wrong attempts from anywhere within an hour pause all sign-ins for a while.
Setting a new password, or **Sign out all devices** (in Remote access at home, or in the
footer of a signed-in remote visit), signs every device out. The password can only be set
or changed from the home network.

<img src="docs/login.png" alt="Sign-in page shown to visitors through the tunnel" width="260">

How it tells the two apart: cloudflared connects to a second port, 8081
(`--tunnel-port`), which listens only on the Pi itself, and every request on that port
needs the password. On the home port, 8080, a request still counts as remote when it
carries Cloudflare headers (`Cf-Ray`, `Cf-Connecting-Ip`) or comes from an address
outside the home network, so opening 8080 to the internet by mistake would not skip the
password.

The home network itself is protected from web pages: any site you visit could make your
browser send requests to the Pi, so without a password the Pi still only answers
requests addressed to it by IP, as `pi4.local` or `localhost`, or by its hostname (add
others with `--allowed-host`), and only accepts changes sent as JSON by its own pages.

The link is a random `https://….trycloudflare.com` address that **changes whenever the
tunnel restarts** (for example after a reboot). The dashboard footer shows the current
one when you open it at home, and `cat /var/lib/pianotrack/tunnel-url` prints it.

Cloudflare's own email-code gate ([Protected Quick
Tunnels](https://blog.cloudflare.com/protected-quick-tunnels/)) can be added in front by
passing emails: `./deploy/install-tunnel.sh you@example.com`. As of October 2026 it signs
you out about 10 seconds after login, which breaks every button on the dashboard
([cloudflared#1752](https://github.com/cloudflare/cloudflared/issues/1752)), so it is
off by default.

To stop remote access: `sudo systemctl disable --now pianotrack-tunnel`.

## Public demo

To show the dashboard to other people without showing your own practice, run a demo
next to the real one. It serves four months of simulated practice by a made-up beginner
(the four repertoire pieces, named, with wrong notes and restarts), needs no password,
and refuses every change: goals, piece names, password and backups are hidden, and their
API calls get 403.

```bash
./deploy/install-demo.sh          # prints the demo's own https://….trycloudflare.com link
./deploy/install-demo.sh --remove # takes it down again
```

It runs as its own services, `pianotrack-demo` (ports 8090 on the home network and 8091
for its tunnel) and `pianotrack-demo-tunnel`, with its own database in
`/var/lib/pianotrack-demo/`. The real service, database, password and link are not
touched, and `run --demo` refuses a database that holds any session the simulator did
not make, so pointing it at the real one by mistake changes nothing. The history is
rebuilt on the first start of each day, so it always ends today; a timer restarts the
demo at 04:15 for that (the rebuild takes a few minutes on a Pi 4, while the link
answers with an error). Like the real one, the link changes when its tunnel restarts:
`cat /var/lib/pianotrack-demo/tunnel-url` prints it.

Locally: `python3 -m pianotrack --db /tmp/demo.db run --demo --port 8099`.

## Backups

Every night at 03:30 (or within a few minutes of starting, if the last copy is more
than a day old) the Pi copies the database with SQLite's online backup, which is
consistent even while you play. Each copy passes an integrity check before it is put
in place. Copies (and the dashboard download) leave out the remote login's cookie key, so
someone holding a copy can't make their own login; restoring one signs every device out,
and your password still works. The backup folder keeps **7 daily and 4 weekly** copies
(`daily-2026-10-21.db`, `weekly-2026-W43.db`); by default it is
`/var/lib/pianotrack/backups`, set with `--backup-dir` or `PIANOTRACK_BACKUP_DIR`.

<img src="docs/backup.png" alt="Backup box in the dashboard: last backup, last copy to the Mac, download button" width="380">

The **Backup** box on the dashboard shows when the last copy was made, with a warning
when it is more than 2 days old or the last attempt failed. At home it also has
**Download backup** (a fresh copy, `GET /api/backup`) and **Back up now**. Neither works
through the remote link.

**Copy to a Mac.** Copies on the Pi undo a bad update or a damaged database, but not a
dead SD card. `deploy/mac/` pulls the newest backup onto a Mac over the SSH key you
already use for the Pi:

```bash
./deploy/mac/install.sh raspberry@192.168.1.108    # run on the Mac
```

This installs a launchd agent that runs at login, when the Mac wakes and every hour.
If the Pi can't be reached (Mac away from home, Pi off) it does nothing and tries again
next time, so a missed night is caught up as soon as both are home. Each copy is checked
with `PRAGMA integrity_check` before it replaces anything, and the Mac keeps its own 7
daily and 4 weekly copies in `~/Backups/pianotrack/`. After each copy the Mac leaves a
note on the Pi, so the dashboard shows "Last copied to <Mac>" and warns when that is more
than 3 days old. Log: `~/Library/Logs/pianotrack-backup.log`. Remove with
`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.pianotrack.backup.plist`.
Alternatively, point `--backup-dir` at a USB stick.

**Restore.** Stop the service, restore, start it again:

```bash
sudo systemctl stop pianotrack
python3 -m pianotrack --db /var/lib/pianotrack/pianotrack.db restore --force ~/daily-2026-10-21.db
sudo systemctl start pianotrack
```

`restore` checks the backup first, refuses to overwrite a database that has sessions
unless you pass `--force`, and keeps the replaced one as
`pianotrack.db.before-restore-<time>`. On a fresh SD card, install as usual, then restore
into the empty database. `python3 -m pianotrack backup` makes a copy by hand.

## Try it without a piano

```bash
# 60 days of simulated history (--beginner plays a small repertoire with a learner's
# mistakes, so Pieces has something to find), then the dashboard
python3 -m pianotrack --db /tmp/demo.db backfill --days 60 --beginner
python3 -m pianotrack --db /tmp/demo.db run --no-collector

# full pipeline: the collector reads a FIFO that the simulator plays into
python3 -m pianotrack --db /tmp/demo.db run --device /tmp/piano.fifo --idle-gap 20 &
python3 -m pianotrack simulate --fifo /tmp/piano.fifo --minutes 3 --speed 2

# a learner's practice: 4 short pieces with 10-15% wrong or missed notes, restarts
# and 50-100% tempo, then the pieces report on it
python3 -m pianotrack --db /tmp/beginner.db backfill --days 30 --beginner
python3 -m pianotrack --db /tmp/beginner.db pieces --sessions

# score the pieces matcher against simulated beginner practice (exit code 1 on fail)
python3 -m pianotrack pieces --check --seed 1

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
* `--tunnel-port` (8081) the port cloudflared forwards to; it listens on 127.0.0.1 only and always asks for the password (0 turns it off)
* `--allowed-host NAME` another name the home network uses for the Pi, besides its IP, hostname, `*.local` and `localhost` (repeatable)
* `--idle-gap` seconds of silence that end a session (180)
* `--db` or `PIANOTRACK_DB` for the database path
* `--backup-dir` or `PIANOTRACK_BACKUP_DIR` folder for the nightly copies (default `backups/` next to the database)
* `--backup-time` local time of the nightly copy (03:30), `--no-backup` to turn copies off
* `--demo` rebuild `--db` with simulated practice (once a day) and serve it read-only with no password, no collector and no backups; refused on a database with real recordings. `--demo-days` sets the history length (120)

Other commands: `backup [--backup-dir DIR]` copies the database now, `restore FILE [--force]`
replaces the database with a backup, `recompute [--dry-run]` brings stored session metrics
up to the current formulas (`run` does this in the background after it starts, while recording goes on; it first keeps a checked copy as
`<db>.pre-metrics-v<N>.db`, writes every session in one transaction, and does nothing
when all are current), and `devices`, `backfill`, `simulate`, `replay`
(see above).

The daily goal is set from the dashboard.

`python3 -m pianotrack pieces --help` (read-only report):

* `--days N` only the last N days (default: all history)
* `--sessions` also list every segment with the piece it matched
* `--check` run on simulated beginner practice instead of the database and print
  the right/wrong rates; `--seed` picks the simulation

`backfill` and `simulate` take `--beginner` to play the simulator's small repertoire
the way a learner does.

`python3 -m pianotrack vectors [--out DIR]` rewrites the engine test vectors in
`tests/vectors/`: fixed MIDI input and the sessions, metrics, daily totals, streaks and
pieces the engine makes of it, so a port of the engine (such as the planned iOS app) can
be checked against this one. See [docs/engine-vectors.md](docs/engine-vectors.md).

## API

POST requests send JSON (`Content-Type: application/json`); anything else gets 415. Bad
query values get 400 with an `error` message.

| Endpoint | Returns |
|---|---|
| `GET /api/summary` | today (with `invite`, the line above the ring), week, streak, `week_days` (played and target, Monday to today), `last_week` on Mondays only, else null (`start`, `played`, `target`, `met`, `active_seconds` for last Monday to Sunday), records, totals, live session, collector status, `demo` |
| `GET /api/status` | collector state: piano connected, device, last MIDI event |
| `GET /api/auth` | `{"password_set": ..., "remote": ..., "demo": ...}` whether a remote password exists, whether this request came through the tunnel, and whether this is the read-only demo |
| `POST /api/password` | `{"password": "..."}` sets the remote-access password (home network only, 8+ characters) |
| `GET /login`, `POST /login`, `GET /logout` | sign-in page for tunnel visitors |
| `POST /api/signout-all` | signs every remote device out (the password stays) |
| `GET /api/backup` | a fresh, consistent copy of the database as a `.db` file (home network only) |
| `POST /api/backup` | make a backup into the backup folder now (home network only); returns the status below |
| `GET /api/backups` | backup folder, last backup time, `stale` (over 2 days), daily/weekly counts, last error, and `offsite`: when and by which machine the last copy was pulled (`offsite_stale` after 3 days) |
| `GET /api/tunnel` | `{"url": ...}` the current remote link, or null when no tunnel runs |
| `GET /api/days?days=365` | active seconds and notes per day |
| `GET /api/trends?days=60` | daily steadiness, notes/min, velocity, dynamic range, tempo |
| `GET /api/keys?days=30` | key usage summed over the period (`days=0` for all time) |
| `GET /api/sessions?limit=50` | session list with headline metrics, each with `uid` (a UUID that stays with the session, for syncing) and `device` (the id of the database that recorded it) |
| `GET /api/sessions/<id>` | full metrics, timeline, key histogram, `uid`, `device`, and the pieces played in it with their `stumbles` and `clean_run` (`pieces_pending` is true while they are still being found, e.g. after a restart or right after the session closes: this request never runs a Pieces pass itself, it starts one in the background and the dashboard asks again) |
| `GET /api/sessions/<id>/events` | the session as a time series for replay: notes `[on, off, pitch, velocity]` and pedals `[t, cc, value]`, seconds from start |
| `GET /api/sessions/<id>.mid` / `.csv` | the session as MIDI or notes CSV |
| `GET /api/sessions.csv` | all sessions as CSV |
| `GET /api/pieces` | 503 with `{"warming": true}` and `Retry-After: 3` while the first pass after a restart runs (the dashboard says "Finding your pieces…" and asks again), otherwise the pieces found in the history, most recently played first: `key`, `label`, `name`, `active_seconds`, `sessions`, `last`, `opening` (most played phrase and where to hear it), `history` per session (`session`, `start`, `offset` (seconds into the session to play this recording from, 1 s before the piece), `active_seconds`, `tempo_bpm`, `steadiness`, `stumbles`, `stumbles_per_min` (null under 30 s), `clean_run` in seconds and `clean_run_offset` to play it from), `best_run` (`seconds`, `session`, `offset`), `trouble` (up to 3: `notes`, `stumbles`, `passes`, `session`, `offset`) |
| `POST /api/pieces/name` | `{"key": "...", "name": "..."}` names a piece (empty name forgets it); returns the pieces |
| `GET/POST /api/settings` | `{"daily_goal_minutes": 30, "streak_min_minutes": 5, "weekly_days_target": 5}` |

## Roadmap

What's planned next, and ideas already decided against, are in
[docs/ROADMAP.md](docs/ROADMAP.md).

## License

Code: MIT. three.js 0.180.0 in `pianotrack/static/vendor/`: MIT (see `three-LICENSE` there),
served from the Pi, nothing loaded from the internet. Piano samples in `pianotrack/static/piano/`: Salamander Grand Piano V3 by
Alexander Holm, CC-BY 3.0 (see `ATTRIBUTION.md` there).
