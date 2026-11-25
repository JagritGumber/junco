"""Pictures are never decoded past a size, however small the file.

A PNG of a few KB can claim to be 9000 × 9000 (all one colour compresses
a thousandfold) and take hundreds of MB to decode. Every place Courier
decodes a picture someone else made is checked here: senders' pictures
and logos, BIMI logos (SVG), each account's own photo, the images in an
email (which the app's Qt decodes, so the engine decides which it gets),
and the picture you choose for an account.

The bombs are real files, but nothing big is ever decoded, even on code
without the limits: a stand-in for Pillow's decoder records each size it
is asked for and refuses the big ones. Nothing touches the network.
Run from the engine folder: python3 -m unittest discover tests
"""

from __future__ import annotations

import base64
import contextlib
import email.message
import email.policy
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import warnings
import zlib
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
import courier_avatars as avatars  # noqa: E402
import courier_html  # noqa: E402
import courier_mail as mail  # noqa: E402

from PIL import Image, ImageFile  # noqa: E402

# Anything over this many pixels counts as a bomb going off.
BIG = 20_000_000


def bomb_png(width: int, height: int) -> bytes:
    """A real 1-bit PNG, all black: a few KB that decode to width × height."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = (b"\x00" * (1 + (width + 7) // 8)) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def ico(*frames: tuple[tuple[int, int], bytes]) -> bytes:
    """An .ico of these frames, each (the size it claims, its PNG)."""
    directory = struct.pack("<HHH", 0, 1, len(frames))
    offset, blobs = 6 + 16 * len(frames), b""
    for (width, height), data in frames:
        directory += struct.pack("<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return directory + blobs


def picture(fmt: str, size: tuple[int, int], colour=(30, 90, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, fmt)
    return out.getvalue()


@contextlib.contextmanager
def decodes():
    """The size of every picture Pillow decodes inside. One over BIG is
    refused rather than decoded, so a test of old code fails, not the
    machine."""
    seen: list[tuple[int, int]] = []
    real = ImageFile.ImageFile.load

    def load(self):
        if self.tile:  # still to decode (a second load() is free)
            seen.append(tuple(self.size))
            if self.size[0] * self.size[1] > BIG:
                raise RuntimeError(f"decoded a {self.size[0]} × {self.size[1]} picture")
        return real(self)

    with unittest.mock.patch.object(ImageFile.ImageFile, "load", load):
        yield seen


class SenderPictureTest(unittest.TestCase):
    """courier_avatars.round_png: senders, logos, and each account's own photo."""

    def test_a_png_bomb_is_never_decoded(self) -> None:
        limit, filters = Image.MAX_IMAGE_PIXELS, list(warnings.filters)
        data = bomb_png(6000, 6000)
        self.assertLess(len(data), avatars.MAX_BYTES)  # passes the download cap
        with decodes() as seen:
            self.assertIsNone(avatars.round_png(data, "png"))
        self.assertEqual(seen, [])
        # Pillow's own limit and the warning filters are as they were.
        self.assertEqual(Image.MAX_IMAGE_PIXELS, limit)
        self.assertEqual(warnings.filters, filters)

    def test_an_icon_hiding_a_bomb_is_never_decoded(self) -> None:
        # The directory says 256 × 256; the PNG inside is 6000 × 6000.
        # Pillow decodes an icon as it opens it, before any size check.
        data = ico(((256, 256), bomb_png(6000, 6000)))
        with decodes() as seen:
            self.assertIsNone(avatars.round_png(data, "ico"))
        self.assertEqual([size for size in seen if max(size) > 4096], [])

    def test_one_huge_side_is_refused_too(self) -> None:
        with decodes() as seen:
            self.assertIsNone(avatars.round_png(bomb_png(20000, 300), "png"))
        self.assertEqual(seen, [])

    def test_a_big_jpeg_is_decoded_small(self) -> None:
        # Within the limit, but a JPEG decodes at 1/2 to 1/8 scale when that
        # still covers the 256 px disc.
        with decodes() as seen:
            out = avatars.round_png(picture("JPEG", (2048, 2048)), "jpg")
        self.assertIsNotNone(out)
        self.assertEqual(seen, [(256, 256)])
        with Image.open(io.BytesIO(out)) as made:
            self.assertEqual(made.size, (avatars.PICTURE_SIZE, avatars.PICTURE_SIZE))

    def test_bytes_are_opened_only_as_what_they_claim(self) -> None:
        # A BMP sent as "png" is not a PNG; only the kind judged from the bytes is tried.
        self.assertIsNone(avatars.round_png(picture("BMP", (300, 300)), "png"))

    def test_ordinary_pictures_still_work(self) -> None:
        for data, kind in ((picture("PNG", (300, 300)), "png"), (picture("JPEG", (200, 120)), "jpg"),
                           (picture("WEBP", (128, 128)), "webp"), (ico(((64, 64), picture("PNG", (64, 64)))), "ico"),
                           (picture("PNG", (4096, 64)), "png")):
            with self.subTest(kind=kind):
                out = avatars.round_png(data, kind)
                self.assertIsNotNone(out)
                with Image.open(io.BytesIO(out)) as made:
                    self.assertEqual(made.size, (avatars.PICTURE_SIZE, avatars.PICTURE_SIZE))

    def test_a_bomb_costs_only_its_own_picture(self) -> None:
        # One sender's bomb; the run carries on and the next sender gets theirs.
        found = {"d:bomb.example": (bomb_png(6000, 6000), "png"), "d:fine.example": (picture("PNG", (300, 300)), "png")}
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        with unittest.mock.patch.dict(os.environ, {"XDG_CACHE_HOME": home.name}), \
                unittest.mock.patch.object(avatars, "brand_picture", side_effect=lambda domain: found[f"d:{domain}"]), \
                decodes() as seen:
            self.assertEqual(avatars.look_up("d:bomb.example"), ("d:bomb.example", None))
            key, name = avatars.look_up("d:fine.example")
        self.assertTrue(name)
        self.assertEqual([size for size in seen if size[0] * size[1] > BIG], [])

    def test_svg_logos_are_drawn_with_a_memory_limit(self) -> None:
        calls = []

        def run(command, **options):
            calls.append(command)
            return subprocess.CompletedProcess(command, 1, b"", b"")

        with unittest.mock.patch.object(avatars.subprocess, "run", run):
            self.assertIsNone(avatars.round_png(b'<svg xmlns="http://www.w3.org/2000/svg"/>', "svg"))
        self.assertEqual(calls[0][0], "prlimit")
        self.assertEqual(calls[0][1:3], [f"--as={512 * 1024 * 1024}", "rsvg-convert"])

    @unittest.skipUnless(shutil.which("rsvg-convert") and shutil.which("prlimit"), "needs rsvg-convert and prlimit")
    def test_an_svg_logo_still_draws_within_the_limit(self) -> None:
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="red"/></svg>'
        out = avatars.round_png(svg, "svg")
        self.assertIsNotNone(out)
        with Image.open(io.BytesIO(out)) as made:
            self.assertEqual(made.size, (avatars.PICTURE_SIZE, avatars.PICTURE_SIZE))


