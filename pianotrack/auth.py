"""Password login for visitors who come in through the Cloudflare tunnel.

Requests made directly on the home network need no login. Requests that went
through Cloudflare carry a Cf-Ray header (cloudflared forwards it), and those
need a signed session cookie, issued after the password is entered once.
"""

import hashlib
import hmac
import ipaddress
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit

COOKIE = "pianotrack_session"
SESSION_DAYS = 30
MIN_PASSWORD = 8
PBKDF2_ROUNDS = 200_000
MAX_FAILURES = 5          # per client, within FAILURE_WINDOW
FAILURE_WINDOW = 15 * 60
GLOBAL_MAX_FAILURES = 20  # all clients together, within GLOBAL_WINDOW
GLOBAL_WINDOW = 60 * 60


class Auth:
    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock
        self._failures = {}
        self._all_failures = []
        self._lock = threading.Lock()

    # --- password ---

    @property
    def password_set(self):
        return self.store.secret("password_hash") is not None

    def set_password(self, password):
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS)
        self.store.set_secret("password_hash", f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest.hex()}")
        self.sign_out_everyone()  # a new password signs every device out

    def sign_out_everyone(self):
        """Invalidate every issued session cookie by changing the signing key."""
        self.store.set_secret("session_key", secrets.token_hex(32))

    def check_password(self, password):
        stored = self.store.secret("password_hash")
        if not stored:
            return False
        _, rounds, salt, digest = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(got.hex(), digest)

    # --- rate limiting ---

    def blocked(self, client):
        """True while this client, or everyone together, has failed too often."""
        now = self.clock()
        with self._lock:
            self._all_failures = [t for t in self._all_failures if now - t < GLOBAL_WINDOW]
            for c in list(self._failures):
                self._failures[c] = [t for t in self._failures[c] if now - t < FAILURE_WINDOW]
                if not self._failures[c]:
                    del self._failures[c]
            return (len(self._failures.get(client, [])) >= MAX_FAILURES
                    or len(self._all_failures) >= GLOBAL_MAX_FAILURES)

    def record_failure(self, client):
        now = self.clock()
        with self._lock:
            self._failures.setdefault(client, []).append(now)
            self._all_failures.append(now)

    # --- session cookies ---

    def _key(self):
        key = self.store.secret("session_key")
        if not key:
            key = secrets.token_hex(32)
            self.store.set_secret("session_key", key)
        return bytes.fromhex(key)

    def new_session(self):
        expires = int(self.clock()) + SESSION_DAYS * 86400
        sig = hmac.new(self._key(), str(expires).encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{sig}"

    def valid_session(self, token):
        try:
            expires, sig = token.split(".", 1)
            if int(expires) < self.clock():
                return False
        except (ValueError, AttributeError):
            return False
        want = hmac.new(self._key(), expires.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, want)

    def cookie_header(self, token):
        return (f"{COOKIE}={token}; Max-Age={SESSION_DAYS * 86400}; Path=/; "
                "HttpOnly; Secure; SameSite=Lax")

    @staticmethod
    def clear_cookie_header():
        return f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"


def via_tunnel(headers):
    """True when the request came through Cloudflare rather than the home network."""
    return bool(headers.get("Cf-Ray") or headers.get("Cf-Connecting-Ip"))


def home_peer(address):
    """True for a client on the home network or this machine (private, loopback, link-local)."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


def home_host(host, extra=()):
    """True when the Host header names this machine the way the home network does.

    A page on some other site can make a browser on the home Wi-Fi send requests
    here, but (short of DNS rebinding) only under that site's own name, so a
    request is trusted only when it addresses the Pi by IP, as name.local, by its
    hostname, as localhost, or by a name passed with --allowed-host.
    """
    if not host:
        return False
    name = urlsplit("//" + host).hostname or ""
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    own = socket.gethostname().lower().split(".")[0]
    allowed = {"localhost", own, own + ".local"} | {h.lower() for h in extra}
    return name in allowed or name.endswith(".local")


def same_origin(headers):
    """False when a browser says the request came from a page on another site."""
    origin = headers.get("Origin")
    if not origin:
        return True  # not sent by a browser page (curl, scripts), or a same-origin GET
    if origin == "null":
        return False
    return urlsplit(origin).netloc.lower() == (headers.get("Host") or "").lower()


def client_id(headers, fallback):
    return headers.get("Cf-Connecting-Ip") or fallback


def read_cookie(headers, name=COOKIE):
    for part in (headers.get("Cookie") or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Piano Practice: sign in</title>
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<style>
:root { color-scheme: light dark; --bg:#f4f3f0; --surface:#fcfcfb; --border:#e4e2dc; --text:#0b0b0b; --muted:#52514e; --accent:#2a78d6; --bad:#d03b3b; }
@media (prefers-color-scheme: dark) { :root { --bg:#111110; --surface:#1a1a19; --border:#2c2c2a; --text:#f0efec; --muted:#c3c2b7; --accent:#3987e5; --bad:#e66767; } }
body { margin:0; min-height:100vh; display:grid; place-items:center; background:var(--bg); color:var(--text);
  font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; padding:16px; box-sizing:border-box; }
form { background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:24px; width:100%; max-width:340px; }
h1 { font-size:20px; margin:0 0 4px; } p { color:var(--muted); margin:0 0 16px; font-size:14px; }
input { width:100%; box-sizing:border-box; font:inherit; padding:10px 12px; border-radius:8px; border:1px solid var(--border); background:var(--bg); color:var(--text); }
button { margin-top:12px; width:100%; font:inherit; font-weight:600; padding:10px; border-radius:8px; border:0; background:var(--accent); color:#fff; cursor:pointer; }
.err { color:var(--bad); font-size:14px; margin-top:10px; }
</style></head><body>
<form method="post" action="/login">
  <h1>Piano Practice</h1>
  <p>Enter the dashboard password. You'll stay signed in on this device for 30 days.</p>
  <input type="password" name="password" autocomplete="current-password" autofocus required aria-label="Password">
  <input type="hidden" name="next" value="{next}">
  <button type="submit">Sign in</button>
  {error}
</form></body></html>"""
