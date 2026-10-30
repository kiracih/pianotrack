"""Pieces matcher: finds the stretches of practice that play the same music.

Step 1 of the Pieces feature, and read-only: it reads sessions and notes, and
never writes to the database. Each session is cut into segments at pauses, the
top voice of each segment is reduced to its pitch intervals (so a piece played
in another key or at another tempo looks the same), and segments that share
enough interval n-grams are grouped as one piece, oldest first.

Beginners play wrong notes, miss notes and restart, so a segment only needs a
share of its n-grams to match, not all of them.
"""

import hashlib
import inspect
import json
import statistics
import zlib
from collections import Counter, defaultdict

from . import metrics

GAP = 3.5  # seconds of silence that end a segment
MAX_SEGMENT = 240.0  # longer stretches are cut into segments of this length
MIN_NOTES = 24  # top-voice notes a segment needs before it is matched
CHORD = 0.06  # notes struck this close together count as one chord
N = 4  # intervals per n-gram (five notes)
MATCH = 0.2  # share of a segment's n-grams that must be known to a piece
MIN_HITS = 6  # and at least this many of them
MERGE = 0.6  # core overlap at which two groups are taken to be one piece
CORE_AFTER = 5  # segments heard before a piece ignores n-grams heard only once
CORE_SHARE = 0.03  # and n-grams heard in fewer than this share of its plays
PHRASE_MAX = 8.0  # seconds: a five-note phrase slower than this is a stop, not tempo
PHRASES_MIN = 5  # timed phrases a segment needs before its tempo is trusted


def top_voice(notes):
    """The melody line: notes with nothing higher struck with or held over them.

    `notes` are dicts with t_on, t_off, pitch, sorted by t_on. Left-hand notes
    that slip through between legato melody notes are dropped when they sit
    far below the notes either side of them.
    """
    out = []
    recent = []  # earlier notes that may still cover the current one
    for i, n in enumerate(notes):
        t, p = n["t_on"], n["pitch"]
        recent = [o for o in recent if o["t_off"] > t - 0.15 or t - o["t_on"] < CHORD]
        covered = False
        for o in recent:
            # An octave or more below a note just let go is the other hand
            # showing through a legato gap, not the melody.
            held = o["t_off"] > t + 0.02 or (o["pitch"] - p >= 12 and o["t_off"] > t - 0.15)
            if o["pitch"] > p and (held or t - o["t_on"] < CHORD):
                covered = True
                break
        k = i + 1
        while not covered and k < len(notes) and notes[k]["t_on"] - t < CHORD:
            if notes[k]["pitch"] > p:
                covered = True
            k += 1
        if not covered:
            out.append(n)
        recent.append(n)
    keep = []
    for i, n in enumerate(out):
        prev = out[i - 1]["pitch"] if i else None
        nxt = out[i + 1]["pitch"] if i + 1 < len(out) else None
        if prev is not None and nxt is not None and prev - n["pitch"] >= 10 and nxt - n["pitch"] >= 10:
            continue
        keep.append(n)
    return keep


def segments(notes, gap=GAP, max_len=MAX_SEGMENT):
    """Split one session's notes into stretches of continuous playing."""
    segs, cur = [], []
    last_end = None
    for n in notes:
        if cur and (n["t_on"] - last_end > gap or n["t_on"] - cur[0]["t_on"] > max_len):
            segs.append(cur)
            cur = []
        last_end = max(last_end, n["t_off"]) if cur else n["t_off"]
        cur.append(n)
    if cur:
        segs.append(cur)
    return segs


def _generic(gram):
    """A plain scale run up or down, or mostly one repeated key: such n-grams
    turn up in scales and in most pieces, so they can't tell pieces apart."""
    return (all(1 <= x <= 2 for x in gram) or all(-2 <= x <= -1 for x in gram)
            or gram.count(0) >= 3)


