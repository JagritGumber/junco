"""How the reader shows an email (courier_mail.reading): simple HTML in the
app's colours, designed HTML on its paper, machine mail's text part drawn
natively, and each sender's choice remembered.

Run from the engine folder: python3 -m unittest discover tests
"""

from __future__ import annotations

import contextlib
import email
import email.message
import email.policy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
import courier_html  # noqa: E402
import courier_mail as mail  # noqa: E402
import courier_theme as theme_  # noqa: E402

from PIL import Image  # noqa: E402

DARK = theme_.Theme("#121318", "#e4e5f0", "#a9aab5", "#b9c6ee")

GITHUB_TEXT = """@priya requested your review on: lumen/app#482 Onboarding checklist.

The checklist now has three steps and a progress bar.

- Adds `ChecklistCard` in src/onboarding/Checklist.tsx
- Commit 3f9c2ab moves the copy to strings.json

> Can you look at the empty state?

—
Reply to this email directly, view it on GitHub <https://github.com/lumen/app/pull/482>, or unsubscribe <https://github.com/notifications/unsubscribe-auth/X>.
You are receiving this because your review was requested.
"""
GITHUB_HTML = """<p><b>@priya</b> requested your review on: <a href="https://github.com/lumen/app/pull/482">lumen/app#482</a> Onboarding checklist.</p>
<p>The checklist now has three steps and a progress bar.</p><ul><li>Adds <code>ChecklistCard</code></li></ul>
<p style="color:#666;font-size:12px">Reply to this email directly, <a href="https://github.com/x">view it on GitHub</a>.</p>"""
NEWSLETTER_HTML = """<html><body style="background:#f3f4f6"><table width="600" bgcolor="#ffffff"><tr><td>
<img src="cid:hero" width="600" height="240" alt=""></td></tr>
<tr><td bgcolor="#7c3aed" style="color:#ffffff;font-size:32px">Winter sale</td></tr>
<tr><td bgcolor="#f59e0b">Free shipping</td></tr><tr><td bgcolor="#0ea5e9"><a href="https://shop.example/x" style="display:inline-block;background:#111827;padding:12px">Shop now</a></td></tr>
</table></body></html>"""


def png(size: tuple[int, int], colour=(30, 30, 30, 255), mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, colour if mode == "RGBA" else colour[:3]).save(out, "PNG")
    return out.getvalue()


def build(sender: str, html_part: str | None, text_part: str | None, headers: dict[str, str] | None = None,
          images: dict[str, bytes] | None = None):
    message = email.message.EmailMessage(policy=email.policy.default)
    message["From"], message["To"], message["Subject"] = sender, "alex@lumenlabs.example", "Hello"
    for name, value in (headers or {}).items():
        message[name] = value
    if text_part is not None:
        message.set_content(text_part)
        if html_part is not None:
            message.add_alternative(html_part, subtype="html")
    else:
        message.set_content(html_part, subtype="html")
    for cid, data in (images or {}).items():
        body = message.get_body(preferencelist=("html",))
        body.add_related(data, "image", "png", cid=f"<{cid}>")
    return email.message_from_bytes(message.as_bytes(), policy=email.policy.default)


class ReaderViewTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        patcher = unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(root / "run"), "XDG_CACHE_HOME": str(root / "cache"),
                                                         "XDG_STATE_HOME": str(root / "state"), "XDG_CONFIG_HOME": str(root / "config")})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Nothing here touches the network.
        fetch = unittest.mock.patch.object(courier_html, "fetch_all", lambda urls: {})
        fetch.start()
        self.addCleanup(fetch.stop)

    def github(self):
        return build("Priya <notifications@github.com>", GITHUB_HTML, GITHUB_TEXT,
                     {"X-GitHub-Reason": "review_requested", "List-Id": "lumen/app <app.lumen.github.com>", "Precedence": "list"})

    def test_a_notification_shows_its_text_natively(self) -> None:
        shown = mail.reading(self.github(), {"updates"}, "notifications@github.com", DARK)
        self.assertEqual(shown["view"], "plain")
        self.assertEqual(shown["plain"], mail.message_text(self.github()))
        # The footer starts at the rule above "Reply to this email directly".
        self.assertTrue(shown["plain"][shown["plainFooter"]:].lstrip().startswith("—"))
        self.assertTrue(shown["plainAuto"])

    def test_a_review_comment_shows_its_file_and_diff(self) -> None:
        # GitHub's review comments name the file and show the diff only in
        # their HTML; the text part has neither, so the HTML shows (dark).
        text = ("@codex commented on this pull request.\n\nChoose staging by the last completed deploy.\n\n"
                "If staging deploys overlap, the newer build still shows as running even though an older deploy applied last.\n\n"
                "—\nReply to this email directly, view it on GitHub <https://github.com/lumen/app/pull/29>.\n")
        markup = ('<p>@codex commented on this pull request.</p><hr><p>In <a href="https://github.com/x">apps/api/src/seal.ts</a>:</p>'
                  '<pre>&gt; +  const runs = (environment) =&gt;\n+    deploys.find((d) =&gt; d.status === "ok")</pre>'
                  '<p>Choose staging by the last completed deploy.</p>')
        parsed = build("Codex <notifications@github.com>", markup, text, {"X-GitHub-Reason": "author", "Precedence": "list"})
        shown = mail.reading(parsed, {"updates"}, "notifications@github.com", DARK)
        self.assertFalse(shown["plainAuto"])
        self.assertEqual(shown["view"], "themed")
        self.assertTrue(shown["plain"])  # "Show plain text" still has it
        # An ordinary notification whose code is in its text stays plain.
        self.assertEqual(mail.reading(self.github(), {"updates"}, "notifications@github.com", DARK)["view"], "plain")
        # Hostile HTML can't make the check slow.
        import time
        started = time.monotonic()
        mail.html_only_code("<pre" * 100000 + "In " + "a" * 100000, "x")
        self.assertLess(time.monotonic() - started, 3)

    def test_simple_html_is_drawn_in_the_apps_colours(self) -> None:
        parsed = build("Bank <alerts@bank.example>", GITHUB_HTML, None)
        shown = mail.reading(parsed, {"updates"}, "alerts@bank.example", DARK)
        self.assertEqual((shown["view"], shown["kind"], shown["themed"]), ("themed", "simple", True))
        self.assertEqual(shown["htmlBackground"], "")
        # Grey text became light, readable on the dark surface; links the theme's.
        self.assertNotIn("#666", shown["html"])
        self.assertIn("a{color:#b9c6ee}", shown["html"])
        # Without the app's theme it stays on paper.
        self.assertEqual(mail.reading(parsed, {"updates"}, "alerts@bank.example")["view"], "designed")

    def test_a_designed_newsletter_stays_on_paper(self) -> None:
        parsed = build("Shop <news@shop.example>", NEWSLETTER_HTML, "Winter sale! Free shipping on everything this week, " * 4,
                       {"List-Unsubscribe": "<https://shop.example/u>", "Precedence": "bulk"}, {"hero": png((1200, 480))})
        shown = mail.reading(parsed, {"newsletters"}, "news@shop.example", DARK)
        self.assertEqual((shown["view"], shown["kind"], shown["themed"]), ("designed", "designed", False))
        self.assertIn("#7c3aed", shown["html"])

    def test_people_still_read_as_text(self) -> None:
        parsed = build("Maya <maya@larkpost.example>", "<p>Lisbon in March?</p>", "Lisbon in March?")
        self.assertEqual(mail.reading(parsed, {"people"}, "maya@larkpost.example", DARK)["view"], "text")

    def test_link_heavy_alerts_keep_their_html(self) -> None:
        links = "\n".join(f"Job {n}: https://jobs.example/view/{n}?trk=abcdefghijklmnopqrstuvwxyz0123456789abcdef" for n in range(12))
        parsed = build("Jobs <alerts@jobs.example>", "<p>12 new jobs for you</p>" + "<p>Job</p>" * 12, f"New jobs for you\n\n{links}",
                       {"List-Unsubscribe": "<https://jobs.example/u>"})
        shown = mail.reading(parsed, {"updates"}, "alerts@jobs.example", DARK)
        self.assertFalse(shown["plainAuto"])
        self.assertEqual(shown["view"], "themed")

    def test_html_in_the_text_part_isnt_a_text_version(self) -> None:
        source = "<html><body><p>Dear Investor,</p><p>Your statement for the quarter is attached.</p><br><p>Regards</p></body></html>"
        parsed = build("Exchange <alerts@exchange.example>", "<p>Dear Investor, your statement is attached.</p>", source,
                       {"Auto-Submitted": "auto-generated"})
        self.assertEqual(mail.reading(parsed, {"updates"}, "alerts@exchange.example", DARK)["view"], "themed")

    def test_each_senders_choice_is_remembered(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["reader-pref", "Notifications@GitHub.com", "--plain", "original"]), 0)
        self.assertEqual(json.loads(out.getvalue())["plain"], "original")
        self.assertEqual(mail.reading(self.github(), {"updates"}, "notifications@github.com", DARK)["view"], "themed")
        mail.set_reader_pref("notifications@github.com", plain="auto", colours="original")
        self.assertEqual(mail.reading(self.github(), {"updates"}, "notifications@github.com", DARK)["view"], "plain")
        mail.set_reader_pref("notifications@github.com", plain="original")
        self.assertEqual(mail.reading(self.github(), {"updates"}, "notifications@github.com", DARK)["view"], "designed")
        # "Dark" for a designed newsletter, and "always" plain text for a person.
        mail.set_reader_pref("news@shop.example", colours="dark")
        parsed = build("Shop <news@shop.example>", NEWSLETTER_HTML, None, images={"hero": png((1200, 480))})
        self.assertEqual(mail.reading(parsed, {"newsletters"}, "news@shop.example", DARK)["view"], "themed")
        mail.set_reader_pref("maya@larkpost.example", plain="always")
        parsed = build("Maya <maya@larkpost.example>", "<p>Hi</p>", "Lisbon in March? The flat has a terrace and the evening sun.")
        self.assertEqual(mail.reading(parsed, {"people"}, "maya@larkpost.example", DARK)["view"], "plain")
        with self.assertRaises(mail.MailError):
            mail.set_reader_pref("x@y.example", colours="neon")

    def test_a_dark_see_through_logo_gets_a_light_backing(self) -> None:
        logo = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
        logo.paste((20, 20, 20, 255), (10, 10, 110, 30))
        data = io.BytesIO()
        logo.save(data, "PNG")
        parsed = build("Bank <alerts@bank.example>", '<p>Your statement</p><img src="cid:logo" width="120" height="40">', None,
                       images={"logo": data.getvalue()})
        made = courier_html.designed(parsed, parsed.get_body(preferencelist=("html",)).get_content(), DARK)
        self.assertTrue(made["themed"])
        width, height = (int(v) for v in __import__("re").search(r'width="(\d+)" height="(\d+)"', made["html"]).groups())
        self.assertEqual((width, height), (132, 52))  # 6 px of light card around it
        # A huge logo shown small: its card is drawn at most twice the size shown.
        big = Image.new("RGBA", (3000, 1000), (0, 0, 0, 0))
        big.paste((20, 20, 20, 255), (200, 200, 2800, 800))
        data = io.BytesIO()
        big.save(data, "PNG")
        parsed = build("Bank <alerts@bank.example>", '<p>Hi</p><img src="cid:logo" width="30" height="10">', None,
                       images={"logo": data.getvalue()})
        made = courier_html.designed(parsed, parsed.get_body(preferencelist=("html",)).get_content(), DARK)
        card = __import__("re").search(r'src="file://([^"]+)"', made["html"]).group(1)
        with Image.open(card) as drawn:
            self.assertLessEqual(drawn.width, 2 * 30 + 2 * 12)
        # A light logo reads on dark as it is.
        parsed = build("Bank <alerts@bank.example>", '<p>Hi</p><img src="cid:logo" width="120" height="40">', None,
                       images={"logo": png((120, 40), (240, 240, 240, 255), "RGBA")})
        made = courier_html.designed(parsed, parsed.get_body(preferencelist=("html",)).get_content(), DARK)
        self.assertIn('width="120" height="40"', made["html"])


