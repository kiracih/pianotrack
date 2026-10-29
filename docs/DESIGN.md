# pianotrack design direction

Status: proposed 2026-10-24 by the design lead; increment 1 (tokens and type) shipped the same day.
The owner can still change the direction.

## Subject

A practice room at home: an upright piano with a claret felt strip behind the keys,
ebony and ivory, brass pedals, rosewood, a score on the stand. The person is a
beginner who checks the page on an iPhone right before or after practising. The page has
one job: make sitting down to play feel inviting today, and show over weeks that it adds up.
It should feel like that room. A fitness band's report is not the model.

## Palette

Six named colours per theme. Charts use one claret ramp; brass is kept for "goal met" and
records. Contrast was checked against both backgrounds, and every text pair is AA or better.

| Name | Light | Dark | Role |
|---|---|---|---|
| Plaster (page) | #EDEEEA | #1B1416 (rosewood) | page background: a cool practice-room wall, not cream |
| Ivory (surface) | #FBFAF6 | #251C1E (lacquer) | cards, white keys |
| Ebony (ink) | #1F1A1C | #F2ECE4 | text, black keys |
| Felt (accent) | #9B2335 | #E57A8A | the brand colour: progress, play button, focus ring, selection |
| Brass (reward) | #A8822F (text #7A5A1C) | #D6AA52 | goal met, records, streak |
| Graphite (secondary) | #55514F (muted #6E6965) | #C2B6B0 (muted #988B86) | labels, axes |

Felt ramp (light): #E6E5DF, #EBC3C9, #D27D8B, #9B2335, #5E1320. In dark mode the ramp
reverses toward light pink. Goal-met days use brass rather than the darkest step. The key map is the exception: its
`--kseq` ramp (#EBC3C9, #D27D8B, #9B2335, #5E1320) is the same in both themes so "most"
is always the darkest key (owner feedback, 2026-10-23). The octave's keys also stay ivory in
both themes, so its fills use on-key colours: felt #9B2335 in both themes, brass #A8822F light
and #8C6A1F dark (dark brass #D6AA52 is only 1.7:1 on an ivory key). A day at 1.5× the goal
or more is deep brass, #6F5418 light and #5C4510 dark (7:1 and 9:1 on ivory), with its multiple
("2×") engraved in ivory serif near the bottom of the key, so an outstanding day stands apart
from one just over the goal.
Do not use: pure #000 or #0b0b0b, the cream #F4F1EA, terracotta, blue/green "fitness"
colours, gradients or soft grey card shadows.

## Type

- **Headings and figures: Apple's New York** via
  `ui-serif, "New York", "Iowan Old Style", Charter, "Bitstream Charter", Georgia, serif`.
  These are system fonts on iPhone and Mac (Apple licence, never bundled). Charter (Bitstream,
  free licence) and Georgia are the fallbacks. The native app uses the same family through
  SwiftUI `.fontDesign(.serif)`, so web and app match. Headings use sentence case at
  weight 600. Big numbers are serif with lining tabular figures.
- **Body, labels, tables: SF Pro** via `system-ui, -apple-system, sans-serif`, at 13–15 px.
- No all-caps labels, no monospace data labels, no eyebrow labels above headings.
- Musical marks (pp, mf, ff, the hairpin) are set in the serif's bold italic, the way
  dynamics appear in a printed score. If that is not enough, the optional upgrade is a
  subset of Bravura (SIL OFL 1.1), bundled in `static/fonts/`.
- Type scale (about 1.2 ratio): 13 / 15 / 19 / 22 / 26 / 44.

## Layout (phone first, 390 px)

```
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀  ← felt strip (6 px claret)
Piano Practice          ● idle
                                   (no card: today sits on the page)
Today                Sat 24 Oct
  18           8 days streak
  of 30 min    86% of days, 4 wks
┌─┬┬─┬┬─┬─┬┬─┬┬─┬┬─┬─┐            ← the week is an octave
│ ││ ││ │ ││ ││ ││ │ │              C D E F G A B = Mon … Sun
│▓│ │▓│ │█│▓│ │▓│ │ │░│              felt fills to goal, brass when met
└─┴─┴─┴─┴─┴─┴─┘                    today's key outlined
 M  T  W  T  F  S  S   3 h 02 this week
───────────────────────────
Pieces                       card
Recent sessions              card
Trends · Calendar · Keys     cards
Records & settings           quiet, no card borders
```

- Content is left-aligned. Only the octave spans the full width.
- Card hierarchy: Today has no card. Working sections use ivory cards with hairline
  borders and corners of 4 px on top and 10 px at the bottom, like a key. Settings and records
  sit on plaster with no border. Not every section gets the same box.
- Wider screens keep the current 12-column grid. The octave sits beside Today.
- Respect `env(safe-area-inset-*)` for the home-screen app.

## Motion

One moment: on load, today's key presses down (translateY 2 px plus a darker bottom edge,
180 ms ease-out) and settles. When the goal is met that day, its fill turns brass at the
same time. Everything else responds only to the user: pressing replay keys, tabs, rows.
No entrance animations and no pulsing, except the live dot while playing.
`prefers-reduced-motion`: no press; the key is drawn in its pressed state.
Animate only transform and opacity, and list properties instead of using `transition: all`.

