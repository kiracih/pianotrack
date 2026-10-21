# Roadmap

Kept by the product review (one PM cycle per run). Every item ties to one of three
outcomes: **practise better**, **practise more**, or **easier setup**. Effort is S
(an evening), M (a few days), L (a week or more). Nothing here is built until the
owner says so.

Last review: 2026-10-21 (first run). Owner decisions recorded the same day.

## Now

At most three. Owner approved #1 and #2 on 2026-10-21; #1 shipped the same day.

### 1. Practice history backup (bug risk, S) · shipped 2026-10-21 (see Done)

**Problem.** All practice history lives in one SQLite file on the Pi's SD card. SD
cards fail, and there is no copy anywhere, so one bad card loses months of
streaks, records and replays. For the owner today, and a must-have before anyone
else uses it.

**User story.** As the owner, I want my history copied automatically and
downloadable in one tap, so a dead SD card or a bad update never costs me data.

**Acceptance criteria**
- A nightly copy of the database is made with SQLite's online backup (consistent
  while the collector writes), kept as 7 daily + 4 weekly files.
- The rotated copies live on the Pi (`--backup-dir`). On their own they only undo
  bad updates or a corrupted database, not a dead card, so the off-card copy is
  the owner's Mac (owner decision 2026-10-21):
  - A small script plus a launchd agent in `deploy/mac/` pulls the newest backup
    from the Pi over the existing SSH key into a folder on the Mac (default
    `~/Backups/pianotrack/`), keeping the same 7 daily + 4 weekly rotation.
  - The agent runs at login, on wake and every hour. When the Mac is asleep, away
    from home or the Pi is unreachable, it does nothing and quietly tries again on
    the next run, so a missed night is caught up as soon as the Mac is back.
  - Each pull is checked (SQLite `PRAGMA integrity_check`) before replacing
    anything; a failed check keeps the previous copies.
  - The Mac reports each good pull to the Pi (or the Pi notes the file being
    read), so the dashboard shows "last copied to Mac" and warns when the Mac
    hasn't picked up a backup for 3 days.
  - Installing the agent on the Mac is a separate step that waits for the owner's
    go-ahead.
- `GET /api/backup` downloads a consistent copy of the database; it is home
  network only, like the password setting.
- A "Download backup" link in the dashboard's settings area.
- `python3 -m pianotrack --db new.db restore backup.db` (or documented copy steps)
  brings the history back; a test restores a backup and gets the same summary.
- The footer or settings shows the time of the last good backup; a backup older
  than 2 days is shown as a warning.
- README (features, API table, CLI) and screenshots updated; tests pass.

**Out of scope.** Cloud upload for now (Google Drive through rclone, encrypted, is
the planned follow-up if the Mac copy isn't enough), two-way sync, encrypting
backups.

**How we'll know.** A backup file exists every morning; the owner downloads one
and it opens.

### 2. Pieces: know what you practised (practice insight, M) · approved 2026-10-21 as a trial

**Problem.** Every session is anonymous ("Today 19:05, 22 min"). The owner can't
see how long they've spent on a given piece or whether it is getting steadier
and faster, which is the question a teacher asks every week. The market scan
found this ("compare repeated passages over time") is what no tracker does well.

**User story.** As a beginner to early-intermediate pianist learning a piece, I
want sessions grouped by piece with tempo and steadiness over time, so I can see
the piece improve without logging anything, even while I still make plenty of
mistakes.

**Main risk.** The owner plays with wrong notes, hesitations, restarts and slow
tempos. Matching must survive that, so it is built in two steps: first the
matcher alone, measured on simulated beginner playing and then on the owner's real
sessions; the Pieces view only follows if the matcher holds up.

**Acceptance criteria**
- **Step 1 gate:** a matcher report (CLI, e.g. `python3 -m pianotrack pieces
  --report`) groups existing sessions without changing anything stored. With the
  simulator's beginner mode (10 to 15% wrong or missed notes, stops and restarts
  from a few bars back, 50 to 100% tempo) at least 9 in 10 segments land on the
  right piece and fewer than 1 in 20 on a wrong one. Then the owner checks it on
  their real history before step 2 starts.
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
- Session replay, `.mid` and `.csv` downloads stay exactly as they are: the raw
  session is never cut, merged or changed by piece grouping. Pieces only add
  links from a session to the pieces found in it.
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

- 2026-10-21: **Days follow your clock: no action.** Day boundaries use the Pi's
  time zone while times show in the browser's; the owner always plays in one zone
  (UTC+3), so this is parked. That only holds if the Pi itself is set to UTC+3
  (e.g. `Europe/Istanbul`); check `timedatectl` on the Pi at the next deploy and set
  it with `sudo timedatectl set-timezone Europe/Istanbul` if it is UTC. Revisit
  if the owner travels or ships to others.

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
- 2026-10-21: Nightly backups with Mac copy (launchd agent pulls on login, wake and
  hourly), Download backup, Back up now, restore. Live on the Pi; first Mac pull verified.
