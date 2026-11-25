"""Teach fields end to end (courier_templates.py, courier-mail's teach
commands, courier-sync's hook): a hand-built mailbox of made-up Forgeline
notifications, shaped like the demo profile's, indexed by notmuch in a
temporary folder. Nothing here is real mail."""

from __future__ import annotations

import contextlib
import email.message
import email.policy
import email.utils
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def load(name: str):
    """A private copy of an engine module, as the other tests load them
    (nothing registered in sys.modules for the others to trip over)."""
    spec = importlib.util.spec_from_file_location(name, HERE.parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = load("courier_sync")
mail = load("courier_mail")
templates = mail.templates

FORGE = "https://forgeline.example"
PULLS = {
    1471: ("lumenlabs/lumen-app", "Team invites: send one email per teammate"),
    1479: ("lumenlabs/lumen-app", "Onboarding v2: checklist and empty states"),
    899: ("lumenlabs/lumen-api", "Rate limits per team, not per token"),
    455: ("lumenlabs/lumen-web", "Pricing page: annual toggle"),
}


def push_html(login: str, repo: str, number: int, commits: list[tuple[str, str]], forced: bool = False) -> str:
    """A push notification the way a forge writes one (as demo/make_demo.py)."""
    link = f"{FORGE}/{repo}/pull/{number}/files/{commits[-1][0][:12]}"
    noun = "commit" if len(commits) == 1 else "commits"
    head = (f'<p><a class="user-mention" href="{FORGE}/{login}">@{login}</a> '
            + ("force-pushed the branch." if forced else f"pushed {len(commits)} {noun}.") + "</p>")
    rows = "".join(f'<li><a class="commit-link" href="{FORGE}/{repo}/commit/{sha}">{sha[:7]}</a>  {message}</li>\n'
                   for sha, message in commits)
    return (f"{head}\n<ul>\n{rows}</ul>\n"
            f'<p class="fl-foot" style="font-size:small;color:#666">&mdash;<br><a href="{link}">View it on Forgeline</a> or '
            f'<a href="{FORGE}/notifications/unsubscribe/x">unsubscribe</a>.<br>You are receiving this because you are '
            "subscribed to this thread.</p>")

ACCOUNTS = [{"id": "work", "email": "alex@lumenlabs.example"}]
START = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def sha(seed: int) -> str:
    return hashlib.sha1(f"test-{seed}".encode()).hexdigest()


def notification(number: int, who: str, login: str, pull: int, html: str, text: str) -> bytes:
    repo, title = PULLS[pull]
    message = email.message.EmailMessage(policy=email.policy.SMTP)
    message["From"] = email.utils.formataddr((who, "notifications@forgeline.example"))
    message["To"] = "alex@lumenlabs.example"
    message["Subject"] = f"Re: [{repo}] {title} (PR #{pull})"
    message["Date"] = email.utils.format_datetime(START + timedelta(hours=number))
    message["Message-ID"] = f"<push-{number}@forgeline.example>"
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message.as_bytes(policy=email.policy.SMTP)


def push(number: int, who: str, login: str, pull: int, messages: list[str], **shape) -> bytes:
    repo, _ = PULLS[pull]
    commits = [(sha(100 * number + k), text) for k, text in enumerate(messages)]
    line = "force-pushed the branch." if shape.get("forced") else f"pushed {len(commits)} {'commit' if len(commits) == 1 else 'commits'}."
    text = (f"@{login} {line}\n\n" + "\n".join(f"{s}  {m}" for s, m in commits)
            + f"\n\n-- \nView it on Forgeline:\n{FORGE}/{repo}/pull/{pull}/files/{commits[-1][0][:12]}\n")
    return notification(number, who, login, pull, push_html(login, repo, pull, commits, **shape), text)


PUSHES = [
    ("Daniel Kim", "dkim", 1471, ["Batch invites", "Trim spaces"]),
    ("Lena Fischer", "lena-f", 1479, ["Checklist: remember what was done"]),
    ("Ruth Adeyemi", "ruth-a", 899, ["Team limits table", "Migrate token limits", "Count per team", "Docs"]),
    ("Owen Price", "owen-p", 455, ["Say 2 months free"]),
    ("Daniel Kim", "dkim", 1471, ["Retry a bounced invite once", "Plain-text part", "Tests"]),
]


class TemplatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        root = Path(self.home.name)
        self.env = unittest.mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_RUNTIME_DIR": str(root / "run"), "COURIER_NO_NOTIFY": "1", "COURIER_OFFLINE": "1"})
        self.env.start()
        (root / "config" / "courier").mkdir(parents=True)
        (root / "config" / "courier" / "accounts.json").write_text(json.dumps({"accounts": ACCOUNTS}))
        sync.configure(ACCOUNTS, {"work": "[Gmail]/All Mail"})
        for number, (who, login, pull, messages) in enumerate(PUSHES):
            self.deliver(f"p{number}", push(number, who, login, pull, messages))
        # After a redesign: a force-push says no count.
        self.deliver("forced", push(9, "Hana Sato", "hana-sato", 1479, ["Rebase on main"], forced=True))
        sync.index(ACCOUNTS)
        import notmuch2

        os.environ["NOTMUCH_CONFIG"] = str(sync.config_dir() / "notmuch-config")
        self.db = notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY)

    def tearDown(self) -> None:
        self.db.close()
        self.env.stop()
        self.home.cleanup()

    def deliver(self, name: str, content: bytes) -> None:
        for folder in ("all", "inbox"):
            base = sync.mail_dir() / "work" / folder
            for part in ("cur", "new", "tmp"):
                (base / part).mkdir(parents=True, exist_ok=True)
            (base / "cur" / f"{name}:2,S").write_bytes(content)

    def mail_state(self) -> dict:
        files = {str(p.relative_to(sync.mail_dir())): hashlib.sha1(p.read_bytes()).hexdigest()
                 for p in sync.mail_dir().rglob("*") if p.is_file() and "/cur/" in str(p) or "/new/" in str(p)}
        tags = {m.messageid: sorted(m.tags) for m in self.db.messages("*")}
        return {"files": files, "tags": tags}

    def select(self, message_id: str, value: str, after: str = "", surface: str = "text") -> dict:
        page = templates.read_mail(self.db, message_id).page_for(surface)
        begin = page.text.index(value, page.text.index(after) + len(after) if after else 0)
        return templates.select(self.db, message_id, {"start": begin, "end": begin + len(value), "shown": page.text,
                                                      "surface": surface})

    def taught(self, message_id: str = "push-4@forgeline.example", surface: str = "text") -> dict:
        start = templates.start(self.db, message_id, surface)
        fields = []
        for name, picked, flags in [
            ("Author", self.select(message_id, "@dkim", surface=surface), {}),
            ("Commits", self.select(message_id, "3", "pushed", surface=surface), {}),
            ("Hashes", self.select(message_id, sha(400) if surface == "text" else sha(400)[:7], surface=surface), {"list": True}),
            ("PR", templates.select(self.db, message_id, {"subject": True, "value": "1471"}), {"subject": True}),
        ]:
            example = {k: picked[k] for k in ("id", "value", "start", "end") if k in picked}
            fields.append({"name": name, "examples": [example], **flags})
        return dict(start["template"], fields=fields)

    def test_one_template_for_the_pushes(self) -> None:
        start = templates.start(self.db, "push-4@forgeline.example")
        self.assertFalse(start["saved"])
        self.assertEqual(start["count"], 6)  # the five pushes and the force-push
        self.assertEqual(start["template"]["surface"], "text")
        self.assertIn("Forgeline", start["template"]["name"])
        self.assertEqual(len(start["preview"]["rows"]), 6)

    def test_a_selection_is_placed_in_the_email(self) -> None:
        picked = self.select("push-4@forgeline.example", "@dkim")
        self.assertEqual(picked["value"], "@dkim")
        # Qt's text for the same email: other whitespace and paragraph marks.
        page = templates.read_mail(self.db, "push-4@forgeline.example").page_for("text")
        shown = page.text.replace("\n", " ").replace("  ", " ")
        begin = shown.index("3 commits")
        placed = templates.select(self.db, "push-4@forgeline.example",
                                  {"start": begin, "end": begin + 1, "shown": shown, "surface": "text"})
        self.assertEqual(placed["value"], "3")
        with self.assertRaises(templates.TemplateError):
            templates.select(self.db, "push-4@forgeline.example", {"subject": True, "value": "not in it"})

    def test_preview_reads_the_other_emails_and_flags_the_changed_one(self) -> None:
        preview = templates.preview(self.db, "push-4@forgeline.example", self.taught())
        rows = {row["id"]: row for row in preview["rows"]}
        ruth = rows["push-2@forgeline.example"]
        self.assertEqual(ruth["status"], "ok")
        self.assertEqual(ruth["values"]["Author"], "@ruth-a")
        self.assertEqual(ruth["values"]["Commits"], "4")
        self.assertEqual(ruth["values"]["Hashes"], [sha(200 + k) for k in range(4)])
        self.assertEqual(ruth["values"]["PR"], "899")
        forced = rows["push-9@forgeline.example"]
        self.assertEqual(forced["status"], "reteach")
        self.assertEqual(forced["values"], {})  # never a wrong value
        self.assertIn("Commits", forced["missing"])
        self.assertEqual([f["name"] for f in preview["fields"]], ["Author", "Commits", "Hashes", "PR"])

    def test_save_table_card_and_delete(self) -> None:
        before = self.mail_state()
        saved = templates.save(self.db, "push-4@forgeline.example", self.taught())
        self.assertEqual((saved["count"], saved["flagged"]), (6, 1))
        folder = sync.state_dir() / "templates" / "work"
        self.assertTrue((folder / f"{saved['id']}.json").is_file())
        kept = json.loads((folder / f"{saved['id']}.json").read_text())
        # What was taught is kept as Message-IDs and offsets, not mail text.
        self.assertNotIn("Batch invites", json.dumps(kept["fields"]))

        table = templates.table(self.db, saved["id"])
        self.assertEqual([c["name"] for c in table["columns"]], ["Author", "Commits", "Hashes", "PR"])
        self.assertEqual(len(table["rows"]), 6)
        self.assertEqual(table["flagged"], 1)
        flagged = next(row for row in table["rows"] if row["status"] == "reteach")
        self.assertEqual(flagged["values"], {})

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["message", "push-0@forgeline.example"]), 0)
        card = json.loads(out.getvalue())["fields"]
        self.assertEqual(card["status"], "ok")
        self.assertEqual({f["name"]: f["value"] for f in card["fields"]}["Author"], "@dkim")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["message", "push-9@forgeline.example"]), 0)
        card = json.loads(out.getvalue())["fields"]
        self.assertEqual(card["status"], "reteach")
        self.assertTrue(all(f["value"] is None for f in card["fields"]))

        self.assertEqual([t["id"] for t in templates.listing()], [saved["id"]])
        templates.delete_template(saved["id"])
        self.assertEqual(templates.listing(), [])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mail.main(["message", "push-0@forgeline.example"])
        self.assertIsNone(json.loads(out.getvalue())["fields"])
        # Teaching never touched the mail or its tags.
        self.assertEqual(self.mail_state(), before)

    def test_optional_fields_do_not_flag(self) -> None:
        template = self.taught()
        for field in template["fields"]:
            if field["name"] == "Commits":
                field["optional"] = True
        saved = templates.save(self.db, "push-4@forgeline.example", template)
        self.assertEqual(saved["flagged"], 0)
        row = next(r for r in templates.table(self.db, saved["id"])["rows"] if r["id"] == "push-9@forgeline.example")
        self.assertEqual(row["status"], "partial")
        self.assertEqual(row["values"]["Author"], "@hana-sato")

    def test_taught_on_the_designed_version(self) -> None:
        saved = templates.save(self.db, "push-4@forgeline.example", self.taught(surface="html"))
        row = next(r for r in templates.table(self.db, saved["id"])["rows"] if r["id"] == "push-2@forgeline.example")
        self.assertEqual(row["values"]["Hashes"], [sha(200 + k)[:7] for k in range(4)])

    def test_new_mail_is_read_after_a_sync(self) -> None:
        saved = templates.save(self.db, "push-4@forgeline.example", self.taught())
        self.db.close()
        self.deliver("new", push(20, "Priya Natarajan", "priya-n", 1479, ["Empty state copy", "Smaller illustration"]))
        sync.index(ACCOUNTS)
        import notmuch2

        self.db = notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY)
        values = json.loads((sync.state_dir() / "templates" / "work" / f"{saved['id']}.values.json").read_text())
        self.assertEqual(values["push-20@forgeline.example"]["values"]["Commits"], "2")
        self.assertEqual(values["push-20@forgeline.example"]["values"]["Author"], "@priya-n")

    def test_the_panel_talks_json_on_stdin(self) -> None:
        page = templates.read_mail(self.db, "push-4@forgeline.example").page_for("text")
        begin = page.text.index("@dkim")
        payload = json.dumps({"start": begin, "end": begin + 5, "shown": page.text, "surface": "text"})
        out = io.StringIO()
        with unittest.mock.patch("sys.stdin", io.StringIO(payload)), contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["teach-select", "push-4@forgeline.example"]), 0)
        self.assertEqual(json.loads(out.getvalue())["value"], "@dkim")
        out = io.StringIO()
        with unittest.mock.patch("sys.stdin", io.StringIO("not json")), contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["teach-save", "push-4@forgeline.example"]), 1)
        self.assertIn("error", json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
