"""courier-mail through its command line, on a hand-built Maildir indexed by courier-sync.

Run from the engine folder:  python3 -m unittest discover tests
"""

from __future__ import annotations

import contextlib
import email
import email.policy
import importlib.util
import io
import json
import re
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = load("courier_sync")
mail = load("courier_mail")

ME = "someone@example.com"
ACCOUNTS = [{"id": "personal", "email": ME}]


def message(message_id: str, sender: str, to: str, subject: str, body: str, date: str, extra: str = "") -> bytes:
    return (
        f"Message-ID: <{message_id}>\nFrom: {sender}\nTo: {to}\nSubject: {subject}\nDate: {date}\n{extra}"
        f"Content-Type: text/plain; charset=utf-8\n\n{body}"
    ).encode()


class MailFixture(unittest.TestCase):
    """A hand-built mailbox, indexed; no tests of its own."""

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        root = Path(self.home.name)
        self.env = unittest.mock.patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"), "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"), "COURIER_NO_NOTIFY": "1"},
        )
        self.env.start()
        (root / "config" / "courier").mkdir(parents=True)
        (root / "config" / "courier" / "accounts.json").write_text(json.dumps({"accounts": ACCOUNTS}))
        sync.configure(ACCOUNTS, {"personal": "[Gmail]/All Mail"})

        self.deliver("1", message("a1@x", "Aarav Mehta <aarav@northwind.example>", ME, "Brand review",
                                  "Sharing the guidelines.\n", "Thu, 19 Nov 2026 18:02:00 +0530"), "S")
        self.deliver("2", message("me1@x", f"Jagrit <{ME}>", "Aarav Mehta <aarav@northwind.example>", "Re: Brand review",
                                  "Looks great.\n\nOn Thu, 19 Nov 2026 at 18:02, Aarav <aarav@northwind.example> wrote:\n> Sharing the guidelines.\n",
                                  "Thu, 19 Nov 2026 18:20:00 +0530", "In-Reply-To: <a1@x>\n"), "S", inbox=False)
        html = (
            "Message-ID: <a2@x>\nFrom: Aarav Mehta <aarav@northwind.example>\nTo: someone@example.com\n"
            "Subject: Re: Brand review\nDate: Fri, 20 Nov 2026 10:40:00 +0530\nReferences: <a1@x> <me1@x>\n"
            "Content-Type: text/html; charset=utf-8\n\n"
            "<html><head><style>p{}</style></head><body><p>Can we move it to <b>Thursday</b>?</p>"
            "<div class=\"gmail_quote\">On Thu wrote:<blockquote>Looks great.</blockquote></div></body></html>"
        ).encode()
        self.deliver("3", html)
        self.deliver("4", message("pr@gh", "GitHub <notifications@github.com>", ME, "[studio/app] Fix dock (PR #7)",
                                  "Merged.\n", "Fri, 20 Nov 2026 09:00:00 +0530", "X-GitHub-Reason: review_requested\n"))
        self.deliver("5", message("news@figma", "Figma <hello@figma.example>", ME, "What's new",
                                  "Variables.\n", "Fri, 20 Nov 2026 07:00:00 +0530", "List-Unsubscribe: <mailto:u@figma.example>\n"))
        sync.index(ACCOUNTS)

    def tearDown(self) -> None:
        self.env.stop()
        self.home.cleanup()

    def deliver(self, name: str, content: bytes, flags: str = "", inbox: bool = True) -> None:
        """Files an email the way Gmail's IMAP shows it: in All Mail, and also
        in INBOX while it's in the inbox."""
        for folder in ("all", "inbox") if inbox else ("all",):
            base = sync.mail_dir() / "personal" / folder
            for part in ("cur", "new", "tmp"):
                (base / part).mkdir(parents=True, exist_ok=True)
            (base / "cur" / f"{name}:2,{flags}").write_bytes(content)

    def run_json(self, *args: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(list(args)), 0)
        return json.loads(out.getvalue())



