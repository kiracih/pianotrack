"""HTTP server: the dashboard page plus a small JSON/CSV API."""

import csv
import io
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from urllib.parse import parse_qs, quote, urlparse

from . import auth as authmod, backup as backupmod, metrics, pieces as piecesmod
from .midi import write_smf

log = logging.getLogger(__name__)
STATIC = os.path.join(os.path.dirname(__file__), "static")
ASSETS = {"/manifest.webmanifest": "application/manifest+json", "/icon.svg": "image/svg+xml",
          "/icon-180.png": "image/png", "/icon-512.png": "image/png", "/replay.js": "text/javascript; charset=utf-8",
          "/keys3d.js": "text/javascript; charset=utf-8", "/piano3d.js": "text/javascript; charset=utf-8",
          "/falling3d.js": "text/javascript; charset=utf-8"}
# Bundled libraries (three.js, MIT). The version is in the path, so browsers may keep them.
VENDOR = {"/vendor/three-0.180.0/three.module.min.js", "/vendor/three-0.180.0/three.core.min.js"}
SESSION_FIELDS = ["start", "end", "duration_seconds", "active_seconds", "note_count",
                  "notes_per_minute", "velocity_mean", "dynamic_range", "tempo_bpm",
                  "steadiness", "intensity", "load", "sustain_fraction", "unique_keys",
                  "lowest_pitch", "highest_pitch", "chord_count", "left_hand_share"]