## The one memorable element

**The week as an octave.** Seven white keys, C to B, are Monday to Sunday. Each key fills
from the bottom with felt up to the daily goal and turns brass when the goal is met.
Today's key is outlined and presses down once. Black keys sit between them as decoration
only, under a thin felt rail that repeats the page's strip. Days still to come are plain
keys, the same as a day without practice: the octave never marks a gap. A beginner learns
the octave and sees their week in it. It becomes the home-screen widget and the native app's hero.

## Principles

1. **The room, not the gym.** Every colour, shape and word should exist in a practice room.
   If it would fit any fitness or SaaS dashboard, change it.
2. **Spend boldness once.** The octave and the felt strip are loud; everything else is quiet.
3. **Invite, don't grade.** Zero minutes reads as "Ready when you are", never as an empty
   ring. Heuristic numbers stay small and secondary.
4. **Calm by default.** Low-saturation surfaces, one accent, motion only on purpose.
5. **Portable to SwiftUI.** Tokens, the system serif and SF, plain shapes. No effect
   needs WebKit tricks.
6. **Quality floor.** WCAG AA text, 3:1 for graphics, visible `:focus-visible`, 44 px
   tap targets, Intl dates (tr-TR, 24 h, week starts Monday), works offline.

## Increments

### 1. Felt and ebony: tokens and type (S)
Before: blue/green on grey, ALL-CAPS card titles, #0b0b0b, system font only, every
section the same card, no focus style.
After: the palette above in both themes, serif sentence-case headings and figures, Today
shown without a card, a 6 px felt strip at the top, claret charts with brass for goal met,
a felt focus ring, `touch-action: manipulation`, and no middle dots in visible copy.
Acceptance:
- No `text-transform: uppercase` remains in index.html.
- `--text` is not #0b0b0b.
- Every text/background pair is at least 4.5:1 in both themes (script check).
- `theme-color` has light and dark values.
- Tab through the page and every control shows a felt outline.
- Screenshots at 390/1100 px in light and dark are regenerated.
- The README screenshots are updated.

### 2. The week as an octave (S–M)
Before: a 7-bar chart with axis ticks and a dashed goal line, starting on Sunday.
After: an SVG octave as described above, Monday first. Tapping a key shows the same
tooltip as today. Today's key presses once on load.
Acceptance:
- 7 white and 5 black keys.
- A key's fill height is min(minutes/goal, 1).
- Goal-met days are brass.
- At 0 minutes today, the Today area reads "Ready when you are".
- Reduced motion draws the pressed state without animation.
- Each key has an aria-label, e.g. "Tuesday, 24 minutes, goal met".
- Fits 360 px wide with no horizontal scroll.

### 3. Engraved dynamics and locale (S)
Before: dynamics as plain-text bucket names; the theme toggle glyph renders broken; en-US dates
("10:05 PM").
After: pp p mp mf f ff in serif bold italic under the dynamics bars; the dynamic-range trend
labelled with a drawn hairpin; an SVG sun/moon toggle with an aria-label; dates via
`Intl.DateTimeFormat` with the browser locale and 24 h in tr-TR.
Acceptance:
- No hardcoded "AM/PM" formats remain.
- The toggle renders the same in Safari and Chromium.
- Dynamics labels are readable at 390 px.

## Week card (proposed 2026-10-28)

A picture of one Monday-to-Sunday week to post or send, drawn as one SVG and turned into a
PNG on the phone. Post 1080×1350 (4:5) and Story 1080×1920 (the same card, centred).
It is written in the sharer's voice ("My week at the piano", "My biggest week yet").
From top to bottom:

1. The felt strip. "My week at the piano" and the dates.
2. The week's time, big serif figures with small units (3 h 14 min), and one kind line in
   bold italic: brass for a record or a met target, felt otherwise, "A rest week" when empty.
3. The octave, as on the dashboard, with each day's minutes under its letter.
4. Three figures: days played (brass when the target is met), streak, keys pressed.
5. The week's keys on an 88-key keyboard in the felt key ramp, with the three most played named.
6. The most practised *named* piece with its minutes and a kind fact (stumbles fell, or its
   longest clean run). With names hidden or none named: "3 pieces practised".
7. A small italic product name at the bottom right.

Ivory (light) and Rosewood (dark) looks; the keys stay ivory in both, as in the octave.
No avatar, no location, no time of day. Nothing leaves the Pi unless the owner shares it.

