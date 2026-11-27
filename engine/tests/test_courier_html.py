"""Designed email made safe for Qt's rich text (courier_html.py)."""

from __future__ import annotations

import email
import email.policy
import http.client
import http.server
import importlib.util
import io
import os
import re
import socket
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(out, "PNG")
    return out.getvalue()


def parsed(markup: str, inline: bytes = b""):
    """An email with this HTML, and an image sent inside it as cid:logo."""
    message = email.message.EmailMessage(policy=email.policy.default)
    message["Subject"] = "Designed"
    message.set_content("text version")
    message.add_alternative(markup, subtype="html")
    if inline:
        message.get_payload()[1].add_related(inline, "image", "png", cid="<logo>")
    return email.message_from_bytes(message.as_bytes(), policy=email.policy.default)


class DesignedEmailTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        patcher = unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.folder / "run"), "XDG_CACHE_HOME": str(self.folder / "cache")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.html = load("courier_html")
        # Nothing here touches the network.
        self.fetched: list[str] = []
        self.web = {}

        def fake_fetch(url: str):
            self.fetched.append(url)
            data = self.web.get(url)
            if data is None:
                return None
            path = self.html.cache_dir() / str(len(self.fetched))
            path.write_bytes(data)
            return path

        fetch = unittest.mock.patch.object(self.html, "fetch", side_effect=fake_fetch)
        fetch.start()
        self.addCleanup(fetch.stop)

    def render(self, markup: str, inline: bytes = b"") -> dict | None:
        return self.html.designed(parsed(markup, inline), markup)

    def test_nothing_active_survives(self) -> None:
        out = self.render(
            '<script>alert(1)</script><iframe src="https://x"></iframe><form><input name="q">Search</form>'
            '<a href="javascript:steal()">bad</a> <a href="https://example.com/a?b=1&amp;c=2" onclick="x()">good</a>'
            '<link rel="stylesheet" href="https://x/a.css"><style>@import url(https://x/b.css); p{color:red}</style>'
        )["html"]
        for gone in ("script", "alert", "iframe", "<input", "javascript", "onclick", "<link", "@import", "https://x/"):
            self.assertNotIn(gone, out)
        self.assertIn('<a href="https://example.com/a?b=1&amp;c=2">good</a>', out)
        self.assertIn(">bad</a>", out)
        self.assertIn("Search", out)
        self.assertIn("p{color:red}", out)

    def test_hidden_preview_text_stays_hidden(self) -> None:
        out = self.render(
            '<style>.preheader{display:none !important}</style>'
            '<div class="preheader">Preview text</div><span style="display: none">also hidden</span>'
            '<div style="mso-hide:all"><div>Outlook only</div></div><p>Shown</p>'
        )["html"]
        self.assertNotIn("Preview text", out)
        self.assertNotIn("also hidden", out)
        self.assertNotIn("Outlook only", out)
        self.assertIn("Shown", out)

    def test_images_are_local_files_with_their_exact_size(self) -> None:
        self.web = {"https://cdn.example.com/hero.png": png(1200, 600)}
        out = self.render(
            '<table><tr><td><img src="cid:logo" alt="Logo"><img src="https://cdn.example.com/hero.png" style="width:100%"></td></tr></table>',
            inline=png(80, 40),
        )
        images = re.findall(r'<img src="([^"]+)" width="(\d+)" height="(\d+)"', out["html"])
        self.assertEqual([(w, h) for _, w, h in images], [("80", "40"), ("600", "300")])
        self.assertTrue(all(src.startswith("file://") for src, _, _ in images))
        self.assertTrue(out["layout"])
        inline_file = Path(images[0][0].removeprefix("file://"))
        self.assertEqual(oct(inline_file.stat().st_mode & 0o777), "0o600")

    def test_tracking_pixels_are_never_fetched_or_drawn(self) -> None:
        self.web = {"https://cdn.example.com/spacer": png(1, 1)}
        out = self.render(
            '<p>Hi</p><img src="https://t.example.com/a.gif" width="1" height="1">'
            '<img src="https://news.example.com/open.html?u=9"><img src="https://x.example.com/track/open/5">'
            '<img src="https://cdn.example.com/spacer">'
        )["html"]
        self.assertEqual(self.fetched, ["https://cdn.example.com/spacer"])
        self.assertNotIn("<img", out)

    def test_line_heights_hold_their_images(self) -> None:
        out = self.render('<td style="font-size:0;line-height:0">x</td><p style="font-size:15px;line-height:1.4">y</p>')["html"]
        self.assertNotIn("line-height:0", out.replace(" ", ""))
        self.assertIn("line-height:21px", out)

    def test_cell_backgrounds_fill_the_cell(self) -> None:
        out = self.render('<table><tr><td bgcolor="#F3EEFF" style="padding:8px 18px">New</td></tr></table>')["html"]
        self.assertIn('<table width="100%" cellspacing="0" cellpadding="0" bgcolor="#f3eeff"><tr><td style="padding-top:8px;padding-right:18px;padding-bottom:8px;padding-left:18px">New</td></tr></table>', out)

    def test_button_links_become_padded_buttons(self) -> None:
        out = self.render('<a href="https://x.example.com" style="display:inline-block;padding:14px 18px;background:#12706a;color:#fff">Read</a>')["html"]
        self.assertRegex(out, r'<table cellspacing="0" cellpadding="0" bgcolor="#12706a"><tr><td style="padding-top:14px;[^"]*"><a [^>]*>Read</a></td></tr></table>')

    def test_background_follows_the_body(self) -> None:
        self.assertEqual(self.render('<body style="background-color: rgb(24, 24, 24)"><p>Dark</p></body>')["background"], "#181818")
        self.assertEqual(self.render('<body bgcolor="transparent"><p>x</p></body>')["background"], "")

    def test_code_and_quotes_look_like_github(self) -> None:
        out = self.render('<p>Run <code>make</code></p><pre><code>a very long line</code></pre><blockquote><p>quoted</p></blockquote>')["html"]
        # A code block wraps (Qt would clip it) inside a shaded, padded box.
        self.assertRegex(out, r'<table width="100%" cellspacing="0" cellpadding="0" bgcolor="#f6f8fa"><tr><td style="padding-top:10px[^"]*"><pre style="white-space:pre-wrap;margin:0"><code>a very long line</code></pre></td></tr></table>')
        self.assertIn('<code style="background-color:#eff1f3">make</code>', out)
        self.assertIn('<table width="100%" cellspacing="0" cellpadding="0" bgcolor="#d0d7de"><tr><td style="padding-left:3px">'
                      '<table width="100%" cellspacing="0" cellpadding="0" bgcolor="#ffffff"><tr><td style="padding-left:12px;color:#57606a">'
                      '<p>quoted</p></td></tr></table></td></tr></table>', out)
        self.assertNotIn("<blockquote", out)
        # On a dark email, the dark palette.
        self.assertIn('bgcolor="#2d333b"', self.render('<body bgcolor="#0d1117"><pre>x</pre></body>')["html"])

    def test_markdown_is_recognised_and_its_html_stays_text(self) -> None:
        self.assertFalse(self.html.looks_like_markdown("Hi,\n\nSee you at 5.\n\n- J\n"))
        text = "## Notes\n\nShipped **v2**: run `make` <img src=x onerror=alert(1)>\n"
        self.assertTrue(self.html.looks_like_markdown(text))
        out = self.html.markdown_html(text)
        self.assertIn("<h2>Notes</h2>", out)
        self.assertIn("<strong>v2</strong>", out)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", out)
        self.assertEqual(self.html.markdown_html("see `https://x.example`")
                         , "<p>see <code>https://x.example</code></p>\n")

    def test_style_blocks_cannot_smuggle_markup(self) -> None:
        # The cleaner's parser ends a <style> at "</style " too; a regex
        # waiting for "</style>" used to keep going and put the markup in
        # between back into the page, unchecked.
        out = self.render(
            '<html><head><style>p{color:#123456}</style ><a href="file:///etc/passwd">open</a>'
            '<img src="https://evil.example/x.png"></style></head><body><p>Hello</p></body></html>'
        )["html"]
        head, body = out.split("<body>")
        self.assertEqual(head.count("<style>"), 1)
        style = re.search(r"<style>(.*)</style>", head, re.S).group(1)
        self.assertNotIn("<", style)
        self.assertIn("color:#123456", style)
        self.assertNotIn("/etc/passwd", out)
        self.assertNotIn("evil.example", out)
        self.assertIn("Hello", body)

    def test_a_style_tag_inside_an_attribute_is_just_text(self) -> None:
        # A regex saw "<style>" in the title and swallowed the email up to
        # the next "</style>", "after" included, into the stylesheet.
        out = self.render('<p title="<style>">before</p><b>after</b><p title="</style>">end</p>')["html"]
        head, body = out.split("<body>")
        self.assertNotIn("<style>", head)
        self.assertIn("<b>after</b>", body)
        self.assertIn("before", body)
        self.assertIn("end", body)

    def test_css_cannot_spell_a_tag_or_a_url(self) -> None:
        out = self.render(
            "<style>p{color:red} &lt;/style&gt;&lt;img src=x&gt; .a{background:u\\72l(https://t.example/p.gif)}"
            " .b{background-image:&#117;rl(https://t.example/q.gif)}</style><p class=\"a\">x</p>"
            '<p style="background:u\\rl(https://t.example/r.gif)">y</p>'
        )["html"]
        head = out.split("<body>")[0]
        style = re.search(r"<style>(.*)</style>", head, re.S).group(1)
        self.assertFalse(set(style) & {"<", "&", "\\"})
        # What's left of them is inert text: nothing Qt would load.
        self.assertNotIn("url(", out.lower())
        self.assertIn('<p style="background:none">y</p>', out)

    def test_heavy_font_weights_clamp_to_600(self) -> None:
        out = self.render(
            '<style>.lead{font-weight:bold;color:#111} .heavy{font-weight: 800 !important}</style>'
            '<p class="lead" style="font-weight:700">Hello</p><span style="font-weight: bold">World</span>'
        )["html"]
        self.assertIn("font-weight:600", out)
        self.assertIn("font-weight:600 !important", out)
        self.assertNotIn("font-weight:bold", out.lower())
        self.assertNotIn("font-weight:700", out.lower())
        self.assertNotIn("font-weight: 800", out.lower())

    def test_empty_html_has_nothing_to_show(self) -> None:
        self.assertIsNone(self.render("<div> &nbsp; </div><script>x</script>"))


