"""Practice metrics, computed from the stored notes of a session.

All tempo and intensity figures are heuristics meant for trends over time,
the way a fitness band's calorie count is, not for grading a performance.
"""

import math
import statistics
from datetime import date, datetime, timedelta

ACTIVE_GAP = 3.0       # a pause longer than this stops the "active" clock
CHORD_WINDOW = 0.05    # onsets this close together count as one event
LOWEST_KEY, HIGHEST_KEY = 21, 108  # A0..C8 on an 88-key piano
DYNAMIC_BANDS = [("pp", 0, 32), ("p", 32, 48), ("mp", 48, 64),
                 ("mf", 64, 80), ("f", 80, 96), ("ff", 96, 128)]
# Effort zones by notes per minute, the piano version of heart-rate zones.
ZONES = [("Rest", 0), ("Light", 30), ("Moderate", 120), ("Vigorous", 240), ("Peak", 400)]
SIMPLE_RATIOS = [0.25, 1 / 3, 0.5, 2 / 3, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]


def _percentile(sorted_vals, q):
    if not sorted_vals:
        return 0
    k = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def onset_groups(onsets):
    """Collapse onsets within CHORD_WINDOW into (time, size) events."""
    groups = []
    for t in onsets:
        if groups and t - groups[-1][0] <= CHORD_WINDOW:
            groups[-1][1] += 1
        else:
            groups.append([t, 1])
    return groups


def active_seconds(notes):
    if not notes:
        return 0.0
    onsets = [n["t_on"] for n in notes]
    total = sum(min(b - a, ACTIVE_GAP) for a, b in zip(onsets, onsets[1:]))
    last = notes[-1]
    return total + min(max(last["t_off"] - last["t_on"], 0.25), ACTIVE_GAP)


# Bumped whenever a stored session metric is computed differently; sessions
# stored with an older "v" are recomputed by recompute.py (backup first).
METRICS_VERSION = 2


def tempo_metrics(onsets):
    """Estimate tempo and steadiness from inter-onset intervals.

    Each interval is compared with the median of its neighbours and snapped to
    the nearest simple rhythmic ratio (half, double, triplet...). Steadiness
    falls with the average timing error as a share of that local beat, so slow
    practice is judged as fairly as fast playing: 100 is metronomic, about 75 is
    a 3.5% wobble at any tempo, below 40 is uneven. `timing_error_ms` keeps the
    same error in milliseconds.
    """
    groups = onset_groups(onsets)
    iois = [b[0] - a[0] for a, b in zip(groups, groups[1:])]
    iois = [x for x in iois if 0.06 <= x <= 2.0]
    if len(iois) < 16:
        return {"tempo_bpm": None, "steadiness": None, "timing_error_ms": None}
    beat = statistics.median(iois)
    bpm = 60.0 / beat
    while bpm < 60:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    devs, rels = [], []
    half = 4
    for i, x in enumerate(iois):
        window = iois[max(0, i - half):i] + iois[i + 1:i + 1 + half]
        local = statistics.median(window)
        r = x / local
        nearest = min(SIMPLE_RATIOS, key=lambda s: abs(math.log(r / s)))
        devs.append(min(abs(x - nearest * local), 0.15))
        rels.append(min(abs(x - nearest * local) / local, 0.6))
    mean_err = sum(devs) / len(devs)
    steadiness = 100.0 * math.exp(-(sum(rels) / len(rels)) / 0.12)
    return {"tempo_bpm": round(bpm), "steadiness": round(steadiness),
            "timing_error_ms": round(mean_err * 1000, 1)}


def max_polyphony(notes):
    edges = []
    for n in notes:
        edges.append((n["t_on"], 1))
        edges.append((n["t_off"], -1))
    edges.sort(key=lambda e: (e[0], e[1]))
    cur = best = 0
    for _, d in edges:
        cur += d
        best = max(best, cur)
    return best


def _pedal_usage(pedals, cc, end):
    """(presses, seconds held down) for one pedal controller."""
    presses, down_time, down_at = 0, 0.0, None
    for p in pedals:
        if p["cc"] != cc:
            continue
        if p["value"] >= 64 and down_at is None:
            presses += 1
            down_at = p["t"]
        elif p["value"] < 64 and down_at is not None:
            down_time += p["t"] - down_at
            down_at = None
    if down_at is not None:
        down_time += max(0.0, end - down_at)
    return presses, down_time


