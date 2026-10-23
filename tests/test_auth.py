import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from pianotrack import auth as authmod
from pianotrack.auth import Auth
from pianotrack.server import Api, make_server
from pianotrack.store import Store

TUNNEL = {"Cf-Ray": "abc123-AMS", "Cf-Connecting-Ip": "203.0.113.7"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, "t.db"))
        self.httpd = make_server(Api(self.store), "127.0.0.1", 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.opener = urllib.request.build_opener(NoRedirect)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()
        self.dir.cleanup()

    def req(self, path, headers=None, data=None, json_body=None):
        h = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, headers=h)
        try:
            with self.opener.open(r) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_home_network_needs_no_login(self):
        self.assertEqual(self.req("/api/summary")[0], 200)
        self.assertEqual(self.req("/")[0], 200)

    def test_tunnel_locked_until_password_set(self):
        self.assertEqual(self.req("/api/summary", TUNNEL)[0], 403)
        self.assertEqual(self.req("/", TUNNEL)[0], 403)

    def test_password_can_only_be_set_at_home(self):
        code, _, _ = self.req("/api/password", TUNNEL, json_body={"password": "correct horse"})
        self.assertEqual(code, 403)
        self.assertEqual(self.req("/api/password", json_body={"password": "short"})[0], 400)
        self.assertEqual(self.req("/api/password", json_body={"password": "correct horse"})[0], 200)
        settings = json.loads(self.req("/api/settings")[2])
        self.assertNotIn("password_hash", json.dumps(settings))

    def test_login_flow(self):
        self.req("/api/password", json_body={"password": "correct horse"})
        code, headers, _ = self.req("/", TUNNEL)
        self.assertEqual(code, 303)
        self.assertTrue(headers["Location"].startswith("/login"))
        self.assertEqual(self.req("/api/summary", TUNNEL)[0], 401)
        self.assertEqual(self.req("/login", TUNNEL)[0], 200)

        form = urllib.parse.urlencode({"password": "wrong one", "next": "/"}).encode()
        self.assertEqual(self.req("/login", TUNNEL, data=form)[0], 401)

        form = urllib.parse.urlencode({"password": "correct horse", "next": "//evil.example"}).encode()
        code, headers, _ = self.req("/login", TUNNEL, data=form)
        self.assertEqual(code, 303)
        self.assertEqual(headers["Location"], "/")
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("Secure", headers["Set-Cookie"])
        authed = dict(TUNNEL, Cookie=cookie)
        self.assertEqual(self.req("/api/summary", authed)[0], 200)
        self.assertEqual(self.req("/", authed)[0], 200)

        # A forged or tampered cookie is rejected.
        expires, sig = cookie.split("=", 1)[1].split(".")
        forged = dict(TUNNEL, Cookie=f"pianotrack_session={int(expires) + 999}.{sig}")
        self.assertEqual(self.req("/api/summary", forged)[0], 401)

        # Changing the password signs everyone out.
        self.req("/api/password", json_body={"password": "another horse"})
        self.assertEqual(self.req("/api/summary", authed)[0], 401)

    def test_other_sites_cannot_post_from_home_browsers(self):
        evil = {"Origin": "https://evil.example"}
        code, _, _ = self.req("/api/password", evil, json_body={"password": "attacker pw"})
        self.assertEqual(code, 403)
        self.assertFalse(Auth(self.store).password_set)
        own = {"Origin": self.base}
        self.assertEqual(self.req("/api/password", own, json_body={"password": "correct horse"})[0], 200)
        # A plain-text body (no CORS preflight) is refused even without an Origin.
        code, _, _ = self.req("/api/settings", {"Content-Type": "text/plain"},
                              data=b'{"daily_goal_minutes": 5}')
        self.assertEqual(code, 415)

    def test_unknown_host_names_are_refused_at_home(self):
        # DNS rebinding: an attacker's name pointed at the Pi.
        self.assertEqual(self.req("/api/summary", {"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.req("/api/summary", {"Host": "pi4.local:8080"})[0], 200)
        self.assertEqual(self.req("/api/summary", {"Host": "192.168.1.108:8080"})[0], 200)
        self.assertTrue(authmod.home_host("piano.home", extra=["piano.home"]))
        self.assertFalse(authmod.home_host("piano.home"))
        self.assertFalse(authmod.home_host(""))

    def test_only_home_addresses_skip_the_password(self):
        for ip in ("192.168.1.20", "10.0.0.5", "127.0.0.1", "::1", "fe80::1", "::ffff:192.168.1.2"):
            self.assertTrue(authmod.home_peer(ip), ip)
        for ip in ("1.1.1.1", "8.8.8.8", "2001:4860::1", "nonsense"):
            self.assertFalse(authmod.home_peer(ip), ip)

    def test_tunnel_port_always_needs_the_password(self):
        tunnel = make_server(Api(self.store), "127.0.0.1", 0, tunnel=True)
        threading.Thread(target=tunnel.serve_forever, daemon=True).start()
        base, self.base = self.base, f"http://127.0.0.1:{tunnel.server_address[1]}"
        try:
            self.assertEqual(self.req("/api/summary")[0], 403)  # no password yet
            self.assertEqual(self.req("/api/password", json_body={"password": "correct horse"})[0], 403)
            Auth(self.store).set_password("correct horse")
            self.assertEqual(self.req("/api/summary")[0], 401)
            self.assertEqual(self.req("/api/backup")[0], 401)
        finally:
            self.base = base
            tunnel.shutdown()
            tunnel.server_close()

    def test_sign_out_all_devices(self):
        self.req("/api/password", json_body={"password": "correct horse"})
        form = urllib.parse.urlencode({"password": "correct horse", "next": "/"}).encode()
        cookie = self.req("/login", TUNNEL, data=form)[1]["Set-Cookie"].split(";")[0]
        authed = dict(TUNNEL, Cookie=cookie)
        self.assertEqual(self.req("/api/summary", authed)[0], 200)
        self.assertEqual(self.req("/api/signout-all", json_body={})[0], 200)
        self.assertEqual(self.req("/api/summary", authed)[0], 401)
        self.assertTrue(Auth(self.store).check_password("correct horse"))

    def test_bad_input_gets_a_clear_400(self):
        code, _, body = self.req("/api/sessions?limit=abc")
        self.assertEqual(code, 400)
        self.assertIn("limit", json.loads(body)["error"])
        self.assertEqual(self.req("/api/settings", json_body=[1, 2])[0], 400)
        self.assertEqual(self.req("/api/settings", json_body={"daily_goal_minutes": "x"})[0], 400)
        self.assertEqual(self.req("/api/days?days=-5")[0], 200)

    def test_global_rate_limit(self):
        auth = Auth(self.store)
        for i in range(authmod.GLOBAL_MAX_FAILURES):
            auth.record_failure(f"10.0.{i}.1")
        self.assertTrue(auth.blocked("198.51.100.1"))  # a fresh address is blocked too

    def test_rate_limit(self):
        auth = Auth(self.store)
        auth.set_password("correct horse")
        for _ in range(5):
            auth.record_failure("1.2.3.4")
        self.assertTrue(auth.blocked("1.2.3.4"))
        self.assertFalse(auth.blocked("5.6.7.8"))

    def test_session_expiry(self):
        now = [1_000_000.0]
        auth = Auth(self.store, clock=lambda: now[0])
        token = auth.new_session()
        self.assertTrue(auth.valid_session(token))
        now[0] += 31 * 86400
        self.assertFalse(auth.valid_session(token))


if __name__ == "__main__":
    unittest.main()