def fingerprint(pitches, n=N):
    """The set of interval n-grams of a melody; the same in any key or tempo.

    Plain scale runs and repeated notes are left out: they say nothing about
    which piece it is, and with them every piece looks a bit like a scale.
    """
    iv = [max(-12, min(12, b - a)) for a, b in zip(pitches, pitches[1:])]
    grams = (tuple(iv[i:i + n]) for i in range(len(iv) - n + 1))
    return {g for g in grams if not _generic(g)}


def _names(pitches):
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return " ".join(f"{names[p % 12]}{p // 12 - 1}" for p in pitches)


class Matcher:
    """Groups segments into pieces as they arrive, oldest first."""

    def __init__(self, match=None, min_hits=None, core_after=None, merge=True):
        self.match = MATCH if match is None else match
        self.min_hits = MIN_HITS if min_hits is None else min_hits
        self.core_after = CORE_AFTER if core_after is None else core_after
        self.merge = merge
        self.pieces = []  # {"grams": Counter, "segments": [...]}, None once merged away
        self.index = defaultdict(set)  # n-gram -> pieces that contain it

    def core(self, piece):
        """A piece's n-grams, minus one-off slips once it has been heard enough."""
        grams = piece["grams"]
        if len(piece["segments"]) < self.core_after:
            return grams.keys()
        if piece.get("core") is None:
            # A big group collects enough slips to match any stepwise melody; a share
            # keeps its core to what the piece really is as its history grows.
            least = max(2, CORE_SHARE * len(piece["segments"]))
            piece["core"] = {g for g, c in grams.items() if c >= least}
        return piece["core"]

    def add(self, seg):
        """Assign a segment (dict with "fp") to a piece; returns its index or None."""
        fp = seg["fp"]
        if not fp:
            return None
        candidates = Counter(i for g in fp for i in self.index.get(g, ()))
        hits = []
        for i, n in candidates.items():
            if n < self.min_hits:
                continue
            p = self.pieces[i]
            common = fp & self.core(p)
            score = len(common) / len(fp)
            if len(common) >= self.min_hits and score >= self.match:
                hits.append((score, i))
        if not hits:
            self.pieces.append({"grams": Counter(fp), "segments": [seg]})
            seg["piece"] = len(self.pieces) - 1
            for g in fp:
                self.index[g].add(seg["piece"])
            return seg["piece"]
        best = max(hits)[1]
        piece = self.pieces[best]
        piece["segments"].append(seg)
        piece["grams"].update(fp)
        piece["core"] = None
        for g in fp:
            self.index[g].add(best)
        seg["piece"] = best
        if self.merge:
            best = self._consolidate(best)
        return best

    def _consolidate(self, i):
        """Merge piece i with any settled piece whose core is mostly the same.

        Early on, a hard-to-recognise play can start a second group of a piece
        it belongs to; once both groups have a settled core they are joined.
        """
        piece = self.pieces[i]
        if len(piece["segments"]) < self.core_after:
            return i
        core = self.core(piece)
        for j, other in self.groups():
            if j == i or len(other["segments"]) < self.core_after:
                continue
            ocore = self.core(other)
            if not core or not ocore:
                continue
            if len(core & ocore) / min(len(core), len(ocore)) >= MERGE:
                keep, gone = (i, j) if len(piece["segments"]) >= len(other["segments"]) else (j, i)
                k, g = self.pieces[keep], self.pieces[gone]
                k["grams"].update(g["grams"])
                k["core"] = None
                for x in g["grams"]:
                    self.index[x].discard(gone)
                    self.index[x].add(keep)
                k["segments"] = sorted(k["segments"] + g["segments"], key=lambda s: s["start"])
                for s in g["segments"]:
                    s["piece"] = keep
                self.pieces[gone] = None
                return self._consolidate(keep)
        return i

    def groups(self):
        return [(i, p) for i, p in enumerate(self.pieces) if p is not None]