def pedal_metrics(pedals, start, end):
    span = max(end - start, 1e-9)
    presses, sustain = _pedal_usage(pedals, 64, end)
    soft_presses, soft = _pedal_usage(pedals, 67, end)
    return {"sustain_presses": presses,
            "sustain_fraction": round(min(sustain / span, 1.0), 3),
            "soft_presses": soft_presses,
            "soft_fraction": round(min(soft / span, 1.0), 3),
            "soft_pedal_used": soft_presses > 0}


def zone_for(npm):
    name = ZONES[0][0]
    for z, lo in ZONES:
        if npm >= lo:
            name = z
    return name


def timeline(notes, start, end):
    """Bucketed notes/min and mean velocity for the session chart."""
    duration = max(end - start, 1.0)
    bucket = max(15, int(math.ceil(duration / 120 / 15.0)) * 15)
    n_buckets = int(duration // bucket) + 1
    counts = [0] * n_buckets
    vel_sum = [0] * n_buckets
    for n in notes:
        i = min(int((n["t_on"] - start) // bucket), n_buckets - 1)
        counts[i] += 1
        vel_sum[i] += n["velocity"]
    points = []
    zones = {z: 0.0 for z, _ in ZONES}
    for i in range(n_buckets):
        npm = counts[i] * 60.0 / bucket
        span = min(bucket, duration - i * bucket)
        zones[zone_for(npm)] += max(span, 0)
        points.append({"t": i * bucket, "npm": round(npm, 1),
                       "velocity": round(vel_sum[i] / counts[i], 1) if counts[i] else None})
    return {"bucket_seconds": bucket, "points": points,
            "zone_seconds": {k: round(v) for k, v in zones.items()}}


def session_metrics(notes, pedals):
    if not notes:
        return {"note_count": 0, "active_seconds": 0, "duration_seconds": 0}
    notes = sorted(notes, key=lambda n: n["t_on"])
    start = notes[0]["t_on"]
    end = max(n["t_off"] for n in notes)
    active = active_seconds(notes)
    vels = sorted(n["velocity"] for n in notes)
    pitches = [n["pitch"] for n in notes]
    mean_vel = statistics.fmean(vels)
    npm = len(notes) / (active / 60.0) if active > 0 else 0.0

    hist = [0] * (HIGHEST_KEY - LOWEST_KEY + 1)
    for p in pitches:
        if LOWEST_KEY <= p <= HIGHEST_KEY:
            hist[p - LOWEST_KEY] += 1

    dyn = {name: 0 for name, _, _ in DYNAMIC_BANDS}
    for v in vels:
        for name, lo, hi in DYNAMIC_BANDS:
            if lo <= v < hi:
                dyn[name] += 1

    groups = onset_groups([n["t_on"] for n in notes])
    intensity = round(100 * min(1.0, 0.6 * min(npm / 400.0, 1.0) + 0.4 * mean_vel / 127.0))

    out = {
        "start": start,
        "end": end,
        "duration_seconds": round(end - start, 1),
        "active_seconds": round(active, 1),
        "note_count": len(notes),
        "notes_per_minute": round(npm, 1),
        "velocity_mean": round(mean_vel, 1),
        "velocity_std": round(statistics.pstdev(vels), 1),
        "velocity_p10": round(_percentile(vels, 0.1)),
        "velocity_p90": round(_percentile(vels, 0.9)),
        "dynamic_range": round(_percentile(vels, 0.9) - _percentile(vels, 0.1)),
        "dynamics": dyn,
        "lowest_pitch": min(pitches),
        "highest_pitch": max(pitches),
        "unique_keys": len(set(pitches)),
        "left_hand_share": round(sum(1 for p in pitches if p < 60) / len(pitches), 3),
        "key_histogram": hist,
        "chord_count": sum(1 for g in groups if g[1] >= 3),
        "max_polyphony": max_polyphony(notes),
        "intensity": intensity,
        "load": round(active / 60.0 * intensity / 50.0, 1),
        "timeline": timeline(notes, start, end),
    }
    out.update(tempo_metrics([n["t_on"] for n in notes]))
    out["v"] = METRICS_VERSION
    out.update(pedal_metrics(pedals, start, end))
    return out


# --- aggregates across sessions --------------------------------------------

def local_day(ts):
    return datetime.fromtimestamp(ts).date()


def daily_totals(sessions):
    """{date: {"active_seconds", "notes", "sessions", "load"}} from session rows."""
    days = {}
    for s in sessions:
        m = s.get("metrics") or {}
        d = local_day(s["start"])
        agg = days.setdefault(d, {"active_seconds": 0.0, "notes": 0, "sessions": 0, "load": 0.0})
        agg["active_seconds"] += m.get("active_seconds", 0)
        agg["notes"] += m.get("note_count", 0)
        agg["load"] += m.get("load", 0)
        agg["sessions"] += 1
    return days


def streaks(days, min_seconds, today=None):
    """Current and longest run of consecutive days meeting the minimum.

    The current streak survives until the end of today, so not having played
    yet today does not break it.
    """
    today = today or date.today()
    good = sorted(d for d, v in days.items() if v["active_seconds"] >= min_seconds)
    longest, run, prev = 0, 0, None
    for d in good:
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        longest = max(longest, run)
        prev = d
    good_set = set(good)
    cur, d = 0, today if today in good_set else today - timedelta(days=1)
    while d in good_set:
        cur += 1
        d -= timedelta(days=1)
    return {"current": cur, "longest": longest}


def goal_times(active_seconds: float, goal_seconds: float) -> float:
    """A day's practice as a multiple of the daily goal, to the nearest half, from 1.5x;
    0 below that. The week's octave marks such days apart from ones just over the goal."""
    if not goal_seconds or active_seconds < 1.5 * goal_seconds:
        return 0
    return round(2 * active_seconds / goal_seconds) / 2


def invite(today_seconds: float, goal_seconds: float, streak_min_seconds: float, streak: int,
           days_since_last=None) -> str:
    """One calm line for Today: the next small step, never a scolding.

    `streak` is the current streak as `streaks` returns it, which counts today
    only once today has reached `streak_min_seconds`. `days_since_last` is how
    many days ago you last played at least `streak_min_seconds` (None if not in
    the history), so a break is met with a welcome back rather than a zero.
    """
    # Goal minutes round the way the ring shows them, so the two always agree.
    if goal_seconds and round(100 * today_seconds / goal_seconds) >= 100:
        return "Goal met today"
    if today_seconds < streak_min_seconds:
        need = max(1, math.ceil((streak_min_seconds - today_seconds) / 60))
        if streak:
            return f"{need} min keeps your {streak}-day run going"
        if not today_seconds and days_since_last == 2:
            return f"One day off doesn't undo a habit. {need} min picks it back up."
        if not today_seconds and (days_since_last or 0) > 2:
            return f"Welcome back. {need} min is a good start."
        return f"{need} min starts a new run" if not today_seconds else f"{need} min more starts a new run"
    goal_min = round(goal_seconds / 60)
    return f"{max(1, goal_min - round(today_seconds / 60))} min to your {goal_min} min goal"


def last_week(days, min_seconds: float, target: int, today=None) -> dict:
    """Last calendar week (Monday to Sunday): days with at least `min_seconds`,
    whether that met the weekly `target`, and the time played.

    Shown on Monday, when this week's octave is still empty.
    """
    today = today or date.today()
    start = today - timedelta(days=today.weekday() + 7)
    week = [days.get(start + timedelta(days=i), {}).get("active_seconds", 0) for i in range(7)]
    played = sum(1 for s in week if s >= min_seconds)
    return {"start": start.isoformat(), "played": played, "target": target,
            "met": played >= target, "active_seconds": round(sum(week))}


def week_days(days, min_seconds, today=None):
    """Days this calendar week (Monday to today) with at least `min_seconds`.

    A weekly count forgives a missed day that would end a streak.
    """
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return sum(1 for i in range((today - monday).days + 1)
               if days.get(monday + timedelta(days=i), {}).get("active_seconds", 0) >= min_seconds)


def consistency(days, today=None, window=28):
    """Share of the last `window` days with any practice, 0..100."""
    today = today or date.today()
    played = sum(1 for i in range(window) if today - timedelta(days=i) in days)
    return round(100 * played / window)