def data_uri(data: bytes, kind: str = "png") -> str:
    return f"data:image/{kind};base64,{base64.b64encode(data).decode()}"


class EmailImageTest(unittest.TestCase):
    """courier_html: Qt decodes every image the reader draws, whole, so the
    engine decides which images it gets (by their headers)."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(Path(folder.name) / "run"),
                                                         "XDG_CACHE_HOME": str(Path(folder.name) / "cache")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def render(self, markup: str) -> str:
        message = email.message.EmailMessage(policy=email.policy.default)
        message["Subject"] = "Pictures"
        message.set_content("text version")
        message.add_alternative(markup, subtype="html")
        parsed = email.message_from_bytes(message.as_bytes(), policy=email.policy.default)
        with decodes() as seen:
            out = courier_html.designed(parsed, markup)["html"]
        self.assertEqual(seen, [])  # sizes come from headers; nothing is decoded here
        return out

    def drawn(self, out: str) -> list[tuple[str, str]]:
        return re.findall(r'<img src="[^"]+" width="(\d+)" height="(\d+)"', out)

    def test_an_oversized_image_shows_its_description(self) -> None:
        out = self.render(f'<p>Report</p><img src="{data_uri(bomb_png(8000, 8000))}" alt="Sales chart">'
                          f'<img src="{data_uri(picture("PNG", (300, 200)))}" alt="Logo">')
        self.assertEqual(self.drawn(out), [("300", "200")])
        self.assertIn("<span>Sales chart</span>", out)

    def test_one_emails_images_share_a_budget(self) -> None:
        # Each is under the per-image limit; together they're over the email's.
        sizes = [(6000, 6000), (6001, 6000), (6002, 6000)]
        out = self.render("".join(f'<img src="{data_uri(bomb_png(*size))}" alt="Photo {n}">' for n, size in enumerate(sizes)))
        self.assertEqual(len(self.drawn(out)), 2)
        self.assertIn("<span>Photo 2</span>", out)

    def test_the_same_image_twice_counts_once(self) -> None:
        uri = data_uri(bomb_png(6000, 6000))
        out = self.render(f'<img src="{uri}" alt="A"><img src="{uri}" alt="A"><img src="{uri}" alt="A">')
        self.assertEqual(len(self.drawn(out)), 3)

    def test_icons_are_never_handed_to_qt(self) -> None:
        # Pillow sizes an .ico by its biggest claimed frame (256 here, a
        # real 256 px PNG); Qt draws its first frame, which claims 1 × 1 but
        # holds 8000 × 8000. So no .ico reaches Qt.
        data = ico(((1, 1), bomb_png(8000, 8000)), ((256, 256), picture("PNG", (256, 256))))
        out = self.render(f'<img src="{data_uri(data, "x-icon")}" alt="Icon">')
        self.assertEqual(self.drawn(out), [])

    def test_ordinary_images_are_unchanged(self) -> None:
        out = self.render(f'<img src="{data_uri(picture("JPEG", (1200, 600)))}" style="width:100%">'
                          f'<img src="{data_uri(picture("GIF", (80, 40)))}"><img src="{data_uri(picture("WEBP", (90, 30)))}">')
        self.assertEqual(self.drawn(out), [("600", "300"), ("80", "40"), ("90", "30")])


class YourPictureTest(unittest.TestCase):
    """courier_mail.set_account_picture: the picture you choose for an account."""

    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = Path(home.name)
        patcher = unittest.mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.home / "config"), "XDG_DATA_HOME": str(self.home / "data"),
            "XDG_STATE_HOME": str(self.home / "state"), "XDG_CACHE_HOME": str(self.home / "cache"),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.home / "config" / "courier").mkdir(parents=True)
        (self.home / "config" / "courier" / "accounts.json").write_text(
            json.dumps({"accounts": [{"id": "work", "email": "someone@studio.example"}]}))

    def test_a_huge_picture_is_refused_not_decoded(self) -> None:
        chosen = self.home / "huge.png"
        chosen.write_bytes(bomb_png(9000, 9000))
        with decodes() as seen, self.assertRaisesRegex(mail.MailError, "too big"):
            mail.set_account_picture("work", str(chosen))
        self.assertEqual(seen, [])
        self.assertFalse(mail.account_picture_path("work").exists())

    def test_a_big_photo_is_decoded_small_and_cropped_right(self) -> None:
        # Left half red, right half blue; keep a square from the right half.
        image = Image.new("RGB", (2400, 1200), (255, 0, 0))
        image.paste((0, 0, 255), (1200, 0, 2400, 1200))
        chosen = self.home / "photo.jpg"
        image.save(chosen, quality=95)
        with decodes() as seen:
            mail.set_account_picture("work", str(chosen), (1300, 100, 1000))
        self.assertEqual(seen, [(600, 300)])  # a quarter: the square is still 250 px
        with Image.open(mail.account_picture_path("work")) as made:
            self.assertEqual(made.size, (160, 160))
            red, green, blue = made.convert("RGB").getpixel((80, 80))
            self.assertGreater(blue, 200)
            self.assertLess(red, 60)

    def test_only_the_picture_types_the_chooser_offers(self) -> None:
        chosen = self.home / "icon.png"
        chosen.write_bytes(ico(((64, 64), picture("PNG", (64, 64)))))
        with self.assertRaisesRegex(mail.MailError, "isn't a picture"):
            mail.set_account_picture("work", str(chosen))


if __name__ == "__main__":
    unittest.main()
