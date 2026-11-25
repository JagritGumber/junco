"""courier-auth against a fake Google, through its command-line interface.

Uses the real desktop keyring under app=courier-selftest and removes what it
stores. Run from the engine folder:  python3 -m unittest discover tests
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import secrets
import shutil
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("courier_auth", HERE.parent / "courier_auth.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)

CLIENT = {"client_id": "test-client.apps.googleusercontent.com", "client_secret": "test-secret"}
EMAIL = "someone@example.com"


def fake_id_token(email: str) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part({'email': email})}.sig"


class FakeGoogle:
    """Stands in for the browser, Google's consent page and its token endpoint."""

    def __init__(self) -> None:
        self.codes: dict[str, tuple[str, str]] = {}
        self.live_refresh_tokens: set[str] = set()
        self.granted = " ".join(["openid", "https://www.googleapis.com/auth/userinfo.email", *auth.REQUIRED_SCOPES])
        self.token_calls: list[dict] = []
        self.revoked: list[str] = []
        self.stale_replies: list[int] = []
        self.counter = 0
        google = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                fields = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
                status, body = google.handle(self.path, fields)
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.server.server_port}"
        self.urls = {"AUTH_URL": f"{base}/auth", "TOKEN_URL": f"{base}/token", "REVOKE_URL": f"{base}/revoke"}

    def browser(self, url: str) -> None:
        query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
        assert query["code_challenge_method"] == "S256"
        assert query["client_id"] == CLIENT["client_id"]
        assert query["access_type"] == "offline"
        code = f"code-{secrets.token_hex(4)}"
        self.codes[code] = (query["code_challenge"], query["redirect_uri"])

        def visit() -> None:
            # A stale tab first: wrong state must be refused without ending the wait.
            stale = f"{query['redirect_uri']}/?code=forged&state=wrong"
            try:
                urllib.request.urlopen(stale).read()
            except urllib.error.HTTPError as error:
                self.stale_replies.append(error.code)
            good = f"{query['redirect_uri']}/?code={code}&state={urllib.parse.quote(query['state'])}"
            urllib.request.urlopen(good).read()

        threading.Thread(target=visit, daemon=True).start()

    def handle(self, path: str, fields: dict[str, str]) -> tuple[int, dict]:
        if path == "/revoke":
            self.revoked.append(fields["token"])
            self.live_refresh_tokens.discard(fields["token"])
            return 200, {}
        self.token_calls.append(fields)
        if (fields["client_id"], fields["client_secret"]) != (CLIENT["client_id"], CLIENT["client_secret"]):
            return 401, {"error": "invalid_client"}
        self.counter += 1
        access = {"access_token": f"at-{self.counter}", "expires_in": 3599, "token_type": "Bearer"}
        if fields["grant_type"] == "authorization_code":
            challenge, redirect = self.codes.pop(fields["code"])
            verifier_ok = base64.urlsafe_b64encode(hashlib.sha256(fields["code_verifier"].encode()).digest()).rstrip(b"=").decode() == challenge
            if not verifier_ok or fields["redirect_uri"] != redirect:
                return 400, {"error": "invalid_grant"}
            refresh = f"rt-{self.counter}"
            self.live_refresh_tokens.add(refresh)
            return 200, {**access, "refresh_token": refresh, "scope": self.granted, "id_token": fake_id_token(EMAIL)}
        if fields["grant_type"] == "refresh_token":
            if fields["refresh_token"] not in self.live_refresh_tokens:
                return 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
            return 200, {**access, "scope": self.granted}
        return 400, {"error": "unsupported_grant_type"}


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = auth.main(list(args))
    return code, out.getvalue(), err.getvalue()


class CourierAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("secret-tool") is None:
            self.skipTest("secret-tool missing")
        probe = subprocess.run(["secret-tool", "search", "app", "courier-selftest"], capture_output=True, text=True, timeout=10)
        if probe.returncode != 0 and probe.stderr.strip():
            self.skipTest(f"keyring unavailable: {probe.stderr.strip()}")

        self.google = FakeGoogle()
        self.config = tempfile.TemporaryDirectory()
        self.patches = {"KEYRING_APP": "courier-selftest", "open_browser": self.google.browser, **self.google.urls}
        self.saved = {name: getattr(auth, name) for name in self.patches}
        for name, value in self.patches.items():
            setattr(auth, name, value)
        self.env = unittest.mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": self.config.name})
        self.env.start()

        client_file = Path(self.config.name) / "client_secret.json"
        client_file.write_text(json.dumps({"installed": {**CLIENT, "redirect_uris": ["http://localhost"]}}))
        self.assertEqual(run("setup", str(client_file))[0], 0)

    def tearDown(self) -> None:
        for kind in ("client", "refresh", "access"):
            subprocess.run(["secret-tool", "clear", "app", "courier-selftest", "kind", kind], capture_output=True)
        for name, value in self.saved.items():
            setattr(auth, name, value)
        self.env.stop()
        self.config.cleanup()
        self.google.server.shutdown()
        self.google.server.server_close()

    def stored(self, kind: str, account: str) -> str | None:
        return auth.keyring_get(kind, account)

    def test_pkce_challenge_matches_rfc7636_example(self) -> None:
        self.assertEqual(
            auth.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )

    def test_add_signs_in_and_token_reuses_then_refreshes(self) -> None:
        code, out, _ = run("add", "personal")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.google.stale_replies, [400])
        self.assertEqual(auth.load_accounts(), [{"id": "personal", "email": EMAIL}])
        self.assertEqual(self.stored("refresh", "personal"), "rt-1")

        calls = len(self.google.token_calls)
        self.assertEqual(run("token", "personal")[1].strip(), "at-1")
        self.assertEqual(len(self.google.token_calls), calls, "a fresh cached token must not hit Google")

        auth.keyring_set("access", "personal", json.dumps({"token": "at-1", "expires": 0}), "test")
        self.assertEqual(run("token", "personal")[1].strip(), "at-2")
        self.assertEqual(self.google.token_calls[-1]["grant_type"], "refresh_token")

        code, out, _ = run("list")
        self.assertIn(EMAIL, out)

    def test_revoked_sign_in_exits_2(self) -> None:
        self.assertEqual(run("add", "work")[0], 0)
        self.google.live_refresh_tokens.clear()
        auth.keyring_set("access", "work", json.dumps({"token": "at-1", "expires": 0}), "test")
        code, out, err = run("token", "work")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("courier-auth add work", err)
        self.assertIsNone(self.stored("access", "work"))

    def test_unticked_calendar_is_refused_and_revoked(self) -> None:
        self.google.granted = f"openid {auth.MAIL_SCOPE}"
        code, _, err = run("add", "personal")
        self.assertEqual(code, 1)
        self.assertIn("calendar", err)
        self.assertEqual(self.google.revoked, ["rt-1"])
        self.assertIsNone(self.stored("refresh", "personal"))
        self.assertEqual(auth.load_accounts(), [])

    def test_remove_revokes_and_clears(self) -> None:
        self.assertEqual(run("add", "personal")[0], 0)
        self.assertEqual(run("remove", "personal")[0], 0)
        self.assertEqual(self.google.revoked, ["rt-1"])
        self.assertIsNone(self.stored("refresh", "personal"))
        self.assertIsNone(self.stored("access", "personal"))
        self.assertEqual(auth.load_accounts(), [])

    def test_unknown_account_and_missing_client(self) -> None:
        code, _, err = run("token", "nobody")
        self.assertEqual(code, 1)
        self.assertIn("courier-auth add nobody", err)
        auth.keyring_clear("client")
        code, _, err = run("add", "personal")
        self.assertEqual(code, 1)
        self.assertIn("courier-auth setup", err)


if __name__ == "__main__":
    unittest.main()
