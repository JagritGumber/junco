"""Account pictures: each account's own (Google photo, else Gravatar, else
initials), and the one you choose, which nothing ever overwrites.

A fake web stands in for Google's userinfo, Google's photo host and Gravatar;
nothing here touches the network or the keyring. Run from the engine folder:
python3 -m unittest discover tests
"""

from __future__ import annotations

import contextlib
import email.message
import http.client
import http.server
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
import courier_avatars as avatars  # noqa: E402
import courier_html  # noqa: E402
import courier_mail as mail  # noqa: E402

from PIL import Image  # noqa: E402

ACCOUNTS = [{"id": "personal", "email": "someone@gmail.com"}, {"id": "work", "email": "someone@studio.example"}]
USERINFO = avatars.USERINFO_URL
PHOTO = "https://lh3.googleusercontent.com/a/ACg8ocTest"


def png(colour: tuple[int, int, int], size: tuple[int, int] = (300, 300)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


class FakeWeb:
    """urlopen for the tests: url -> (body, content type), an exception, or a 404."""

    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append((url, dict(request.header_items())))
        route = self.routes.get(url)
        if route is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", email.message.Message(), io.BytesIO())
        if isinstance(route, Exception):
            raise route
        body, content_type = route
        return FakeResponse(body, content_type)

    def urls(self) -> list[str]:
        return [url for url, _ in self.calls]


class FakeResponse:
    def __init__(self, body: bytes, content_type: str) -> None:
        self.body = body
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        pass


def userinfo(picture: str | None) -> tuple[bytes, str]:
    info = {"sub": "1", "email": "someone@gmail.com", "email_verified": True}
    if picture is not None:
        info["picture"] = picture
    return json.dumps(info).encode(), "application/json"


class AccountPicturesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        root = Path(self.home.name)
        self.env = unittest.mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"),
        })
        self.env.start()
        (root / "config" / "courier").mkdir(parents=True)
        self.set_accounts(ACCOUNTS)
        self.web = FakeWeb()
        self.tokens: list[str] = []
        patches = [
            # Google's userinfo is asked with urllib; pictures come through
            # courier_html.public_get. Both are served by the fake web.
            unittest.mock.patch.object(avatars.urllib.request, "urlopen", self.web),
            unittest.mock.patch.object(avatars.courier_html, "public_get", side_effect=self.public_get),
            unittest.mock.patch.object(avatars.sync, "auth_token", self.token),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        # Both accounts are Google sign-ins with a photo, unless a test says otherwise.
        self.signed_in = {"personal", "work"}
        self.web.routes[USERINFO] = userinfo(f"{PHOTO}=s96-c")
        self.web.routes[f"{PHOTO}=s256-c"] = (png((200, 30, 30)), "image/png")

    def tearDown(self) -> None:
        self.env.stop()
        self.home.cleanup()

    def set_accounts(self, accounts: list[dict]) -> None:
        path = Path(os.environ["XDG_CONFIG_HOME"]) / "courier" / "accounts.json"
        path.write_text(json.dumps({"accounts": accounts}))

    def public_get(self, url: str, **options) -> tuple[int, str, bytes | None]:
        self.web.calls.append((url, {}))
        route = self.web.routes.get(url)
        if route is None:
            return 404, "text/html", b""
        if isinstance(route, Exception):
            raise route
        body, content_type = route
        limit = options.get("limit")
        return 200, content_type, body if limit is None or len(body) <= limit else None

    def token(self, account: str) -> str:
        self.tokens.append(account)
        if account not in self.signed_in:
            raise avatars.sync.SyncError(f"courier-auth: No account named '{account}'.")
        return f"token-for-{account}"

    def accounts(self, *args: str) -> dict:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["accounts", *args]), 0)
        return {entry["id"]: entry for entry in json.loads(out.getvalue())}

    def test_google_photo_is_the_default(self) -> None:
        self.assertEqual(avatars.fetch_account_pictures(), {"personal": "google", "work": "google"})

        # Asked with the sign-in Courier has, for a picture as big as the disc.
        call = next(headers for url, headers in self.web.calls if url == USERINFO)
        self.assertEqual(call["Authorization"], "Bearer token-for-personal")
        self.assertIn(f"{PHOTO}=s256-c", self.web.urls())

        shown = self.accounts()["personal"]
        self.assertEqual(shown["pictureSource"], "google")
        self.assertEqual(shown["defaultSource"], "google")
        self.assertEqual(shown["picture"], str(avatars.default_picture_path("personal")))
        with Image.open(shown["picture"]) as picture:
            self.assertEqual(picture.size, (avatars.PICTURE_SIZE, avatars.PICTURE_SIZE))
            # Round: clear corners, the photo in the middle.
            self.assertEqual(picture.convert("RGBA").getpixel((0, 0))[3], 0)
            self.assertEqual(picture.convert("RGB").getpixel((128, 128)), (200, 30, 30))

    def test_fetched_once(self) -> None:
        avatars.fetch_account_pictures()
        asked = len(self.web.calls)
        self.assertEqual(avatars.fetch_account_pictures(), {})
        self.assertEqual(self.accounts("--fetch")["work"]["pictureSource"], "google")
        self.assertEqual(len(self.web.calls), asked)

    def test_your_picture_wins_and_is_never_overwritten(self) -> None:
        avatars.fetch_account_pictures()
        chosen = Path(self.home.name) / "me.png"
        chosen.write_bytes(png((20, 120, 220)))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["account-picture", "personal", str(chosen)]), 0)
        self.assertEqual(json.loads(out.getvalue())["pictureSource"], "custom")
        mine = mail.account_picture_path("personal")
        before = mine.read_bytes()

        # Looking every account up again, with a new Google photo, leaves it be.
        self.web.routes[f"{PHOTO}=s256-c"] = (png((10, 160, 10)), "image/png")
        avatars.fetch_account_pictures(again=True)
        self.assertEqual(mine.read_bytes(), before)
        shown = self.accounts()["personal"]
        self.assertEqual((shown["picture"], shown["pictureSource"], shown["defaultSource"]), (str(mine), "custom", "google"))

        # Back to the default: the account's own photo, the newer one.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mail.main(["account-picture", "personal", "--clear"]), 0)
        self.assertFalse(mine.exists())
        shown = self.accounts()["personal"]
        self.assertEqual((shown["picture"], shown["pictureSource"]), (str(avatars.default_picture_path("personal")), "google"))
        with Image.open(shown["picture"]) as picture:
            self.assertEqual(picture.convert("RGB").getpixel((128, 128)), (10, 160, 10))

    def test_gravatar_when_google_has_no_photo(self) -> None:
        self.web.routes[USERINFO] = userinfo(None)
        self.web.routes[avatars.gravatar_url("someone@studio.example", 256)] = (png((240, 200, 0)), "image/png")
        result = avatars.fetch_account_pictures()
        self.assertEqual(result, {"personal": "", "work": "gravatar"})
        shown = self.accounts()
        self.assertEqual((shown["personal"]["picture"], shown["personal"]["pictureSource"]), ("", ""))
        self.assertEqual(shown["work"]["pictureSource"], "gravatar")

    def test_gravatar_for_an_account_not_signed_in_to_google(self) -> None:
        self.signed_in = {"personal"}
        self.web.routes[avatars.gravatar_url("someone@studio.example", 256)] = (png((240, 200, 0)), "image/png")
        self.assertEqual(avatars.fetch_account_pictures()["work"], "gravatar")

    def test_initials_and_a_weekly_look_when_there_is_nothing(self) -> None:
        self.web.routes[USERINFO] = userinfo(None)
        avatars.fetch_account_pictures()
        self.assertEqual(self.accounts()["work"]["picture"], "")
        self.assertFalse(avatars.default_picture_path("work").exists())
        self.assertEqual(avatars.fetch_account_pictures(), {})
        entry = avatars.load_account_index()["work"]
        self.assertTrue(avatars.needs_lookup(ACCOUNTS[1], entry, time.time() + avatars.RETRY_MISSES_AFTER + 1))

    def test_not_an_image_is_not_kept(self) -> None:
        self.web.routes[f"{PHOTO}=s256-c"] = (b"<html>sign in</html>", "image/png")
        self.assertEqual(avatars.fetch_account_pictures()["personal"], "")
        self.assertFalse(avatars.default_picture_path("personal").exists())

    def test_only_googles_photo_host(self) -> None:
        self.web.routes[USERINFO] = userinfo("https://tracker.example/me.png")
        self.web.routes["https://tracker.example/me.png=s256-c"] = (png((1, 2, 3)), "image/png")
        avatars.fetch_account_pictures()
        self.assertNotIn("https://tracker.example/me.png=s256-c", self.web.urls())
        self.assertEqual(self.accounts()["personal"]["pictureSource"], "")

    def test_offline_keeps_the_picture_and_asks_again_later(self) -> None:
        avatars.fetch_account_pictures()
        before = avatars.default_picture_path("personal").read_bytes()
        offline = urllib.error.URLError("Name or service not known")
        self.web.routes = {USERINFO: offline, f"{PHOTO}=s256-c": offline}
        result = avatars.fetch_account_pictures(again=True)
        self.assertTrue(result["personal"].startswith("error: "))
        self.assertEqual(avatars.default_picture_path("personal").read_bytes(), before)
        self.assertEqual(self.accounts()["personal"]["pictureSource"], "google")
        # Not asked again at once; after an hour, yes.
        self.assertEqual(avatars.fetch_account_pictures(), {})
        entry = avatars.load_account_index()["personal"]
        self.assertTrue(avatars.needs_lookup(ACCOUNTS[0], entry, time.time() + avatars.RETRY_ERRORS_AFTER + 1))

    def test_offline_first_time_is_not_no_picture(self) -> None:
        self.web.routes = {USERINFO: urllib.error.URLError("offline")}
        avatars.fetch_account_pictures()
        entry = avatars.load_account_index()["personal"]
        self.assertTrue(entry["failed"])
        self.assertIsNone(entry["source"])

    def test_a_removed_account_loses_only_its_own_picture(self) -> None:
        avatars.fetch_account_pictures()
        chosen = Path(self.home.name) / "me.png"
        chosen.write_bytes(png((20, 120, 220)))
        mail.set_account_picture("work", str(chosen))
        self.set_accounts(ACCOUNTS[:1])
        self.assertEqual(avatars.fetch_account_pictures(), {"work": "removed"})
        self.assertFalse(avatars.default_picture_path("work").exists())
        self.assertTrue(mail.account_picture_path("work").exists())

    def test_a_name_given_to_another_address_looks_up_anew(self) -> None:
        avatars.fetch_account_pictures()
        self.set_accounts([{"id": "personal", "email": "other@gmail.com"}, ACCOUNTS[1]])
        self.assertEqual(avatars.fetch_account_pictures(), {"personal": "google"})
        self.assertEqual(avatars.load_account_index()["personal"]["email"], "other@gmail.com")

    def test_crop_picks_the_square_you_framed(self) -> None:
        # Left half red, right half blue; keep a square from the right half.
        image = Image.new("RGB", (400, 200), (255, 0, 0))
        image.paste((0, 0, 255), (200, 0, 400, 200))
        chosen = Path(self.home.name) / "wide.png"
        image.save(chosen)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["account-picture", "work", str(chosen), "--crop", "210,10,180"]), 0)
        with Image.open(json.loads(out.getvalue())["picture"]) as picture:
            self.assertEqual(picture.size, (160, 160))
            self.assertEqual(picture.convert("RGB").getpixel((80, 80)), (0, 0, 255))
        # Without a crop: the centred square, which straddles both halves.
        mail.set_account_picture("work", str(chosen))
        with Image.open(mail.account_picture_path("work")) as picture:
            self.assertEqual(picture.convert("RGB").getpixel((40, 80)), (255, 0, 0))

    def test_a_broken_lookup_never_costs_the_account_list(self) -> None:
        avatars.fetch_account_pictures()
        with unittest.mock.patch.object(avatars, "fetch_account_pictures", side_effect=RuntimeError("bug")), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            shown = self.accounts("--fetch")
        self.assertEqual(set(shown), {"personal", "work"})
        self.assertEqual(shown["personal"]["pictureSource"], "google")
        self.assertIn("bug", errors.getvalue())

    def test_bad_requests(self) -> None:
        for args in (["account-picture", "personal"], ["account-picture", "nobody", "--clear"],
                     ["account-picture", "personal", "x.png", "--crop", "a,b"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(mail.main(args), 1, args)
            self.assertIn("error", json.loads(out.getvalue()))

    def test_command_line(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(avatars.main(["accounts"]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"personal": "google", "work": "google"})


class SenderLookupTest(unittest.TestCase):
    """Sender logos, BIMI logos and Gravatars: a sender names these places,
    so Courier only ever connects to public addresses. Every socket
    connection is refused except to this test's own server, so nothing
    reaches the real network either."""

    PUBLIC = "93.184.216.34"

    def setUp(self) -> None:
        self.routes: dict[str, tuple[int, dict, bytes]] = {}
        self.seen: list[str] = []
        test = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                test.seen.append(self.path)
                status, headers, body = test.routes.get(self.path, (404, {}, b""))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.names: dict[str, list[str]] = {}
        real_resolve, real_connect = socket.getaddrinfo, socket.create_connection
        self.attempts: list[tuple] = []

        def resolve(host, port, *args, **kwargs):
            if host in self.names:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in self.names[host]]
            return real_resolve(host, port, *args, **kwargs)

        def connect(address, *args, **kwargs):
            if tuple(address) == ("127.0.0.1", self.port):
                return real_connect(address, *args, **kwargs)
            self.attempts.append(tuple(address))
            raise ConnectionRefusedError(f"test refuses {address}")

        def connection(scheme, name, address, port, timeout):
            self.attempts.append(("pinned", scheme, name, address, port))
            return http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)

        for patch in (unittest.mock.patch("socket.getaddrinfo", side_effect=resolve),
                      unittest.mock.patch("socket.create_connection", side_effect=connect),
                      unittest.mock.patch.object(courier_html, "_connection", side_effect=connection)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_sender_lookups_never_connect_inside(self) -> None:
        self.names.update({"brand.example": ["10.0.0.9"], "www.brand.example": ["127.0.0.1"],
                           "logo.intranet.example": ["192.168.1.5"], "gravatar.com": ["169.254.169.254"]})
        with unittest.mock.patch.object(avatars, "bimi_logo", return_value="https://logo.intranet.example/brand.svg"):
            self.assertIsNone(avatars.brand_picture("brand.example"))
        self.assertIsNone(avatars.person_picture("someone@brand.example"))
        self.assertEqual(self.attempts, [])
        self.assertEqual(self.seen, [])

    def test_ip_literals_and_single_names_are_never_looked_up(self) -> None:
        asked = []
        with unittest.mock.patch.object(avatars, "bimi_logo", side_effect=lambda name: asked.append(name)):
            for domain in ("10.0.0.1", "127.0.0.1", "[::1]", "localhost", "intranet", "x..example", "-bad.example", "a b.example"):
                self.assertIsNone(avatars.brand_picture(domain), domain)
        self.assertEqual(asked, [])
        self.assertEqual(self.attempts, [])

    def test_a_public_senders_icon_still_downloads(self) -> None:
        icon = png((10, 90, 200), (64, 64))
        self.names.update({"brand.example": [self.PUBLIC]})
        self.routes.update({
            "/": (200, {"Content-Type": "text/html"}, b'<html><head><link rel="icon" href="/icon.png"></head></html>'),
            "/icon.png": (200, {"Content-Type": "image/png"}, icon),
        })
        with unittest.mock.patch.object(avatars, "bimi_logo", return_value=None):
            found = avatars.brand_picture("brand.example")
        self.assertEqual(found, (icon, "png"))
        self.assertEqual(self.seen, ["/", "/icon.png"])
        self.assertEqual({attempt[3] for attempt in self.attempts}, {self.PUBLIC})


if __name__ == "__main__":
    unittest.main()