def session_segments(store, sid):
    """Matchable segments of one stored session (read-only)."""
    out = []
    for seg in segments(store.notes(sid)):
        melody = top_voice(seg)
        if len(melody) < MIN_NOTES:
            continue
        pitches = [n["pitch"] for n in melody]
        out.append({
            "session": sid,
            "start": seg[0]["t_on"],
            "end": max(n["t_off"] for n in seg),
            "notes": len(seg),
            "active": metrics.active_seconds(seg),
            **{k: v for k, v in metrics.tempo_metrics([n["t_on"] for n in seg]).items()
               if k in ("tempo_bpm", "steadiness")},
            "opening": pitches[:8],
            "melody": [(n["t_on"], n["pitch"]) for n in melody],
            "fp": fingerprint(pitches),
        })
    return out


_engine = []


def engine_id():
    """A hash of everything that shapes a session's segments, so stored segments
    from older code are never reused; None (store nothing) without the sources."""
    if not _engine:
        try:
            consts = {k: v for k, v in vars(metrics).items() if k.isupper()}
            src = repr((GAP, MAX_SEGMENT, MIN_NOTES, CHORD, N, sorted(consts.items()))) + "".join(
                inspect.getsource(f) for f in (segments, top_voice, session_segments, fingerprint,
                                               _generic, metrics.active_seconds, metrics.tempo_metrics,
                                               metrics.onset_groups, pack, unpack))
            _engine.append(hashlib.sha256(src.encode()).hexdigest()[:16])
        except (OSError, TypeError):
            _engine.append(None)
    return _engine[0]


def pack(segs) -> bytes:
    """One session's segments as compact bytes for storing (fingerprints are rebuilt)."""
    out = []
    for g in segs:
        d = {k: v for k, v in g.items() if k not in ("fp", "session", "piece", "melody")}
        d["melody"] = [[round(t - g["start"], 6), p] for t, p in g["melody"]]
        out.append(d)
    return zlib.compress(json.dumps(out, separators=(",", ":")).encode(), 6)


def unpack(sid, blob) -> list:
    """The segments `pack` stored, as `session_segments` returns them."""
    segs = json.loads(zlib.decompress(blob))
    for d in segs:
        d["session"] = sid
        d["melody"] = [(d["start"] + t, p) for t, p in d["melody"]]
        d["fp"] = fingerprint([p for _, p in d["melody"]])
    return segs


def closed_in_order(store, since=None):
    """Closed sessions in the order the matcher takes them: oldest first."""
    return sorted(store.sessions(since=since, closed_only=True), key=lambda s: s["start"])


def add_sessions(matcher, store, sessions, cache=None):
    """Feed these sessions' segments to the matcher in order; returns the segments.

    `cache` (session id -> segments) saves re-reading sessions that are closed
    and so can no longer change. Adding sessions newer than all earlier ones to a
    matcher gives the same pieces as grouping everything again.
    """
    segs = []
    for s in sessions:
        if cache is None:
            found = session_segments(store, s["id"])
        else:
            if s["id"] not in cache:
                cache[s["id"]] = session_segments(store, s["id"])
            found = cache[s["id"]]
        for seg in found:
            seg.pop("piece", None)
            matcher.add(seg)
            segs.append(seg)
    return segs


def group(store, since=None, cache=None):
    """Match every closed session's segments, oldest first. Changes nothing."""
    matcher = Matcher()
    segs = add_sessions(matcher, store, closed_in_order(store, since), cache)
    return matcher, segs


def pieces_report(matcher):
    """Groups heard three or more times, most practised first."""
    rows = []
    for index, p in matcher.groups():
        segs = p["segments"]
        if len(segs) < 3:
            continue
        rows.append({
            "segments": len(segs),
            "sessions": len({s["session"] for s in segs}),
            "seconds": sum(s["end"] - s["start"] for s in segs),
            "first": segs[0]["start"],
            "last": segs[-1]["start"],
            "opening": segs[0]["opening"],
            "index": index,
        })
    for i, r in enumerate(sorted(rows, key=lambda r: r["first"])):
        r["label"] = _label(i)  # letters in the order pieces were first played
    rows.sort(key=lambda r: -r["seconds"])
    return rows


def _label(i):
    return "Piece " + (chr(65 + i) if i < 26 else str(i + 1))