class HostileInputTest(unittest.TestCase):
    def test_bad_colours_and_long_tags_are_harmless(self) -> None:
        self.assertIsNone(theme_.parse("rgb(1.2.3, 4, 5)"))
        self.assertEqual(DARK.foreground("rgb(1.2.3, 4, 5)"), None)
        import time
        started = time.monotonic()
        courier_html.BACKGROUND_IMAGE.search(("<td " + "a" * 100000) * 5)
        self.assertLess(time.monotonic() - started, 1.0)


class ColourTest(unittest.TestCase):
    def test_text_reads_on_the_surface(self) -> None:
        for colour in ("#000000", "#24292f", "#57606a", "#666666", "#999999", "#cf222e", "#0969da", "#1a7f37", "#ffffff"):
            mapped = theme_.parse(DARK.foreground(colour))[:3]
            self.assertGreaterEqual(theme_.contrast(mapped, DARK.surface), 4.49, colour)
        # Greys keep their order: darker on white, brighter on dark.
        greys = [theme_.luminance(theme_.parse(DARK.foreground(c))[:3]) for c in ("#333333", "#666666", "#999999")]
        self.assertEqual(greys, sorted(greys, reverse=True))

    def test_backgrounds_become_the_surface(self) -> None:
        self.assertEqual(DARK.background("#ffffff"), "#121318")
        elevated = theme_.parse(DARK.background("#f6f8fa"))[:3]
        self.assertGreater(theme_.luminance(elevated), theme_.luminance(DARK.surface))
        # A coloured block keeps its hue, dark enough for the theme's text.
        green = theme_.parse(DARK.background("#2da44e"))[:3]
        self.assertGreaterEqual(theme_.contrast(green, DARK.text), 4.49)
        self.assertGreater(green[1], green[0])

    def test_a_light_theme_keeps_colours(self) -> None:
        light = theme_.Theme("#fdf8ff", "#1b1b21")
        self.assertEqual(light.background("#ffffff"), "#fdf8ff")
        self.assertGreaterEqual(theme_.contrast(theme_.parse(light.foreground("#bbbbbb"))[:3], light.surface), 4.49)


