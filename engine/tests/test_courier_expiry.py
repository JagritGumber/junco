"""Comprehensive unit & integration tests for Junco Mail Auto-Expiry.

Uses isolated temporary directories, temporary SQLite databases, hand-built
Maildirs, and mocked IMAP/action providers. Never touches real user data.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = load("courier_sync")
mail = load("courier_mail")
later = load("courier_later")
views = load("courier_views")
expiry = load("courier_expiry")
gmail = load("courier_gmail")

ME = "alex@demo.example"
ACCOUNTS = [{"id": "personal", "email": ME}]


def make_msg(
    message_id: str,
    sender: str,
    to: str,
    subject: str,
    body: str,
    date_hdr: str,
    extra: str = "",
) -> bytes:
    return (
        f"Message-ID: <{message_id}>\n"
        f"From: {sender}\n"
        f"To: {to}\n"
        f"Subject: {subject}\n"
        f"Date: {date_hdr}\n"
        f"{extra}"
        f"Content-Type: text/plain; charset=utf-8\n\n"
        f"{body}\n"
    ).encode()


class ExpiryUnitTest(unittest.TestCase):
    """Pure SQLite schema, parsing, classification, and rule CRUD tests."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "expiry.db"
        self.conn = expiry.open_db(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_schema_migration_idempotency_and_permissions(self) -> None:
        mode = stat.S_IMODE(self.db_path.stat().st_mode)
        self.assertEqual(mode, 0o600)

        rules = expiry.list_rules(self.conn)
        keys = {r["provider_key"] for r in rules}
        self.assertEqual(
            keys,
            {"github", "linear", "gitlab", "jira", "slack", "vercel", "stripe", "notion", "linkedin"},
        )
        # All built-in presets start OFF, 7d, notifications_only, skip_starred, trash
        for r in rules:
            self.assertFalse(r["enabled"])
            self.assertEqual(r["retention_days"], 7)
            self.assertTrue(r["notifications_only"])
            self.assertTrue(r["skip_starred"])
            self.assertEqual(r["action"], "trash")
            self.assertTrue(r["is_builtin"])

        # Modify one built-in rule and re-run init_db — user edits must be preserved
        expiry.save_rule(self.conn, {"provider_key": "github", "enabled": True, "retention_days": 14})
        expiry.init_db(self.conn)
        gh = expiry.get_rule(self.conn, "github")
        self.assertTrue(gh["enabled"])
        self.assertEqual(gh["retention_days"], 14)

        # Verify due query uses the partial index
        plan = [
            row["detail"]
            for row in self.conn.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT * FROM thread_expiries
                WHERE expires_at <= '2026-12-01T00:00:00Z'
                  AND executed_at IS NULL AND cancelled_at IS NULL
                ORDER BY expires_at ASC
                """
            ).fetchall()
        ]
        self.assertTrue(any("idx_thread_expiries_due" in step for step in plan), plan)

    def test_custom_rule_crud_and_builtin_delete_guard(self) -> None:
        created = expiry.save_rule(
            self.conn,
            {
                "display_name": "College Portal",
                "match_senders": "notices@college.edu, *.alerts.edu",
                "retention_days": 30,
                "enabled": True,
                "notifications_only": True,
                "skip_starred": True,
            },
        )
        self.assertTrue(created["provider_key"].startswith("custom:"))
        self.assertFalse(created["is_builtin"])
        self.assertEqual(created["match_senders"], ["notices@college.edu", "*.alerts.edu"])

        # Update custom rule
        updated = expiry.save_rule(self.conn, {"id": created["id"], "retention_days": 60})
        self.assertEqual(updated["retention_days"], 60)

        # Cannot delete built-in rule
        with self.assertRaises(expiry.ExpiryError):
            expiry.delete_rule(self.conn, "builtin:github")

        # Can delete custom rule
        res = expiry.delete_rule(self.conn, created["id"])
        self.assertEqual(res["deleted"], created["id"])
        self.assertIsNone(expiry.get_rule(self.conn, created["id"]))

    def test_duration_and_date_parsing(self) -> None:
        base = datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(expiry.parse_expiry_time("7d", base), base + timedelta(days=7))
        self.assertEqual(expiry.parse_expiry_time("14d", base), base + timedelta(days=14))
        self.assertEqual(expiry.parse_expiry_time("30d", base), base + timedelta(days=30))
        self.assertEqual(expiry.parse_expiry_time("6m", base), datetime(2027, 5, 27, 12, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(expiry.parse_expiry_time("1y", base), datetime(2027, 11, 27, 12, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(expiry.parse_expiry_time("2y", base), datetime(2028, 11, 27, 12, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(expiry.parse_expiry_time("3y", base), datetime(2029, 11, 27, 12, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(
            expiry.parse_expiry_time("2029-06-15", base),
            datetime(2029, 6, 15, 0, 0, 0, tzinfo=timezone.utc),
        )
        # Leap year clamping: 2028-02-29 + 1y -> 2029-02-28
        leap = datetime(2028, 2, 29, 9, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(expiry.parse_expiry_time("1y", leap), datetime(2029, 2, 28, 9, 0, 0, tzinfo=timezone.utc))

        # Reject past dates and invalid inputs
        with self.assertRaises(expiry.ExpiryError):
            expiry.parse_expiry_time("2020-01-01", base)
        with self.assertRaises(expiry.ExpiryError):
            expiry.parse_expiry_time("0d", base)
        with self.assertRaises(expiry.ExpiryError):
            expiry.parse_expiry_time("nonsense", base)

    def test_notification_classification_catches_bots_skips_humans(self) -> None:
        gh_rule = expiry.get_rule(self.conn, "github")
        linear_rule = expiry.get_rule(self.conn, "linear")
        jira_rule = expiry.get_rule(self.conn, "jira")
        linkedin_rule = expiry.get_rule(self.conn, "linkedin")

        # Real GitHub notification -> MATCH
        self.assertTrue(
            expiry.matches_rule(
                gh_rule,
                {"From": "GitHub <notifications@github.com>", "X-GitHub-Reason": "subscribed", "List-Id": "org/repo"},
                "notifications@github.com",
            )
        )
        # GitHub CI alert from non-standard local part WITH X-GitHub header -> MATCH
        self.assertTrue(
            expiry.matches_rule(
                gh_rule,
                {"From": "GitHub <builds@github.com>", "X-GitHub-Sender": "ci-bot"},
                "builds@github.com",
            )
        )
        # Personal 1-on-1 human email from a GitHub employee -> SKIP!
        self.assertFalse(
            expiry.matches_rule(
                gh_rule,
                {"From": "Priya <priya@github.com>", "Subject": "Coffee next week?"},
                "priya@github.com",
            )
        )
        # Personal 1-on-1 human reply from Linear employee -> SKIP!
        self.assertFalse(
            expiry.matches_rule(
                linear_rule,
                {"From": "Sam <sam@linear.app>", "Subject": "Re: Feedback"},
                "sam@linear.app",
            )
        )
        # Spoofed X-GitHub header from unrelated domain -> SKIP!
        self.assertFalse(
            expiry.matches_rule(
                gh_rule,
                {"From": "Attacker <bot@evil.example>", "X-GitHub-Reason": "mention"},
                "bot@evil.example",
            )
        )
        # Jira wildcard subdomain -> MATCH
        self.assertTrue(
            expiry.matches_rule(
                jira_rule,
                {"From": "Jira <jira@acme.atlassian.net>", "Auto-Submitted": "auto-generated"},
                "jira@acme.atlassian.net",
            )
        )
        # LinkedIn *-noreply pattern -> MATCH
        self.assertTrue(
            expiry.matches_rule(
                linkedin_rule,
                {"From": "LinkedIn <jobalerts-noreply@linkedin.com>", "Precedence": "bulk"},
                "jobalerts-noreply@linkedin.com",
            )
        )

    def test_manual_schedule_crud_and_precedence(self) -> None:
        now = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
        # Create a 2-year manual schedule with note "college"
        item = expiry.set_thread_expiry(
            self.conn,
            "t-college-01",
            after="2y",
            note="college",
            subject="Semester 5 Exam Schedule",
            sender="registrar@uni.edu",
            now=now,
        )
        self.assertEqual(item["source"], "manual")
        self.assertEqual(item["note"], "college")
        self.assertEqual(item["action"], "trash")
        self.assertEqual(item["expires_at"], "2028-11-27T10:00:00Z")
        self.assertEqual(item["remaining"], "2y")

        # Rule attempt MUST NOT override active manual schedule
        kept = expiry.set_thread_expiry(
            self.conn,
            "t-college-01",
            after="7d",
            source="rule:github",
            now=now,
        )
        self.assertEqual(kept["source"], "manual")
        self.assertEqual(kept["expires_at"], "2028-11-27T10:00:00Z")
        self.assertEqual(kept["note"], "college")

        # Edit manual schedule to 3 years
        edited = expiry.set_thread_expiry(
            self.conn, "t-college-01", after="3y", note="college-archive", now=now
        )
        self.assertEqual(edited["expires_at"], "2029-11-27T10:00:00Z")
        self.assertEqual(edited["note"], "college-archive")

        # Listing active expiries includes it
        active = expiry.list_expiries(self.conn, now=now)
        self.assertEqual([a["thread_id"] for a in active], ["t-college-01"])

        # Cancel it
        cancelled = expiry.cancel_thread_expiry(self.conn, "t-college-01", now=now)
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(expiry.list_expiries(self.conn, now=now), [])
        self.assertEqual(len(expiry.list_expiries(self.conn, include_inactive=True, now=now)), 1)


class ExpiryIntegrationTest(unittest.TestCase):
    """Full Maildir + notmuch + sync + tick + CLI + IMAP mock integration tests."""

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        root = Path(self.home.name)
        self.env = unittest.mock.patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "COURIER_NO_NOTIFY": "1",
            },
        )
        self.env.start()
        (root / "config" / "courier").mkdir(parents=True)
        (root / "config" / "courier" / "accounts.json").write_text(json.dumps({"accounts": ACCOUNTS}))
        sync.configure(ACCOUNTS, {"personal": "[Gmail]/All Mail"})

        # 1. Old GitHub notification (10 days old relative to Nov 27 -> due under 7d rule)
        self.deliver(
            "gh_old",
            make_msg(
                "gh-old@github.com",
                "GitHub <notifications@github.com>",
                ME,
                "[org/app] CI failed on main (#401)",
                "Workflow failed.",
                "Tue, 17 Nov 2026 09:00:00 +0000",
                "X-GitHub-Reason: ci_activity\nList-Id: org/app <app.org.github.com>\n",
            ),
            "S",
        )
        # 2. Recent GitHub notification (2 days old -> expires in 5d under 7d rule)
        self.deliver(
            "gh_recent",
            make_msg(
                "gh-recent@github.com",
                "GitHub <notifications@github.com>",
                ME,
                "[org/app] Review requested on PR #412",
                "Please review.",
                "Wed, 25 Nov 2026 09:00:00 +0000",
                "X-GitHub-Reason: review_requested\nList-Id: org/app <app.org.github.com>\n",
            ),
        )
        # 3. Starred GitHub notification (12 days old, flagged -> MUST be protected!)
        self.deliver(
            "gh_starred",
            make_msg(
                "gh-starred@github.com",
                "GitHub <notifications@github.com>",
                ME,
                "[org/app] Release v2.0 checklist (#390)",
                "Important release notes.",
                "Sun, 15 Nov 2026 09:00:00 +0000",
                "X-GitHub-Reason: mention\nList-Id: org/app <app.org.github.com>\n",
            ),
            "FS",
        )
        # 4. Direct 1-on-1 personal human email from a GitHub employee (MUST NOT match!)
        self.deliver(
            "gh_human",
            make_msg(
                "gh-human@github.com",
                "Maya Chen <maya@github.com>",
                ME,
                "Lunch after the meetup?",
                "Hey, want to grab coffee?",
                "Mon, 16 Nov 2026 11:00:00 +0000",
            ),
            "S",
        )
        # 5. College email (for 2-year manual schedule)
        self.deliver(
            "college_1",
            make_msg(
                "college-1@uni.edu",
                "Registrar <registrar@uni.edu>",
                ME,
                "Fall 2026 Transcript & Fee Receipt",
                "Keep this for your records.",
                "Thu, 26 Nov 2026 10:00:00 +0000",
            ),
            "S",
        )
        sync.index(ACCOUNTS)

    def tearDown(self) -> None:
        self.env.stop()
        self.home.cleanup()

    def deliver(self, name: str, content: bytes, flags: str = "", inbox: bool = True) -> None:
        for folder in ("all", "inbox") if inbox else ("all",):
            base = sync.mail_dir() / "personal" / folder
            for part in ("cur", "new", "tmp"):
                (base / part).mkdir(parents=True, exist_ok=True)
            (base / "cur" / f"{name}:2,{flags}").write_bytes(content)

    def thread_id_of(self, message_id: str) -> str:
        idx = mail.Index()
        try:
            return idx.db.find(message_id).threadid
        finally:
            idx.close()

    def run_mail_json(self, *args: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mail.main(list(args))
        self.assertEqual(code, 0, out.getvalue())
        return json.loads(out.getvalue())

    def test_preview_rule_and_dry_run_vs_execute_and_starred_recheck(self) -> None:
        now = datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc)
        conn = expiry.open_db()
        try:
            # Preview GitHub rule before enabling: catches gh_old + gh_recent,
            # skips gh_starred (starred) and gh_human (personal human email).
            idx = mail.Index()
            try:
                prev = expiry.preview_rule(conn, idx, "github", now=now)
            finally:
                idx.close()
            self.assertEqual(prev["match_count"], 2)
            self.assertEqual(prev["due_now_count"], 1)
            self.assertEqual(prev["skipped_starred"], 1)
            matched_mids = {item["message_id"] for item in prev["sample"]}
            self.assertEqual(matched_mids, {"gh-old@github.com", "gh-recent@github.com"})

            # Enable GitHub rule (7 days) and apply to existing threads
            expiry.save_rule(conn, {"provider_key": "github", "enabled": True, "retention_days": 7}, now=now)
            idx = mail.Index()
            try:
                applied = expiry.apply_rule_to_existing(conn, idx, "github", now=now)
            finally:
                idx.close()
            self.assertEqual(applied["scheduled"], 2)
            self.assertEqual(applied["skipped_starred"], 1)

            # Dry-run preview of due items: reports gh_old without deleting!
            idx = mail.Index()
            try:
                due_preview = expiry.preview_due(conn, index=idx, now=now)
            finally:
                idx.close()
            self.assertTrue(due_preview["dry_run"])
            self.assertEqual(due_preview["due_count"], 1)
            self.assertEqual(due_preview["items"][0]["status"], "would_execute")
            self.assertEqual(due_preview["items"][0]["message_ids"], ["gh-old@github.com"])

            # Now simulate the user starring gh-old BEFORE sweep executes!
            mail.mark("star", ["gh-old@github.com"])

            calls: list[tuple[str, list[str]]] = []
            report = expiry.sweep_due(
                conn,
                lambda action, ids: calls.append((action, list(ids))),
                open_index=mail.Index,
                dry_run=False,
                now=now,
                force=True,
            )
            self.assertEqual(calls, [])
            self.assertEqual(report["executed_count"], 0)
            self.assertEqual(report["skipped_starred"], 1)
            audit = expiry.list_audit_log(conn)
            self.assertEqual(audit[0]["action"], "skipped_starred")

            # Advance clock 6 days: gh_recent is now due (was 2d old + 6d = 8d > 7d) -> trashed!
            later_now = now + timedelta(days=6)
            report2 = expiry.sweep_due(
                conn,
                lambda action, ids: calls.append((action, list(ids))),
                open_index=mail.Index,
                dry_run=False,
                now=later_now,
                force=True,
            )
            self.assertEqual(report2["executed_count"], 1)
            self.assertEqual(report2["trashed_messages"], 1)
            self.assertEqual(calls, [("trash", ["gh-recent@github.com"])])

            # Audit log recorded the trash execution
            audit2 = expiry.list_audit_log(conn)
            self.assertEqual(audit2[0]["action"], "trash")
            self.assertEqual(audit2[0]["message_count"], 1)

            # Running again immediately does NOT re-execute
            report3 = expiry.sweep_due(
                conn,
                lambda action, ids: calls.append((action, list(ids))),
                open_index=mail.Index,
                dry_run=False,
                now=later_now + timedelta(hours=2),
                force=True,
            )
            self.assertEqual(report3["due_count"], 0)
            self.assertEqual(len(calls), 1)
        finally:
            conn.close()

    def test_sync_hook_applies_rules_and_respects_manual_override(self) -> None:
        conn = expiry.open_db()
        try:
            expiry.save_rule(conn, {"provider_key": "github", "enabled": True, "retention_days": 7})
            # Set manual 2y schedule on gh_recent first
            gh_recent_tid = self.thread_id_of("gh-recent@github.com")
            expiry.set_thread_expiry(conn, gh_recent_tid, after="2y", note="keep-pr")
        finally:
            conn.close()

        # Deliver a brand-new GitHub notification AND a reply to gh_recent, then sync.index()
        self.deliver(
            "gh_fresh",
            make_msg(
                "gh-fresh@github.com",
                "GitHub <notifications@github.com>",
                ME,
                "[org/app] Dependabot bump (#500)",
                "Automated PR.",
                "Fri, 27 Nov 2026 08:00:00 +0000",
                "X-GitHub-Reason: subscribed\nList-Id: org/app <app.org.github.com>\n",
            ),
        )
        self.deliver(
            "gh_recent_reply",
            make_msg(
                "gh-recent-2@github.com",
                "GitHub <notifications@github.com>",
                ME,
                "Re: [org/app] Review requested on PR #412",
                "New comment.",
                "Fri, 27 Nov 2026 09:00:00 +0000",
                "In-Reply-To: <gh-recent@github.com>\nX-GitHub-Reason: comment\nList-Id: org/app <app.org.github.com>\n",
            ),
        )
        sync.index(ACCOUNTS)

        conn = expiry.open_db()
        try:
            fresh_tid = self.thread_id_of("gh-fresh@github.com")
            fresh_exp = expiry.get_thread_expiry(conn, fresh_tid)
            self.assertIsNotNone(fresh_exp)
            self.assertEqual(fresh_exp["source"], "rule:github")
            # expires_at = 2026-11-27T08:00:00Z + 7 days = 2026-12-04T08:00:00Z
            self.assertEqual(fresh_exp["expires_at"], "2026-12-04T08:00:00Z")

            # Manual schedule on gh_recent was NOT overridden by the new reply!
            manual_exp = expiry.get_thread_expiry(conn, gh_recent_tid)
            self.assertEqual(manual_exp["source"], "manual")
            self.assertEqual(manual_exp["note"], "keep-pr")
        finally:
            conn.close()

    def test_hourly_idle_throttle_and_tick_piggyback(self) -> None:
        now = datetime(2026, 11, 27, 12, 0, 0, tzinfo=timezone.utc)
        conn = expiry.open_db()
        try:
            college_tid = self.thread_id_of("college-1@uni.edu")
            # Schedule due in 30 minutes
            expiry.set_thread_expiry(
                conn, college_tid, expires_at=now + timedelta(minutes=30), note="short-test", now=now
            )
            calls: list[tuple[str, list[str]]] = []

            # First tick at T=0: nothing due yet, records last_sweep_at = T=0
            r1 = expiry.sweep_due(conn, lambda a, ids: calls.append((a, ids)), open_index=mail.Index, now=now, force=False)
            self.assertFalse(r1["throttled"])
            self.assertEqual(r1["due_count"], 0)

            # Second tick at T+45m: throttled (< 1 hour since last sweep), zero DB/notmuch work
            r2 = expiry.sweep_due(
                conn,
                lambda a, ids: calls.append((a, ids)),
                open_index=mail.Index,
                now=now + timedelta(minutes=45),
                force=False,
            )
            self.assertTrue(r2["throttled"])
            self.assertEqual(calls, [])

            # Third tick via courier_later.tick() at T+65m: > 1 hour -> sweeps & trashes!
            tick_report = later.tick(
                lambda action, ids, label="": calls.append((action, list(ids))),
                mail.Index,
                now=(now + timedelta(minutes=65)).timestamp(),
            )
            self.assertEqual(tick_report["expired"], 1)
            self.assertEqual(calls, [("trash", ["college-1@uni.edu"])])
        finally:
            conn.close()

    def test_cli_views_and_bin_courier_expiry(self) -> None:
        college_tid = self.thread_id_of("college-1@uni.edu")

        # CLI via courier_mail.py expiry ...
        rules_res = self.run_mail_json("expiry", "rules", "--with-counts")
        gh = next(r for r in rules_res["rules"] if r["provider_key"] == "github")
        self.assertEqual(gh["match_count"], 2)

        set_res = self.run_mail_json("expiry", "set", college_tid, "--after", "2y", "--note", "college")
        self.assertEqual(set_res["source"], "manual")
        self.assertEqual(set_res["note"], "college")
        self.assertEqual(set_res["remaining"], "2y")

        # Views expose expiring count, row expiry pill, and reader expiry metadata
        folders_res = self.run_mail_json("folders")
        exp_folder = next(f for f in folders_res["folders"] if f["id"] == "expiring")
        self.assertEqual(exp_folder["count"], 1)

        exp_list = self.run_mail_json("list", "expiring")
        rows = [row for sec in exp_list["sections"] for row in sec["rows"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["expiry"]["note"], "college")

        msg_view = self.run_mail_json("message", "college-1@uni.edu")
        self.assertIsNotNone(msg_view["expiry"])
        self.assertEqual(msg_view["expiry"]["note"], "college")
        self.assertEqual(msg_view["details"]["expiry"]["note"], "college")

        # CLI via bin/courier expiry ...
        proc = subprocess.run(
            [str(ROOT / "bin" / "courier"), "expiry", "list"],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=True,
        )
        listed = json.loads(proc.stdout)
        self.assertEqual(len(listed["items"]), 1)
        self.assertEqual(listed["items"][0]["note"], "college")

        # Dry-run via bin/courier expiry run --dry-run
        dry = subprocess.run(
            [str(ROOT / "bin" / "courier"), "expiry", "run", "--dry-run"],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertTrue(json.loads(dry.stdout)["dry_run"])

        # Cancel via CLI
        cancel_res = self.run_mail_json("expiry", "cancel", college_tid)
        self.assertTrue(cancel_res["cancelled"])
        self.assertEqual(self.run_mail_json("expiry", "list")["items"], [])

    def test_opt_in_permanent_delete_imap_action(self) -> None:
        class FakeImap:
            def __init__(self) -> None:
                self.calls: list[tuple] = []
                self.selected = None

            def list(self):
                return "OK", [
                    b'(\\HasNoChildren) "/" "INBOX"',
                    b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
                    b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"',
                ]

            def select(self, folder):
                self.selected = folder
                return "OK", [b"1"]

            def uid(self, command, *args):
                self.calls.append((command, *args))
                return ("OK", [b"42"]) if command == "SEARCH" else ("OK", [b""])

            def expunge(self):
                self.calls.append(("EXPUNGE",))
                return "OK", [b""]

        imap = FakeImap()
        count = gmail.apply({"id": "personal", "email": ME}, "delete", ["gh-old@github.com"], imap=imap)
        self.assertEqual(count, 1)
        self.assertIn(("MOVE", "42", '"[Gmail]/Trash"'), imap.calls)
        self.assertIn(("STORE", "42", "+FLAGS.SILENT", "(\\Deleted)"), imap.calls)
        self.assertIn(("EXPUNGE",), imap.calls)


if __name__ == "__main__":
    unittest.main()