def _key(piece):
    first = min(piece["segments"], key=lambda s: s["start"])
    return f"{first['session']}-{int(first['start'])}"


def resolve_names(matcher, named, min_overlap=0.5, min_share=0.3):
    """Map group index -> (name id, name) for groups that match a named piece.

    `named` holds (id, name, grams) rows saved when the owner named a group.
    Grouping is recomputed from scratch, so names follow the music: a group
    takes a name when most of its n-grams belong to the named piece and it
    holds a fair share of that piece (so a short scale group inside it
    doesn't take its name).
    """
    out = {}
    for index, p in matcher.groups():
        if len(p["segments"]) < 3:
            continue
        core = matcher.core(p)
        best, score = None, min_overlap
        for nid, name, grams in named:
            if not core or not grams:
                continue
            common = len(core & grams)
            o = common / len(core)
            if o >= score and common >= min_share * len(grams):
                best, score = (nid, name), o
        if best:
            out[index] = best
    return out


def _motif(segs, rep, n=6):
    """The phrase of n melody notes found in the most plays of a piece (exact
    keys: a phrase you would recognise), and a play to hear it in: the best
    play `rep` if it has it, else the latest play that does."""
    counts = Counter()
    for s in segs:
        p = [x[1] for x in s.get("melody", ())]
        counts.update({tuple(p[i:i + n]) for i in range(len(p) - n + 1)
                       if len(set(p[i:i + n])) >= 3})
    if not counts:
        return tuple(rep["opening"][:n]), rep, rep["start"]
    motif = counts.most_common(1)[0][0]
    for s in [rep] + segs[::-1]:
        m = s.get("melody", ())
        for i in range(len(m) - n + 1):
            if tuple(x[1] for x in m[i:i + n]) == motif:
                return motif, s, m[i][0]
    return motif, rep, rep["start"]


def _phrase_times(seg):
    """Median duration of each five-note melody phrase (by intervals) in a segment."""
    mel = seg["melody"]
    pitches = [p for _, p in mel]
    found = defaultdict(list)
    for i in range(len(mel) - N):
        dt = mel[i + N][0] - mel[i][0]
        if 0 < dt < PHRASE_MAX:
            found[tuple(b - a for a, b in zip(pitches[i:i + N], pitches[i + 1:i + N + 1]))].append(dt)
    return {g: statistics.median(v) for g, v in found.items()}