class ImageFetchTest(unittest.TestCase):
    """Web images: only from the public internet, every redirect checked.
    A local server stands in for web servers, and a fake resolver says which
    address a name has; nothing reaches the real network."""

    PUBLIC = "93.184.216.34"

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = unittest.mock.patch.dict(os.environ, {"XDG_CACHE_HOME": folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.html = load("courier_html")
        self.routes: dict[str, tuple[int, dict, bytes]] = {}
        self.seen: list[tuple[str, str]] = []
        test = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                test.seen.append((self.path, self.headers.get("Host", "")))
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
        # Names the fake resolver knows; anything else resolves for real.
        self.names: dict[str, list[str]] = {}
        real = socket.getaddrinfo

        def resolve(host, port, *args, **kwargs):
            if host in self.names:
                return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in self.names[host]]
            return real(host, port, *args, **kwargs)

        resolver = unittest.mock.patch.object(self.html.socket, "getaddrinfo", side_effect=resolve)
        resolver.start()
        self.addCleanup(resolver.stop)
        # Every connection the fetcher makes, and where it really goes: the
        # local server, standing in for a public one.
        self.connected: list[tuple[str, str, str, int]] = []

        def connection(scheme, name, address, port, timeout):
            self.connected.append((scheme, name, address, port))
            return http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)

        connector = unittest.mock.patch.object(self.html, "_connection", side_effect=connection)
        connector.start()
        self.addCleanup(connector.stop)

    def test_private_and_local_addresses_are_never_fetched(self) -> None:
        self.routes["/a.png"] = (200, {"Content-Type": "image/png"}, png(4, 4))
        self.names["inside.example"] = ["10.0.0.7"]
        for url in (
            f"http://127.0.0.1:{self.port}/a.png", f"http://localhost:{self.port}/a.png",
            "http://127.0.0.1/a.png", "http://[::1]/a.png", "http://10.0.0.5/a.png", "http://192.168.1.1/a.png",
            "http://169.254.169.254/latest/meta-data/", "http://0.0.0.0/a.png", "http://2130706433/a.png",
            "http://[::ffff:127.0.0.1]/a.png", "http://[2002:7f00:1::]/a.png", "http://100.64.0.1/a.png",
            "http://[fe80::1]/a.png", "http://224.0.0.1/a.png", "https://inside.example/a.png",
        ):
            self.assertIsNone(self.html.fetch(url), url)
        self.assertEqual(self.connected, [])
        self.assertEqual(self.seen, [])

    def test_a_name_with_any_private_answer_is_refused(self) -> None:
        self.names["mixed.example"] = [self.PUBLIC, "10.1.2.3"]
        self.names["rebind.example"] = ["192.168.0.20"]
        self.names["v6.example"] = ["::1"]
        for host in ("mixed.example", "rebind.example", "v6.example"):
            self.assertIsNone(self.html.fetch(f"http://{host}/a.png"), host)
        self.assertEqual(self.connected, [])

    def test_every_redirect_is_checked_again(self) -> None:
        self.names["cdn.example"] = [self.PUBLIC]
        self.names["inside.example"] = ["192.168.0.2"]
        self.routes.update({
            "/to-loopback": (302, {"Location": "http://127.0.0.1/secret.png"}, b""),
            "/to-inside": (301, {"Location": "http://inside.example/secret.png"}, b""),
            "/to-file": (302, {"Location": "file:///etc/passwd"}, b""),
            "/to-port": (307, {"Location": "http://cdn.example:6379/secret.png"}, b""),
            "/loop": (302, {"Location": "/loop"}, b""),
            "/secret.png": (200, {"Content-Type": "image/png"}, png(4, 4)),
        })
        for path in ("/to-loopback", "/to-inside", "/to-file", "/to-port", "/loop"):
            self.assertIsNone(self.html.fetch(f"http://cdn.example{path}"), path)
        self.assertNotIn("/secret.png", [path for path, _ in self.seen])
        self.assertEqual([path for path, _ in self.seen].count("/loop"), self.html.IMAGE_REDIRECTS + 1)
        self.assertTrue(all(address == self.PUBLIC for _, _, address, _ in self.connected))

    def test_public_images_still_download(self) -> None:
        image = png(8, 4)
        self.names["cdn.example"] = [self.PUBLIC]
        self.routes["/old.png"] = (301, {"Location": "/new.png"}, b"")
        self.routes["/new.png"] = (200, {"Content-Type": "image/png"}, image)
        path = self.html.fetch("http://cdn.example/old.png")
        self.assertEqual(path.read_bytes(), image)
        self.assertEqual(self.seen, [("/old.png", "cdn.example"), ("/new.png", "cdn.example")])
        self.assertEqual(self.connected[0], ("http", "cdn.example", self.PUBLIC, 80))

    def test_limits_on_kind_size_port_and_credentials(self) -> None:
        self.names["cdn.example"] = [self.PUBLIC]
        self.routes["/page"] = (200, {"Content-Type": "text/html"}, b"<html>")
        self.routes["/big.png"] = (200, {"Content-Type": "image/png"}, b"x" * 5000)
        with unittest.mock.patch.object(self.html, "IMAGE_LIMIT", 1000):
            self.assertIsNone(self.html.fetch("http://cdn.example/big.png"))
        self.assertIsNone(self.html.fetch("http://cdn.example/page"))
        self.assertIsNone(self.html.fetch("http://cdn.example:8080/a.png"))
        self.assertIsNone(self.html.fetch("http://user:pass@cdn.example/a.png"))
        self.assertIsNone(self.html.fetch("ftp://cdn.example/a.png"))
        self.assertEqual(len(self.connected), 2)

    def test_https_connects_to_the_checked_address_with_the_name_on_the_certificate(self) -> None:
        wrapped, dialled = {}, []

        class Context:
            def wrap_socket(self, raw, server_hostname=None):
                wrapped["name"] = server_hostname
                return raw

        # The real _connection (setUp swapped in a spy), from a fresh load.
        real = load("courier_html")._connection
        with unittest.mock.patch("ssl.create_default_context", return_value=Context()), \
                unittest.mock.patch("socket.create_connection", side_effect=lambda where, timeout: dialled.append(where) or object()):
            real("https", "cdn.example", self.PUBLIC, 443, 2).connect()
        self.assertEqual(dialled, [(self.PUBLIC, 443)])
        self.assertEqual(wrapped["name"], "cdn.example")