class Api:
    """Pure functions over the store, kept apart from HTTP for testing."""

    def __init__(self, store, collector=None, backups=None, demo=False):
        self.store = store
        self.demo = demo  # simulated data, shown to anyone, changed by no one
        self.collector = collector
        self.backups = backups
        self._live_cache = {}
        self._segments = {}  # closed session id -> its piece segments (closed sessions never change)
        self._matcher = None  # (session ids in the order added, matcher) kept between calls
        self._pieces_cache = None
        self._pieces_lock = threading.RLock()  # also held while name_piece reads the matcher
        self._refresh, self._refresh_guard = None, threading.Lock()  # background pieces pass
        self._refresh_failed = float("-inf")

    def _metrics(self, s):
        if s["metrics"] and s["closed"]:
            return json.loads(s["metrics"]) if isinstance(s["metrics"], str) else s["metrics"]
        notes = self.store.notes(s["id"])
        key = (s["id"], len(notes))
        if key not in self._live_cache:
            self._live_cache = {key: metrics.session_metrics(notes, self.store.pedals(s["id"]))}
        m = self._live_cache[key]
        if s["closed"]:
            self.store.set_metrics(s["id"], m)
        return m

    def _sessions_with_metrics(self, since=None):
        out = []
        for s in self.store.sessions(since=since):
            s = dict(s)
            s["metrics"] = self._metrics(s)
            out.append(s)
        return out

    def summary(self):
        settings = self.store.settings()
        today = date.today()
        since = datetime.combine(today - timedelta(days=400), datetime.min.time()).timestamp()
        sessions = self._sessions_with_metrics(since)
        days = metrics.daily_totals(sessions)
        empty = {"active_seconds": 0, "notes": 0, "sessions": 0, "load": 0}
        t = days.get(today, empty)
        goal = settings["daily_goal_minutes"] * 60
        week = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            v = days.get(d, empty)
            week.append({"date": d.isoformat(), "active_seconds": round(v["active_seconds"]),
                         "notes": v["notes"], "goal_met": v["active_seconds"] >= goal,
                         "goal_times": metrics.goal_times(v["active_seconds"], goal)})
        live = None
        for s in sessions:
            if not s["closed"]:
                m = s["metrics"]
                live = {"session_id": s["id"], "start": s["start"],
                        "last_event": s["end"], "note_count": m.get("note_count", 0),
                        "active_seconds": m.get("active_seconds", 0),
                        "notes_per_minute": m.get("notes_per_minute", 0),
                        "velocity_mean": m.get("velocity_mean")}
        closed = [s for s in sessions if s["closed"] and s["metrics"].get("note_count")]
        records = {}
        if closed:
            longest = max(closed, key=lambda s: s["metrics"]["active_seconds"])
            records["longest_session"] = {"session_id": longest["id"],
                                          "active_seconds": longest["metrics"]["active_seconds"]}
            busiest = max(closed, key=lambda s: s["metrics"]["note_count"])
            records["most_notes"] = {"session_id": busiest["id"],
                                     "note_count": busiest["metrics"]["note_count"]}
            steady = [s for s in closed if s["metrics"].get("steadiness") is not None]
            if steady:
                best = max(steady, key=lambda s: s["metrics"]["steadiness"])
                records["steadiest"] = {"session_id": best["id"],
                                        "steadiness": best["metrics"]["steadiness"]}
        if days:
            bd = max(days.items(), key=lambda kv: kv[1]["active_seconds"])
            records["best_day"] = {"date": bd[0].isoformat(),
                                   "active_seconds": round(bd[1]["active_seconds"])}
        streak = metrics.streaks(days, settings["streak_min_minutes"] * 60, today)
        # Last day that counted toward a streak, so "one day off" only follows a real habit day.
        played = [d for d, v in days.items()
                  if d <= today and v["active_seconds"] >= settings["streak_min_minutes"] * 60]
        last_played = (today - max(played)).days if played else None
        week_secs = sum(w["active_seconds"] for w in week)
        prev_week = sum(days.get(today - timedelta(days=i), empty)["active_seconds"]
                        for i in range(7, 14))
        return {
            "now": time.time(),
            "settings": settings,
            "today": {"date": today.isoformat(), "active_seconds": round(t["active_seconds"]),
                      "notes": t["notes"], "sessions": t["sessions"],
                      "load": round(t["load"], 1), "goal_seconds": goal,
                      "goal_pct": round(100 * t["active_seconds"] / goal) if goal else 0,
                      "invite": metrics.invite(t["active_seconds"], goal, settings["streak_min_minutes"] * 60,
                                               streak["current"], last_played)},
            "week": week,
            "week_total_seconds": round(week_secs),
            "prev_week_total_seconds": round(prev_week),
            "streak": streak,
            "week_days": {"played": metrics.week_days(days, settings["streak_min_minutes"] * 60, today),
                          "target": settings["weekly_days_target"]},
            # Mondays only (the Pi's date, the day boundary everywhere): the week
            # starts afresh, so say how last week went.
            "last_week": (metrics.last_week(days, settings["streak_min_minutes"] * 60,
                                            settings["weekly_days_target"], today)
                          if today.weekday() == 0 else None),
            "consistency_28d": metrics.consistency(days, today),
            "totals": {"sessions": len(closed),
                       "active_seconds": round(sum(s["metrics"]["active_seconds"] for s in closed)),
                       "notes": sum(s["metrics"]["note_count"] for s in closed)},
            "records": records,
            "live": live,
            "collector": self.collector.status if self.collector else None,
            "demo": self.demo,
        }

    def recap(self, day=None):
        """One calendar week (Monday to Sunday) for the share card: the octave, time,
        days played, streak, keys pressed, the most played keys and pieces.

        `day` is any date in the week; by default this week, or last week on a
        Monday, when this one has only just begun.
        """
        settings = self.store.settings()
        today = date.today()
        if day is None:
            day = today - timedelta(days=7) if today.weekday() == 0 else today
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=6)
        lo = datetime.combine(start - timedelta(days=400), datetime.min.time()).timestamp()
        sessions = self._sessions_with_metrics(lo)
        days = metrics.daily_totals(sessions)
        min_secs = settings["streak_min_minutes"] * 60
        goal = settings["daily_goal_minutes"] * 60
        empty = {"active_seconds": 0, "notes": 0, "sessions": 0}
        week = []
        for i in range(7):
            d = start + timedelta(days=i)
            v = days.get(d, empty)
            week.append({"date": d.isoformat(), "active_seconds": round(v["active_seconds"]),
                         "notes": v["notes"], "goal_met": v["active_seconds"] >= goal,
                         "goal_times": metrics.goal_times(v["active_seconds"], goal),
                         "later": d > today})
        total = sum(w["active_seconds"] for w in week)
        prev = sum(days.get(start - timedelta(days=i), empty)["active_seconds"] for i in range(1, 8))
        # Every earlier week in the window, to tell a record week.
        weeks = {}
        for d, v in days.items():
            if d < start:
                k = d - timedelta(days=d.weekday())
                weeks[k] = weeks.get(k, 0) + v["active_seconds"]
        mine = [s for s in sessions if s["closed"] and s["metrics"].get("note_count")
                and start <= metrics.local_day(s["start"]) <= end]
        hist = [0] * (metrics.HIGHEST_KEY - metrics.LOWEST_KEY + 1)
        for s in mine:
            for i, c in enumerate(s["metrics"].get("key_histogram") or []):
                hist[i] += c
        top = sorted(range(len(hist)), key=lambda i: -hist[i])[:3]
        longest = max(mine, key=lambda s: s["metrics"]["active_seconds"], default=None)
        return {
            "start": start.isoformat(), "end": end.isoformat(),
            "complete": end < today,
            "days": week,
            "goal_seconds": goal,
            "active_seconds": total,
            "prev_active_seconds": round(prev),
            "best_week": total > 0 and all(total > w for w in weeks.values()),
            "played": sum(1 for w in week if w["active_seconds"] >= min_secs),
            "target": settings["weekly_days_target"],
            "streak": metrics.streaks(days, min_secs, min(end, today)),
            "sessions": len(mine),
            "notes": sum(s["metrics"]["note_count"] for s in mine),
            "longest_session": ({"session_id": longest["id"], "start": longest["start"],
                                 "active_seconds": longest["metrics"]["active_seconds"]}
                                if longest else None),
            "histogram": hist,
            "top_keys": [{"pitch": metrics.LOWEST_KEY + i, "count": hist[i]} for i in top if hist[i]],
            "pieces": self._recap_pieces({s["id"] for s in mine}),
        }

    def _recap_pieces(self, ids):
        """The week's most played pieces, with stumbles a minute at the first and
        last play of the week. None while the pieces are still being found."""
        now = self._pieces_now()[0]
        if now is None:
            return None
        out = []
        for r in now[1]:
            hs = [h for h in r["history"] if h["session"] in ids]
            if not hs:
                continue
            rated = [h["stumbles_per_min"] for h in hs if h["stumbles_per_min"] is not None]
            out.append({"key": r["key"], "label": r["label"], "named": bool(r["name"]),
                        "active_seconds": sum(h["active_seconds"] for h in hs),
                        "plays": len(hs),
                        "clean_run": max(h["clean_run"] for h in hs),
                        "stumbles_per_min": [rated[0], rated[-1]] if len(rated) > 1 else None})
        out.sort(key=lambda p: -p["active_seconds"])
        return out[:3]

    def days(self, n=365):
        today = date.today()
        since = datetime.combine(today - timedelta(days=n), datetime.min.time()).timestamp()
        days = metrics.daily_totals(self._sessions_with_metrics(since))
        out = []
        for i in range(n - 1, -1, -1):
            d = today - timedelta(days=i)
            v = days.get(d)
            out.append({"date": d.isoformat(),
                        "active_seconds": round(v["active_seconds"]) if v else 0,
                        "notes": v["notes"] if v else 0,
                        "load": round(v["load"], 1) if v else 0})
        return out

    def trends(self, n=60):
        """Per-day averages (weighted by active time) of the skill metrics."""
        today = date.today()
        since = datetime.combine(today - timedelta(days=n), datetime.min.time()).timestamp()
        buckets = {}
        for s in self._sessions_with_metrics(since):
            m = s["metrics"]
            if not m.get("note_count"):
                continue
            d = metrics.local_day(s["start"]).isoformat()
            b = buckets.setdefault(d, {"w": 0.0, "steadiness": [0.0, 0.0],
                                       "notes_per_minute": 0.0, "velocity_mean": 0.0,
                                       "dynamic_range": 0.0, "tempo_bpm": [0.0, 0.0]})
            w = m["active_seconds"]
            b["w"] += w
            for k in ("notes_per_minute", "velocity_mean", "dynamic_range"):
                b[k] += m[k] * w
            for k in ("steadiness", "tempo_bpm"):
                if m.get(k) is not None:
                    b[k][0] += m[k] * w
                    b[k][1] += w
        out = []
        for d in sorted(buckets):
            b = buckets[d]
            if b["w"] <= 0:
                continue
            row = {"date": d}
            for k in ("notes_per_minute", "velocity_mean", "dynamic_range"):
                row[k] = round(b[k] / b["w"], 1)
            for k in ("steadiness", "tempo_bpm"):
                row[k] = round(b[k][0] / b[k][1], 1) if b[k][1] else None
            out.append(row)
        return out

    def tunnel_url(self):
        """Public URL of the Cloudflare tunnel, written next to the database by deploy/tunnel.sh."""
        path = os.path.join(os.path.dirname(os.path.abspath(self.store.path)), "tunnel-url")
        try:
            with open(path) as f:
                return f.read().strip() or None
        except OSError:
            return None

    def keys(self, n=30):
        """Key usage summed over the last `n` days (n=0 means all time)."""
        since = None
        if n:
            since = datetime.combine(date.today() - timedelta(days=n - 1),
                                     datetime.min.time()).timestamp()
        hist = [0] * (metrics.HIGHEST_KEY - metrics.LOWEST_KEY + 1)
        count = 0
        for s in self._sessions_with_metrics(since):
            h = s["metrics"].get("key_histogram")
            if not h:
                continue
            count += 1
            for i, c in enumerate(h):
                hist[i] += c
        return {"days": n, "sessions": count, "total": sum(hist), "histogram": hist}

    def sessions(self, limit=50):
        out = []
        for s in self.store.sessions(limit=limit):
            m = self._metrics(s)
            row = {"id": s["id"], "uid": s["uid"], "device": s["device"],
                   "closed": bool(s["closed"]), "source": s["source"]}
            row.update({k: m.get(k) for k in SESSION_FIELDS})
            row["start"], row["end"] = s["start"], s["end"]
            out.append(row)
        return out

    def session(self, sid):
        s = self.store.session(sid)
        if not s:
            return None
        m = self._metrics(s)
        found = []
        now, fresh = self._pieces_peek() if s["closed"] else (None, False)
        if now:
            for r in now[1]:
                for h in r["history"]:
                    if h["session"] == sid:
                        found.append({"key": r["key"], "label": r["label"],
                                      "active_seconds": h["active_seconds"],
                                      "stumbles": h["stumbles"], "clean_run": h["clean_run"]})
        return {"id": s["id"], "uid": s["uid"], "device": s["device"],
                "closed": bool(s["closed"]), "source": s["source"],
                "start": s["start"], "end": s["end"], "metrics": m, "pieces": found,
                # Not in the last view while a pass runs: it may just not be counted yet.
                "pieces_pending": bool(s["closed"]) and (now is None or (not fresh and not found))}

    def _pieces_now(self):
        """(pieces, fresh) without waiting: while a pass runs (the first after a
        restart can take a minute on the Pi), the last view with fresh False, or
        None before there is one."""
        if self._pieces_lock.acquire(blocking=False):
            try:
                return self._pieces(), True
            finally:
                self._pieces_lock.release()
        return (self._pieces_cache[1] if self._pieces_cache else None), False

    def _pieces_peek(self):
        """(pieces, fresh) from the last view, never running a pass here: opening a
        session right after practice must not wait for Pieces. A stale view starts
        a pass in the background and is returned with fresh False."""
        cache = self._pieces_cache
        if cache and cache[0] == self._pieces_key()[2]:
            return cache[1], True
        with self._refresh_guard:
            # After a failed pass, wait a minute: the page asks every 3 s.
            if not (self._refresh and self._refresh.is_alive()) and time.monotonic() - self._refresh_failed > 60:
                self._refresh = threading.Thread(target=self._refresh_pass, daemon=True)
                self._refresh.start()
        return (cache[1] if cache else None), False

    def _refresh_pass(self):
        try:
            self._pieces()
        except Exception:
            log.exception("finding pieces failed; trying again in a minute")
            self._refresh_failed = time.monotonic()

    def _pieces_key(self):
        """(closed sessions oldest first, piece names, the key a view is valid for)."""
        closed = piecesmod.closed_in_order(self.store)
        ids = tuple((s["id"], s["start"]) for s in closed)  # ids alone can be reused after a delete
        named = self.store.piece_names()
        return closed, named, (ids, tuple((n[0], n[1]) for n in named))

    def _pieces(self):
        """(matcher, view) over all closed sessions, recomputed when they or names change.

        Sessions that close after everything already matched are added to the kept
        matcher, which gives the same pieces as regrouping and is far cheaper with a
        long history. A deleted or out-of-order session regroups from scratch.
        """
        with self._pieces_lock:
            closed, named, key = self._pieces_key()
            ids = key[0]
            if self._pieces_cache and self._pieces_cache[0] == key:
                return self._pieces_cache[1]
            done = self._matcher[0] if self._matcher else None
            if done is None or ids[:len(done)] != done:
                # Keep cached segments only for sessions that are still the same recording.
                keep = {sid for sid, _ in (set(ids) & set(done) if done else ids)}
                self._segments = {k: v for k, v in self._segments.items() if k in keep}
                self._matcher = ((), piecesmod.Matcher())
                done = ()
            matcher = self._matcher[1]
            if len(ids) > len(done):
                self._load_segments(closed[len(done):])
                self._matcher = None  # until the add succeeds: a half-fed matcher must regroup
                piecesmod.add_sessions(matcher, self.store, closed[len(done):], self._segments)
                self._matcher = (ids, matcher)
            view = piecesmod.pieces_view(matcher, named, {s["id"]: s["start"] for s in closed})
            self._pieces_cache = (key, (matcher, view))
            return matcher, view

    def _load_segments(self, sessions):
        """Fill the segment cache from the database, and store the ones it lacks:
        a restart then reads each session's notes once, not on every start."""
        new = [s for s in sessions if s["id"] not in self._segments]
        if not new:
            return
        engine = piecesmod.engine_id()
        have = self.store.stored_segments(engine, [s["id"] for s in new]) if engine else {}
        rows = []
        for s in new:
            got = have.get(s["id"])
            if got and got[0] == s["start"]:
                self._segments[s["id"]] = piecesmod.unpack(s["id"], got[1])
            else:
                segs = self._segments[s["id"]] = piecesmod.session_segments(self.store, s["id"])
                rows.append((s["id"], s["start"], engine, piecesmod.pack(segs)))
        if rows and engine:
            self.store.save_segments(rows)

    def pieces(self):
        """Pieces found in the practice history, most recently played first, or
        None while the first pass after a restart is still running."""
        now = self._pieces_now()[0]
        if now is None:
            return None
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in now[1]]

    def name_piece(self, data):
        """Give a piece a name (an empty name forgets it). Changes no recordings."""
        key, name = str(data.get("key", "")), " ".join(str(data.get("name", "")).split())[:80]
        with self._pieces_lock:  # the matcher grows in place when a session closes
            return self._name_piece(key, name)

    def _name_piece(self, key, name):
        matcher, view = self._pieces()
        row = next((r for r in view if key in r["_keys"]), None)
        if row is None:
            raise ValueError("no such piece")
        if row["_name_id"] is not None:
            if name:
                self.store.save_piece_name(name, None, nid=row["_name_id"])
            else:
                self.store.delete_piece_name(row["_name_id"])
        elif name:
            grams = set()
            for i in row["_groups"]:
                grams |= matcher.core(matcher.pieces[i])
            self.store.save_piece_name(name, grams)
        return self.pieces()

    def session_events(self, sid):
        """The session as a compact time series for replay, times relative to start."""
        s = self.store.session(sid)
        if not s:
            return None
        t0 = s["start"]
        notes = [[round(n["t_on"] - t0, 4), round(n["t_off"] - t0, 4), n["pitch"], n["velocity"]]
                 for n in self.store.notes(sid)]
        pedals = [[round(p["t"] - t0, 4), p["cc"], p["value"]] for p in self.store.pedals(sid)]
        duration = max([n[1] for n in notes] + [p[0] for p in pedals] + [0])
        return {"id": sid, "start": t0, "duration": duration, "notes": notes, "pedals": pedals}

    def session_midi(self, sid):
        s = self.store.session(sid)
        if not s:
            return None
        t0 = s["start"]
        events = []
        for n in self.store.notes(sid):
            events.append((n["t_on"] - t0, (0x90 | n["channel"], n["pitch"], n["velocity"])))
            events.append((n["t_off"] - t0, (0x80 | n["channel"], n["pitch"], 0)))
        for p in self.store.pedals(sid):
            events.append((p["t"] - t0, (0xB0, p["cc"], p["value"])))
        return write_smf(events)

    def sessions_csv(self):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "start_local"] + SESSION_FIELDS[1:])
        for row in self.sessions(limit=100000):
            w.writerow([row["id"], datetime.fromtimestamp(row["start"]).isoformat(timespec="seconds")]
                       + [row.get(k) for k in SESSION_FIELDS[1:]])
        return buf.getvalue()

    def notes_csv(self, sid):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["t_on", "t_off", "pitch", "velocity", "channel"])
        for n in self.store.notes(sid):
            w.writerow([round(n["t_on"], 4), round(n["t_off"], 4), n["pitch"],
                        n["velocity"], n["channel"]])
        return buf.getvalue()

    def update_settings(self, data):
        limits = {"daily_goal_minutes": 600, "streak_min_minutes": 600, "weekly_days_target": 7}
        new = {}
        for key, hi in limits.items():
            if key in data:
                new[key] = v = int(data[key])
                if not 1 <= v <= hi:
                    raise ValueError(f"{key} must be between 1 and {hi}")
        for key, v in new.items():  # all or nothing
            self.store.set_setting(key, v)
        return self.store.settings()