class CourierMailTest(MailFixture):
    def test_conversations_group_people_updates_and_newsletters(self) -> None:
        conversations = {c["id"]: c for c in self.run_json("conversations")}
        self.assertEqual(set(conversations), {"p:aarav@northwind.example", "u:github.com", "n:all"})
        aarav = conversations["p:aarav@northwind.example"]
        self.assertEqual((aarav["kind"], aarav["name"], aarav["unread"]), ("person", "Aarav Mehta", 1))
        self.assertEqual(aarav["preview"], "Can we move it to Thursday?")
        self.assertEqual(conversations["u:github.com"]["logo"], "github")
        self.assertEqual(conversations["n:all"]["preview"], "Figma")

    def test_thread_is_a_chat_without_quoted_history(self) -> None:
        thread = self.run_json("thread", "p:aarav@northwind.example")
        self.assertEqual([m["from"] for m in thread], ["them", "me", "them"])
        self.assertEqual([m["body"] for m in thread], ["Sharing the guidelines.", "Looks great.", "Can we move it to Thursday?"])
        # The subject shows once; "Re:" doesn't count as a new one.
        self.assertEqual([m.get("subject") for m in thread], ["Brand review", None, None])

    def test_update_cards(self) -> None:
        [card] = self.run_json("thread", "u:github.com")
        self.assertEqual((card["kind"], card["status"], card["meta"], card["title"]), ("update", "review", "studio/app", "Fix dock (PR #7)"))

    def test_reply_threads_onto_the_latest_message(self) -> None:
        result = self.run_json("send", "p:aarav@northwind.example", "--body", "Thursday works.", "--dry-run")
        text = result["message"]
        self.assertIn("From: Jagrit <someone@example.com>", text)
        self.assertIn("To: Aarav Mehta <aarav@northwind.example>", text)
        self.assertIn("Subject: Re: Brand review", text)
        self.assertIn("In-Reply-To: <a2@x>", text)
        self.assertIn("References: <a1@x> <me1@x> <a2@x>", text)
        self.assertTrue(text.endswith("Thursday works.\r\n"))

    def test_reader_shows_new_text_with_quoted_history_on_request(self) -> None:
        mail_json = self.run_json("message", "me1@x")
        self.assertEqual(mail_json["body"], "Looks great.")
        self.assertIn("Sharing the guidelines.", mail_json["full"])
        self.assertTrue(mail_json["mine"])
        self.assertFalse(mail_json["hasOriginal"])

    def test_designed_mail_reads_as_designed_and_people_as_text(self) -> None:
        self.deliver("6", (
            "Message-ID: <promo@x>\nFrom: Figma <hello@figma.example>\nTo: someone@example.com\nSubject: Config\n"
            "Date: Fri, 20 Nov 2026 08:00:00 +0530\nList-Unsubscribe: <mailto:u@figma.example>\n"
            "Content-Type: text/html; charset=utf-8\n\n"
            "<html><body bgcolor=\"#f4f4f4\"><table width=\"600\"><tr><td><h1>Config is back</h1>"
            "<script>alert(1)</script></td></tr></table></body></html>"
        ).encode())
        sync.index(ACCOUNTS)
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.home.name}):
            promo = self.run_json("message", "promo@x")
            person = self.run_json("message", "a2@x")
        self.assertEqual((promo["view"], promo["htmlBackground"]), ("designed", "#f4f4f4"))
        self.assertIn("<h1>Config is back</h1>", promo["html"])
        self.assertNotIn("alert", promo["html"])
        # A person's HTML mail reads as text; the designed version is a click away.
        self.assertEqual(person["view"], "text")
        self.assertIn("<b>Thursday</b>", person["html"])

    def test_plain_text_written_in_markdown_reads_rendered(self) -> None:
        self.deliver("8", message("md@x", "Aarav Mehta <aarav@northwind.example>", ME, "Release notes",
                                  "## Shipped\n\n- **Search** is faster\n- `make deploy` works again\n", "Fri, 20 Nov 2026 11:00:00 +0530"))
        sync.index(ACCOUNTS)
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.home.name}):
            mail_json = self.run_json("message", "md@x")
        # From a person, yet shown rendered: it was written in Markdown.
        self.assertEqual(mail_json["view"], "designed")
        self.assertIn("<h2>Shipped</h2>", mail_json["html"])
        self.assertIn("<strong>Search</strong>", mail_json["html"])

    def test_original_opens_with_scripts_blocked(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.home.name}):
            path = Path(self.run_json("original", "a2@x")["path"])
        page = path.read_text()
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertTrue(page.startswith('<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy"'))
        self.assertIn("default-src 'none'", page)
        self.assertIn("Thursday", page)

    def test_original_cannot_redirect_the_browser(self) -> None:
        self.deliver("redir", (
            "Message-ID: <redir@x>\nFrom: Promo <hi@promo.example>\nTo: someone@example.com\nSubject: Deal\n"
            "Date: Fri, 20 Nov 2026 12:00:00 +0530\nContent-Type: text/html; charset=utf-8\n\n"
            '<html><head><meta http-equiv="&#114;efresh" content="0;url=https://evil.example/a">'
            '<META HTTP-EQUIV=Refresh CONTENT="0;URL=https://evil.example/b">'
            '<meta content="0;url=https://evil.example/c" http-equiv = "refresh"></head><body><p>Deal</p></body></html>'
        ).encode())
        sync.index(ACCOUNTS)
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.home.name}):
            page = Path(self.run_json("original", "redir@x")["path"]).read_text()
        # Only the page's own Content-Security-Policy is still an attribute
        # named http-equiv (the email's are renamed, so the browser ignores them).
        self.assertEqual(len(re.findall(r"(?i)(?<![\w-])http-equiv\s*=", page)), 1)
        self.assertIn('<meta http-equiv="Content-Security-Policy"', page)
        self.assertIn("Deal", page)

    def test_attachments_save_without_overwriting(self) -> None:
        raw = (
            "Message-ID: <inv@x>\nFrom: Daniel <daniel@okafor.example>\nTo: someone@example.com\nSubject: Invoice\n"
            "Date: Fri, 20 Nov 2026 16:30:00 +0530\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=b\n\n"
            "--b\nContent-Type: text/plain\n\nAttached.\n--b\nContent-Type: application/pdf\n"
            "Content-Disposition: attachment; filename=\"../Invoice 2041.pdf\"\nContent-Transfer-Encoding: base64\n\n"
            "JVBERi0xLjQK\n--b--\n"
        ).encode()
        self.deliver("inv", raw)
        sync.index(ACCOUNTS)
        downloads = Path(self.home.name) / "Downloads"
        with unittest.mock.patch.dict(os.environ, {"XDG_DOWNLOAD_DIR": str(downloads)}):
            first = self.run_json("attachment", "inv@x", "0")
            second = self.run_json("attachment", "inv@x", "0")
        self.assertEqual(first["name"], "_Invoice 2041.pdf")  # no climbing out of Downloads
        self.assertEqual(second["name"], "_Invoice 2041 (1).pdf")
        self.assertEqual((downloads / first["name"]).read_bytes(), b"%PDF-1.4\n")

    def test_previews_open_only_pictures_pdfs_and_text_under_safe_names(self) -> None:
        files = email.message.EmailMessage(policy=email.policy.default)
        files["Message-ID"] = "<files@x>"
        files["From"] = "Stranger <someone@stranger.example>"
        files["To"] = ME
        files["Subject"] = "Files"
        files["Date"] = "Fri, 20 Nov 2026 17:00:00 +0530"
        files.set_content("Have a look.")
        launcher = b"[Desktop Entry]\nType=Application\nExec=sh -c 'touch /tmp/owned'\n"
        program = b"\x7fELF\x02\x01\x01" + bytes(64)
        picture = b"\x89PNG\r\n\x1a\n" + bytes(32)
        document = b"%PDF-1.7\n%fake\n"
        files.add_attachment(launcher, maintype="application", subtype="x-desktop", filename="invoice.desktop")
        files.add_attachment(program, maintype="image", subtype="jpeg", filename="photo.jpg")
        files.add_attachment(picture, maintype="application", subtype="octet-stream", filename="\u202egnp.exe")
        files.add_attachment(document, maintype="application", subtype="pdf", filename="report#1?.pdf")
        files.add_attachment(b"Plain notes.\n", maintype="text", subtype="plain", filename="notes.txt")
        self.deliver("files", files.as_bytes())
        sync.index(ACCOUNTS)
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.home.name}):
            shown = {number: self.run_json("preview", "files@x", str(number)) for number in (0, 2, 3, 4)}
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                refused = mail.main(["preview", "files@x", "1"])
        # A launcher is only ever text to read; a program is never opened.
        self.assertEqual(Path(shown[0]["path"]).name, "invoice.txt")
        self.assertEqual(Path(shown[0]["path"]).read_bytes(), launcher)
        self.assertEqual(refused, 1)
        self.assertIn("Save it", json.loads(out.getvalue())["error"])
        # Named for what the bytes are, without the sender's tricks.
        # "\u202egnp.exe" reads as "exe.png" on screen; it is a picture,
        # so it opens as one, with the flip and the .exe gone.
        self.assertEqual(Path(shown[2]["path"]).name, "gnp.png")
        self.assertEqual(Path(shown[3]["path"]).name, "report_1.pdf")
        self.assertEqual(Path(shown[4]["path"]).name, "notes.txt")
        for result in shown.values():
            path = Path(result["path"])
            self.assertEqual(result["url"], path.as_uri())
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            self.assertTrue(path.suffix in {".txt", ".png", ".pdf"})

    def deliver_draft(self, name: str, content: bytes) -> None:
        """A Gmail draft as mbsync files it: in All Mail (with only Gmail's
        Draft label, so nothing marks it there) and in Drafts."""
        self.deliver(name, content, "S", inbox=False)
        drafts = sync.mail_dir() / "personal" / "drafts"
        for part in ("cur", "new", "tmp"):
            (drafts / part).mkdir(parents=True, exist_ok=True)
        (drafts / "cur" / f"{name}:2,S").write_bytes(content)

    def test_a_gmail_draft_never_shows_as_sent(self) -> None:
        # The IGNOU case: an empty reply Gmail saved as a draft in a thread.
        draft = message("draft@me", f"Jagrit <{ME}>", "Aarav Mehta <aarav@northwind.example>", "Re: Brand review", "",
                        "Fri, 20 Nov 2026 19:00:00 +0530", "In-Reply-To: <a2@x>\nReferences: <a1@x> <me1@x> <a2@x>\n")
        self.deliver_draft("draft", draft)
        sync.index(ACCOUNTS)
        thread = self.run_json("thread", "p:aarav@northwind.example")
        self.assertEqual([m["body"] for m in thread], ["Sharing the guidelines.", "Looks great.", "Can we move it to Thursday?"])
        conversations = {c["id"]: c for c in self.run_json("conversations")}
        self.assertEqual(conversations["p:aarav@northwind.example"]["preview"], "Can we move it to Thursday?")
        sent = self.run_json("list", "sent")
        self.assertNotIn("draft@me", [i for section in sent["sections"] for row in section["rows"] for i in row["ids"]])
        # Never something a rule acts on either (deleting it would delete it in Gmail).
        later = load("courier_later")
        query = later.rule_query({"kind": "delete", "category": "", "from": ME, "subject": "", "afterDays": 0})
        index = mail.Index()
        try:
            self.assertEqual(index.db.count_messages(f"({query}) and id:draft@me"), 0)
        finally:
            index.close()

    def test_an_email_with_no_text_goes_only_when_asked(self) -> None:
        def compose(*args: str) -> tuple[int, dict]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = mail.main(["compose", *args, "--dry-run"])
            return code, json.loads(out.getvalue())

        self.assertEqual(compose("--to", "aarav@northwind.example", "--subject", "Hi", "--body", "  \n"),
                         (1, {"error": "This email has no text.", "empty": True}))
        self.assertEqual(compose("--reply-to", "a2@x", "--body", "")[1].get("empty"), True)
        code, asked = compose("--to", "aarav@northwind.example", "--subject", "Hi", "--body", "", "--empty-ok")
        self.assertEqual(code, 0)
        self.assertIn("Subject: Hi", asked["message"])
        # A forward carries the email it forwards.
        self.assertEqual(compose("--to", "mira@northwind.example", "--forward", "a2@x", "--body", "")[0], 0)
        # A reply in a chat is never empty.
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            mail.main(["send", "p:aarav@northwind.example", "--body", "  ", "--dry-run"])

    def test_marks_reach_the_maildir_flags_gmail_syncs(self) -> None:
        folder = sync.mail_dir() / "personal" / "all" / "cur"
        self.assertEqual(self.run_json("mark", "star", "a1@x"), {"changed": 1})
        self.assertTrue((folder / "1:2,FS").exists())
        self.assertEqual(self.run_json("mark", "unread", "a1@x"), {"changed": 1})
        self.assertTrue((folder / "1:2,F").exists())
        self.assertEqual(self.run_json("mark", "unstar", "a1@x"), {"changed": 1})
        self.assertEqual(self.run_json("mark", "unstar", "a1@x"), {"changed": 0})
        [card] = self.run_json("thread", "u:github.com")
        self.assertEqual((card["sender"], card["snippet"], card["unread"], card["starred"]), ("GitHub", "Merged.", True, False))

    def test_reading_marks_only_what_is_shown(self) -> None:
        for number in range(mail.THREAD_LIMIT + 5):
            self.deliver(f"n{number}", message(f"news{number}@x", "Figma <hello@figma.example>", ME, f"Issue {number}", "Hi.\n",
                                               f"Fri, 13 Nov 2026 07:{number % 60:02d}:00 +0530", "List-Unsubscribe: <mailto:u@figma.example>\n"))
        sync.index(ACCOUNTS)
        self.assertEqual(self.run_json("read", "n:all"), {"read": mail.THREAD_LIMIT})
        conversations = {c["id"]: c for c in self.run_json("conversations")}
        self.assertEqual(conversations["n:all"]["unread"], 6)

    def test_reading_marks_the_conversation_read(self) -> None:
        self.assertEqual(self.run_json("read", "p:aarav@northwind.example"), {"read": 1})
        conversations = {c["id"]: c for c in self.run_json("conversations")}
        self.assertEqual(conversations["p:aarav@northwind.example"]["unread"], 0)
        self.assertTrue((sync.mail_dir() / "personal" / "all" / "cur" / "3:2,S").exists())


    # The inbox, mailboxes and search --------------------------------------------

    def test_archived_conversations_leave_the_list_but_stay_findable(self) -> None:
        self.deliver("6", message("old@x", "Rhea Kapoor <rhea@studio.example>", ME, "Old notes", "From last year.\n",
                                  "Mon, 02 Nov 2026 09:00:00 +0530"), "S", inbox=False)
        sync.index(ACCOUNTS)
        self.assertNotIn("p:rhea@studio.example", {c["id"] for c in self.run_json("conversations")})
        self.assertIn("old@x", [m["id"] for m in self.run_json("thread", "m:archive")])
        self.assertIn("old@x", [m["id"] for m in self.run_json("thread", "s:last year")])

    def test_sent_mailbox_shows_who_it_went_to(self) -> None:
        [sent] = self.run_json("thread", "m:sent")
        self.assertEqual((sent["id"], sent["sender"]), ("me1@x", "To Aarav Mehta"))

    def test_starred_mailbox(self) -> None:
        self.run_json("mark", "star", "pr@gh")
        self.assertEqual([m["id"] for m in self.run_json("thread", "m:starred")], ["pr@gh"])

    # Gmail actions --------------------------------------------------------------

    def act(self, *args: str):
        with unittest.mock.patch.object(mail.gmail, "apply", return_value=1) as apply, unittest.mock.patch.object(mail, "start_sync"):
            result = self.run_json("act", *args)
        return result, apply

    def test_archiving_a_conversation_archives_its_inbox_emails_in_gmail(self) -> None:
        result, apply = self.act("archive", "--conversation", "p:aarav@northwind.example")
        (account, action, ids), _ = apply.call_args
        self.assertEqual((account["id"], action, sorted(ids)), ("personal", "archive", ["a1@x", "a2@x"]))
        self.assertEqual(result["done"], 1)
        self.assertNotIn("p:aarav@northwind.example", {c["id"] for c in self.run_json("conversations")})
        self.act("inbox", "a2@x")
        self.assertIn("p:aarav@northwind.example", {c["id"] for c in self.run_json("conversations")})

    def test_deleted_and_spam_emails_vanish_everywhere(self) -> None:
        self.act("trash", "a2@x")
        self.assertNotIn("a2@x", [m["id"] for m in self.run_json("thread", "m:all")])
        self.act("spam", "news@figma")
        self.assertNotIn("n:all", {c["id"] for c in self.run_json("conversations")})
        self.act("untrash", "a2@x")
        self.assertIn("a2@x", [m["id"] for m in self.run_json("thread", "m:all")])

    def test_trash_as_last_seen_follows_deletes_and_restores(self) -> None:
        # Nothing saved yet: the app waits for Gmail.
        self.assertEqual(self.run_json("trash", "--cached"), {"rows": [], "cached": False})
        with unittest.mock.patch.object(mail, "trash_rows", return_value=[
                {"id": "old@x", "title": "Old", "subtitle": "Gone", "time": "", "epoch": 1700000000, "account": "personal"}]):
            self.assertEqual([r["id"] for r in self.run_json("trash")["rows"]], ["old@x"])
        self.act("trash", "a2@x")
        saved = self.run_json("trash", "--cached")
        self.assertTrue(saved["cached"])
        self.assertEqual([(r["id"], r["title"]) for r in saved["rows"]], [("a2@x", "Aarav Mehta"), ("old@x", "Old")])
        self.assertTrue(saved["rows"][1]["time"])
        self.act("untrash", "a2@x")
        self.assertEqual([r["id"] for r in self.run_json("trash", "--cached")["rows"]], ["old@x"])

    def test_gmail_errors_reach_the_app(self) -> None:
        with unittest.mock.patch.object(mail.gmail, "apply", side_effect=mail.gmail.GmailError("Gmail refused.")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(mail.main(["act", "archive", "a1@x"]), 1)
        self.assertEqual(json.loads(out.getvalue()), {"error": "Gmail refused."})
        self.assertIn("p:aarav@northwind.example", {c["id"] for c in self.run_json("conversations")})

    # Writing --------------------------------------------------------------------

    def test_reply_all_keeps_everyone_but_you(self) -> None:
        self.deliver("7", message("team@x", "Aarav Mehta <aarav@northwind.example>", f"{ME}, Ira <ira@northwind.example>",
                                  "Launch plan", "Thoughts?\n", "Sat, 21 Nov 2026 09:00:00 +0530", f"Cc: Dev <dev@northwind.example>, {ME}\n"))
        sync.index(ACCOUNTS)
        reply = self.run_json("draft", "reply", "team@x")
        self.assertEqual((reply["to"], reply["cc"], reply["subject"]), (["Aarav Mehta <aarav@northwind.example>"], [], "Re: Launch plan"))
        everyone = self.run_json("draft", "replyall", "team@x")
        self.assertEqual(everyone["to"], ["Aarav Mehta <aarav@northwind.example>", "Ira <ira@northwind.example>"])
        self.assertEqual(everyone["cc"], ["Dev <dev@northwind.example>"])
        self.assertEqual(self.run_json("draft", "forward", "team@x")["subject"], "Fwd: Launch plan")

    def test_replying_to_a_note_to_yourself_goes_to_you(self) -> None:
        self.deliver("9", message("note@x", f"Jagrit <{ME}>", ME, "Groceries", "Milk.\n", "Sat, 21 Nov 2026 10:00:00 +0530"))
        sync.index(ACCOUNTS)
        self.assertEqual(self.run_json("draft", "reply", "note@x")["to"], [ME])
        self.assertEqual(self.run_json("draft", "reply", "me1@x")["to"], ["Aarav Mehta <aarav@northwind.example>"])

    def test_reply_quotes_and_threads_under_the_email(self) -> None:
        text = self.run_json("compose", "--to", "aarav@northwind.example", "--subject", "Re: Brand review",
                             "--reply-to", "a1@x", "--body", "Thanks!", "--dry-run")["message"]
        self.assertIn("In-Reply-To: <a1@x>", text)
        self.assertIn("> Sharing the guidelines.", text)

    def test_forward_carries_the_text_and_attachments(self) -> None:
        self.deliver("8", (
            "Message-ID: <inv@x>\nFrom: Billing <billing@vendor.example>\nTo: someone@example.com\nSubject: Invoice\n"
            "Date: Sat, 21 Nov 2026 08:00:00 +0530\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=b\n\n"
            "--b\nContent-Type: text/plain\n\nYour invoice.\n--b\nContent-Type: application/pdf\n"
            "Content-Disposition: attachment; filename=\"Invoice 2041.pdf\"\nContent-Transfer-Encoding: base64\n\nJVBERi0xLjQK\n--b--\n"
        ).encode())
        sync.index(ACCOUNTS)
        text = self.run_json("compose", "--to", "accounts@studio.example", "--subject", "Fwd: Invoice",
                             "--forward", "inv@x", "--body", "For the books.", "--dry-run")["message"]
        self.assertIn("---------- Forwarded message ---------", text)
        self.assertIn("Your invoice.", text)
        self.assertIn('filename="Invoice 2041.pdf"', text)

    def test_quick_reply_goes_to_whoever_reply_would_pick(self) -> None:
        text = self.run_json("compose", "--reply-to", "a2@x", "--body", "Thursday works.", "--dry-run")["message"]
        self.assertIn("To: Aarav Mehta <aarav@northwind.example>", text)
        self.assertIn("Subject: Re: Brand review", text)
        self.assertIn("In-Reply-To: <a2@x>", text)

    def test_new_email_with_attachment_copies_and_bcc(self) -> None:
        attachment = Path(self.home.name) / "notes.txt"
        attachment.write_text("hello")
        text = self.run_json("compose", "--to", "Rhea <rhea@studio.example>", "--cc", "ira@northwind.example",
                             "--bcc", "me2@example.com", "--subject", "Notes", "--attach", str(attachment),
                             "--body", "Attached.", "--dry-run")["message"]
        self.assertIn("To: Rhea <rhea@studio.example>", text)
        self.assertIn("Cc: ira@northwind.example", text)
        self.assertIn("Bcc: me2@example.com", text)  # msmtp sends to it and strips the header
        self.assertIn('filename="notes.txt"', text)

    def test_writing_to_nobody_is_refused(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mail.main(["compose", "--subject", "Hi", "--body", "x", "--dry-run"]), 1)
        self.assertEqual(json.loads(out.getvalue()), {"error": "Add someone to send it to."})

    def test_contacts_are_people_not_robots_or_you(self) -> None:
        found = [c["address"] for c in self.run_json("contacts")]
        self.assertEqual(found, ["aarav@northwind.example"])


class GmailActionsTest(unittest.TestCase):
    """The IMAP conversation courier_gmail has with Gmail, against a stand-in."""

    def setUp(self) -> None:
        # Folder names are cached under the state folder; keep that temporary.
        self.state = tempfile.TemporaryDirectory()
        self.env = unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.state.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.state.cleanup()

    class FakeImap:
        def __init__(self) -> None:
            self.calls: list[tuple] = []
            self.selected = None

        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
                          b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Bin"', b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"']

        def select(self, folder):
            self.selected = folder
            return "OK", [b"3"]

        def uid(self, command, *args):
            self.calls.append((command, *args))
            return ("OK", [b"11 12"]) if command == "SEARCH" else ("OK", [b""])

    def test_archive_removes_the_inbox_label(self) -> None:
        gmail = load("courier_gmail")
        imap = self.FakeImap()
        self.assertEqual(gmail.apply({"id": "p", "email": ME}, "archive", ["a@x", "b@y"], imap=imap), 2)
        self.assertEqual(imap.selected, '"[Gmail]/All Mail"')
        self.assertEqual(imap.calls, [("SEARCH", "X-GM-RAW", '"rfc822msgid:a@x OR rfc822msgid:b@y"'),
                                      ("STORE", "11,12", "-X-GM-LABELS", "(\\Inbox)")])

    def test_delete_moves_to_the_accounts_own_trash_and_back(self) -> None:
        gmail = load("courier_gmail")
        imap = self.FakeImap()
        gmail.apply({"id": "p", "email": ME}, "trash", ["a@x"], imap=imap)
        self.assertEqual(imap.calls[-1], ("MOVE", "11,12", '"[Gmail]/Bin"'))
        imap = self.FakeImap()
        gmail.apply({"id": "p", "email": ME}, "untrash", ["a@x"], imap=imap)
        self.assertEqual((imap.selected, imap.calls[-1]), ('"[Gmail]/Bin"', ("MOVE", "11,12", '"INBOX"')))

    def test_message_ids_cannot_widen_the_search(self) -> None:
        gmail = load("courier_gmail")
        imap = self.FakeImap()
        hostile = ["a)OR(in:inbox", "b\tOR\tlabel:inbox", "c}{in:anywhere", "d\\", "e:f@x", "g|h@x",
                   "\u00fcni@x", 'i"j@x', "k l@x", "m\r\nX@x"]
        gmail.find_uids(imap, ["ok.1+tag=x@mail.example", *hostile])
        self.assertEqual(imap.calls, [("SEARCH", "X-GM-RAW", '"rfc822msgid:ok.1+tag=x@mail.example"')])

    def test_a_search_matching_far_more_than_asked_changes_nothing(self) -> None:
        gmail = load("courier_gmail")

        class Greedy(self.FakeImap):
            def uid(self, command, *args):
                self.calls.append((command, *args))
                return ("OK", [b"1 2 3 4 5"]) if command == "SEARCH" else ("OK", [b""])

        imap = Greedy()
        with self.assertRaises(gmail.GmailError):
            gmail.apply({"id": "p", "email": ME}, "trash", ["a@x"], imap=imap)
        self.assertEqual([call[0] for call in imap.calls], ["SEARCH"])


INVITE = (
    "Message-ID: <invite@x>\nFrom: Aarav Mehta <aarav@northwind.example>\nTo: someone@example.com\n"
    "Subject: Invitation: Design review\nDate: Sat, 21 Nov 2026 10:24:00 +0530\nMIME-Version: 1.0\n"
    "Content-Type: multipart/mixed; boundary=b\n\n--b\nContent-Type: text/plain\n\nSee you tomorrow!\n"
    "--b\nContent-Type: text/calendar; method=REQUEST; charset=utf-8\n\n"
    "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:review-123@google.com\nSUMMARY:Design review\n"
    "DTSTART;TZID=Asia/Kolkata:20261122T113000\nDTEND;TZID=Asia/Kolkata:20261122T120000\n"
    "ORGANIZER;CN=Aarav Mehta:mailto:aarav@northwind.example\n"
    "ATTENDEE;CN=Sana Lal;ROLE=REQ-PARTICIPANT:mailto:sana@northwind.example\n"
    "ATTENDEE;CN=Jagrit:mailto:someone@example.com\n"
    "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij\nEND:VEVENT\nEND:VCALENDAR\n--b--\n"
).encode()


class SmartViewsTest(MailFixture):
    """The sidebar, the smart list and the panel beside an email."""

    NOW = 1795249800  # Sat 21 Nov 2026, 13:20 in India

    def setUp(self) -> None:
        super().setUp()
        self.later = load("courier_later")
        self.views = load("courier_views")
        for minute, number in enumerate((1429, 1430, 1431)):
            self.deliver(f"gh{number}", message(f"pr{number}@gh", "GitHub <notifications@github.com>", ME, f"[studio/app] Fix dock (PR #{number})",
                                                "Review.\n", f"Sat, 21 Nov 2026 09:0{minute}:00 +0530", "X-GitHub-Reason: review_requested\n"))
        self.deliver("inv", INVITE)
        sync.index(ACCOUNTS)

    def rows(self, folder: str, account: str = ""):
        index = mail.Index()
        try:
            listing = self.views.smart_list(index, folder, now=self.NOW, account=account)
        finally:
            index.close()
        return [row for section in listing["sections"] for row in section["rows"]], listing

    def test_machine_mail_folds_per_sender_per_day(self) -> None:
        rows, listing = self.rows("smart")
        github = next(row for row in rows if row["title"] == "GitHub")
        self.assertEqual(github["subtitle"], "3 pull requests need your review")
        self.assertEqual(github["chips"], ["#1431", "#1430", "+1"])
        self.assertEqual(len(github["members"]), 3)

    def test_lists_read_today_yesterday_earlier(self) -> None:
        # NOW is Sat 21 Nov 13:20: the GitHub and invite mail came today, the
        # rest on 19 and 20 Nov. One list holds them all, newest first.
        self.deliver("old", message("old@x", "Mira <mira@northwind.example>", ME, "Old plans", "Hi.\n", "Mon, 02 Nov 2026 09:00:00 +0530"))
        sync.index(ACCOUNTS)
        rows, listing = self.rows("all")
        self.assertEqual([section["name"] for section in listing["sections"]], ["Today", "Yesterday", "Earlier"])
        self.assertEqual(rows, sorted(rows, key=lambda row: -row["epoch"]))
        self.assertNotIn("tabs", listing)

    def test_meetings_read_their_invite(self) -> None:
        rows, _ = self.rows("meetings")
        self.assertEqual([(row["title"], row["subtitle"]) for row in rows], [("Design review", "Google Meet · Tomorrow, 11:30")])
        index = mail.Index()
        try:
            message, parsed = mail.find_message(index, "invite@x")
            meeting = self.views.meeting_of(parsed, [{"uid": "review-123@google.com", "link": "https://calendar.google.com/e"}], now=self.NOW)
        finally:
            index.close()
        self.assertEqual(meeting["when"], "Tomorrow, Sun 22 Nov · 11:30 – 12:00 (30 min)")
        self.assertEqual((meeting["provider"], meeting["link"]), ("Google Meet", "https://meet.google.com/abc-defg-hij"))
        self.assertEqual([a["name"] for a in meeting["attendees"]], ["Aarav Mehta", "Sana Lal", "Jagrit"])
        self.assertTrue(meeting["added"])
        self.assertEqual(meeting["eventLink"], "https://calendar.google.com/e")

    def test_snoozing_archives_now_and_brings_it_back_when_due(self) -> None:
        calls = []
        act = lambda action, ids, label="": calls.append((action, list(ids)))  # noqa: E731
        self.later.snooze(act, ["a2@x"], "2099-01-01T09:00", "Re: Brand review")
        self.assertEqual(calls, [("archive", ["a2@x"])])
        self.assertEqual([item["id"] for item in self.later.snoozed()], ["a2@x"])
        with unittest.mock.patch.object(self.later, "notify") as notify:
            report = self.later.tick(act, mail.Index, now=4102444800 + 3600)
        self.assertEqual(report["woke"], 1)
        self.assertEqual(calls[-1], ("inbox", ["a2@x"]))
        self.assertEqual(self.later.snoozed(), [])
        notify.assert_called_once()

    def test_reminders_and_retention_come_due(self) -> None:
        calls = []
        act = lambda action, ids, label="": calls.append((action, list(ids)))  # noqa: E731
        self.later.remind("a2@x", "2099-01-01T09:00", "Re: Brand review")
        self.later.set_retention("news@figma", "1w", "What's new")
        with unittest.mock.patch.object(self.later, "notify") as notify:
            self.assertEqual(self.later.tick(act, mail.Index, now=1000)["reminded"], 0)
            report = self.later.tick(act, mail.Index, now=4102444800 + 3600)
        self.assertEqual((report["reminded"], report["deleted"]), (1, 1))
        self.assertIn(("trash", ["news@figma"]), calls)
        notify.assert_called_once_with("Reminder", "Re: Brand review", "appointment-soon")

    def test_rules_never_cover_all_mail_and_wait_before_deleting(self) -> None:
        with self.assertRaises(self.later.LaterError):
            self.later.save_rule({"kind": "archive"})
        with self.assertRaises(self.later.LaterError):
            self.later.save_rule({"kind": "delete", "category": "newsletters", "afterDays": 0})
        rule = self.later.save_rule({"kind": "archive", "category": "newsletters", "afterDays": 0, "enabled": True})
        self.assertEqual(self.later.describe(rule), "Archive newsletters")
        calls = []
        act = lambda action, ids, label="": calls.append((action, list(ids)))  # noqa: E731
        self.later.tick(act, mail.Index, now=self.NOW)
        self.assertEqual(calls, [("archive", ["news@figma"])])
        # Rules run at most hourly.
        self.later.tick(act, mail.Index, now=self.NOW + 60)
        self.assertEqual(len(calls), 1)

    def test_busy_index_queues_the_change_for_sync(self) -> None:
        sync.queue_retag(["a2@x"], [], ["inbox"])
        sync.index(ACCOUNTS)
        self.assertNotIn("inbox", set(self.views_tags("a2@x")))
        self.assertEqual(list((sync.state_dir() / "retag").glob("*.json")), [])

    def views_tags(self, message_id: str):
        index = mail.Index()
        try:
            return set(index.db.find(message_id).tags)
        finally:
            index.close()

    def test_an_account_filter_keeps_other_accounts_out(self) -> None:
        mine, _ = self.rows("all", account="personal")
        other, _ = self.rows("all", account="work")
        self.assertTrue(mine)
        self.assertEqual(other, [])

    def test_details_beside_an_email(self) -> None:
        mail_json = self.run_json("message", "a2@x")
        details = mail_json["details"]
        self.assertEqual([t["id"] for t in details["thread"]], ["a1@x", "me1@x", "a2@x"])
        self.assertTrue(details["thread"][-1]["current"])
        self.assertEqual(details["category"], "people")
        self.assertTrue(details["toMe"])


class ConferenceLinkTest(unittest.TestCase):
    """The Join and Open event buttons only ever get a web link: the sender
    writes the invite, and Qt.openUrlExternally would open anything."""

    GOOD = b"X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij"

    def meeting(self, raw: bytes, events: list | None = None) -> dict:
        views = load("courier_views")
        parsed = email.message_from_bytes(raw, policy=email.policy.default)
        return views.meeting_of(parsed, events or [], now=SmartViewsTest.NOW)

    def invite(self, conference: str, description: str = "") -> bytes:
        line = f"X-GOOGLE-CONFERENCE:{conference}" + (f"\nDESCRIPTION:{description}" if description else "")
        return INVITE.replace(self.GOOD, line.encode())

    def test_only_web_links_reach_join(self) -> None:
        for bad in ("file:///etc/passwd", "smb://evil.example/share", "javascript:alert(1)", "steam://run/10",
                    "x-scheme-handler:open", "https://user:pw@evil.example/j", "https:///no-host", "data:text/html,hi",
                    "https://meet.example/\u0000x", "https://meet.example:99999/x"):
            self.assertEqual(self.meeting(self.invite(bad))["link"], "", bad)

    def test_a_bad_link_falls_back_to_a_meeting_link_in_the_text(self) -> None:
        meeting = self.meeting(self.invite("file:///etc/passwd", "Join at https://meet.google.com/xyz-abcd-efg"))
        self.assertEqual((meeting["link"], meeting["provider"]), ("https://meet.google.com/xyz-abcd-efg", "Google Meet"))

    def test_real_links_and_the_calendar_link_are_checked_too(self) -> None:
        self.assertEqual(self.meeting(INVITE)["link"], "https://meet.google.com/abc-defg-hij")
        teams = self.meeting(self.invite("http://teams.microsoft.com/l/meetup-join/19%3a1"))
        self.assertEqual(teams["link"], "http://teams.microsoft.com/l/meetup-join/19%3a1")
        event = self.meeting(INVITE, [{"uid": "review-123@google.com", "link": "file:///home/someone"}])
        self.assertEqual(event["eventLink"], "")


if __name__ == "__main__":
    unittest.main()
