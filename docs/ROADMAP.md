# Roadmap

Kept by the product review (one PM cycle per run). Every item ties to one of three
outcomes: **practise better**, **practise more**, or **easier setup**. Effort is S
(an evening), M (a few days), L (a week or more). Nothing here is built until the
owner says so.

Last review: 2026-10-21 (first run).

## Now

At most three. Waiting for the owner to pick which ones to build.

### 1. Practice history backup (bug risk, S)

**Problem.** All practice history lives in one SQLite file on the Pi's SD card. SD
cards fail, and there is no copy anywhere, so one bad card loses months of
streaks, records and replays. For the owner today, and a must-have before anyone
else uses it.

**User story.** As the owner, I want my history copied automatically and
downloadable in one tap, so a dead SD card or a bad update never costs me data.

**Acceptance criteria**
- A nightly copy of the database is made with SQLite's online backup (consistent
  while the collector writes), kept as 7 daily + 4 weekly files.
- The copies go to a backup folder set with `--backup-dir` that is meant to be off
  the SD card (a USB stick, or a share on another machine). Copies kept on the SD
  card only undo bad updates or a corrupted database, not a dead card, so the
  dashboard warns while no off-card folder is set. *Owner decision: USB stick or
  the Mac.*
- `GET /api/backup` downloads a consistent copy of the database; it is home
  network only, like the password setting.
- A "Download backup" link in the dashboard's settings area.
- `python3 -m pianotrack --db new.db restore backup.db` (or documented copy steps)
  brings the history back; a test restores a backup and gets the same summary.
- The footer or settings shows the time of the last good backup; a backup older
  than 2 days is shown as a warning.
- README (features, API table, CLI) and screenshots updated; tests pass.

**Out of scope.** Cloud upload, two-way sync, encrypting backups.

**How we'll know.** A backup file exists every morning; the owner downloads one
and it opens.

### 2. Days follow your clock (bug, S)

**Problem.** "Today", the goal ring, streaks and the calendar are split at
midnight in the **Pi's** time zone (`date.today()` in `server.py` and
`metrics.local_day`), while session times are shown in the **browser's** time
zone. A Pi left on the default UTC puts a 01:00 session in Istanbul on the
previous day, can break a streak, and resets the goal ring at 03:00 local time.
Not yet checked on the owner's Pi (`timedatectl` will tell).

**User story.** As a pianist who sometimes practises late, I want a session to
count for the day it happened on my clock, so my streak and ring are right.

**Acceptance criteria**
- `deploy/install.sh` warns when the Pi's time zone is UTC and prints the
  `sudo timedatectl set-timezone …` command.
- The dashboard shows a one-line warning when the browser's UTC offset differs
  from the server's (the API reports the server's zone and offset).
- A test runs daily totals and streaks under two `TZ` settings and checks that a
  session at 23:30 and one at 00:30 land on different days in local time.
- README updated (install section).

**Out of scope.** Per-user time zones, travel.

**How we'll know.** The owner's late sessions show on the right day; the
warning is never shown on the owner's own setup after the fix.

### 3. Pieces: know what you practised (practice insight, M)

**Problem.** Every session is anonymous ("Today 19:05, 22 min"). The owner can't
see how long they've spent on a given piece or whether it is getting steadier
and faster, which is the question a teacher asks every week. The market scan
found this ("compare repeated passages over time") is what no tracker does well.

**User story.** As a pianist learning a piece, I want sessions grouped by piece
with tempo and steadiness over time, so I can see the piece improve without
logging anything.

**Acceptance criteria**
- When a session closes, its melody is fingerprinted (pitch-interval n-grams of
  the top voice, transposition-insensitive) and matched against earlier sessions;
  sessions that share enough material are grouped as one piece, automatically.
- A session can contain several pieces; matching works on segments of a few
  minutes, not only whole sessions.
- The owner can name a piece once ("Clair de lune"); the name sticks to future
  matches. Naming is optional; unnamed pieces show as "Piece A, B…" with a mini
  replay of the opening bars to recognise it.