class BadRequest(ValueError):
    """A request the client got wrong; answered with 400 and the message."""


def _int_param(q, name, default, lo, hi):
    raw = q.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except ValueError:
        raise BadRequest(f"{name} must be a whole number") from None
    return max(lo, min(v, hi))


def _date_param(q, name):
    raw = q.get(name)
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise BadRequest(f"{name} must be a date like 2026-10-26") from None


def _safe_next(target):
    """Only allow redirects to a path on this site after login."""
    return target if target.startswith("/") and not target.startswith("//") else "/"


def make_handler(api, tunnel=False, allowed_hosts=()):
    """Request handler class. `tunnel` marks the port cloudflared forwards to:
    every request there is remote and needs the password. A demo API needs no
    password anywhere and refuses every change."""
    auth = authmod.Auth(api.store)

    class Handler(BaseHTTPRequestHandler):
        server_version = "pianotrack"

        @property
        def remote(self):
            """True unless the request comes straight from the home network."""
            return (tunnel or authmod.via_tunnel(self.headers)
                    or not authmod.home_peer(self.client_address[0]))

        def log_message(self, fmt, *args):
            log.debug("%s " + fmt, self.address_string(), *args)

        def _send(self, code, body, ctype="application/json", extra=None):
            if not isinstance(body, (bytes, bytearray)):
                body = (json.dumps(body) if ctype == "application/json" else body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            extra = dict(extra or {})
            self.send_header("Cache-Control", extra.pop("Cache-Control", "no-store"))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _login_page(self, code, nxt="/", error=""):
            page = (authmod.LOGIN_PAGE.replace("{next}", escape(nxt, quote=True))
                    .replace("{error}", f'<div class="err">{escape(error)}</div>' if error else ""))
            return self._send(code, page, "text/html; charset=utf-8",
                              {"X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"})

        def _allowed(self, path, write=False):
            """Gate every request. Sends the refusal itself."""
            if api.demo:
                if write or path == "/api/backup":
                    self._send(403, {"error": "this is a demo; nothing can be changed or downloaded"})
                    return False
                return True
            if not self.remote:
                # Home network: no password, but only for requests addressed to
                # this machine (stops DNS rebinding) and, for changes, sent by
                # its own pages (stops other sites posting through the browser).
                if not authmod.home_host(self.headers.get("Host"), allowed_hosts):
                    log.warning("refused request for unknown host %r", self.headers.get("Host"))
                    self._send(403, {"error": "unknown host name; see --allowed-host"})
                    return False
                if write and not authmod.same_origin(self.headers):
                    log.warning("refused cross-site %s from %r", path, self.headers.get("Origin"))
                    self._send(403, {"error": "cross-site request refused"})
                    return False
                return True
            if path in ("/login", "/icon.svg"):
                return True
            if not auth.password_set:
                self._send(403, "Remote access is locked until a password is set on the "
                                "dashboard at home (Settings, Remote access).",
                           "text/plain; charset=utf-8")
                return False
            if auth.valid_session(authmod.read_cookie(self.headers)):
                return True
            if path.startswith("/api/"):
                self._send(401, {"error": "sign in required", "login": "/login"})
            else:
                self._send(303, b"", "text/plain", {"Location": "/login?next=" + quote(self.path)})
            return False

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path
            if not self._allowed(path):
                return
            try:
                if path == "/login":
                    return self._login_page(200, _safe_next(q.get("next", "/")))
                if path == "/logout":
                    return self._send(303, b"", "text/plain", {
                        "Location": "/login", "Set-Cookie": authmod.Auth.clear_cookie_header()})
                if path == "/api/auth":
                    return self._send(200, {"password_set": auth.password_set,
                                            "remote": self.remote, "demo": api.demo})
                if path in ("/", "/index.html"):
                    with open(os.path.join(STATIC, "index.html"), "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                if path in ASSETS:
                    with open(os.path.join(STATIC, path[1:]), "rb") as f:
                        return self._send(200, f.read(), ASSETS[path])
                if path in VENDOR:
                    with open(os.path.join(STATIC, path[1:]), "rb") as f:
                        return self._send(200, f.read(), "text/javascript; charset=utf-8",
                                          {"Cache-Control": "public, max-age=31536000"})
                m = re.fullmatch(r"/piano/([A-G]s?[0-8])\.mp3", path)
                if m and os.path.exists(os.path.join(STATIC, "piano", m.group(1) + ".mp3")):
                    with open(os.path.join(STATIC, "piano", m.group(1) + ".mp3"), "rb") as f:
                        return self._send(200, f.read(), "audio/mpeg",
                                          {"Cache-Control": "public, max-age=31536000"})
                if path == "/api/keys":
                    return self._send(200, api.keys(_int_param(q, "days", 30, 0, 5000)))
                if path == "/api/summary":
                    return self._send(200, api.summary())
                if path == "/api/recap":
                    return self._send(200, api.recap(_date_param(q, "week")))
                if path in ("/recap", "/recap.html"):
                    with open(os.path.join(STATIC, "recap.html"), "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                if path == "/api/days":
                    return self._send(200, api.days(_int_param(q, "days", 365, 1, 2000)))
                if path == "/api/trends":
                    return self._send(200, api.trends(_int_param(q, "days", 60, 1, 2000)))
                if path == "/api/sessions":
                    return self._send(200, api.sessions(_int_param(q, "limit", 50, 1, 5000)))
                if path == "/api/sessions.csv":
                    return self._send(200, api.sessions_csv(), "text/csv",
                                      {"Content-Disposition": "attachment; filename=sessions.csv"})
                if path == "/api/settings":
                    return self._send(200, api.store.settings())
                if path == "/api/tunnel":
                    return self._send(200, {"url": api.tunnel_url()})
                if path == "/api/backups":
                    return self._send(200, api.backups.status() if api.backups else {})
                if path == "/api/backup":
                    return self._send_backup()
                if path == "/api/status":
                    return self._send(200, api.collector.status if api.collector else {})
                if path == "/api/pieces":
                    data = api.pieces()
                    if data is None:  # still finding them after a restart
                        return self._send(503, {"warming": True}, extra={"Retry-After": "3"})
                    return self._send(200, data)
                m = re.fullmatch(r"/api/sessions/(\d+)/events", path)
                if m:
                    data = api.session_events(int(m.group(1)))
                    return self._send(200 if data else 404, data or {"error": "not found"})
                m = re.fullmatch(r"/api/sessions/(\d+)(\.mid|\.csv)?", path)
                if m:
                    sid, ext = int(m.group(1)), m.group(2)
                    if ext == ".mid":
                        data = api.session_midi(sid)
                        if data is None:
                            return self._send(404, {"error": "not found"})
                        return self._send(200, data, "audio/midi", {
                            "Content-Disposition": f"attachment; filename=session-{sid}.mid"})
                    if ext == ".csv":
                        return self._send(200, api.notes_csv(sid), "text/csv", {
                            "Content-Disposition": f"attachment; filename=session-{sid}.csv"})
                    data = api.session(sid)
                    return self._send(200 if data else 404, data or {"error": "not found"})
                return self._send(404, {"error": "not found"})
            except BadRequest as e:
                return self._send(400, {"error": str(e)})
            except Exception:  # keep the server up whatever happens
                log.exception("error serving %s", self.path)
                return self._send(500, {"error": "internal error"})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= 64 * 1024:
                self.close_connection = True
                return self._send(400, {"error": "bad or too large Content-Length"})
            body = self.rfile.read(n)
            if not self._allowed(path, write=True):
                return
            if path == "/login":
                return self._login(body)
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self._send(415, {"error": "send JSON (Content-Type: application/json)"})
            try:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise BadRequest("expected a JSON object")
                if path == "/api/signout-all":
                    auth.sign_out_everyone()
                    extra = {"Set-Cookie": auth.clear_cookie_header()} if self.remote else None
                    return self._send(200, {"signed_out": True}, extra=extra)
                if path == "/api/settings":
                    return self._send(200, api.update_settings(data))
                if path == "/api/pieces/name":
                    return self._send(200, api.name_piece(data))
                if path == "/api/password":
                    if self.remote:
                        return self._send(403, {"error": "the password can only be changed at home"})
                    auth.set_password(str(data.get("password", "")))
                    return self._send(200, {"password_set": True})
                if path == "/api/backup":
                    if self.remote:
                        return self._send(403, {"error": "backups can only be made at home"})
                    if not api.backups:
                        return self._send(404, {"error": "backups are off"})
                    try:
                        api.backups.run()
                    except Exception:
                        pass  # the status carries the error
                    return self._send(200, api.backups.status())
                return self._send(404, {"error": "not found"})
            except (ValueError, TypeError) as e:  # bad JSON or a rejected value
                return self._send(400, {"error": str(e)})
            except Exception:
                log.exception("error serving POST %s", self.path)
                return self._send(500, {"error": "internal error"})

        def _send_backup(self):
            """Stream a fresh, consistent copy of the database (home network only)."""
            if self.remote:
                return self._send(403, {"error": "backups can only be downloaded at home"})
            with tempfile.TemporaryDirectory() as tmp:
                path = backupmod.snapshot(api.store.path, os.path.join(tmp, "pianotrack.db"))
                name = f"pianotrack-{datetime.now():%Y-%m-%d-%H%M}.db"
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.sqlite3")
                self.send_header("Content-Length", str(os.path.getsize(path)))
                self.send_header("Content-Disposition", f"attachment; filename={name}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with open(path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)

        def _login(self, body):
            form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}
            nxt = _safe_next(form.get("next", "/"))
            client = authmod.client_id(self.headers, self.client_address[0])
            if not auth.password_set:
                return self._login_page(403, nxt, "No password has been set yet. Set one on the dashboard at home.")
            if auth.blocked(client):
                return self._login_page(429, nxt, "Too many wrong attempts. Try again in 15 minutes.")
            if not auth.check_password(form.get("password", "")):
                auth.record_failure(client)
                time.sleep(1)
                return self._login_page(401, nxt, "Wrong password.")
            return self._send(303, b"", "text/plain", {
                "Location": nxt, "Set-Cookie": auth.cookie_header(auth.new_session())})

    return Handler


def make_server(api, host="0.0.0.0", port=8080, tunnel=False, allowed_hosts=()):
    return ThreadingHTTPServer((host, port), make_handler(api, tunnel, allowed_hosts))
