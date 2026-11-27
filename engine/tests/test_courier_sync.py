"""courier-sync's local half: generated configs, indexing, lanes, inbox mirror.

Gmail itself is out of reach in tests; these drive a hand-built Maildir laid
out the way mbsync writes it. Run from the engine folder:
    python3 -m unittest discover tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("courier_sync", HERE.parent / "courier_sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

import notmuch2  # noqa: E402

ME = "someone@example.com"
WORK = "me@example.org"
ACCOUNTS = [{"id": "personal", "email": ME}, {"id": "work", "email": WORK}]
FOLDERS = {"personal": "[Gmail]/All Mail", "work": "[Gmail]/All Mail"}


def mail(message_id: str, sender: str, subject: str, extra: str = "") -> bytes:
    return (
        f"Message-ID: <{message_id}>\n"
        f"From: {sender}\n"
        f"To: {ME}\n"
        f"Subject: {subject}\n"
        "Date: Fri, 20 Nov 2026 10:40:00 +0530\n"
        f"{extra}"
        "\n"
        "Body.\n"
    ).encode()


class CourierSyncTest(unittest.TestCase):
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
        sync.configure(ACCOUNTS, FOLDERS)
        self.mail = sync.mail_dir()

    def tearDown(self) -> None:
        self.env.stop()
        self.home.cleanup()

    def deliver(self, folder: str, name: str, content: bytes, flags: str = "") -> Path:
        base = self.mail / folder
        for part in ("cur", "new", "tmp"):
            (base / part).mkdir(parents=True, exist_ok=True)
        path = base / "cur" / f"{name}:2,{flags}"
        path.write_bytes(content)
        return path

    def tags(self, message_id: str) -> set[str]:
        with notmuch2.Database() as db:
            return set(db.find(message_id).tags)

    def test_generated_configs_parse(self) -> None:
        rc = sync.config_dir() / "mbsyncrc"
        self.assertEqual(oct(rc.stat().st_mode & 0o777), "0o600")
        result = subprocess.run(["mbsync", "-c", str(rc), "-l", "no-such-channel"], capture_output=True, text=True)
        self.assertIn("No channel or group named", result.stdout + result.stderr)
        self.assertIn('Far :personal-remote:"[Gmail]/All Mail"', rc.read_text())
        self.assertIn("Sync PullNew PullUpgrade PullGone Flags", rc.read_text())
        self.assertNotIn("Expunge Both", rc.read_text())

    def test_drafts_are_pulled_only(self) -> None:
        sync.configure(ACCOUNTS, FOLDERS, {"personal": "[Gmail]/Drafts"})
        rc = sync.config_dir() / "mbsyncrc"
        text = rc.read_text()
        block = text.split("Channel personal-drafts", 1)[1].split("\n\n", 1)[0]
        self.assertIn('Far :personal-remote:"[Gmail]/Drafts"', block)
        self.assertIn("Near :personal-local:drafts", block)
        self.assertIn("Sync Pull\n", block)
        self.assertNotIn("Push", block)
        self.assertIn("Group personal\nChannel personal-inbox\nChannel personal-all\nChannel personal-drafts", text)
        self.assertNotIn("Channel work-drafts", text)  # Its Drafts folder isn't known yet.
        result = subprocess.run(["mbsync", "-c", str(rc), "-l", "no-such-channel"], capture_output=True, text=True)
        self.assertIn("No channel or group named", result.stdout + result.stderr)

    def test_a_draft_is_never_sent_mail(self) -> None:
        # Gmail keeps a draft in All Mail too, with only its \\Draft label;
        # the copy in Drafts is what says it is one.
        draft = mail("draft@me", f"Me <{ME}>", "Re: Viva", "In-Reply-To: <viva@ignou>\n")
        self.deliver("personal/all", "1", draft, "S")
        copy = self.deliver("personal/drafts", "1", draft, "S")
        sync.index(ACCOUNTS)
        self.assertIn("unsent", self.tags("draft@me"))
        self.assertNotIn("sent", self.tags("draft@me"))
        # Another sync changes nothing: notmuch doesn't take the tag away.
        sync.index(ACCOUNTS)
        self.assertIn("unsent", self.tags("draft@me"))
        # Sent (or discarded) in Gmail: the Drafts copy goes.
        copy.unlink()
        sync.index(ACCOUNTS)
        self.assertNotIn("unsent", self.tags("draft@me"))
        self.assertIn("sent", self.tags("draft@me"))

    def fake_mbsync(self, script: str) -> dict:
        folder = Path(self.home.name) / "fakebin"
        folder.mkdir(exist_ok=True)
        (folder / "mbsync").write_text("#!/bin/sh\n" + script)
        (folder / "mbsync").chmod(0o755)
        return {"PATH": f"{folder}{os.pathsep}{os.environ.get('PATH', '')}", "FAKE_ALL": str(self.mail / "personal" / "all")}

    def test_a_run_busy_removing_mail_is_not_cut_short(self) -> None:
        # Removals and flag changes bring no new files; only mbsync's journal
        # moves. That is progress, not a stall.
        (self.mail / "personal" / "all").mkdir(parents=True, exist_ok=True)
        env = self.fake_mbsync('for i in $(seq 1 22); do date +%s%N >> "$FAKE_ALL/.mbsyncstate.journal"; sleep 0.3; done\n')
        with unittest.mock.patch.dict(os.environ, env), unittest.mock.patch.object(sync, "STALL_TIMEOUT", 1.5), \
                unittest.mock.patch.object(sync, "POLL", 0.25, create=True):
            sync.run_mbsync("personal")

    def test_a_stalled_run_is_asked_to_stop_first(self) -> None:
        marker = Path(self.home.name) / "stopped"
        env = self.fake_mbsync(f"trap 'echo term > {marker}; exit 143' TERM\nsleep 30 &\nwait\n")
        with unittest.mock.patch.dict(os.environ, env), unittest.mock.patch.object(sync, "STALL_TIMEOUT", 0.5), \
                unittest.mock.patch.object(sync, "POLL", 0.25, create=True):
            with self.assertRaises(sync.SyncError):
                sync.run_mbsync("personal")
        self.assertEqual(marker.read_text(), "term\n")

    def test_index_sorts_lanes_and_mirrors_the_inbox(self) -> None:
        person = mail("aarav@x", "Aarav Mehta <aarav@northwind.studio>", "Brand review")
        inbox_copy = self.deliver("personal/inbox", "1", person)
        self.deliver("personal/all", "1", person)
        self.deliver("personal/all", "2", mail("pr@github", "GitHub <notifications@github.com>", "PR #42", "List-Id: studio/app <app.studio.github.com>\n"), "S")
        self.deliver("personal/all", "3", mail("news@figma", "Figma <hello@figma.com>", "What's new", "List-Unsubscribe: <mailto:u@figma.com>\n"))
        self.deliver("personal/all", "4", mail("sent@me", f"Me <{ME}>", "Re: Brand review"), "S")
        self.deliver("work/all", "5", mail("deploy@vercel", "Vercel <no-reply@vercel.com>", "Deployment ready"))

        counts = sync.index(ACCOUNTS)
        self.assertEqual(counts, {"personal": 4, "work": 1})

        self.assertEqual(self.tags("aarav@x"), {"people", "inbox", "unread", "account/personal"})
        self.assertEqual(self.tags("pr@github"), {"updates", "dev", "account/personal"})
        self.assertEqual(self.tags("news@figma"), {"newsletters", "dev", "unread", "account/personal"})
        self.assertEqual(self.tags("sent@me"), {"people", "sent", "account/personal"})
        self.assertEqual(self.tags("deploy@vercel"), {"updates", "dev", "unread", "account/work"})

        # Archived in Gmail: mbsync drops the inbox copy, the next run follows.
        inbox_copy.unlink()
        self.assertEqual(sync.index(ACCOUNTS), {"personal": 0, "work": 0})
        self.assertEqual(self.tags("aarav@x"), {"people", "unread", "account/personal"})

    def test_college_and_meeting_categories(self) -> None:
        self.deliver("personal/all", "1", mail("fee@ignou", "IGNOU <rcdelhi2@ignou.ac.in>", "Semester fee receipt"))
        invite = (
            "Message-ID: <invite@x>\nFrom: Aarav Mehta <aarav@northwind.studio>\nTo: someone@example.com\n"
            "Subject: Invitation: Design review\nDate: Sat, 21 Nov 2026 10:24:00 +0530\nMIME-Version: 1.0\n"
            "Content-Type: multipart/mixed; boundary=b\n\n--b\nContent-Type: text/plain\n\nSee you.\n"
            "--b\nContent-Type: text/calendar; method=REQUEST\n\nBEGIN:VCALENDAR\nEND:VCALENDAR\n--b--\n"
        ).encode()
        self.deliver("personal/all", "2", invite)
        sync.index(ACCOUNTS)
        self.assertIn("college", self.tags("fee@ignou"))
        self.assertIn("meeting", self.tags("invite@x"))
        self.assertNotIn("meeting", self.tags("fee@ignou"))

    def test_reading_in_courier_sets_the_seen_flag_mbsync_pushes(self) -> None:
        path = self.deliver("personal/all", "1", mail("aarav@x", "aarav@northwind.studio", "Hi"))
        sync.index(ACCOUNTS)
        with notmuch2.Database(mode=notmuch2.Database.MODE.READ_WRITE) as db:
            message = db.find("aarav@x")
            message.tags.discard("unread")
            message.tags.to_maildir_flags()
        self.assertFalse(path.exists())
        self.assertEqual([p.name for p in path.parent.iterdir()], ["1:2,S"])

    def test_lane_rules(self) -> None:
        me, wrote = {ME}, {"support@mega.example", "azure-noreply@microsoft.example"}

        def check(headers: dict, sender: str) -> str:
            return sync.lane(headers, sender, me, wrote)

        self.assertEqual(check({"To": "maya@studio.example"}, ME), "people")
        # Gmail's Unsubscribe button mails the list from you; that's no chat.
        self.assertEqual(check({"To": "unsub+x1@convertkit-mail.example", "Subject": "unsubscribe"}, ME), "updates")
        self.assertEqual(check({"To": "leave-123@lists.example"}, ME), "updates")
        self.assertEqual(check({"List-Id": "x"}, "notifications@github.com"), "updates")
        self.assertEqual(check({}, "bot@eu.linear.app"), "updates")
        self.assertEqual(check({"Precedence": "bulk"}, "noah@startup.example"), "newsletters")
        self.assertEqual(check({}, "donotreply@bank.example"), "updates")
        self.assertEqual(check({}, "account-security-noreply@microsoft.example"), "updates")
        self.assertEqual(check({}, "no_reply@communications.paypal.example"), "updates")
        # A reply once sent to a no-reply address doesn't make it a person.
        self.assertEqual(check({}, "azure-noreply@microsoft.example"), "updates")
        # Role addresses are a company, unless you've written to them.
        self.assertEqual(check({}, "hello@jobs.example"), "updates")
        self.assertEqual(check({}, "support@mega.example"), "people")
        # Their bulk mail stays a newsletter even though you've written to them.
        self.assertEqual(check({"List-Unsubscribe": "<mailto:u@mega.example>"}, "support@mega.example"), "newsletters")
        # Sending services give themselves away in their headers.
        self.assertEqual(check({"Feedback-ID": "1:2:3"}, "orders@shop.example"), "updates")
        self.assertEqual(check({"feedback-id": "1"}, "rahul@shop.example"), "updates")
        self.assertEqual(check({"Return-Path": "<bounce-77@mailer.esp.example>"}, "maya@studio.example"), "updates")
        self.assertEqual(check({"Return-Path": "<maya@studio.example>"}, "maya@studio.example"), "people")
        self.assertEqual(check({"Auto-Submitted": "auto-generated"}, "ops@studio.example"), "updates")
        self.assertEqual(check({}, "noah@friends.example"), "people")
        # Machine subdomains and a brand's own name in the mailbox.
        self.assertEqual(check({}, "teams@notifications.microsoft.example"), "updates")
        self.assertEqual(check({}, "microsoftanswers@microsoft.example"), "updates")
        self.assertEqual(check({}, "mailer@algo-one.example"), "updates")
        self.assertEqual(check({}, "student@mail.university.example"), "people")
        self.assertEqual(check({}, "maya@cs.university.example"), "people")

    def test_writing_to_someone_moves_their_mail_to_people(self) -> None:
        self.deliver("personal/all", "1", mail("ticket@mega", "Mega Support <support@mega.example>", "Your ticket"))
        sync.index(ACCOUNTS)
        self.assertIn("updates", self.tags("ticket@mega"))

        reply = (
            f"Message-ID: <reply@me>\nFrom: Me <{ME}>\nTo: support@mega.example\n"
            "Subject: Re: Your ticket\nDate: Fri, 20 Nov 2026 11:00:00 +0530\n\nThanks.\n"
        ).encode()
        self.deliver("personal/all", "2", reply, "S")
        sync.index(ACCOUNTS)
        self.assertEqual(self.tags("ticket@mega"), {"people", "unread", "account/personal"})
        self.assertEqual(self.tags("reply@me"), {"people", "sent", "account/personal"})

    def test_signed_out_account_is_reported_not_fatal(self) -> None:
        fake_auth = Path(self.home.name) / "fake-auth"
        fake_auth.write_text("#!/bin/sh\nexit 2\n")
        fake_auth.chmod(0o755)
        sync.write_private(sync.state_dir() / "folders.json", json.dumps(FOLDERS))
        # A finished sync starts courier-avatars.service; a stand-in systemctl
        # keeps this test from starting the real one on this PC.
        bin_dir = Path(self.home.name) / "bin"
        bin_dir.mkdir()
        asked = Path(self.home.name) / "systemctl.log"
        (bin_dir / "systemctl").write_text(f'#!/bin/sh\necho "$*" >> "{asked}"\n')
        (bin_dir / "systemctl").chmod(0o755)
        path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        with unittest.mock.patch.object(sync, "AUTH", fake_auth), unittest.mock.patch.dict(os.environ, {"PATH": path}):
            code = sync.main([])
        self.assertEqual(code, 2)
        self.assertEqual(asked.read_text(), "--user start --no-block courier-avatars.service\n")
        status = json.loads((sync.state_dir() / "sync.json").read_text())
        self.assertEqual(status["accounts"]["personal"]["state"], "signed-out")
        self.assertEqual(status["accounts"]["work"]["state"], "signed-out")


class NotificationTest(unittest.TestCase):
    """Desktop notifications carry other people's words (sender names,
    subjects, invite titles): never read as notify-send options, and never
    drawn as markup that loads something."""

    HOSTILE = "-u critical --icon=/etc/passwd <img src=https://t.example/p.png> ![x](https://t.example/q.png)"

    def sent(self, act) -> list[list[str]]:
        calls = []
        with unittest.mock.patch.dict(os.environ, {"COURIER_NO_NOTIFY": ""}), \
                unittest.mock.patch("subprocess.run", side_effect=lambda args, **kwargs: calls.append(list(args))):
            act()
        return [args for args in calls if args and args[0] == "notify-send"]

    def check(self, args: list[str], summary: str, body: str) -> None:
        self.assertIn("--", args)
        cut = args.index("--")
        self.assertEqual(len(args), cut + 3)
        self.assertEqual(args[cut + 1:], [summary, body])
        for text in args[cut + 1:]:
            self.assertFalse(set(text) & {"<", ">"}, text)
            self.assertNotIn("](", text)

    def test_new_mail(self) -> None:
        [args] = self.sent(lambda: sync.notify([(self.HOSTILE, self.HOSTILE)]))
        inert = "-u critical --icon=/etc/passwd \u2039img src=https://t.example/p.png\u203a ![x]\u200b(https://t.example/q.png)"
        self.check(args, inert, inert)

    def test_markdown_by_reference_and_new_lines(self) -> None:
        # An invite's place can hold new lines: a reference image needs one.
        [args] = self.sent(lambda: sync.desktop_notify("Meet", "in 5 min \u00b7 ![x][p]\n[p]: https://t.example/p.png\r\nend"))
        body = args[-1]
        self.assertNotIn("\n", body)
        self.assertNotIn("\r", body)
        self.assertNotIn("][", body)
        self.assertEqual(body, "in 5 min \u00b7 ![x]\u200b[p] [p]: https://t.example/p.png end")

    def test_reminders_and_snoozes(self) -> None:
        spec = importlib.util.spec_from_file_location("courier_later", HERE.parent / "courier_later.py")
        later = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(later)
        later.sync = sync
        [args] = self.sent(lambda: later.notify("-a Evil", "--app-name=x", "appointment-soon"))
        self.check(args, "-a Evil", "--app-name=x")


if __name__ == "__main__":
    unittest.main()
