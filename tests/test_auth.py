import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

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
