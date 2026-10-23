# Roadmap

Kept by the product review (one PM cycle per run). Every item ties to one of three
outcomes: **practise better**, **practise more**, or **easier setup**. Effort is S
(an evening), M (a few days), L (a week or more). Nothing here is built until the
owner says so.

Last review: 2026-10-23 (research: phone or small box instead of the Pi; similar
products and protecting the idea; black keys in the key map).
Previous: 2026-10-22 (app target added), 2026-10-21 (first run).

## Now

At most three. Proposed 2026-10-23; nothing is built until the owner says go.

### 1. Black keys you can read in "Most used keys" (practice insight, S) · shipped 2026-10-23 (owner approved)

**Problem.** Owner, 2026-10-22: "I don't really understand which black keys pressed
most." An unused black key is drawn black (#2c2c2a) and the most used one dark blue
(#184f95, the top of the colour scale), so on the keyboard the two look the same.
In dark mode it is worse. White keys read fine.

**Proposed fix.** Keep the piano looking like a piano (white keys white, black keys
black) and show use as a coloured band on **every** key, on the same scale: the
lower part of each white key and of each black key is filled with the usage colour,
and the strongest band is outlined so it never melts into black. Also:
- tapping or hovering any key shows its name, count and share ("F♯4 · 1,204 notes ·
  2.1%"), on a phone too;
- a second chip row "Top black keys" (e.g. "F♯4 3.1% · B♭3 2.4% · C♯5 1.9%"), since
  accidentals are what a learner stumbles on.

**Acceptance criteria**
- In both light and dark mode, on a phone and a laptop, the 3 most used black keys
  in the demo data are visibly the darkest-banded black keys (checked on the
  screenshots), and an unused black key has no band.
- White and black keys use one legend ("few … most"); the legend sits next to it.
- Same drawing in the session detail's "Keys played".
- Top black keys row lists up to 5, hidden when no black key was played.
- README and screenshots (keys.png, session.png) updated; tests pass.

**Out of scope.** Changing the colour scale for white keys, per-hand split.

**How we'll know.** The owner can name their most used black keys from the
screenshot without asking.

### 2. Does phone-only capture work? A 10-minute check (app path, no code)

**Problem.** The native iOS app only replaces the Pi if the iPhone keeps receiving
MIDI with the screen locked. Apple gives no MIDI background mode: a suspended app
gets no MIDI (Apple developer forum, July 2026). Yet *Piano Tracker* (iOS, free,
2025) says it tracks "with the screen off or in the background". Checking that costs
nothing and decides the capture design below.

Owner, 2026-10-23: *Piano Tracker* is not in the Turkish App Store, so this check
can't be done that way. Alternative: the review can test it with our own small
test app later (milestone 4), or try *DigitalPianoMIDITimer* if it is available in
Turkey.

**Original check.** Install the free *Piano Tracker* app, pair the FP-30X
over Bluetooth inside the app, lock the phone, play 10 minutes, unlock: did it count
10 minutes? Then once more after leaving the phone untouched for an hour first.

**How we'll know.** Yes → phone-only capture is realistic (design for it). No →
the app needs the always-on box (App target, capture option B).

### 3. Pieces trial: watch it on real practice (practice insight) · in trial

Step 1 (matcher) and step 2 (Pieces card, naming, Listen) shipped and deployed
2026-10-21; spec in git history (roadmap as of 3c78ef1). Open question: does the
Chopin A minor waltz stay **one** piece across several days of real practice, and do
left-hand-alone stretches show up as separate pieces? Needs a look at the Pi's real
data (owner's go-ahead) or the owner's own check. Graduates from "trial" when the
owner confirms the grouping after about two weeks. Pieces is also the clearest
difference from the competing apps found on 2026-10-23 (see App target).

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
5. **Choose the product name** (business, S). "pianotrack" sits next to the App
   Store's *Piano Tracker* and *PianoTrax*; a distinctive name is needed before any
   public launch or trademark filing. *Owner decision.*

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

### What's already on the market (checked 2026-10-23)

Automatic practice timers from MIDI now exist on iOS, so "automatic minutes and
streaks" alone is no longer unique:
- **Piano Tracker** (iOS, free, since March 2025): counts active playing time from
  USB or Bluetooth MIDI, pauses on silence, streaks, daily goal, consistency, notes
  per day; says it works with the screen off. No pieces, no replay found.
- **DigitalPianoMIDITimer** (iOS 26+, 2026, free + $9.99/yr): starts on play,
  pauses on silence, saves each session as MIDI with playback, weekly/monthly
  charts, streaks, "piece rankings" (from names you give the logs), iCloud.
- **Yamaha Piano Diary**: older iPad recorder/diary, manual start.
  **LevelUp Piano**: gamified lessons over MIDI, not a tracker.
  Roland's diaries are discontinued (2026-10-20 scan).

Not found anywhere: **pieces recognised from the notes alone** (with a beginner's
mistakes) and their tempo and steadiness over weeks, the 88-key map over time,
**always-on capture without the phone**, and replay with a piano sound in the
dashboard. That is where the app has to win; the basic timer is table stakes.

### Capture without the Pi (owner question 2026-10-22)

| Option | Always on? | Setup for the user | Cost | Effort for us |
|---|---|---|---|---|
| A. iPhone itself over the piano's Bluetooth | Only while the app may run: in front, or kept awake by a background audio session (App Review may refuse it if the app makes no sound) or iOS 26's continued-processing task started by a tap | Pair once, keep phone near the piano | none | part of the app |
| B. USB-stick-size box: ESP32-S3 (e.g. LilyGO T-Dongle-S3) as USB host on the piano, stores notes in its flash and syncs to the phone over Bluetooth or wifi when the app opens | Yes, phone can be anywhere | Plug into the piano's USB to Host port and a USB charger, join wifi from the app | about $15 parts | L: firmware in C++ (open-source ESP32_Host_MIDI, MIT, already does USB host + BLE + wifi MIDI) |
| C. Pi Zero 2 W running today's code | Yes | Same as the Pi today, smaller | about $15 + SD card + power | S: works now |
| D. Keep the Pi 4 as the hub, app syncs from it | Yes | as now | owned | M: sync API |

Recommendation: design the app so capture can come from A, B or D and the engine is
the same. Start with **A for the owner's own use** (FP-30X has Bluetooth MIDI), keep
the Pi (D) as the always-on fallback, and only build **B** if the 10-minute check
(Now #2) shows the phone can't capture reliably, or when the app goes to other
people. B is the "simpler than a Pi" box: one stick, no SD card, no Linux.

### Protecting the idea (owner question 2026-10-22)

Not legal advice; a patent attorney should confirm before money is spent.
- **Patent: probably not worth it.** The code and the method have been public on
  GitHub under MIT since 2026-10-20. Turkey and Europe need absolute novelty, so that
  publication already blocks a patent there. The US allows a 1-year grace period
  for the inventor's own disclosure (until 2026-10-20 next year), but automatic
  MIDI practice timers are prior art (above), and melody fingerprinting by interval
  n-grams is well known in music search, so only a narrow claim would be left.
  A US filing with an attorney costs roughly $10–20k over its life.
- **Copyright: automatic.** The code is already protected by copyright, but the MIT
  licence lets anyone reuse what is published. Releases stay MIT forever; future
  work (the iOS app, the box firmware) can be kept private or licensed differently.
- **Trademark: worth doing before launch.** A distinctive name plus logo, filed in
  Turkey (TÜRKPATENT) or the EU (EUIPO, about €850 for one class) and the US (USPTO,
  about $350 per class), protects the brand that users and app stores see.
- **Real protection is the head start:** the pieces matcher tuned on real beginner
  playing, the engine test vectors, and the owner's own months of data and feedback.

### Path from today's Pi + web dashboard (each step ships on its own)

1. **Phone-quality web app (now).** The current dashboard as an installable home
   screen app: phone-first layout (shipped 2026-10-22), reminders. Proves which
   screens matter before they are rebuilt natively.
2. **Portable engine.** Golden test vectors from the Python engine (shipped 2026-10-22), then
   a Swift port of recorder, metrics and pieces that passes them.
3. **Browser mode (Web MIDI), optional.** The same page captures from Chrome/Edge/Android
   Chrome and stores in IndexedDB; export/import in the Pi's database format.
   First thing others can try with no hardware; measures demand.
4. **Native iOS app.** SwiftUI app with Core MIDI capture (Bluetooth and USB),
   the Swift engine, Today, Pieces, replay and local notifications. Capture option
   A first (see table), syncing from the Pi (D) for always-on. Android later.
5. **Capture stick (option B), if needed.** ESP32-S3 firmware that records while
   the phone is away and syncs when the app opens.
6. **Pi as hub + sync.** The app pulls sessions from a Pi on the home network or
   through the tunnel, so always-on capture and the phone app combine.
7. **Sharing and Pro.** Teacher share links, subscription (about $39/yr), then
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
- 2026-10-23: **Recommended against a patent** (code public since 2026-10-20, prior
  art exists); trademark on a new name instead. Owner to confirm.
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
- 2026-10-23: Key map: usage bands on white and black keys, Top black keys row.
- 2026-10-22: Engine test vectors (Now #2 of 2026-10-22): `python3 -m pianotrack vectors`, four cases in
  `tests/vectors/`, format in docs/engine-vectors.md, checked by tests/test_vectors.py.
- 2026-10-22: Phone-first page order: Today, week, Pieces, sessions first on a phone;
  one Trends card (tabs on a phone); Pieces table fits the phone width; trend notes
  say "no change" instead of "up 0".
- 2026-10-21: Pieces trial steps 1 and 2: matcher, `pieces` report, dashboard Pieces
  card with naming and Listen. Live on the Pi.
- 2026-10-21: Nightly backups with Mac copy (launchd agent pulls on login, wake and
  hourly), Download backup, Back up now, restore. Live on the Pi; first Mac pull verified.