- A Pieces view lists each piece with total time, last played, and a chart of
  tempo and steadiness per session.
- Simulator gains 3 to 4 repeating "pieces" so tests and screenshots show real
  grouping; a test checks the same piece played transposed or 20% faster still
  matches, and two different pieces don't.
- README (features, metrics, API) and screenshots updated.

**Out of scope.** Recognising published pieces by title, sheet music, accuracy
against a score, scales/exercises detection (later).

**How we'll know.** After two weeks the owner's real sessions group into the
pieces they actually played (owner confirms), and they open the Pieces view
more than once a week.

## Next

1. **Streak-at-risk nudge to the phone** (habit, S–M). Problem: the streak breaks
   on evenings you simply forget. A notification at a chosen time ("12 min to
   your goal, streak 9 days") when today is short. Needs a push channel: ntfy
   (one HTTP POST, stdlib only) is easiest but sends the message text through a
   third-party server unless self-hosted. *Owner decision needed.*
2. **Weekly target instead of all-or-nothing streak** (habit, S). Problem: one
   missed day resets a long streak, which demotivates. Add "5 of 7 days" weekly
   goal and a weekly summary card (time, best day, change vs last week).
3. **Ignore accompaniment and split channels** (setup / data quality, S).
   Problem: notes from every MIDI channel count, so rhythm or song playback sent
   over MIDI inflates practice. Add a channel filter setting (default: all) and
   count song-playback channels separately.
4. **Pedal held before the first note** (bug, S). Problem: pedal events are only
   recorded once a session is open, so a pedal pressed just before the first
   note is lost and sustain share reads low. Remember the last pedal state and
   write it at session start.
5. **Bluetooth MIDI and other ALSA sequencer sources** (setup, L). Problem: the
   collector only reads raw USB MIDI, so the FP-30X's own Bluetooth, a second
   instrument, or software ports can't be tracked. Needs reading `/dev/snd/seq`
   with stdlib ioctls.

## Later

- **Browser mode (Web MIDI)**: same dashboard, capture from a Chrome/Edge tab, no
  Pi. First step toward a product others can try (see the
  [Pianotrack beyond the Pi](https://claude.ai/artifact/3tuwsgPuDxTURj3R45KrAs) analysis).
- **Teacher/parent share link**: read-only weekly view for a teacher.
- **Summary scales with history**: `/api/summary` recomputes over 400 days of
  sessions on every load; cache daily totals before it gets slow on the Pi.
- **Repeated passage drill view**: once Pieces exist, show the bars you repeat
  most (where you get stuck) and whether they're getting steadier.
- **Android app / plug-in box / pricing**: only after browser mode shows demand.

## Decided and rejected

- 2026-10-21: **Keep the random trycloudflare link** rather than buy a domain for a
  named tunnel (owner's choice). Revisit only if the owner asks.
- 2026-10-21: **Own password login instead of Cloudflare's email gate**, because
  Cloudflare's gate signs you out after about 10 s (cloudflared#1752). Switch back
  if Cloudflare fixes it.
- Rejected: **manual practice logging** of any kind (timers, forms). The product's
  point is that nothing has to be logged. Naming a piece once (Now #3) is the only
  optional input.
- Rejected for now: **sending practice data to a cloud service.** Data stays on the
  Pi unless the owner opts in.

## Done

- 2026-10-20: MIDI collector, sessions, metrics, dashboard, simulator.
- 2026-10-20: Key heatmap over 7/30/90 days, soft pedal stats, home screen icon.
- 2026-10-20: Session replay with grand piano sound and live keyboard.
- 2026-10-20: README screenshots generated by script; docs checks in tests.
- 2026-10-21: Boot waits for network time (no RTC on the Pi).
- 2026-10-21: Remote access through a Cloudflare Quick Tunnel.
- 2026-10-21: Password login for tunnel visitors; replay fixed behind Cloudflare.
