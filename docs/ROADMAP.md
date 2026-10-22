# Roadmap

Kept by the product review (one PM cycle per run). Every item ties to one of three
outcomes: **practise better**, **practise more**, or **easier setup**. Effort is S
(an evening), M (a few days), L (a week or more). Nothing here is built until the
owner says so.

Last review: 2026-10-22 (from now on the review also tracks the app target below).
Previous: 2026-10-21 (first run, owner decisions recorded the same day).

## Now

At most three. Proposed 2026-10-22; nothing is built until the owner says go.

### 1. Today's pieces on the Today card (practice insight, S) · today's increment

**Problem.** The Today card says *how much* you played (minutes, notes, streak) but
not *what*, and not whether it went better than last time. The answer to "did the
waltz get better?" sits three screens down in the Pieces table, and on a phone the
three flat trend charts (steadiness, notes per minute, dynamic range, each "up 0
over the period") come first. Pieces is the only metric that tells a learner they
are improving, so it should be the first thing they see after playing.

**User story.** As the owner, when I open the dashboard after practising, I want to
see which pieces I played today and how each compares with the last time I played
it, so I know at a glance whether today's practice moved anything.

**Acceptance criteria**
- Under the ring, the Today card lists up to 3 pieces played today, most time
  first: name (or "Piece C" with its phrase), time today, tempo and steadiness
  today, and the change vs the previous day that piece was played ("+6 bpm",
  "steadier +4"). No previous day: "first time".
- Changes smaller than the noise (tempo within ±3 bpm, steadiness within ±3) read
  "about the same" rather than "+1".
- Tapping a piece opens that piece's charts in the Pieces card (existing view).
- Nothing played today, or no pieces found yet: the line is hidden, the card looks
  exactly as now.
- Data comes from the existing pieces grouping (`/api/summary` gains a
  `today_pieces` list, or the page reuses `/api/pieces`); raw sessions, replay,
  `.mid` and `.csv` are untouched.
- Small fix in the same change: trend notes say "steady" instead of "up 0" / "down 0".
- Tests: a simulated day with two pieces returns both with the right deltas; a day
  with none returns an empty list. README (features, API) and screenshots updated.

**Out of scope.** Goals per piece, notifications, reordering the rest of the page
(see Next #1).

**How we'll know.** The owner can say what changed today without scrolling; over a
week they tap through to a piece's charts from the Today card.

### 2. Pieces trial: watch it on real practice (practice insight) · in trial

Step 1 (matcher) and step 2 (Pieces card, naming, Listen) shipped and deployed
2026-10-21; spec in git history (roadmap as of 3c78ef1). Open question for the next
reviews: does the Chopin A minor waltz stay **one** piece across several days of
real practice, and do left-hand-alone stretches show up as separate pieces? Needs a
look at the Pi's real data (owner's go-ahead) or the owner's own check. Graduates
from "trial" when the owner confirms the grouping after about two weeks.

### 3. Engine test vectors (app path, M) · proposed

**Problem.** Every app route (browser mode, phone app, plug-in box) needs the
recorder, metrics and pieces engine outside Python. Porting it without a fixed
reference means the phone and the Pi will disagree on minutes, streaks and pieces.

**Acceptance criteria**
- A command writes golden files from the simulator: a few `.mid` inputs (beginner
  and clean, two pieces, a pause-heavy session) and the exact sessions, metrics and
  piece groups the Python engine produces for them, as JSON in `tests/vectors/`.
- A Python test re-runs the engine and fails on any drift, so the vectors stay true.
- The format is documented in a short `docs/engine-vectors.md`, written for whoever
  ports the engine.
- No change to anything the owner sees.

**Out of scope.** The JavaScript port itself (milestone 2 below).

**How we'll know.** A port can be checked against the vectors with one command.

## Next

1. **Phone-first page order** (polish, S). Problem: on a phone you scroll past three
   flat trend charts to reach Pieces and the session list, the parts that change day
   to day. Order becomes Today, This week, Pieces, Sessions, then one "Trends" card
   with the three charts as tabs, calendar and keys below. Desktop keeps its grid.
2. **Streak-at-risk nudge to the phone** (habit, S–M). Problem: the streak breaks
   on evenings you simply forget. A notification at a chosen time ("12 min to
   your goal, streak 9 days") when today is short. Needs a push channel: ntfy
   (one HTTP POST, stdlib only) is easiest but sends the message text through a
   third-party server unless self-hosted. *Owner decision needed.*
3. **Weekly target instead of all-or-nothing streak** (habit, S). Problem: one
   missed day resets a long streak, which demotivates. Add "5 of 7 days" weekly
   goal and a weekly summary card (time, best day, change vs last week).
4. **Ignore accompaniment and split channels** (setup / data quality, S).
   Problem: notes from every MIDI channel count, so rhythm or song playback sent
   over MIDI inflates practice. Add a channel filter setting (default: all) and
   count song-playback channels separately.
5. **Pedal held before the first note** (bug, S). Problem: pedal events are only
   recorded once a session is open, so a pedal pressed just before the first
   note is lost and sustain share reads low. Remember the last pedal state and
   write it at session start.

## Later

- **Browser mode (Web MIDI)**: same dashboard, capture from a Chrome/Edge tab, no
  Pi. First step toward a product others can try (see the
  [Pianotrack beyond the Pi](https://claude.ai/artifact/3tuwsgPuDxTURj3R45KrAs) analysis).
- **Teacher/parent share link**: read-only weekly view for a teacher.
- **Summary scales with history**: `/api/summary` recomputes over 400 days of
  sessions on every load; cache daily totals before it gets slow on the Pi.
- **Repeated passage drill view**: once Pieces exist, show the bars you repeat
  most (where you get stuck) and whether they're getting steadier.
- **Android app / plug-in box / pricing**: see App target; hardware only after preorders.
- **Bluetooth MIDI and other ALSA sequencer sources** (setup, L). Problem: the collector only reads raw USB MIDI, so the FP-30X's own Bluetooth, a second instrument, or software ports can't be tracked. Needs reading `/dev/snd/seq` with stdlib ioctls.
- **Pieces recompute cost**: every new session regroups the whole history in memory
  (segments are cached, matching is not). Fine for months; measure on the Pi at a
  year of data before it slows the first load after practice.
- **Per-piece goals**: "Waltz at 120 bpm, steady 60" with a progress bar, once the
  Pieces trial graduates.

## App target

The end goal is a (probably mobile) app: sit down, play, and the phone shows what
you practised and whether it is getting better, with no Pi to build. The Pi stays as
the open-source, always-on option and becomes a "hub" the app can sync from.
Reviewed every run; changes are dated.

### Features the app needs (2026-10-22)

Must have for a first public version:
- **Automatic capture** from Bluetooth MIDI (most current digital pianos) and USB
  MIDI (Android OTG). On iOS, plan on "keep the app open on the music stand"
  (no Web MIDI in Safari; background MIDI only with an audio session).
- **Today**: goal ring, streak, weekly target, today's pieces vs last time.
- **Pieces**: automatic grouping, naming, tempo and steadiness over time.
- **Session replay** with piano sound and keyboard, `.mid` export.
- **Reminders**: streak at risk, weekly summary (native push, no third party).
- **Local-first data** with backup/export and restore; no account needed to start.
- **Onboarding**: pair the piano in under a minute, choose a daily goal, done.

Later / paid tier:
- Teacher or parent share link (read-only weekly view) and teacher plan.
- Pi hub sync (the always-on recorder at home feeds the phone).
- Several instruments and family profiles; channel filter for arranger keyboards.
- Repeated-passage drill view; per-piece goals.

### Path from today's Pi + web dashboard (each step ships on its own)

1. **Phone-quality web app (now).** The current dashboard as an installable home
   screen app: phone-first layout, today's pieces, reminders. Proves which screens
   matter. *Roadmap: Now #1, Next #1–3.*
2. **Portable engine.** Golden test vectors from the Python engine (Now #3), then
   a JavaScript port of recorder, metrics and pieces that passes them. One engine
   for browser, phone and Pi dashboard.
3. **Browser mode (Web MIDI).** The same page captures from Chrome/Edge/Android
   Chrome and stores in IndexedDB; export/import in the Pi's database format.
   First thing others can try with no hardware; measures demand.
4. **Mobile app shell.** Wrap the web app (e.g. Capacitor) with native Bluetooth
   MIDI, notifications and a foreground service on Android; iOS "on the stand"
   mode. Same UI and engine, so most work is capture and packaging.
5. **Pi as hub + sync.** The app pulls sessions from a Pi on the home network or
   through the tunnel, so always-on capture and the phone app combine.
6. **Sharing and Pro.** Teacher share links, subscription (about $39/yr), then
   decide on a plug-in box only after preorders.

Open owner decisions for the app: wrap the web app (recommended: one codebase,
fastest) or build native apps; Android first (Bluetooth/USB capture in the
background works) or iOS first (owner's own phone?).

## Decided and rejected

- 2026-10-21: **Days follow your clock: no action.** Day boundaries use the Pi's
  time zone while times show in the browser's; the owner always plays in one zone
  (UTC+3), so this is parked. Checked 2026-10-21: the Pi is set to Europe/Istanbul
  and NTP-synced, so days already split at the owner's midnight. Revisit
  if the owner travels or ships to others.

- 2026-10-21: **Keep the random trycloudflare link** rather than buy a domain for a
  named tunnel (owner's choice). Revisit only if the owner asks.
- 2026-10-21: **Own password login instead of Cloudflare's email gate**, because
  Cloudflare's gate signs you out after about 10 s (cloudflared#1752). Switch back
  if Cloudflare fixes it.
- Rejected: **manual practice logging** of any kind (timers, forms). The product's
  point is that nothing has to be logged. Naming a piece once (Pieces) is the only
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
- 2026-10-21: Pieces trial steps 1 and 2: matcher, `pieces` report, dashboard Pieces
  card with naming and Listen. Live on the Pi.
- 2026-10-21: Nightly backups with Mac copy (launchd agent pulls on login, wake and
  hourly), Download backup, Back up now, restore. Live on the Pi; first Mac pull verified.
