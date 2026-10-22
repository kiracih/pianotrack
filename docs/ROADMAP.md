# Roadmap

Kept by the product review (one PM cycle per run). Every item ties to one of three
outcomes: **practise better**, **practise more**, or **easier setup**. Effort is S
(an evening), M (a few days), L (a week or more). Nothing here is built until the
owner says so.

Last review: 2026-10-22 (from now on the review also tracks the app target below).
Previous: 2026-10-21 (first run, owner decisions recorded the same day).

## Now

At most three. Owner decisions 2026-10-22: phone-first page order built and shipped;
engine test vectors approved ("if it's not too much effort, you choose").

### 1. Pieces trial: watch it on real practice (practice insight) · in trial

Step 1 (matcher) and step 2 (Pieces card, naming, Listen) shipped and deployed
2026-10-21; spec in git history (roadmap as of 3c78ef1). Open question for the next
reviews: does the Chopin A minor waltz stay **one** piece across several days of
real practice, and do left-hand-alone stretches show up as separate pieces? Needs a
look at the Pi's real data (owner's go-ahead) or the owner's own check. Graduates
from "trial" when the owner confirms the grouping after about two weeks.

### 2. Engine test vectors (app path, M) · shipped 2026-10-22 (see Done)

**Problem.** Every app route (native iOS app first, then others) needs the
recorder, metrics and pieces engine outside Python (Swift for iOS). Porting it without a fixed
reference means the phone and the Pi will disagree on minutes, streaks and pieces.

**Acceptance criteria**
- A command writes golden files from the simulator: a few `.mid` inputs (beginner
  and clean, two pieces, a pause-heavy session) and the exact sessions, metrics and
  piece groups the Python engine produces for them, as JSON in `tests/vectors/`.
- A Python test re-runs the engine and fails on any drift, so the vectors stay true.
- The format is documented in a short `docs/engine-vectors.md`, written for whoever
  ports the engine.
- No change to anything the owner sees.

**Out of scope.** The Swift port itself (milestone 2 below).

**How we'll know.** A port can be checked against the vectors with one command.

## Next

1. **Black keys readable in the key map** (practice insight, S) · owner request
   2026-10-22. Problem: in "Most used keys" a rarely used black key is drawn black and a
   much used one dark blue, so the owner can't tell which black keys they press most.
   Fix to propose in the 2026-10-23 review (e.g. same colour scale on black and white
   keys with an outline, or a lighter fill for unused black keys).
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
   screen app: phone-first layout (shipped 2026-10-22), reminders. Proves which
   screens matter before they are rebuilt natively.
2. **Portable engine.** Golden test vectors from the Python engine (Now #2), then
   a Swift port of recorder, metrics and pieces that passes them.
3. **Browser mode (Web MIDI), optional.** The same page captures from Chrome/Edge/Android
   Chrome and stores in IndexedDB; export/import in the Pi's database format.
   First thing others can try with no hardware; measures demand.
4. **Native iOS app.** SwiftUI app with Core MIDI capture (Bluetooth and USB),
   the Swift engine, Today, Pieces, replay and local notifications; "on the stand"
   mode while background capture is studied. Android later.
5. **Pi as hub + sync.** The app pulls sessions from a Pi on the home network or
   through the tunnel, so always-on capture and the phone app combine.
6. **Sharing and Pro.** Teacher share links, subscription (about $39/yr), then
   decide on a plug-in box only after preorders.

Owner decisions 2026-10-22: **native app, iOS first.** Consequences: the engine is
ported to Swift (checked against the test vectors), capture uses Core MIDI (Bluetooth
MIDI pairing through Apple's CABTMIDICentralViewController, USB through the Camera
Adapter), and charts are rebuilt in SwiftUI. Browser mode (step 3) becomes optional,
since Safari has no Web MIDI and it would not reach the owner's own phone.

**Research for 2026-10-23 (owner question):** can the phone itself replace the Pi as
the collector, or is there something simpler than a Pi (a USB stick-sized box)?
Points to settle: whether iOS keeps receiving Bluetooth/USB MIDI with the screen off
or the app in the background, what "leave the phone on the stand" costs in practice,
and cheap always-on options (ESP32-S3 USB-host/BLE dongle, Pi Zero 2 W, a piano's own
Bluetooth to the phone).

**Research for 2026-10-23 (owner question):** is exactly this product, or something
close, already on the market? If not, can the idea be protected, and is it worth it?
Points to settle: a fresh competitor scan beyond the 2026-10-20 market scan (apps,
piano makers, hardware dongles, patents); what can be protected (patent on the
automatic piece grouping or capture box, trademark on the name, design, trade
secrets) and roughly what each costs; and the catch that the code is public on
GitHub under MIT since 2026-10-20, which counts as prior disclosure for a patent.

## Decided and rejected

- 2026-10-22: **Rejected: "today's pieces" on the Today card** (owner didn't like it).
  Don't re-propose a per-piece summary on the Today card.
- 2026-10-22: **App: native, iOS first** rather than wrapping the web app.
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
- 2026-10-22: Engine test vectors: `python3 -m pianotrack vectors`, four cases in
  `tests/vectors/`, format in docs/engine-vectors.md, checked by tests/test_vectors.py.
- 2026-10-22: Phone-first page order: Today, week, Pieces, sessions first on a phone;
  one Trends card (tabs on a phone); Pieces table fits the phone width; trend notes
  say "no change" instead of "up 0".
- 2026-10-21: Pieces trial steps 1 and 2: matcher, `pieces` report, dashboard Pieces
  card with naming and Listen. Live on the Pi.
- 2026-10-21: Nightly backups with Mac copy (launchd agent pulls on login, wake and
  hourly), Download backup, Back up now, restore. Live on the Pi; first Mac pull verified.