def piece_tempo(segs):
    """Tempo of each segment of one piece, as {index in segs: bpm or None}.

    Timing every note gap mixes in the left hand and halves or doubles the beat
    from one play to the next. Instead each segment's phrases are timed against
    the same phrases in the piece's other plays, which gives its speed relative
    to the piece; one beat for the whole piece (its typical melody note, folded
    into 60-180 once) turns that into bpm, so a session can't jump by 2x.
    """
    times = [_phrase_times(s) for s in segs]
    pooled = defaultdict(list)
    for t in times:
        for g, d in t.items():
            pooled[g].append(d)
    plays = min(PHRASES_MIN, max(2, len(segs) // 2))  # a new piece has few plays to compare
    ref = {g: statistics.median(v) for g, v in pooled.items() if len(v) >= plays}
    speed = {}
    for i, t in enumerate(times):
        r = [ref[g] / d for g, d in t.items() if g in ref]
        if len(r) >= PHRASES_MIN:
            speed[i] = statistics.median(r)
    if not speed:
        return {i: None for i in range(len(segs))}
    # A melody note at speed 1: the typical gap of the piece's first timed plays, scaled
    # by their speed. Taking the first ones keeps the beat (and its fold) the same as
    # more sessions arrive, so past tempos don't halve or double later.
    gaps = []
    for i, v in sorted(speed.items())[:10]:
        mel = [t for t, _ in segs[i]["melody"]]
        iois = [b - a for a, b in zip(mel, mel[1:]) if 0 < b - a < PHRASE_MAX / N]
        if iois:
            gaps.append(statistics.median(iois) * v)
    beat = 60.0 / statistics.median(gaps) if gaps else 100.0
    while beat > 180:
        beat /= 2
    while beat < 60:
        beat *= 2
    return {i: (beat * speed[i] if i in speed else None) for i in range(len(segs))}


STUMBLE_RATIO = 2.0  # a gap this many times its usual length at that spot is a stumble
STUMBLE_MIN = 0.4  # and at least this many seconds longer than usual
STUMBLE_LOW = 0.3  # "usual" = this quantile of the spot's gaps, how it goes when it goes well
STUMBLE_FALLBACK = 3.0  # x the play's typical gap, at a spot the piece doesn't know
TROUBLE_RECENT = 10  # trouble spots come from this many latest sessions of a piece
TROUBLE_MIN = 3  # stumbles at one spot before it is a trouble spot


def _gap_key(pitches, i):
    """Where in the music the gap after note i sits: the intervals of the four
    notes up to it and the one after (the same in any key)."""
    if i < 3:
        return None
    return tuple(b - a for a, b in zip(pitches[i - 3:i + 1], pitches[i - 2:i + 2]))


def _quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def stumble_count(found) -> int:
    """Stumbles in one play: gaps within 2 notes of the previous one are the same stumble."""
    return sum(1 for k, i in enumerate(found) if k == 0 or i - found[k - 1] > 2)


def piece_stumbles(segs):
    """Stumbling gaps in each play of one piece, as [[note index, ...] per segment];
    `stumble_count` counts them, since one stumble can be felt over a couple of notes.

    A stumble is a gap between two melody notes far longer than the piece
    usually has at that spot (a hesitation, or a stop to find the place again).
    The usual gap is how the spot goes in the piece's better plays, so a spot
    you stumble at most of the time still counts; a held note that the music
    asks for is long in every play and doesn't. Each play is first scaled to
    its own speed, so slow practice isn't one long stumble.
    """
    mels = [([t for t, _ in s["melody"]], [p for _, p in s["melody"]]) for s in segs]
    pooled = defaultdict(list)
    for ts, ps in mels:
        for i in range(len(ts) - 1):
            k = _gap_key(ps, i)
            if k:
                pooled[k].append(ts[i + 1] - ts[i])
    ref = {k: q for k, v in pooled.items() if len(v) >= 3 and (q := _quantile(v, STUMBLE_LOW)) > 0}
    out = []
    for ts, ps in mels:
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        keys = [_gap_key(ps, i) for i in range(len(gaps))]
        ratios = [g / ref[k] for g, k in zip(gaps, keys) if k in ref]
        speed = statistics.median(ratios) if len(ratios) >= 8 else 1.0
        typical = statistics.median(gaps) if gaps else 0.0
        found = []
        for i, (g, k) in enumerate(zip(gaps, keys)):
            usual = ref[k] * speed if k in ref else typical
            ratio = STUMBLE_RATIO if k in ref else STUMBLE_FALLBACK
            if g > ratio * usual and g - usual > STUMBLE_MIN:
                found.append(i)
        out.append(found)
    return out


def clean_run(seg, stumbles):
    """(seconds, start time) of the longest stretch of a play with no stumble."""
    ts = [t for t, _ in seg["melody"]]
    if not ts:
        return 0.0, seg["start"]
    best, at, a = 0.0, ts[0], 0
    for b in list(stumbles) + [len(ts) - 1]:
        if ts[b] - ts[a] > best:
            best, at = ts[b] - ts[a], ts[a]
        a = min(b + 1, len(ts) - 1)
    return best, at


def trouble_spots(segs, stumbles, session_starts=None, n=3):
    """The spots in a piece you stumble at most in its latest sessions: the five
    melody notes before the stumble, how many times you stopped there out of the
    times you got there, and where to hear the latest one."""
    latest = {}
    for s in segs:
        latest[s["session"]] = max(latest.get(s["session"], s["start"]), s["start"])
    recent = set(sorted(latest, key=latest.get)[-TROUBLE_RECENT:])
    stops, passes, last = Counter(), Counter(), {}
    for s, found in zip(segs, stumbles):
        if s["session"] not in recent:
            continue
        ps = [p for _, p in s["melody"]]
        for i in range(4, len(ps)):
            passes[tuple(ps[i - 4:i + 1])] += 1
        for j, i in enumerate(found):
            if i >= 4 and (j == 0 or i - found[j - 1] > 2):
                k = tuple(ps[i - 4:i + 1])
                stops[k] += 1
                last[k] = (s["session"], s["melody"][i - 4][0])
    rows = []
    for k, c in stops.most_common():
        if c < TROUBLE_MIN or len(rows) >= n:
            break
        sid, t = last[k]
        t0 = (session_starts or {}).get(sid, t)
        rows.append({"notes": list(k), "stumbles": c, "passes": max(c, passes[k]),
                     "session": sid, "offset": round(max(t - 2.0, t0) - t0, 2)})
    return rows


def pieces_view(matcher, named=(), session_starts=None):
    """Pieces for the dashboard: groups heard three or more times, plus their
    named matches merged under one name, most recently played first."""
    names = resolve_names(matcher, named)
    groups = {}
    for index, p in matcher.groups():
        if len(p["segments"]) < 3:
            continue
        nid = names.get(index, (None, None))[0]
        g = groups.setdefault(("n", nid) if nid else ("g", index),
                              {"segments": [], "keys": [], "name": names.get(index, (None, None))[1],
                               "name_id": nid})
        g["segments"] += p["segments"]
        g["keys"].append(_key(p))
        core = matcher.core(p)
        best = max(p["segments"], key=lambda s: len(s["fp"] & core))
        if g.get("rep") is None or len(best["fp"] & core) > g["rep_score"]:
            g["rep"], g["rep_score"] = best, len(best["fp"] & core)
    rows = []
    for g in groups.values():
        segs = sorted(g["segments"], key=lambda s: s["start"])
        tempo = piece_tempo(segs)
        stumbles = piece_stumbles(segs)
        best_run = None
        per = {}
        for k, s in enumerate(segs):
            h = per.setdefault(s["session"], {"session": s["session"], "start": s["start"],
                                              "active_seconds": 0.0, "_t": [0.0, 0.0], "_s": [0.0, 0.0]})
            # Where to play this recording from: 1 s before the piece starts, like `opening`.
            t0 = (session_starts or {}).get(s["session"], s["start"])
            h.setdefault("offset", round(max(s["start"] - 1.0, t0) - t0, 2))
            h["active_seconds"] += s["active"]
            h["stumbles"] = h.get("stumbles", 0) + stumble_count(stumbles[k])
            run, run_at = clean_run(s, stumbles[k])
            if run > h.get("clean_run", -1.0):
                h["clean_run"] = run
                h["clean_run_offset"] = round(max(run_at - 1.0, t0) - t0, 2)
            if best_run is None or run > best_run[0]:
                best_run = (run, s["session"], max(run_at - 1.0, t0) - t0)
            if tempo[k]:
                h["_t"][0] += tempo[k] * s["active"]
                h["_t"][1] += s["active"]
            if s.get("steadiness") is not None:
                h["_s"][0] += s["steadiness"] * s["active"]
                h["_s"][1] += s["active"]
        history = []
        for h in sorted(per.values(), key=lambda h: h["start"]):
            t, st = h.pop("_t"), h.pop("_s")
            h["tempo_bpm"] = round(t[0] / t[1]) if t[1] else None
            h["steadiness"] = round(st[0] / st[1]) if st[1] else None
            # Stumbles a minute, so a long session and a short one compare.
            h["stumbles_per_min"] = round(h["stumbles"] / (h["active_seconds"] / 60), 1) \
                if h["active_seconds"] >= 30 else None
            h["active_seconds"] = round(h["active_seconds"])
            h["clean_run"] = round(h["clean_run"])
            history.append(h)
        first = segs[0]
        motif, rep, at = _motif(segs, g["rep"])
        t0 = (session_starts or {}).get(rep["session"], rep["start"])
        rows.append({
            "key": g["keys"][0],
            "name": g["name"],
            "active_seconds": round(sum(s["active"] for s in segs)),
            "segments": len(segs),
            "sessions": len(per),
            "first": first["start"],
            "last": segs[-1]["start"],
            # Its most played phrase, and where to hear it, to recognise it by ear.
            "opening": {"session": rep["session"], "offset": round(max(at - 1.0, rep["start"]) - t0, 2),
                        "notes": list(motif)},
            "history": history,
            # The longest stretch ever played without a stumble, and where to hear it.
            "best_run": {"seconds": round(best_run[0]), "session": best_run[1],
                         "offset": round(best_run[2], 2)},
            "trouble": trouble_spots(segs, stumbles, session_starts),
            "_groups": [i for i, p in matcher.groups() if _key(p) in g["keys"]],
            "_keys": g["keys"],
            "_name_id": g["name_id"],
        })
    rows.sort(key=lambda r: r["first"])
    for i, r in enumerate(rows):
        r["label"] = r["name"] or _label(i)
    rows.sort(key=lambda r: -r["last"])
    return rows


def format_report(matcher, segs):
    from datetime import datetime
    rows = pieces_report(matcher)
    day = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d")
    lines = [f"{len(segs)} segments in {len({s['session'] for s in segs})} sessions; "
             f"{len(rows)} pieces heard 3+ times; "
             f"{sum(1 for _, p in matcher.groups() if len(p['segments']) == 1)} segments matched nothing.",
             "Short scale or arpeggio groups can show up too; naming them comes later.", ""]
    if rows:
        lines.append(f"{'piece':<9} {'time':>7} {'segs':>5} {'sess':>5}  {'first':<10}  {'last':<10}  opening notes")
    for r in rows:
        lines.append(f"{r['label']:<9} {r['seconds'] / 60:6.0f}m {r['segments']:>5} {r['sessions']:>5}"
                     f"  {day(r['first'])}  {day(r['last'])}  {_names(r['opening'])}")
    return "\n".join(lines)


# --- Scoring against the simulator's log ------------------------------------

def truth(seg, log):
    """What the simulator was playing for most of a segment, from its log."""
    best, overlap = None, 0.0
    for a, b, what in log:
        o = min(b, seg["end"]) - max(a, seg["start"])
        if o > overlap:
            best, overlap = what, o
    return best


def evaluate(matcher, segs, log, pieces):
    """Right/wrong rates of the grouping against what was really played.

    Each group is named after the true piece most of its segments came from,
    and each true piece's main group is the biggest group named after it. A
    segment of a real piece is right when it lands in its piece's main group,
    and wrong when it lands in a group named after something else; so is an
    exercise or new music that lands in a group named after anything but
    itself. New music (sight-reading) is wrong whenever it is grouped with
    anything, since each new piece is different. Segments of a piece that end up in a smaller second group of the
    same piece are neither: the piece was split, which is reported apart.
    """
    for s in segs:
        s["truth"] = truth(s, log)
    names, sizes = {}, {}
    for i, p in matcher.groups():
        names[i] = Counter(s["truth"] for s in p["segments"]).most_common(1)[0][0]
        sizes[i] = len(p["segments"])
    main = {}
    for i in names:
        if names[i] in pieces and sizes[i] >= 2 and sizes[i] > sizes.get(main.get(names[i]), 0):
            main[names[i]] = i
    piece_segs = [s for s in segs if s["truth"] in pieces]
    right = sum(1 for s in piece_segs if s["piece"] == main.get(s["truth"]))
    wrong = sum(1 for s in segs if s["piece"] is not None and (
        names[s["piece"]] != s["truth"] or (s["truth"] == "new" and sizes[s["piece"]] > 1)))
    groups = Counter(names[i] for i in names if names[i] in pieces and sizes[i] >= 2)
    return {
        "segments": len(segs),
        "piece_segments": len(piece_segs),
        "right": right / max(1, len(piece_segs)),
        "wrong": wrong / max(1, len(segs)),
        "groups_per_piece": {name: groups.get(name, 0) for name in sorted(pieces)},
    }
