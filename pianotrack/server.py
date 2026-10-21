"""HTTP server: the dashboard page plus a small JSON/CSV API."""

import csv
import io
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from urllib.parse import parse_qs, quote, urlparse

from . import auth as authmod, metrics
from .midi import write_smf

log = logging.getLogger(__name__)
STATIC = os.path.join(os.path.dirname(__file__), "static")
ASSETS = {"/manifest.webmanifest": "application/manifest+json", "/icon.svg": "image/svg+xml",
          "/icon-180.png": "image/png", "/icon-512.png": "image/png", "/replay.js": "text/javascript; charset=utf-8"}
SESSION_FIELDS = ["start", "end", "duration_seconds", "active_seconds", "note_count",
                  "notes_per_minute", "velocity_mean", "dynamic_range", "tempo_bpm",
                  "steadiness", "intensity", "load", "sustain_fraction", "unique_keys",
                  "lowest_pitch", "highest_pitch", "chord_count", "left_hand_share"]


class Api:
    """Pure functions over the store, kept apart from HTTP for testing."""

    def __init__(self, store, collector=None):
        self.store = store
        self.collector = collector
        self._live_cache = {}

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
                         "notes": v["notes"], "goal_met": v["active_seconds"] >= goal})
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
        week_secs = sum(w["active_seconds"] for w in week)
        prev_week = sum(days.get(today - timedelta(days=i), empty)["active_seconds"]
                        for i in range(7, 14))
        return {
            "now": time.time(),
            "settings": settings,
            "today": {"date": today.isoformat(), "active_seconds": round(t["active_seconds"]),
                      "notes": t["notes"], "sessions": t["sessions"],
                      "load": round(t["load"], 1), "goal_seconds": goal,
                      "goal_pct": round(100 * t["active_seconds"] / goal) if goal else 0},
            "week": week,
            "week_total_seconds": round(week_secs),
            "prev_week_total_seconds": round(prev_week),
            "streak": metrics.streaks(days, settings["streak_min_minutes"] * 60, today),
            "consistency_28d": metrics.consistency(days, today),
            "totals": {"sessions": len(closed),
                       "active_seconds": round(sum(s["metrics"]["active_seconds"] for s in closed)),
                       "notes": sum(s["metrics"]["note_count"] for s in closed)},
            "records": records,
            "live": live,
            "collector": self.collector.status if self.collector else None,
        }

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
            row = {"id": s["id"], "closed": bool(s["closed"]), "source": s["source"]}
            row.update({k: m.get(k) for k in SESSION_FIELDS})
            row["start"], row["end"] = s["start"], s["end"]
            out.append(row)
        return out

    def session(self, sid):
        s = self.store.session(sid)
        if not s:
            return None
        m = self._metrics(s)
        return {"id": s["id"], "closed": bool(s["closed"]), "source": s["source"],
                "start": s["start"], "end": s["end"], "metrics": m}

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
        for key in ("daily_goal_minutes", "streak_min_minutes"):
            if key in data:
                v = int(data[key])
                if not 1 <= v <= 600:
                    raise ValueError(f"{key} must be between 1 and 600")
                self.store.set_setting(key, v)
        return self.store.settings()


def _safe_next(target):
    """Only allow redirects to a path on this site after login."""
    return target if target.startswith("/") and not target.startswith("//") else "/"


def make_handler(api):
    auth = authmod.Auth(api.store)

    class Handler(BaseHTTPRequestHandler):
        server_version = "pianotrack"

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

        def _allowed(self, path):
            """Gate for requests that came through the tunnel. Sends the refusal itself."""
            if not authmod.via_tunnel(self.headers):
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
                                            "remote": authmod.via_tunnel(self.headers)})
                if path in ("/", "/index.html"):
                    with open(os.path.join(STATIC, "index.html"), "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                if path in ASSETS:
                    with open(os.path.join(STATIC, path[1:]), "rb") as f:
                        return self._send(200, f.read(), ASSETS[path])
                m = re.fullmatch(r"/piano/([A-G]s?[0-8])\.mp3", path)
                if m and os.path.exists(os.path.join(STATIC, "piano", m.group(1) + ".mp3")):
                    with open(os.path.join(STATIC, "piano", m.group(1) + ".mp3"), "rb") as f:
                        return self._send(200, f.read(), "audio/mpeg",
                                          {"Cache-Control": "public, max-age=31536000"})
                if path == "/api/keys":
                    return self._send(200, api.keys(max(0, min(int(q.get("days", 30)), 5000))))
                if path == "/api/summary":
                    return self._send(200, api.summary())
                if path == "/api/days":
                    return self._send(200, api.days(min(int(q.get("days", 365)), 2000)))
                if path == "/api/trends":
                    return self._send(200, api.trends(min(int(q.get("days", 60)), 2000)))
                if path == "/api/sessions":
                    return self._send(200, api.sessions(int(q.get("limit", 50))))
                if path == "/api/sessions.csv":
                    return self._send(200, api.sessions_csv(), "text/csv",
                                      {"Content-Disposition": "attachment; filename=sessions.csv"})
                if path == "/api/settings":
                    return self._send(200, api.store.settings())
                if path == "/api/tunnel":
                    return self._send(200, {"url": api.tunnel_url()})
                if path == "/api/status":
                    return self._send(200, api.collector.status if api.collector else {})
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
            except Exception as e:  # keep the server up whatever happens
                log.exception("error serving %s", self.path)
                return self._send(500, {"error": str(e)})

        def do_POST(self):
            path = urlparse(self.path).path
            n = min(int(self.headers.get("Content-Length", 0) or 0), 64 * 1024)
            body = self.rfile.read(n)
            if path == "/login":
                return self._login(body)
            if not self._allowed(path):
                return
            try:
                data = json.loads(body or b"{}")
                if path == "/api/settings":
                    return self._send(200, api.update_settings(data))
                if path == "/api/password":
                    if authmod.via_tunnel(self.headers):
                        return self._send(403, {"error": "the password can only be changed at home"})
                    auth.set_password(str(data.get("password", "")))
                    return self._send(200, {"password_set": True})
                return self._send(404, {"error": "not found"})
            except (ValueError, TypeError) as e:
                return self._send(400, {"error": str(e)})

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


def make_server(api, host="0.0.0.0", port=8080):
    return ThreadingHTTPServer((host, port), make_handler(api))
