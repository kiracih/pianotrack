"""Pieces matcher: finds the stretches of practice that play the same music.

Step 1 of the Pieces feature, and read-only: it reads sessions and notes, and
never writes to the database. Each session is cut into segments at pauses, the
top voice of each segment is reduced to its pitch intervals (so a piece played
in another key or at another tempo looks the same), and segments that share
enough interval n-grams are grouped as one piece, oldest first.

Beginners play wrong notes, miss notes and restart, so a segment only needs a
share of its n-grams to match, not all of them.
"""

from collections import Counter

GAP = 3.5  # seconds of silence that end a segment
MAX_SEGMENT = 240.0  # longer stretches are cut into segments of this length
MIN_NOTES = 24  # top-voice notes a segment needs before it is matched
CHORD = 0.06  # notes struck this close together count as one chord
N = 4  # intervals per n-gram (five notes)
MATCH = 0.2  # share of a segment's n-grams that must be known to a piece
MIN_HITS = 6  # and at least this many of them
MERGE = 0.6  # core overlap at which two groups are taken to be one piece
CORE_AFTER = 5  # segments heard before a piece ignores n-grams heard only once


def top_voice(notes):
    """The melody line: notes with nothing higher struck with or held over them.

    `notes` are dicts with t_on, t_off, pitch, sorted by t_on. Left-hand notes
    that slip through between legato melody notes are dropped when they sit
    far below the notes either side of them.
    """
    out = []
    for i, n in enumerate(notes):
        t, p = n["t_on"], n["pitch"]
        covered = False
        j = i - 1
        while j >= 0 and notes[j]["t_on"] > t - 8.0:
            o = notes[j]
            # An octave or more below a note just let go is the other hand
            # showing through a legato gap, not the melody.
            held = o["t_off"] > t + 0.02 or (o["pitch"] - p >= 12 and o["t_off"] > t - 0.15)
            if o["pitch"] > p and (held or t - o["t_on"] < CHORD):
                covered = True
                break
            j -= 1
        k = i + 1
        while not covered and k < len(notes) and notes[k]["t_on"] - t < CHORD:
            if notes[k]["pitch"] > p:
                covered = True
            k += 1
        if not covered:
            out.append(n)
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

    def core(self, piece):
        """A piece's n-grams, minus one-off slips once it has been heard enough."""
        grams = piece["grams"]
        if len(piece["segments"]) < self.core_after:
            return grams.keys()
        return {g for g, c in grams.items() if c >= 2}

    def add(self, seg):
        """Assign a segment (dict with "fp") to a piece; returns its index or None."""
        fp = seg["fp"]
        if not fp:
            return None
        hits = []
        for i, p in self.groups():
            common = fp & self.core(p)
            score = len(common) / len(fp)
            if len(common) >= self.min_hits and score >= self.match:
                hits.append((score, i))
        if not hits:
            self.pieces.append({"grams": Counter(fp), "segments": [seg]})
            seg["piece"] = len(self.pieces) - 1
            return seg["piece"]
        best = max(hits)[1]
        piece = self.pieces[best]
        piece["segments"].append(seg)
        piece["grams"].update(fp)
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
            "opening": pitches[:8],
            "fp": fingerprint(pitches),
        })
    return out


def group(store, since=None):
    """Match every closed session's segments, oldest first. Changes nothing."""
    matcher = Matcher()
    segs = []
    for s in sorted(store.sessions(since=since, closed_only=True), key=lambda s: s["start"]):
        for seg in session_segments(store, s["id"]):
            matcher.add(seg)
            segs.append(seg)
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
    rows.sort(key=lambda r: -r["seconds"])
    for i, r in enumerate(rows):
        r["label"] = "Piece " + (chr(65 + i) if i < 26 else str(i + 1))
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