class LocalMachineTest(unittest.TestCase):
    """An email's image pointing at this PC gets nothing: no spy, no fake
    resolver, a real server listening on 127.0.0.1."""

    def test_this_pc_is_never_fetched_from(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = unittest.mock.patch.dict(os.environ, {"XDG_CACHE_HOME": folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        html = load("courier_html")
        hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                hits.append(self.path)
                body = png(4, 4)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        for url in (f"http://127.0.0.1:{port}/admin.png", f"http://localhost:{port}/admin.png"):
            self.assertIsNone(html.fetch(url), url)
        self.assertEqual(hits, [])


class PrivateFolderTest(unittest.TestCase):
    """Files made from mail (images sent inside it, previews, originals) go
    to a folder only this user can read: the runtime folder, or the user's
    own cache; never a shared /tmp. Making any folder in a shared tmp fails
    the test (and isn't done)."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.shared = self.root / "shared-tmp"
        self.shared.mkdir()
        patcher = unittest.mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root / "cache"), "TMPDIR": str(self.shared)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("XDG_RUNTIME_DIR", None)  # patch.dict puts it back
        shared = unittest.mock.patch.object(tempfile, "tempdir", str(self.shared))
        shared.start()
        self.addCleanup(shared.stop)
        real_mkdir = os.mkdir

        def guarded(path, *args, **kwargs):
            where = os.path.abspath(path)
            if where.startswith(str(self.shared)) or where.startswith("/tmp/courier"):
                raise AssertionError(f"made a folder in a shared tmp: {where}")
            return real_mkdir(path, *args, **kwargs)

        guard = unittest.mock.patch("os.mkdir", side_effect=guarded)
        guard.start()
        self.addCleanup(guard.stop)
        self.html = load("courier_html")
        self.private = self.root / "cache" / "courier" / "tmp"

    def mode(self, path: Path) -> str:
        return oct(path.stat().st_mode & 0o777)

    def test_without_a_runtime_folder_files_go_to_the_users_cache(self) -> None:
        inline = self.html.private_dir("inline")
        self.assertEqual(inline, self.private / "inline")
        self.assertEqual((self.mode(self.private), self.mode(inline)), ("0o700", "0o700"))
        self.assertTrue(self.html.write_image(png(4, 4)).is_relative_to(inline))
        self.assertEqual(list(self.shared.iterdir()), [])

    def test_previews_too(self) -> None:
        views = load("courier_views")
        self.assertEqual(views.preview_path("report.pdf"), self.private / "preview" / "report.pdf")
        self.assertEqual(self.mode(self.private / "preview"), "0o700")

    def test_a_planted_link_is_refused(self) -> None:
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.private.parent.mkdir(parents=True)
        self.private.symlink_to(elsewhere)
        with self.assertRaises(PermissionError):
            self.html.private_dir("inline")
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_an_open_folder_of_ours_is_closed(self) -> None:
        (self.private / "inline").mkdir(parents=True)
        self.private.chmod(0o755)
        (self.private / "inline").chmod(0o777)
        self.html.private_dir("inline")
        self.assertEqual((self.mode(self.private), self.mode(self.private / "inline")), ("0o700", "0o700"))

    def test_a_link_left_at_a_temporary_name_isnt_followed(self) -> None:
        run = self.root / "run"
        run.mkdir(mode=0o700)
        os.environ["XDG_RUNTIME_DIR"] = str(run)
        folder = self.html.private_dir("inline")
        victim = self.root / "victim.txt"
        victim.write_text("keep")
        (folder / "picture.tmp").symlink_to(victim)
        self.html.write_private(folder / "picture", b"data")
        self.assertEqual(victim.read_text(), "keep")
        self.assertEqual((folder / "picture").read_bytes(), b"data")
        self.assertFalse((folder / "picture").is_symlink())


if __name__ == "__main__":
    unittest.main()
