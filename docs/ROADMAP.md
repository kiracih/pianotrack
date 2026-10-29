# Roadmap

Kept by the product review (one PM cycle per run). Every item ties to one of three
outcomes: **practise better**, **practise more**, or **easier setup**. Effort is S
(an evening), M (a few days), L (a week or more). Owner decision 2026-10-29:
the review builds bigger items from the plan below, one at a time, without asking; it
still asks before stored-data changes, costs, data leaving the owner's devices, or the Pi.

Last review: 2026-10-29 (built: replay Loop, demo guard; owner asks: outstanding days,
week card keys in 3D). Previous: 2026-10-28, 2026-10-27, 2026-10-26 (every recording of a piece, welcome back), 2026-10-25 (Pieces added incrementally, Today invite line), 2026-10-24 (piano-room look step 1, "then → now" per piece), 2026-10-23,
2026-10-22 (app target added), 2026-10-21 (first run).

**Plan to the iOS beta (2026-10-29, owner asked "when do we start the iOS app"):**
[Pianotrack product roadmap](https://claude.ai/artifact/BN3TbtzjJLjZEarAkzffvL). Two
tracks from 30 Oct: iOS (1 Swift engine passing tests/vectors, 2 capture test app with
the locked-screen check, 3 first real app, 4 Pi sync, 5 Pieces and replay, 6 TestFlight
beta about 10 Jan 2027; Swift builds run on the owner's Mac, Xcode 26.5) and Pi/web
(pieces drift fix, merge and split pieces, score check step 1). Owner said yes (2026-10-29).

## Now

At most three. Proposed 2026-10-23; nothing is built until the owner says go.

### 1. Pieces stop absorbing other music (pieces, S, engine) · next to build

Finding 2026-10-29 (truth log on the simulator): after 120 days the Ode to Joy group
holds 300 Ode plays, 217 sight-reading and 87 scale segments, because a settled piece's
core keeps every n-gram heard twice, and a big group collects enough slips to match any
stepwise melody. Matcher wrong-rate grows from 1.3% at 30 days to 9–12% at 120 days, and
those foreign segments make most of the "stumbles with no cause". Fix: core n-grams must
be heard in 3% of a piece's plays (and twice). Measured: wrong ≤ 2.7% on seeds 1–5 at 120
days (right ≥ 96.8%), stumbles with no cause 56% → 35%, vectors unchanged. Then a 5-interval
gap key (35% → 27%) and a 120-day gate in `pieces --check`. Changes grouping of real
history (names follow the music), so it ships with a before/after check on the Pi's data.

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
2. ~~**Loop a passage in the replay**~~ Done 2026-10-29 (Loop, ±5 s, Space).
3. **Ignore accompaniment and split channels** (setup / data quality, S).
   Problem: notes from every MIDI channel count, so rhythm or song playback sent
   over MIDI inflates practice. Add a channel filter setting (default: all) and
   count song-playback channels separately.
4. **Pedal held before the first note** (bug, S). Problem: pedal events are only
   recorded once a session is open, so a pedal pressed just before the first
   note is lost and sustain share reads low. Remember the last pedal state and
   write it at session start.
5. **Merge and split pieces** (pieces, M; owner idea 2026-10-26). Problem: the
   matcher sometimes keeps one piece as two (or joins two). "Merge" on a piece joins
   it with another; "Split" separates a play or a group back out. Stored as user
   corrections next to piece names (a new table, so a migration and the owner's go
   on the data change); recordings untouched, the matcher re-applies the
   corrections after every regroup. Carries over to the iOS app.
6. **Share cards for social media** (motivation, M; owner idea 2026-10-26). A
   good-looking image of a week (the octave), a streak, or a piece's "then → now",
   made on the device (canvas to PNG) and shared through the phone's share sheet. Nothing
   leaves the Pi unless the owner shares it. Needs design work first (design lead).
   2026-10-28: the **week card** is designed and prototyped on branch
   `claude/project-thread-dujwl9` (not on main or the Pi): `/recap` page and
   `GET /api/recap`, Post and Story sizes, Ivory and Rosewood, piece names optional.
   Waiting for the owner's go to merge and deploy; streak and "then → now" cards later.
7. **Check playing against the score, step 1: score file** (pieces, M; owner idea
   2026-10-26, "killer feature"; owner said "add it" 2026-10-26). Problem: Pieces
   knows *what* you played but not whether the notes were right. Attach a MusicXML
   (`.xml`/`.mxl`, read with stdlib xml.etree + zipfile) or `.mid` file to a piece;
   every play of that piece is aligned note by note (edit distance over pitches,
   chords as sets, jumps back allowed for restarts) and the piece shows accuracy
   over time and its trouble bars. Counted kindly: a wrong note fixed at once is
   "fixed", hands-alone plays judged on that hand, partial plays on the bars played,
   pedal/dynamics ignored; notes first, rhythm later. Places where your consistent
   playing (the piece's core n-grams) disagrees with the score show as "score or
   you?", not mistakes. Raw replay, `.mid` and `.csv` untouched; score stored next to
   the piece name; engine vectors for the iOS port. Acceptance: on `simulate.py
   --beginner` at least 90% of injected wrong/missed notes found and under 5% of
   correct notes flagged; owner tries it on the Chopin A minor waltz.
   Later steps, decided after step 1: find a score by name (small public-domain
   list, candidates shown with opening notes, S–M), then photo via hosted OMR from
   the iOS app with a listen-and-confirm step (M–L; best OMR still misreads about
   1 symbol in 5 on real scans). Research:
   [Score check research](https://claude.ai/artifact/N3eacvxdqMVHEuWRiNaYGC).
8. **Choose the product name** (business, S). "pianotrack" sits next to the App
   Store's *Piano Tracker* and *PianoTrax*; a distinctive name is needed before any
   public launch or trademark filing. *Owner decision.*
9. **Export falling notes as a video** (replay / sharing, S–M; owner idea 2026-10-27).
   Problem: the owner films their hands and wants the falling notes in the same
   video, Synthesia-style. Proposal, prototyped on demo data 2026-10-27 (branch
   `claude/project-thread-e35a4t`, `static/videoexport.js`; sample clips in project
   files `video-export/`):
   - **Where it renders:** in the browser that asks (Mac or iPhone), never on the Pi.
     The Pi only serves the notes, as for the replay; no ffmpeg, still stdlib only.
   - **Format:** MP4 (H.264 + AAC), which Safari and Chrome record natively
     (MediaRecorder) and Photos, iMovie, CapCut and Final Cut open directly. 30 fps,
     1080 px on the short side; a 30 s clip is about 1.5 MB.
   - **Looks:** *Overlay* (default): flat top-down notes over all 88 keys on chroma
     green, so an editor keys it out and stretches it to the width of the real keyboard
     filmed from above; *Overlay on black* for "screen" blend mode; *3D view*, today's
     falling notes as a clip on its own (split screen or picture-in-picture). Shapes
     16:9 and 9:16; keys "all 88" (lines up with a full-keyboard shot) or "keys used"
     (bigger notes in portrait). True transparency works too (WebM with alpha, checked
     in the prototype) but iPhone editors can't open WebM, so it is a desktop extra.
   - **Sound:** the sampled piano is in the file, so editors that sync by waveform
     can line it up with the camera's sound; mute it in the final edit.
   - **Timing:** pauses are never skipped in an export (it must match camera time).
     The clip starts 1.5 s before the first chosen note, and its file name carries
     the Pi's clock time of that moment (`pianotrack-2026-10-27_21-14-05.3.mp4`) to
     match the phone video's time; the final nudge is by the first note.
   - **Range:** whole session, or from the replay's current position (later the
     A–B loop of Next 2), capped at 10 minutes.

   Step 2 (M), after the owner tries step 1: **Line up with my video**: choose the
   phone video in the page; the browser finds note onsets in its sound and matches
   them to the recorded notes (to about 10 ms), then exports exactly the camera's span.
   Nothing is uploaded. Same step: **frame-exact rendering** with WebCodecs (faster
   than real time, no dropped frames) plus a small in-house MP4 writer. The prototype
   records in real time: the 2D overlay held 30 fps but the 3D view dropped to about
   7 fps on a slow machine, and the screen has to stay on while it records.
   Acceptance (step 1): a 60 s clip from a real session plays in iPhone Photos,
   imports into CapCut and iMovie, the green keys out cleanly, each note reaches the
   line when its sound plays (within one frame), and the Pi does no extra work.
   *Owner questions:* which editor (decides green vs transparency), camera from
   above or from the side, portrait or landscape.

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
- **Per-piece goals**: "Waltz at 120 bpm, steady 60" with a progress bar, once the
  Pieces trial graduates.

## Sections

From 2026-10-24 the daily review runs one agent per section plus a design lead in
parallel (owner request 2026-10-23); the PM picks what to build. Each agent's focus for
the next review is set here at the end of every review.

Ideas found 2026-10-29 (best first; S = an evening). Ideas the PM builds without asking
are S, change no stored data and send nothing off the Pi.

| Section | Ideas waiting (impact, effort) |
|---|---|
| Capture & setup | Re-importing a .mid stores nothing new: uid = uuid5("mid/<sha256>/<k>"), prototype gives 1 row from 3 runs (high, S); `POST /api/sessions` upsert by uid, version (closed, end, notes), overlap ≥ 50% marks `dup_of` (high, M, schema v4, owner's go); "Recorded on Pi · FP-30X" / "Imported from x.mid" on the session (med, S) |
| Today & habits | `usual_start` with a spread check: demo weekdays wander 07:11–21:38 (none), weekends 07:34 (high, S); `nudge()` text and quiet rules as a pure function (high, S engine, M iOS); Monday weekly note linking to /recap (med, S) |
| Pieces | Core n-grams heard in 3% of plays (Now #1, high, S); 5-interval gap key (high, S, vectors change); 120-day + stumble-precision gate in `pieces --check` (med, S) |
| Practice insight | Plain words on the stumbles chart: "Stops in pieces", one decimal (rounding shows 2.6 as 3), an always-visible line (high, S); "3 of 10 plays clean this week" instead of clean run seconds (high, S–M); weekly minutes per piece with the current week drawn "so far" (med, S) |
| Replay & session detail | Zoom the seek bar to the loop: an 8 s band is 2.4 px at 390 px (high, S); falling notes stop at B while looping (med, S); Media Session play/pause/±5 for headphones (med, M) |
| Trust & access | Per-segment cache for `piece_stumbles`/`piece_tempo`: 3.8 → 2.0 s per new session, +40 MB, identical JSON (high, M); hardened `pianotrack-demo.service` (ProtectHome, InaccessiblePaths, syscall filter; needs scoring on the Pi) (med, S, deploy/) |
| Design (lead) | Figure row under the octave, drop "notes today", the octave rises 140 px (med, S, diff ready); "+27 bpm, faster, Piece C" as a figure (med, S); light falling-notes lane (diff still applies) (med, S); 24 h dates (DESIGN.md step 3) |

| Section | Covers | Next review's focus |
|---|---|---|
| Capture & setup | collector, devices, sessions, Bluetooth, install, onboarding, Pi-free capture | Two simulated devices on one sitting (Bluetooth jitter 5–30 ms, 2% dropped): tune the overlap rule to zero false merges |
| Today & habits | ring, streak, week, calendar, goals, reminders | Vectors for `usual_start` and `nudge`; whether the owner's real weekdays settle or need a chosen time |
| Pieces | matcher, Pieces card, per-piece progress, naming | Wrong and missed notes behind a quarter of stumbles: does a missed note played in time count |
| Practice insight | trends, session metrics, zones, dynamics, key map | Whether deliberate stops right after a wrong note should count, before the Trends card changes |
| Replay & session detail | player, keyboard, downloads, session page | Seek bar zoom while looping; a trouble-spot ▶ that starts a 3-pass loop at 0.75× |
| Trust & access | backups, remote login, privacy, Pi speed, reliability | Score the hardened demo unit and time the per-segment cache on the Pi |
| Design (lead) | identity, layout, type, colour, motion, copy | 24 h dates and engraved dynamics (DESIGN.md step 3) |

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

2026-10-27: the two 3D views (key map, falling notes) are web-only for now; on iOS they
map to SceneKit or RealityKit, and the octave, ring and charts stay 2D so they port to
SwiftUI and widgets as they are. Session uid + device id (Capture) is the first step
of Pi-to-app sync and needs the owner's go (schema v2).

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
   screen app: phone-first layout (shipped 2026-10-22), design direction for web and
   app in docs/DESIGN.md (step 1 shipped 2026-10-24; its tokens map to SwiftUI), reminders. Proves which
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

- 2026-10-27: **Approved and built: fair steadiness (past sessions recomputed once,
  copy kept), session uid and device for syncing, Pieces segments kept in the
  database so a restart never makes the page wait** (owner: "make all those 3").
- 2026-10-25: **Approved and built: tempo per piece, the octave week, a weekly days
  target** beside the streak (owner: "make all three"). The streak stays.
- 2026-10-22: **Rejected: "today's pieces" on the Today card** (owner didn't like it).
  Don't re-propose a per-piece summary on the Today card.
- 2026-10-22: **App: native, iOS first** rather than wrapping the web app.
- 2026-10-23: **Daily review redesigned** (owner): one agent per section plus a design
  lead, PM builds small increments itself and reports daily with tomorrow's focus.
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

- 2026-10-29 review: Loop this spot in the replay (Loop ±4 s around a ▶ jump, −5 s / +5 s,
  Space plays, no double start while the piano loads); the public demo only replaces a
  database it built itself. Owner ask: This week days at 1.5× the goal or more turn deep
  brass with the multiple engraved (1.5×, 2×, 3×), on the dashboard and the week card.
- 2026-10-28 review: opening a session never runs a Pieces pass (it answers pending and
  finds them in the background); ▶ on a trouble spot, a recording or Listen starts
  playing; backups and the dashboard download leave out the remote login's cookie key.
- 2026-10-28 (owner: "do all those 3 new metrics"): stumbles per piece (pauses far longer
  than the piece has at that spot), longest clean run with your best, trouble spots with
  ▶; the session page leads with stumbles and clean run, steadiness and the rest under
  Details. Not yet: restarts without a pause, and the Trends card still shows steadiness.
- 2026-10-27 evening (owner go): steadiness as a share of the beat (a 3.5% wobble
  scores about 75 at any tempo; stored sessions recomputed in the background after
  start, copy kept as `<db>.pre-metrics-v2.db`); every session has a `uid` and
  `device`; Pieces keep each session's segments (migration 3), `/api/pieces` answers
  503 "warming" instead of making you wait.
- 2026-10-27: Today: on Mondays, how last week went ("Last week: 6 of 5 days, 3h 10m.
  Target met."), `last_week` in `/api/summary`. Falling notes easier to read: pressed
  keys in felt shades, a brass landing line, 230 px on phones, nothing drawn off screen.
- 2026-10-26 evening (owner request): 3D key map and falling notes in the replay
  (three.js 0.180.0 bundled, served from the Pi); deployed to the Pi.

- 2026-10-26: Pieces: every recording of a piece, newest first, each with ▶ from where the
  piece starts (owner idea); `history[].offset` in `/api/pieces`. Today: "One day off
  doesn't undo a habit" after one missed day, "Welcome back" after a longer break.

- 2026-10-25 (owner go): Pieces tempo timed by phrase per piece (correlation with the real
  tempo 0.91–0.99, was 0.07–0.30); the week as an octave; weekly days target (default 5);
  tips close when you tap elsewhere or scroll.
- 2026-10-25: Pieces: a new session is added to the kept matcher (under 1 s instead of
  about 17 s after practice with 400 days of data; same pieces as a full regroup).
- 2026-10-25: Today: an invite line above the ring ("5 min keeps your 8-day run going");
  the week chart's goal label is no longer hidden by bars.
- 2026-10-24: Piano-room look, step 1 (docs/DESIGN.md): felt and brass palette in both
  themes, serif headings and figures, Today without a card, focus ring, theme colour
  follows the toggle.
- 2026-10-24: Pieces: "then → now" line per piece (first 5 vs last 5 sessions, medians).
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