class FooterTest(unittest.TestCase):
    def test_footers(self) -> None:
        text = mail.tidy_whitespace(GITHUB_TEXT)
        self.assertEqual(text[mail.footer_start(text):].split("\n")[0], "—")
        gitlab = "Pipeline #12 has failed!\n\nProject: lumen / api\nBranch: main\n\nYou're receiving this email because of your account on gitlab.example."
        self.assertTrue(gitlab[mail.footer_start(gitlab):].startswith("You're receiving"))
        self.assertEqual(mail.footer_start("Hi Alex,\n\nSee you at 7!\n\nSam"), -1)


@unittest.skipUnless(shutil.which("node"), "needs node")
class PlainTextFormattingTest(unittest.TestCase):
    def format(self, text: str, footer: int, whole: bool = False) -> str:
        script = (ENGINE.parent / "shell" / "services" / "plaintext.js").read_text().replace(".pragma library", "")
        program = script + f"\nprocess.stdout.write(formatted({json.dumps(text)}, {{text:'#eee',muted:'#aaa',link:'#9cf',code:'#222'}}, " \
                           f"{{footer:{footer},wholeLinks:{json.dumps(whole)}}}));"
        return subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True).stdout

    def test_formatted(self) -> None:
        text = mail.tidy_whitespace(GITHUB_TEXT)
        out = self.format(text, mail.footer_start(text))
        self.assertIn("<code", out)  # `ChecklistCard`, the path and the commit
        self.assertIn("3f9c2ab</code>", out)
        self.assertIn("<ul", out)
        self.assertIn("<blockquote", out)
        self.assertIn('font-size:12px', out)  # the footer, folded
        self.assertNotIn("<br>—", out)
        # GitHub's Markdown: comments and tags gone, **bold**, [label](link),
        # fenced suggestions as code, badges dropped.
        markdown = self.format("<!-- receipt -->\n**Reviewed commit:** `636a4f58a0`\n<br/>\n[Your team](https://chatgpt.com/codex) set it up.\n\n"
                               "```suggestion\n+ const runs = x\n```\n![P2](https://img.shields.io/p2.svg) done", -1)
        self.assertNotIn("receipt", markdown)
        self.assertIn("<b>Reviewed commit:</b>", markdown)
        self.assertIn('<font color="#9cf">Your team</font></a>', markdown)
        self.assertIn("<pre", markdown)
        self.assertNotIn("<li>const", markdown)
        self.assertNotIn("shields", markdown)
        # The footer offset counts characters, emoji included.
        emoji = "Great 👍 work 👎 here 💡 done\n\n—\nReply to this email directly, view it on GitHub."
        out = self.format(emoji, mail.footer_start(emoji))
        self.assertIn("done", out)
        self.assertIn(">Reply to this email directly", out.replace("<font color=\"#aaa\">", ">"))
        # A link whose label is another address says where it goes; the
        # placeholders can't be forged; unclosed comments cost nothing.
        spoof = self.format("Sign in: [https://bank.example/login](https://evil.example/x) or [your account](https://bank.example/a)", -1)
        self.assertIn("https://bank.example/login (evil.example", spoof)
        self.assertIn(">your account<", spoof)
        # user:password@ can't make another site pass for the label's.
        sneaky = self.format("[https://bank.example](https://bank.example:x@evil.example/login)", -1)
        self.assertIn("evil.example", sneaky.split("</font>")[0])
        self.assertNotIn("undefined", self.format("odd \uE0009\uE001 text", -1))
        import time
        started = time.monotonic()
        self.format("<!--" * 20000 + "end", -1)
        self.assertLess(time.monotonic() - started, 5)
        # Entities a sender left in its text part read as characters.
        self.assertIn("It's easy", self.format("It&#x27;s easy, click &quot;Leave feedback&quot;.", -1))
        # Teach mode: the footer in full and links whole.
        whole = self.format(text, -1, True)
        self.assertNotIn("font-size:12px", whole)
        self.assertIn(">https://github.com/lumen/app/pull/482<", whole)


if __name__ == "__main__":
    unittest.main()
