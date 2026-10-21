"""Password login for visitors who come in through the Cloudflare tunnel.

Requests made directly on the home network need no login. Requests that went
through Cloudflare carry a Cf-Ray header (cloudflared forwards it), and those
need a signed session cookie, issued after the password is entered once.
"""

import hashlib
import hmac
import secrets
import threading
import time

COOKIE = "pianotrack_session"
SESSION_DAYS = 30
MIN_PASSWORD = 8
PBKDF2_ROUNDS = 200_000
MAX_FAILURES = 5          # per client, within FAILURE_WINDOW
FAILURE_WINDOW = 15 * 60


class Auth:
    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock
        self._failures = {}
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
        # A new password signs everyone out.
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
        now = self.clock()
        with self._lock:
            recent = [t for t in self._failures.get(client, []) if now - t < FAILURE_WINDOW]
            self._failures[client] = recent
            return len(recent) >= MAX_FAILURES

    def record_failure(self, client):
        with self._lock:
            self._failures.setdefault(client, []).append(self.clock())

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
