"""Practice reminders: when you usually practise, and whether to nudge you today.

Pure functions over plain values, so the iOS app can port them and schedule one
local notification from the answer (pianotrack-ios #3). Times are minutes after
local midnight. `tests/vectors/nudge.json` pins the behaviour for the port.
"""

from typing import List, Optional

DAY = 24 * 60
EARLIEST = 8 * 60  # never remind before 08:00 ...
LATEST = 22 * 60  # ... or after 22:00
MIN_DAYS = 3  # days with practice needed before there is a usual time
WINDOW_DAYS = 14  # how far back the usual time looks
AFTER = 30  # remind this many minutes after the usual start, once it has passed quietly
STOP_AFTER_IGNORED = 3  # stay quiet after this many reminders in a row went unanswered


def _dist(a: int, b: int) -> int:
    d = abs(a - b) % DAY
    return min(d, DAY - d)


def _clamp(m: int) -> int:
    """Move a time outside 08:00-22:00 to the nearer bound around the clock, so
    00:05 becomes 22:00 (2 h 5 min away), not 08:00 (7 h 55 min away)."""
    if EARLIEST <= m <= LATEST:
        return m
    return LATEST if _dist(m, LATEST) <= _dist(m, EARLIEST) else EARLIEST


def usual_start(first_starts: List[int]) -> Optional[int]:
    """The usual time you start practising, from the first session's start (minutes
    after midnight) on each of your last practice days, oldest first. Only the last
    WINDOW_DAYS entries count: the last 14 days you practised, not calendar days,
    so rest days don't shrink the window. None with fewer than MIN_DAYS entries.

    It is the circular medoid: of the starts you actually had, the one with the
    smallest total distance around the clock to all the others, so a week of 23:50
    and 00:10 lands near midnight, not noon. On a tie the smallest minutes value
    wins (00:10 beats 23:50). Then clamped into 08:00-22:00 by moving to the nearer
    bound around the clock.
    """
    xs = [int(m) % DAY for m in first_starts[-WINDOW_DAYS:]]
    if len(xs) < MIN_DAYS:
        return None
    best = min(sorted(set(xs)), key=lambda c: sum(_dist(c, x) for x in xs))
    return _clamp(best)


def nudge(usual: Optional[int], now: int, played_today: float, streak_min: float,
          streak: int, ignored: int) -> Optional[dict]:
    """Whether to remind you today, and when: {"at": minutes, "kind": "streak" | "habit"}.

    `now` is minutes after midnight, `played_today` and `streak_min` are minutes,
    `streak` is the current streak in days (yesterday included), `ignored` is how
    many reminders in a row went by with no practice after them; the caller resets
    it to 0 on any day with practice, so practising again turns reminders back on.
    Nothing when there is no usual time yet, today already counts (some practice
    and at least `streak_min`), the last STOP_AFTER_IGNORED reminders were ignored,
    or the reminder time has passed.
    The reminder is AFTER minutes past the usual start but never after 22:00, so a
    usual start after 21:30 is reminded at 22:00, which can be before the usual
    start itself: a late reminder would be worse than an early one.
    "streak" when there is a streak of 2+ days to keep, else "habit".
    """
    counts = played_today > 0 and played_today >= streak_min
    if usual is None or counts or ignored >= STOP_AFTER_IGNORED:
        return None
    at = min(LATEST, usual + AFTER)
    if now >= at:
        return None
    return {"at": at, "kind": "streak" if streak >= 2 else "habit"}


CASES = [
    # (description, usual_start input, nudge inputs without `usual`)
    ("too few days for a usual time", [1140, 1150], dict(now=600, played_today=0, streak_min=5, streak=0, ignored=0)),
    ("evening player, streak to keep", [1140, 1150, 1130, 1200, 1145],
     dict(now=600, played_today=0, streak_min=5, streak=4, ignored=0)),
    ("today already counts", [1140, 1150, 1130], dict(now=600, played_today=6, streak_min=5, streak=4, ignored=0)),
    ("a short day doesn't count yet", [1140, 1150, 1130], dict(now=600, played_today=3, streak_min=5, streak=1, ignored=0)),
    ("the reminder time has passed", [1140, 1150, 1130], dict(now=1200, played_today=0, streak_min=5, streak=4, ignored=0)),
    ("three ignored in a row: quiet", [1140, 1150, 1130], dict(now=600, played_today=0, streak_min=5, streak=4, ignored=3)),
    ("goal of 0 minutes: still reminded until you play", [1140, 1150, 1130],
     dict(now=600, played_today=0, streak_min=0, streak=1, ignored=0)),
    ("just after midnight: clamped to 22:00, the nearer bound", [5, 10, 15],
     dict(now=600, played_today=0, streak_min=5, streak=0, ignored=0)),
    ("around midnight: wraps, then clamped to 22:00", [1430, 5, 1435, 15, 1420],
     dict(now=600, played_today=0, streak_min=5, streak=2, ignored=0)),
    ("early bird: clamped to 08:00", [380, 390, 400], dict(now=300, played_today=0, streak_min=5, streak=0, ignored=0)),
    ("late usual: the reminder stops at 22:00", [1300, 1310, 1305], dict(now=600, played_today=0, streak_min=5, streak=3, ignored=2)),
    ("only the last 14 days count", [600] * 10 + [1200] * 14, dict(now=300, played_today=0, streak_min=5, streak=0, ignored=0)),
]


def vector() -> dict:
    """The nudge.json test vector: each case's input and what the engine answers."""
    cases = []
    for desc, starts, kw in CASES:
        u = usual_start(starts)
        cases.append({"description": desc, "first_starts": starts, **kw,
                      "expected": {"usual_start": u, "nudge": nudge(u, **kw)}})
    return {"format": 1, "name": "nudge",
            "description": "Practice reminders: usual_start() and nudge() (pianotrack/reminders.py).",
            "constants": {"earliest": EARLIEST, "latest": LATEST, "min_days": MIN_DAYS,
                          "window_days": WINDOW_DAYS, "after": AFTER, "stop_after_ignored": STOP_AFTER_IGNORED},
            "cases": cases}
