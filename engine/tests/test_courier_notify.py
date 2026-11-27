"""Notifications written from an email's fields (courier_notify.py): the
text per kind, the rules file, grouping, silent kinds, bursts, the D-Bus
payload and the buttons. Made-up mail only, and nothing reaches a desktop:
the sender is a stand-in and the bus a fake."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import types
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def load(name: str):
    """A private copy of an engine module, under a name of its own (its
    dataclasses look themselves up in sys.modules), so no other test's
    module is replaced."""
    private = f"_test_notify_{name}"
    spec = importlib.util.spec_from_file_location(private, HERE.parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[private] = module
    spec.loader.exec_module(module)
    return module


cn = load("courier_notify")
T0 = 1_790_000_000.0

import courier_github  # noqa: E402  (the one courier_notify imports when it reads or acts)


def _no_process(*args, **kwargs):
    raise AssertionError(f"a test tried to run {args[0] if args else kwargs.get('args')!r}")


# Nothing a test does reaches GitHub or systemd: gh can't run, and reading
# GitHub after a sync is only recorded (start_enrich).
_guards = [unittest.mock.patch.object(courier_github, "subprocess", types.SimpleNamespace(run=_no_process, TimeoutExpired=TimeoutError)),
           unittest.mock.patch.object(cn, "start_enrich"),
           # Nor the keyring: whether Junco may answer invites is a stand-in.
           unittest.mock.patch.object(cn, "calendar_writable", lambda account: False)]


def setUpModule() -> None:
    for guard in _guards:
        guard.start()


def tearDownModule() -> None:
    for guard in _guards:
        guard.stop()


def mail(subject: str, text: str = "", sender: str = "Priya Natarajan <notifications@github.com>", at: float = T0, n: int = 1,
         github: dict | None = None):
    """A made-up email; `github` is its X-GitHub-* headers (Reason, Sender,
    Recipient), as GitHub sets them."""
    import email.message

    parsed = email.message.EmailMessage()
    for name, value in (github or {}).items():
        parsed[f"X-GitHub-{name}"] = value
    return types.SimpleNamespace(id=f"m{n}@example.test", account="personal", sender=sender, address="notifications@github.com",
                                 subject=subject, text=text, epoch=at, parsed=parsed)


def note(kind: str, values: dict, subject: str, text: str = "", at: float = T0, n: int = 1, github: dict | None = None,
         sender: str = "Priya Natarajan <notifications@github.com>", **extra):
    template = {"kind": kind, "name": "A template", "builtin": True} | extra
    return cn.note_for(mail(subject, text, sender, at=at, n=n, github=github), template, {"status": "ok", "values": values})


def comment(n: int, at: float, who: str = "priya", number: int = 274, reason: str = "author", kind: str = "comment"):
    """A comment by `who` on PR #number; reason "author": the PR is yours."""
    return note(kind, {"author": who, "repo": "lumenlabs/lumen-app", "number": str(number), "title": "Team invites",
                       "link": f"https://github.com/lumenlabs/lumen-app/pull/{number}#issuecomment-{n}"},
                f"Re: [lumenlabs/lumen-app] Team invites (PR #{number})",
                f"{who} left a comment (lumenlabs/lumen-app#{number})\n\nComment number {n}.\n\n-- \nReply to this email directly",
                at=at, n=n, github={"Reason": reason, "Sender": who, "Recipient": "alex"},
                sender=f"{who} <notifications@github.com>")


class Recorder:
    """A Dispatcher's send(): numbers notifications, keeps what was asked."""

    def __init__(self) -> None:
        self.calls = []
        self.next = 0

    def __call__(self, note, title, body, urgency, replaces):
        self.calls.append({"title": title, "body": body, "urgency": urgency, "replaces": replaces, "note": note})
        if replaces:
            return replaces
        self.next += 1
        return self.next


class Text(unittest.TestCase):
    def test_ci_failed(self) -> None:
        got = note("ci-failed", {"repo": "lumenlabs/lumen-app", "workflow": "CI", "status": "Run failed", "branch": "main",
                                 "commit": "4f2a9c1", "jobs": ["build", "test", "lint"],
                                 "results": ["Succeeded in 40 seconds", "Failed in 2 minutes", "Failed in 12 seconds"],
                                 "link": "https://github.com/lumenlabs/lumen-app/actions/runs/1"},
                   "[lumenlabs/lumen-app] Run failed: CI - main (4f2a9c1)")
        self.assertEqual(got.title, "CI failed · lumen-app · main")
        self.assertEqual(got.body, "test, lint failed · 4f2a9c1")

    def test_ci_cancelled_and_passed(self) -> None:
        cancelled = note("ci-failed", {"repo": "o/r", "workflow": "Deploy", "status": "Run cancelled", "branch": "main"},
                         "[o/r] Run cancelled: Deploy - main (4f2a9c1)")
        self.assertEqual(cancelled.title, "Deploy cancelled · r · main")
        passed = note("ci-failed", {"repo": "o/r", "workflow": "CI", "status": "Run succeeded", "branch": "main"},
                      "[o/r] Run succeeded: CI - main (4f2a9c1)")
        self.assertEqual(passed.kind, "ci-passed")

    def test_review_requested(self) -> None:
        got = note("review-requested", {"author": "@priya", "ref": "lumenlabs/lumen-app#274", "repo": "lumenlabs/lumen-app",
                                        "number": "274", "title": "Team invites"},
                   "Re: [lumenlabs/lumen-app] Team invites (PR #274)")
        self.assertEqual(got.title, "Review requested · PR #274 · by Priya Natarajan")
        self.assertEqual(got.body, "lumen-app: Team invites")

    def test_comment_first_line(self) -> None:
        got = comment(1, T0)
        self.assertEqual(got.title, "@priya commented on PR #274 · lumen-app")
        self.assertEqual(got.body, "Comment number 1.")
        self.assertEqual(got.group, "comments:lumenlabs/lumen-app:PR #274")

    def test_excerpt_skips_markup_quotes_and_footer(self) -> None:
        text = ("bot left a comment (o/r#1)\n\n<!-- hidden -->\n<details>\n> quoted\n## Summary of changes\n"
                "-- \nReply to this email directly")
        self.assertEqual(cn.excerpt(text, (r"left a comment \([^)]*\)$",)), "Summary of changes")
        self.assertEqual(cn.excerpt("-- \nReply to this email directly"), "")

    def test_review_push_state(self) -> None:
        review = note("review", {"author": "@priya", "action": "approved", "repo": "o/lumen-app", "number": "274", "title": "T"},
                      "Re: [o/lumen-app] T (PR #274)")
        self.assertEqual(review.title, "Priya Natarajan approved PR #274")
        push = note("push", {"author": "@dkim", "count": "3", "hashes": ["a1b2c3d", "b2c3d4e", "c3d4e5f"],
                             "messages": ["Fix the thing", "Tidy", "Tests"], "repo": "o/lumen-app", "number": "1471", "title": "T"},
                    "Re: [o/lumen-app] T (PR #1471)")
        self.assertEqual(push.title, "@dkim pushed 3 commits to PR #1471 · lumen-app")
        self.assertEqual(push.body, "Fix the thing (+2 more)")
        state = note("state", {"action": "Merged", "number": "182", "repo": "o/r", "title": "T"}, "Re: [o/r] T (PR #182)")
        self.assertEqual(state.title, "PR #182 merged by Priya Natarajan")

    def test_unreadable_falls_back_to_sender_and_subject(self) -> None:
        got = cn.note_for(mail("[o/r] Something new (PR #3)"), {"kind": "comment"}, {"status": "reteach", "values": {}})
        self.assertEqual((got.title, got.body), ("Priya Natarajan", "[o/r] Something new (PR #3)"))

    def test_taught_template(self) -> None:
        got = note("taught", {"order": "#1182", "total": "$40", "link": "https://shop.example/o/1182"}, "Your order",
                   name="Shop orders")
        self.assertEqual(got.title, "Shop orders")
        self.assertEqual(got.body, "order: #1182 · total: $40")
        self.assertEqual(got.link_label, "Open link")


class Rules(unittest.TestCase):
    def test_quiet_is_the_default(self) -> None:
        rules = cn.load_rules(Path("/nonexistent/notify-rules.json"))
        self.assertEqual(rules["profile"], "quiet")
        self.assertEqual(cn.rule_for(rules, "ci-failed")["urgency"], "critical")
        self.assertEqual(cn.rule_for(rules, "security-advisory")["urgency"], "critical")
        self.assertEqual(cn.rule_for(rules, "review-requested")["urgency"], "normal")
        for kind in ("push", "ci-passed", "state", "commit-comment", "dependabot-digest", "account-notice", "something-else"):
            self.assertEqual(cn.rule_for(rules, kind)["urgency"], "silent", kind)
        comment = cn.rule_for(rules, "comment")
        self.assertEqual((comment["reasons"], comment["bots"], comment["self"], comment["otherwise"]),
                         (["author"], "silent", "silent", "silent"))
        self.assertTrue(comment["group"])

    def test_all_profile(self) -> None:
        rules = cn.profile_rules("all")
        self.assertEqual(cn.rule_for(rules, "push")["urgency"], "silent")
        self.assertTrue(cn.rule_for(rules, "comment")["group"])
        self.assertEqual(cn.rule_for(rules, "something-else"), {"urgency": "normal", "group": False})

    def test_file_picks_a_profile(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notify-rules.json"
            path.write_text(json.dumps({"profile": "all"}))
            self.assertEqual(cn.load_rules(path)["profile"], "all")
            path.write_text(json.dumps({"profile": "loud"}))
            with unittest.mock.patch("sys.stderr"):
                self.assertEqual(cn.load_rules(path)["profile"], "quiet")

    def test_quiet_with_changes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notify-rules.json"
            path.write_text(json.dumps({"bot_logins": ["@Deploy-App", 3], "kinds": {
                "comment": {"reasons": ["author", "Mention"], "bots": "low"}, "issue-comment": {"reasons": None},
                "review": {"reasons": "author", "self": "loud"}}}))
            with unittest.mock.patch("sys.stderr"):
                rules = cn.load_rules(path)
        self.assertEqual(rules["bot_logins"], ["deploy-app"])
        self.assertEqual(cn.rule_for(rules, "comment")["reasons"], ["author", "mention"])
        self.assertEqual(cn.rule_for(rules, "comment")["bots"], "low")
        self.assertNotIn("reasons", cn.rule_for(rules, "issue-comment"))
        self.assertEqual(cn.rule_for(rules, "review")["reasons"], ["author"])  # a bad value keeps the profile's
        self.assertEqual(cn.rule_for(rules, "review")["self"], "silent")

    def test_file_changes_rules_and_bad_values_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notify-rules.json"
            path.write_text(json.dumps({"profile": "all", "window": 60, "kinds": {"push": {"urgency": "normal"}, "review": {"group": True},
                                                                 "comment": {"urgency": "loud", "group": "yes"}}}))
            with unittest.mock.patch("sys.stderr"):
                rules = cn.load_rules(path)
        self.assertEqual(rules["window"], 60)
        self.assertEqual(cn.rule_for(rules, "push")["urgency"], "normal")
        self.assertTrue(cn.rule_for(rules, "review")["group"])
        self.assertEqual(cn.rule_for(rules, "comment"), {"urgency": "normal", "group": True})

    def test_broken_file_means_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notify-rules.json"
            path.write_text("{not json")
            with unittest.mock.patch("sys.stderr"):
                self.assertEqual(cn.load_rules(path), cn.load_rules(Path(folder) / "missing.json"))


class Dispatching(unittest.TestCase):
    """How notifications group, go silent and fold, under the "all" profile."""

    def dispatcher(self, rules=None, state=None, most=cn.MOST):
        send = Recorder()
        return cn.Dispatcher(rules or cn.profile_rules("all"), state if state is not None else {}, send, T0, most), send

    def test_comments_on_one_pr_update_one_notification(self) -> None:
        dispatcher, send = self.dispatcher()
        events = [dispatcher.dispatch(comment(1, T0 - 200)), dispatcher.dispatch(comment(2, T0 - 140, "dkim")),
                  dispatcher.dispatch(comment(3, T0))]
        dispatcher.finish()
        self.assertEqual([e.action for e in events], ["popup", "update", "update"])
        self.assertEqual({e.id for e in events}, {1})
        # One popup, then one replacement for both updates in this sync.
        self.assertEqual([c["replaces"] for c in send.calls], [0, 1])
        self.assertEqual(send.calls[-1]["title"], "3 new comments on PR #274 · lumen-app")
        self.assertEqual(events[-1].title, "3 new comments on PR #274 · lumen-app")
        self.assertEqual(events[-1].body, "@priya, @dkim: Comment number 3.")
        # Opening or marking the group acts on all three.
        self.assertEqual(dispatcher.state["sent"]["1"]["ids"], ["m1@example.test", "m2@example.test", "m3@example.test"])

    def test_past_the_window_or_another_pr_starts_afresh(self) -> None:
        dispatcher, _ = self.dispatcher()
        first = dispatcher.dispatch(comment(1, T0 - 400))
        later = dispatcher.dispatch(comment(2, T0 - 99))
        other = dispatcher.dispatch(comment(3, T0 - 98, number=275))
        self.assertEqual([first.action, later.action, other.action], ["popup", "popup", "popup"])
        self.assertEqual(len({first.id, later.id, other.id}), 3)

    def test_same_named_repos_are_different_groups(self) -> None:
        dispatcher, _ = self.dispatcher()
        mine = comment(1, T0 - 10)
        fork = note("comment", {"author": "x", "repo": "someone/lumen-app", "number": "274", "title": "T"},
                    "Re: [someone/lumen-app] T (PR #274)", at=T0 - 5, n=2)
        self.assertEqual([dispatcher.dispatch(mine).action, dispatcher.dispatch(fork).action], ["popup", "popup"])

    def test_a_date_in_the_future_counts_as_now(self) -> None:
        dispatcher, _ = self.dispatcher()
        event = dispatcher.dispatch(comment(1, T0 + 10 * 365 * 86400))
        self.assertEqual(event.note.at, T0)
        self.assertEqual(dispatcher.state["sent"]["1"]["at"], T0)

    def test_silent_kinds_are_counted_not_shown(self) -> None:
        dispatcher, send = self.dispatcher()
        push = note("push", {"author": "@dkim", "count": "1", "messages": ["Fix"], "repo": "o/r", "number": "9", "title": "T"},
                    "Re: [o/r] T (PR #9)")
        event = dispatcher.dispatch(push)
        self.assertEqual(event.action, "silent")
        self.assertEqual(send.calls, [])
        self.assertEqual(list(dispatcher.state["counts"].values()), [{"push": 1}])

    def test_urgency_per_kind(self) -> None:
        dispatcher, send = self.dispatcher()
        dispatcher.dispatch(note("ci-failed", {"repo": "o/r", "workflow": "CI", "status": "Run failed", "branch": "main"},
                                 "[o/r] Run failed: CI - main (4f2a9c1)"))
        dispatcher.dispatch(note("state", {"action": "Closed", "number": "5", "repo": "o/r", "title": "T"}, "Re: [o/r] T (PR #5)"))
        self.assertEqual([c["urgency"] for c in send.calls], ["critical", "normal"])

    def test_a_busy_sync_folds_into_one_summary(self) -> None:
        dispatcher, send = self.dispatcher(most=2)
        for n in range(5):
            dispatcher.dispatch(comment(n, T0 + n, number=300 + n))
        summary = dispatcher.finish()
        self.assertEqual([e.action for e in dispatcher.events], ["popup", "popup", "held", "held", "held", "summary"])
        self.assertEqual(summary.title, "3 more from GitHub")
        self.assertEqual(len(send.calls), 3)

    def test_reviews_can_join_the_comment_group(self) -> None:
        rules = cn.profile_rules("all")
        rules["kinds"]["review"] = {"urgency": "normal", "group": True}
        dispatcher, _ = self.dispatcher(rules)
        dispatcher.dispatch(comment(1, T0))
        review = note("review", {"author": "@bot", "action": "commented on", "repo": "lumenlabs/lumen-app", "number": "274",
                                 "title": "T"}, "Re: [lumenlabs/lumen-app] T (PR #274)", at=T0 + 5, n=2)
        event = dispatcher.dispatch(review)
        self.assertEqual(event.action, "update")
        self.assertEqual(event.title, "2 new comments and reviews on PR #274 · lumen-app")

    def test_prune_forgets_old(self) -> None:
        dispatcher, _ = self.dispatcher()
        dispatcher.dispatch(comment(1, T0 - cn.KEEP - 10))
        dispatcher.prune()
        self.assertEqual((dispatcher.state["sent"], dispatcher.state["groups"]), ({}, {}))


class Quiet(unittest.TestCase):
    """The default profile: popups only for what needs you."""

    def run_notes(self, *notes, rules=None):
        send = Recorder()
        dispatcher = cn.Dispatcher(rules or cn.load_rules(Path("/nonexistent")), {}, send, T0)
        events = [dispatcher.dispatch(n) for n in notes]
        dispatcher.finish()
        return events, dispatcher, send

    def test_people_on_your_prs_pop_up_grouped_with_their_reviews(self) -> None:
        review = note("review", {"author": "@dkim", "action": "approved", "repo": "lumenlabs/lumen-app", "number": "274", "title": "T"},
                      "Re: [lumenlabs/lumen-app] T (PR #274)", at=T0 - 30, n=2,
                      github={"Reason": "author", "Sender": "dkim", "Recipient": "alex"}, sender="D Kim <notifications@github.com>")
        events, _, send = self.run_notes(comment(1, T0 - 60), review)
        self.assertEqual([e.action for e in events], ["popup", "update"])
        self.assertEqual(send.calls[-1]["title"], "2 new comments and reviews on PR #274 · lumen-app")

    def test_bots_are_counted_not_shown(self) -> None:
        bots = [comment(1, T0, who="greptile-apps[bot]"), comment(2, T0, who="codex", number=275),
                comment(3, T0, who="linear-code[bot]", number=276, kind="issue-comment")]
        events, dispatcher, send = self.run_notes(*bots)
        self.assertEqual([e.action for e in events], ["silent"] * 3)
        self.assertEqual(send.calls, [])
        self.assertEqual(list(dispatcher.state["counts"].values()), [{"comment by bots": 2, "issue-comment by bots": 1}])

    def test_a_bot_by_its_display_name_or_the_rules(self) -> None:
        shown = note("comment", {"author": "helper", "repo": "o/r", "number": "1", "title": "T"}, "Re: [o/r] T (PR #1)",
                     github={"Reason": "author", "Sender": "helper", "Recipient": "alex"}, sender="helper[bot] <notifications@github.com>")
        self.assertTrue(shown.bot)
        rules = cn.load_rules(Path("/nonexistent"))
        rules["bot_logins"] = ["deploy-app"]
        events, _, _ = self.run_notes(comment(1, T0, who="deploy-app"), rules=rules)
        self.assertEqual(events[0].action, "silent")

    def test_a_red_branch_alerts_once_an_hour(self) -> None:
        def ci(n, at, branch="main", commit="4f2a9c1"):
            return note("ci-failed", {"repo": "lumenlabs/lumen-app", "workflow": "CI", "status": "Run failed", "branch": branch,
                                      "commit": commit, "jobs": ["test"], "results": ["Failed in 2 minutes"]},
                        f"[lumenlabs/lumen-app] Run failed: CI - {branch} ({commit})", n=n, at=at,
                        github={"Reason": "ci_activity", "Sender": "alex", "Recipient": "alex"})
        events, _, send = self.run_notes(ci(1, T0 - 3000), ci(2, T0 - 1000, commit="9e1d2c3"), ci(3, T0 - 900, branch="fix/x"))
        self.assertEqual([e.action for e in events], ["popup", "update", "popup"])
        self.assertEqual([c["urgency"] for c in send.calls], ["critical", "critical", "critical"])
        self.assertIn("2 CI failures · lumen-app · main", [c["title"] for c in send.calls])
        later, _, _ = self.run_notes(ci(1, T0 - 7300), ci(2, T0))
        self.assertEqual([e.action for e in later], ["popup", "popup"])

    def test_threads_that_arent_yours_and_your_own_comments_are_silent(self) -> None:
        theirs = comment(1, T0, reason="comment")
        mentioned = comment(2, T0, reason="mention", number=275)
        mine = note("comment", {"author": "alex", "repo": "o/r", "number": "9", "title": "T"}, "Re: [o/r] T (PR #9)",
                    github={"Reason": "author", "Sender": "alex", "Recipient": "alex"})
        events, _, send = self.run_notes(theirs, mentioned, mine)
        self.assertEqual([e.action for e in events], ["silent"] * 3)
        self.assertTrue(mine.mine)

    def test_what_still_pops_up(self) -> None:
        ci = note("ci-failed", {"repo": "o/r", "workflow": "CI", "status": "Run failed", "branch": "main"},
                  "[o/r] Run failed: CI - main (4f2a9c1)", github={"Reason": "ci_activity", "Sender": "alex", "Recipient": "alex"})
        advisory = note("security-advisory", {"package": "toml", "title": "DoS", "severity": "High", "repos": ["o/r"]},
                        "[o] A security advisory on toml affects at least one of your repositories", n=2,
                        github={"Reason": "security_alert"})
        asked = note("review-requested", {"author": "@dkim", "ref": "o/r#5", "repo": "o/r", "number": "5", "title": "T"},
                     "Re: [o/r] T (PR #5)", n=3, github={"Reason": "review_requested", "Sender": "dkim", "Recipient": "alex"})
        quiet = [note("push", {"author": "@dkim", "count": "1", "repo": "o/r", "number": "5", "title": "T"}, "Re: [o/r] T (PR #5)", n=4),
                 note("state", {"action": "Merged", "number": "5", "repo": "o/r", "title": "T"}, "Re: [o/r] T (PR #5)", n=5),
                 note("dependabot-digest", {"week": "Nov 10 - Nov 17"}, "Your Dependabot alerts", n=6),
                 note("account-notice", {"notice": "A new SSH key was added"}, "[GitHub] A new SSH key was added", n=7)]
        events, _, send = self.run_notes(ci, advisory, asked, *quiet)
        self.assertEqual([e.action for e in events], ["popup"] * 3 + ["silent"] * 4)
        self.assertEqual([c["urgency"] for c in send.calls], ["critical", "critical", "normal"])


class Services(unittest.TestCase):
    """Other services' mail, notified by what it says."""

    def service(self, subject, brand="Hostinger", service="hostinger-com", domain="hostinger.com", n=1, at=T0, link="",
                address=None, alerts=None):
        values = {"link": link} if link else {}
        address = address or f"team@info.{domain}"
        made = mail(subject, "", f"{brand} <{address}>", at=at, n=n)
        made.address = address
        template = {"kind": "service", "builtin": True, "service": service, "brand": brand, "domain": domain,
                    "alerts": [address] if alerts is None else alerts}
        return cn.note_for(made, template, {"status": "ok", "values": values})

    def test_alerts_only_from_alert_senders(self) -> None:
        """A LinkedIn message whose preview says "Security alert" is someone's words."""
        relayed = self.service("Alex sent you a message: Security alert, new login to your account", "LinkedIn", "linkedin-com",
                               "linkedin.com", address="messages-noreply@linkedin.com", alerts=["security-noreply@linkedin.com"])
        real = self.service("Please verify your new device", "LinkedIn", "linkedin-com", "linkedin.com",
                            address="security-noreply@linkedin.com", alerts=["security-noreply@linkedin.com"])
        self.assertEqual((relayed.kind, relayed.title), ("notice", "LinkedIn · Update"))
        self.assertEqual((real.kind, real.title), ("security-alert", "LinkedIn · Security alert"))
        events, _, send = Quiet().run_notes(relayed, real)
        self.assertEqual([e.action for e in events], ["silent", "popup"])

    def test_kinds(self) -> None:
        cases = {
            "Security alert": "security-alert", "New login to Spotify": "security-alert",
            "Important: Login from new device": "security-alert", "A new device logged into your account": "security-alert",
            "Payment Unsuccessful - Debit Card ending with 1234": "payment-failed", "Domain Auto-Renewals Failed": "payment-failed",
            "Your invoice is overdue": "payment-failed",
            "You have domain(s) expiring soon": "domain-expiring", "Domain Suspended Notification": "domain-expiring",
            "[Action required] Validate example.dev to renew SSL certificates": "domain-expiring",
            "[Action required] Workers CPU limit exceeded": "incident", "Deployment failed for main": "incident",
            "Weekly Account Statement for AB123": "statement", "Your invoice is available": "invoice",
            "Your services auto-renew soon": "invoice", "12 new jobs for you": "digest",
            "Get 3 months of Premium for Rs 59": "marketing", "Your deal expires soon": "marketing",
            "Stablecoin Trading Volume Is Down Nearly 40%": "notice", "Urgent: Re-KYC Overdue": "notice",
        }
        for subject, kind in cases.items():
            self.assertEqual(cn.service_kind(subject)[0], kind, subject)

    def test_note(self) -> None:
        got = self.service("Re: You have domain(s) expiring soon", link="https://hpanel.hostinger.com/domains")
        self.assertEqual((got.kind, got.title, got.body), ("domain-expiring", "Hostinger · Expiring soon", "You have domain(s) expiring soon"))
        self.assertEqual((got.domain, got.link_label, got.group), ("hostinger.com", "Open on Hostinger", "service:hostinger-com:domain-expiring"))

    def test_quiet_pops_alerts_and_counts_the_rest(self) -> None:
        send = Recorder()
        dispatcher = cn.Dispatcher(cn.load_rules(Path("/nonexistent")), {}, send, T0)
        notes = [self.service("Security alert", "Google", "google-com", "google.com", n=1, at=T0 - 100),
                 self.service("Security alert for someone@example.test", "Google", "google-com", "google.com", n=2, at=T0 - 50),
                 self.service("Payment Unsuccessful - Debit Card", "A Bank", "a-bank", "abank.example", n=3),
                 self.service("Weekly Account Statement", "A Broker", "a-broker", "abroker.example", n=4),
                 self.service("Get 3 months of Premium", "Spotify", "spotify-com", "spotify.com", n=5),
                 self.service("Your weekly digest", "Medium", "medium-com", "medium.com", n=6)]
        events = [dispatcher.dispatch(n) for n in notes]
        dispatcher.finish()
        self.assertEqual([e.action for e in events], ["popup", "update", "popup", "silent", "silent", "silent"])
        self.assertEqual(send.calls[-1]["title"], "2 security alerts from Google")
        self.assertEqual([c["urgency"] for c in send.calls], ["critical", "critical", "critical"])
        self.assertEqual(sum(sum(day.values()) for day in dispatcher.state["counts"].values()), 3)

    def test_a_service_link_opens_only_on_its_domain(self) -> None:
        with unittest.mock.patch.object(cn.subprocess, "Popen") as popen:
            cn.open_link({"link": "https://hpanel.hostinger.com/x", "builtin": True, "domain": "hostinger.com"})
            cn.open_link({"link": "https://evil.test/hostinger.com", "builtin": True, "domain": "hostinger.com"})
            cn.open_link({"link": "https://hostinger.com.evil.test/", "builtin": True, "domain": "hostinger.com"})
        self.assertEqual([c[0][0][1] for c in popen.call_args_list], ["https://hpanel.hostinger.com/x"])


class Dock(unittest.TestCase):
    """The notification dock's feed (dock.json): Junco writes, the dock reads."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.env = unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.folder.name, "XDG_CONFIG_HOME": self.folder.name})
        self.env.start()
        # The made-up mail is dated T0: so is "now" (the feed's bounds read the clock).
        self.clock = unittest.mock.patch.object(cn.time, "time", return_value=T0 + 5)
        self.clock.start()

    def tearDown(self) -> None:
        self.clock.stop()
        self.env.stop()
        self.folder.cleanup()

    def ci(self, n, at=T0, status="Run failed", branch="main", commit="4f2a9c1"):
        return note("ci-failed", {"repo": "lumenlabs/lumen-app", "workflow": "CI", "status": status, "branch": branch, "commit": commit,
                                  "jobs": ["build", "test"], "results": ["Succeeded in 1 minute", "Failed in 2 minutes"],
                                  "link": "https://github.com/lumenlabs/lumen-app/actions/runs/1"},
                    f"[lumenlabs/lumen-app] {status}: CI - {branch} ({commit})", at=at, n=n,
                    github={"Reason": "ci_activity", "Sender": "alex", "Recipient": "alex"})

    def service(self, n, subject, brand="Hostinger", service="hostinger-com", domain="hostinger.com", at=T0):
        address = f"team@info.{domain}"
        made = mail(subject, "", f"{brand} <{address}>", at=at, n=n)
        made.address = address
        return cn.note_for(made, {"kind": "service", "builtin": True, "service": service, "brand": brand, "domain": domain,
                                  "alerts": [address]}, {"status": "ok", "values": {}})

    def dispatch(self, feed, *notes, now=T0, cards=False):
        dispatcher = cn.Dispatcher(cn.load_rules(Path("/nonexistent")) | {"_cards": cards}, {}, feed.send, now, most=10**6)
        events = [dispatcher.dispatch(n) for n in notes]
        dispatcher.finish()
        return events

    def test_an_item_as_the_contract_says(self) -> None:
        feed = cn.Feed()
        self.dispatch(feed, self.ci(1))
        [item] = feed.items
        for key in ("id", "unit", "unitLabel", "status", "kind", "urgency", "source", "icon", "title", "summary", "fields", "count",
                    "time", "updated", "actions"):
            self.assertIn(key, item)
        self.assertEqual((item["id"], item["unit"], item["unitLabel"], item["status"], item["kind"], item["urgency"], item["source"]),
                         ("ci:lumenlabs/lumen-app:main", "ci:lumenlabs/lumen-app:main", "lumen-app · main", "open", "ci-failed",
                          "critical", "GitHub"))
        fields = {f["key"]: f["value"] for f in item["fields"]}
        self.assertEqual((fields["repo"], fields["branch"], fields["commit"], fields["workflow"]), ("lumen-app", "main", "4f2a9c1", "CI"))
        self.assertEqual(fields["jobs"], ["test · failed in 2 minutes"])
        self.assertEqual(item["actions"], [
            {"id": "open", "label": "Open on GitHub", "url": "https://github.com/lumenlabs/lumen-app/actions/runs/1"},
            {"id": "open-junco", "label": "Open in Junco"}, {"id": "mark-read", "label": "Mark read", "resolves": True}])

    def test_atomic_private_and_empty(self) -> None:
        path = cn.dock_path()
        cn.Feed().save()
        self.assertEqual(json.loads(path.read_text())["items"], [])
        self.assertEqual(json.loads(path.read_text())["version"], 1)
        feed = cn.Feed.load()
        self.dispatch(feed, self.ci(1))
        feed.save()
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["dock.json"])  # no temp file left
        self.assertEqual(len(cn.Feed.load().items), 1)
        path.write_text("{broken")
        self.assertEqual(cn.Feed.load().items, [])  # a bad file reads as empty; the next save repairs it

    def test_a_unit_grows_in_place(self) -> None:
        feed = cn.Feed()
        self.dispatch(feed, self.ci(1, at=T0 - 600), self.ci(2, at=T0 - 300, commit="9e1d2c3"))
        [item] = feed.items
        self.assertEqual((item["id"], item["count"]), ("ci:lumenlabs/lumen-app:main", 2))
        self.assertIn({"key": "count", "label": "Emails", "value": "2"}, item["fields"])
        asked = note("review-requested", {"author": "@priya", "ref": "lumenlabs/lumen-app#274", "repo": "lumenlabs/lumen-app",
                                          "number": "274", "title": "T"}, "Re: [lumenlabs/lumen-app] T (PR #274)", n=3,
                     github={"Reason": "review_requested", "Sender": "priya", "Recipient": "alex"})
        self.dispatch(feed, asked, comment(4, T0), comment(5, T0 + 10, who="dkim"))
        pr = [i for i in feed.items if i["unit"] == "pr:lumenlabs/lumen-app#274"]
        self.assertEqual(sorted((i["id"], i["count"]) for i in pr),
                         [("pr:lumenlabs/lumen-app#274:comments", 2), ("pr:lumenlabs/lumen-app#274:review-requested", 1)])
        self.assertEqual({i["unitLabel"] for i in pr}, {"lumen-app #274"})

    def test_bounds(self) -> None:
        feed = cn.Feed()
        for n in range(60):
            self.dispatch(feed, self.service(n, f"Security alert {n}", service=f"s{n}", at=T0 - 1000 + n))
        feed.prune(T0)
        self.assertEqual(len(feed.items), cn.DOCK_MOST)
        self.assertEqual(feed.items[0]["summary"], "Security alert 59")  # newest first
        old = cn.Feed()
        self.dispatch(old, self.service(1, "Security alert", at=T0 - cn.DOCK_KEEP - 10))
        old.prune(T0)
        self.assertEqual(old.items, [])

    def test_work_resolves_from_mail(self) -> None:
        feed = cn.Feed()
        asked = note("review-requested", {"author": "@priya", "ref": "lumenlabs/lumen-app#274", "repo": "lumenlabs/lumen-app",
                                          "number": "274", "title": "T"}, "Re: [lumenlabs/lumen-app] T (PR #274)", n=3,
                     github={"Reason": "review_requested", "Sender": "priya", "Recipient": "alex"})
        self.dispatch(feed, self.ci(1), asked, comment(4, T0),
                      self.service(5, "You have domain(s) expiring soon"),
                      self.service(6, "Payment Unsuccessful - Debit Card ending with 4321", "A Bank", "a-bank", "abank.example"),
                      self.service(7, "Security alert: new sign-in", "Google", "google-com", "google.com"))
        self.assertEqual(feed.open_count(), 6)
        # Not settled by: a reminder of a renewal, a later security alert.
        for n in (self.service(8, "Your services auto-renew soon"), self.service(9, "Security alert", "Google", "google-com", "google.com")):
            self.assertEqual(feed.resolve(n), [])
        # Settled by: a green run, your own review, a renewal, a payment.
        passed = self.ci(10, status="Run succeeded")
        self.assertEqual([i["id"] for i in feed.resolve(passed)], ["ci:lumenlabs/lumen-app:main"])
        mine = note("review", {"author": "@alex", "action": "approved", "repo": "lumenlabs/lumen-app", "number": "274", "title": "T"},
                    "Re: [lumenlabs/lumen-app] T (PR #274)", n=11, github={"Reason": "review_requested", "Sender": "alex", "Recipient": "alex"})
        self.assertEqual([i["id"] for i in feed.resolve(mine)], ["pr:lumenlabs/lumen-app#274:review-requested"])
        self.assertEqual([i["kind"] for i in feed.resolve(self.service(12, "Your renewal is confirmed"))], ["domain-expiring"])
        self.assertEqual([i["kind"] for i in feed.resolve(self.service(13, "Payment received, thank you", "A Bank", "a-bank", "abank.example"))],
                         ["payment-failed"])
        merged = note("state", {"action": "Merged", "number": "274", "repo": "lumenlabs/lumen-app", "title": "T"},
                      "Re: [lumenlabs/lumen-app] T (PR #274)", n=14)
        self.assertEqual([i["id"] for i in feed.resolve(merged)], ["pr:lumenlabs/lumen-app#274:comments"])
        self.assertEqual([i["kind"] for i in feed.items if i["status"] == "open"], ["security-alert"])
        # Resolved items go after a minute; new work reopens a unit.
        feed.prune(T0 + 30)
        self.assertEqual(len(feed.items), 6)
        feed.prune(T0 + cn.DOCK_RESOLVED + 30)
        self.assertEqual(len(feed.items), 1)
        self.dispatch(feed, self.ci(15, at=T0 + 100, commit="0a1b2c3"))
        self.assertEqual(feed.find("ci:lumenlabs/lumen-app:main")["status"], "open")

    def test_a_merged_pr_resolves_its_runs(self) -> None:
        """A PR run is named by the PR's title; merging the PR settles it,
        and a PR titled like a branch never settles the branch's runs."""
        feed = cn.Feed()
        self.dispatch(feed, self.ci(1, status="PR run failed", branch="Team invites"), self.ci(2, branch="main"))
        merged = note("state", {"action": "Merged", "number": "274", "repo": "lumenlabs/lumen-app", "title": "Team invites"},
                      "Re: [lumenlabs/lumen-app] Team invites (PR #274)", n=3)
        self.assertEqual([i["id"] for i in feed.resolve(merged)], ["ci:lumenlabs/lumen-app:Team invites (PR run)"])
        decoy = note("state", {"action": "Closed", "number": "999", "repo": "lumenlabs/lumen-app", "title": "main"},
                     "Re: [lumenlabs/lumen-app] main (PR #999)", n=4)
        self.assertEqual(feed.resolve(decoy), [])
        self.assertEqual(feed.find("ci:lumenlabs/lumen-app:main")["status"], "open")

    def test_only_alert_senders_settle_and_a_named_domain_must_match(self) -> None:
        feed = cn.Feed()
        self.dispatch(feed, self.service(1, "Your domain brightloom.example is expiring soon"),
                      self.service(2, "Payment Unsuccessful - Debit Card ending with 4321", "A Bank", "a-bank", "abank.example"))
        relayed = cn.note_for(mail("Payment received, thank you", "", "A Bank <news@abank.example>", n=3),
                              {"kind": "service", "builtin": True, "service": "a-bank", "brand": "A Bank", "domain": "abank.example",
                               "alerts": ["team@info.abank.example"]}, {"status": "ok", "values": {}})
        relayed_mail_address = "news@abank.example"
        self.assertFalse(relayed.trusted, relayed_mail_address)
        self.assertEqual(feed.resolve(relayed), [])
        self.assertEqual(feed.resolve(self.service(4, "Your renewal of otherdomain.example is confirmed")), [])
        self.assertEqual(feed.resolve(self.service(5, "Your renewal is confirmed")), [])  # names no domain: not this one's
        for failed in ("Your renewal of brightloom.example was not successful", "Renewal of brightloom.example could not be completed",
                       "Your renewal of brightloom.example isn't complete", "brightloom.example will be renewed soon"):
            self.assertEqual(feed.resolve(self.service(7, failed)), [], failed)
        self.assertEqual([i["kind"] for i in feed.resolve(self.service(6, "Your renewal of brightloom.example is confirmed"))],
                         ["domain-expiring"])

    def test_feed_text_is_inert(self) -> None:
        feed = cn.Feed()
        hostile = self.service(1, "Security alert: <b>new</b> sign-in [click](https://evil.test)\nfrom Lisbon, Portugal", "Google",
                               "google-com", "google.com")
        self.dispatch(feed, hostile)
        text = json.dumps(feed.items[0], ensure_ascii=False)
        for mark in ("<b>", "](", "\\n"):
            self.assertNotIn(mark, text)

    def test_cards_tell_the_story(self) -> None:
        feed = cn.Feed()
        self.dispatch(feed, self.ci(1), comment(2, T0), comment(3, T0 + 5, who="dkim"),
                      self.service(4, "Security alert: new sign-in on a Linux laptop from Lisbon, Portugal", "Google", "google-com", "google.com"),
                      self.service(5, "Payment Unsuccessful - Debit Card ending with 4321 (Rs 1,299 at Example Store)", "A Bank", "a-bank",
                                   "abank.example"),
                      self.service(6, "Your domain brightloom.example expires on December 3, 2026"))
        lines = {item["kind"]: (item.get("headline"), item.get("detail")) for item in feed.items}
        self.assertEqual(lines["ci-failed"], ("lumen-app · main", "test failed"))
        self.assertEqual(lines["comment"], ("PR #274 · Team invites", "@priya, @dkim: Comment number 3."))
        self.assertEqual(lines["security-alert"][0], "New sign-in · Linux laptop")
        self.assertTrue(lines["security-alert"][1].startswith("Lisbon, Portugal · "))  # then the time, in words
        self.assertEqual(lines["payment-failed"], ("Rs 1,299 at Example Store", "card ending 4321"))
        self.assertEqual(lines["domain-expiring"], ("brightloom.example expires Dec 3", "renew with Hostinger"))
        who = cn.field_value(next(i for i in feed.items if i["kind"] == "comment"), "who")
        self.assertEqual(who, "@priya, @dkim")
        # One icon per source, for its tab: a theme name when Junco keeps no logo.
        self.assertEqual({i["source"]: i["icon"] for i in feed.items}["GitHub"], "github")

    def test_demo_items_never_touch_mail(self) -> None:
        self.put(self.ci(1))  # a real item, which the demo leaves alone
        added = cn.demo()
        feed = cn.Feed.load()
        demos = [i for i in feed.items if i["id"].startswith("demo:")]
        self.assertEqual(len(added), 5)
        self.assertEqual(sorted(i["kind"] for i in demos),
                         ["ci-failed", "review-comment", "review-requested", "security-alert", "security-alert"])
        self.assertTrue(all(i["status"] == "open" and i["messages"] == [] and i["link"] == "https://example.com" for i in demos))
        urls = {a["url"] for i in demos for a in i["actions"] if a.get("url")}
        self.assertEqual(urls, {"https://example.com"})
        self.assertEqual(sorted(i["urgency"] for i in demos), ["critical", "critical", "critical", "normal", "normal"])
        # Rich, as GitHub would tell it: a long review comment with a code
        # block, its diff hunk and thread; a run's log; a PR's description.
        thread = next(i for i in demos if i["kind"] == "review-comment")
        self.assertIn("```ts\n", thread["body"])
        self.assertGreater(len(thread["body"]), 800)
        self.assertEqual(thread["context"]["file"], "src/onboarding/checklist.ts")
        self.assertTrue(thread["context"]["hunk"][0].startswith("@@") and len(thread["context"]["hunk"]) <= 30)
        times = [t["time"] for t in thread["thread"]]
        self.assertEqual((len(times), times), (2, sorted(times)))  # oldest first
        self.assertEqual(thread["title"], "Tomas Ruiz commented on src/onboarding/checklist.ts")
        self.assertEqual(thread["headline"], "PR #268 · Onboarding checklist")
        self.assertTrue(thread["detail"].startswith("Tomas Ruiz: Could we load these"))
        ci = next(i for i in demos if i["kind"] == "ci-failed")
        self.assertTrue(ci["log"][0].startswith("── test (22.x)") and len(ci["log"]) <= 40)
        pr = next(i for i in demos if i["kind"] == "review-requested")
        self.assertEqual(pr["meta"]["files"], "7")
        self.assertTrue(all(i.get("body") for i in demos if i["kind"] == "security-alert"))  # the whole alert
        # Written in version 1 until the v5 dock is live; its v2 buttons are ready.
        self.assertEqual(feed.data["version"], 1)
        self.assertTrue(all("type" not in a for i in demos for a in i["actions"]))
        self.assertEqual([a["id"] for a in cn.item_actions(thread, 2)],
                         ["reply", "react-plus1", "resolve-thread", "open", "open-junco", "mark-read"])
        # Its GitHub buttons do nothing at all: no gh, no mail.
        with unittest.mock.patch.dict(courier_github.ACTIONS, {name: unittest.mock.Mock(side_effect=AssertionError("gh"))
                                                               for name in courier_github.ACTIONS}):
            self.assertEqual(cn.dock_action(thread["id"], "reply", "hi"), 0)
            self.assertEqual(cn.dock_action(thread["id"], "react-plus1"), 0)
            self.assertEqual(cn.dock_action(ci["id"], "rerun-failed"), 0)
            self.assertEqual(cn.dock_action(thread["id"], "resolve-thread"), 0)  # resolves: out of the dock
        self.assertIsNone(cn.Feed.load().find(thread["id"]))
        self.assertIsNotNone(feed.find("ci:lumenlabs/lumen-app:main"))
        demo_ci = next(i["id"] for i in demos if i["kind"] == "ci-failed")
        alert = next(i["id"] for i in demos if i["source"] == "Google")
        with unittest.mock.patch.object(cn, "mark_read") as marked, unittest.mock.patch.object(cn, "open_in_courier") as opened, \
                unittest.mock.patch.object(cn, "open_link") as linked:
            self.assertEqual(cn.dock_action(demo_ci, "open-junco"), 0)
            self.assertEqual(cn.dock_action(demo_ci, "mark-read"), 0)  # ✓: out of the dock, no mail marked
            self.assertEqual(cn.dock_action(alert, "open"), 0)
            self.assertEqual(cn.dock_dismiss(alert), 0)  # ×
        marked.assert_not_called()
        opened.assert_not_called()
        self.assertEqual(linked.call_args[0][0]["link"], "https://example.com")
        left = cn.Feed.load()
        self.assertEqual(len([i for i in left.items if i["id"].startswith("demo:")]), 2)  # 5, less the thread, the ✓ and the ×
        cn.demo(clear=True)
        left = cn.Feed.load()
        self.assertEqual([i["id"] for i in left.items], ["ci:lumenlabs/lumen-app:main"])  # only the real one

    def review_comment(self, n: int, comment: int, at=T0, text="@tomas-r commented on this pull request.\n\nWhy a loop?\n\n-- \nReply"):
        return note("comment", {"author": "tomas-r", "repo": "lumenlabs/lumen-app", "number": "268", "title": "Onboarding checklist",
                                "link": f"https://github.com/lumenlabs/lumen-app/pull/268#discussion_r{comment}"},
                    "Re: [lumenlabs/lumen-app] Onboarding checklist (PR #268)", text, at=at, n=n,
                    github={"Reason": "author", "Sender": "tomas-r", "Recipient": "alex"}, sender="Tomas Ruiz <notifications@github.com>")

    def test_contract_version_gating(self) -> None:
        self.assertEqual(cn.load_rules(Path("/nonexistent"))["dock_version"], 1)
        path = Path(self.folder.name) / "courier" / "notify-rules.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"dock_version": 4}))
        self.assertEqual(cn.dock_version(), 1)  # an unknown version: 1
        # Version 1 (the live v4 dock): Open, Open in Junco, Mark read only,
        # never an input it would run without its text.
        feed = cn.Feed()
        self.dispatch(feed, self.review_comment(1, 1520), self.ci(2), note(
            "review-requested", {"author": "priya-n", "repo": "lumenlabs/lumen-app", "number": "274", "title": "Team invites",
                                 "link": "https://github.com/lumenlabs/lumen-app/pull/274"}, "[lumenlabs/lumen-app] Team invites (PR #274)", n=3))
        feed.save()
        data = json.loads(cn.dock_path().read_text())
        self.assertEqual(data["version"], 1)
        for item in data["items"]:
            self.assertEqual([a["id"] for a in item["actions"]], ["open", "open-junco", "mark-read"])
            self.assertTrue(all("type" not in a and "hint" not in a for a in item["actions"]))
        # Version 2, once the v5 dock is live: each kind's buttons, typed.
        path.write_text(json.dumps({"dock_version": 2}))
        feed = cn.Feed.load()
        feed.save()
        data = json.loads(cn.dock_path().read_text())
        self.assertEqual(data["version"], 2)
        acts = {item["kind"]: [(a["id"], a["type"]) + (("resolves",) if a.get("resolves") else ()) for a in item["actions"]]
                for item in data["items"]}
        self.assertEqual(acts["review-comment"], [("reply", "input"), ("react-plus1", "command"), ("resolve-thread", "command", "resolves"),
                                                  ("open", "url"), ("open-junco", "command"), ("mark-read", "command", "resolves")])
        self.assertEqual(acts["ci-failed"], [("rerun-failed", "command"), ("open", "url"), ("open-junco", "command"),
                                             ("mark-read", "command", "resolves")])
        self.assertEqual(acts["review-requested"], [("open", "url"), ("approve", "confirm", "resolves"), ("open-junco", "command"),
                                                    ("mark-read", "command", "resolves")])
        reply = next(a for i in data["items"] for a in i["actions"] if a["id"] == "reply")
        self.assertEqual(reply["hint"], "Reply to @tomas-r")
        self.assertEqual(next(a["label"] for i in data["items"] if i["kind"] == "ci-failed" for a in i["actions"] if a["id"] == "open"),
                         "Open run")

    def test_a_review_comment_is_its_threads_item(self) -> None:
        feed = cn.Feed()
        self.dispatch(feed, self.review_comment(1, 1520))
        [item] = feed.items
        self.assertEqual((item["id"], item["unit"], item["kind"]),
                         ("pr-thread:lumenlabs/lumen-app#268:r1520", "pr-thread:lumenlabs/lumen-app#268:r1520", "review-comment"))
        self.assertEqual(item["unitLabel"], "lumen-app #268 · review thread")
        self.assertEqual(item["body"], "Why a loop?")  # the email's own text, until GitHub's is read
        self.assertEqual(item["github"], {"owner": "lumenlabs", "repo": "lumen-app", "kind": "pr", "number": "268",
                                          "anchor": "review-comment", "id": "1520"})

    def enrich(self, answers: dict, limit: int = cn.ENRICH_MOST) -> tuple[int, list]:
        """enrich_feed with a stand-in courier_github.details: answers by
        the comment, run or PR it's asked about."""
        asked = []

        def details(where):
            key = where.get("id") or where.get("run") or where.get("number")
            asked.append(key)
            answer = answers[key]
            if isinstance(answer, Exception):
                raise answer
            return json.loads(json.dumps(answer))

        with unittest.mock.patch.object(courier_github, "details", details), unittest.mock.patch.object(courier_github, "pause"):
            return cn.enrich_feed(limit), asked

    def test_github_is_read_once_a_few_items_at_a_time(self) -> None:
        with cn.locked_state():
            feed = cn.Feed()
            self.dispatch(feed, *[comment(n, T0 + n, number=270 + n) for n in range(1, 5)])
            feed.save()
        cn.demo()  # made-up items are never read
        story = {"body": "The whole comment.\n\n```py\nx = 1\n```", "who": "Priya Natarajan", "image": "file:///cache/priya-n.png",
                 "thread": [{"who": "Sam", "time": "2026-11-25T08:00:00Z", "body": "earlier"}], "github": {"login": "priya", "comment_id": "1"}}
        answers = {str(n): story for n in range(1, 5)}
        read, asked = self.enrich(answers)
        self.assertEqual((read, len(asked)), (3, 3))  # a few per sync
        read, asked = self.enrich(answers)
        self.assertEqual((read, len(asked)), (1, 1))  # the rest next time
        read, asked = self.enrich(answers)
        self.assertEqual((read, asked), (0, []))  # each once
        items = [i for i in cn.Feed.load().items if not i["id"].startswith("demo:")]
        self.assertEqual(len(items), 4)
        for item in items:
            self.assertEqual((item["body"], item["image"], item["enriched"]), (story["body"], story["image"], item["link"]))
            self.assertEqual(item["gh"], {"login": "priya", "comment_id": "1"})
            self.assertEqual(item["summary"], "The whole comment.")
        # A newer comment in the same PR: the email's text again, then read anew.
        with cn.locked_state():
            feed = cn.Feed.load()
            self.dispatch(feed, comment(9, T0 + 9, number=271))
            feed.save()
        item = cn.Feed.load().find("pr:lumenlabs/lumen-app#271:comments")
        self.assertEqual(item["body"], "Comment number 9.")
        self.assertNotIn("thread", item)  # the old comment's thread went with it
        read, asked = self.enrich({"9": story})
        self.assertEqual(asked, ["9"])

    def test_when_github_cant_the_email_stands(self) -> None:
        with cn.locked_state():
            feed = cn.Feed()
            self.dispatch(feed, comment(1, T0))
            feed.save()
        for tries in (1, 2):
            read, asked = self.enrich({"1": courier_github.GitHubError("HTTP 404: Not Found")})
            self.assertEqual(asked, ["1"])
        [item] = cn.Feed.load().items
        self.assertEqual(item["body"], "Comment number 1.")
        self.assertEqual(item["enriched"], item["link"])  # tried twice: no more
        self.assertEqual(self.enrich({})[1], [])

    def test_a_reply_joins_its_threads_item(self) -> None:
        with cn.locked_state():
            feed = cn.Feed()
            state = {}
            dispatcher = cn.Dispatcher(cn.load_rules(Path("/nonexistent")), state, feed.send, T0 + 60, most=10**6)
            # Three in one sync (a desktop popup would group them): each its own item in the dock.
            for made in (self.review_comment(1, 1518), self.review_comment(4, 1519, at=T0 + 30), self.review_comment(2, 1520, at=T0 + 60)):
                dispatcher.dispatch(cn.dock_group(made))
            dispatcher.finish()
            feed.take_ids(state["sent"])
            feed.save()
        self.assertEqual(len(cn.Feed.load().items), 3)
        with cn.locked_state():
            feed = cn.Feed.load()
            feed.remove("pr-thread:lumenlabs/lumen-app#268:r1519")
            feed.save()
        self.assertEqual(len(cn.Feed.load().items), 2)
        self.assertEqual([i["messages"] for i in cn.Feed.load().items], [["m2@example.test"], ["m1@example.test"]])  # each its own
        first = {"body": "Why a loop?", "who": "Priya Natarajan", "github": {"thread_root": "1518", "comment_id": "1518"}}
        reply = {"body": "Batching now.", "who": "Tomas Ruiz", "context": {"file": "src/x.ts", "line": 4, "hunk": ["@@ -1 +1 @@", "+x"]},
                 "thread": [{"who": "Priya Natarajan", "time": "t", "body": "Why a loop?"}],
                 "github": {"thread_root": "1518", "comment_id": "1520", "thread_id": "PRRT_1"}}
        self.enrich({"1518": first, "1520": reply})
        [item] = cn.Feed.load().items
        self.assertEqual(item["id"], "pr-thread:lumenlabs/lumen-app#268:r1518")  # the thread's item keeps its id
        self.assertEqual((item["body"], item["count"], item["gh"]["thread_id"]), ("Batching now.", 2, "PRRT_1"))
        self.assertEqual(item["messages"], ["m1@example.test", "m2@example.test"])
        # A reply whose thread has no item yet becomes the thread's item.
        with cn.locked_state():
            feed = cn.Feed()
            self.dispatch(feed, self.review_comment(3, 1530))
            feed.save()
        self.enrich({"1530": reply | {"github": {"thread_root": "1525", "comment_id": "1530"}}})
        self.assertEqual([i["id"] for i in cn.Feed.load().items], ["pr-thread:lumenlabs/lumen-app#268:r1525"])

    def test_github_buttons_act_only_when_pressed(self) -> None:
        import contextlib
        import io

        with cn.locked_state():
            feed = cn.Feed()
            self.dispatch(feed, self.review_comment(1, 1520), self.service(2, "Security alert: new sign-in", "Google", "google-com",
                                                                            "google.com"))
            feed.save()
        thread = "pr-thread:lumenlabs/lumen-app#268:r1520"
        alert = next(i["id"] for i in cn.Feed.load().items if i["id"] != thread)
        pressed = []

        def fake(result):
            def act(where, own, text):
                pressed.append((where["id"], text))
                if isinstance(result, Exception):
                    raise result
                return result
            return act

        def run(item, action, given=None, result="Sent"):
            out, err = io.StringIO(), io.StringIO()
            with unittest.mock.patch.dict(courier_github.ACTIONS, {action: fake(result)} if action in courier_github.ACTIONS else {}), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cn.dock_action(item, action, given)
            return code, out.getvalue(), err.getvalue()

        self.assertEqual(run(thread, "reply", ""), (2, "", "Nothing to send\n"))
        self.assertEqual(run(thread, "reply", " \n\t"), (2, "", "Nothing to send\n"))
        self.assertEqual(pressed, [])  # never sent
        self.assertEqual(run(thread, "reply", "Batching now 👍"), (0, "Sent\n", ""))
        self.assertEqual(pressed, [("1520", "Batching now 👍")])
        self.assertEqual(run(thread, "react-plus1", result="👍 added"), (0, "👍 added\n", ""))
        self.assertEqual(run(thread, "resolve-thread", result=courier_github.GitHubError("HTTP 403: Resource not accessible")),
                         (1, "", "HTTP 403: Resource not accessible\n"))
        self.assertEqual(cn.Feed.load().find(thread)["status"], "open")  # failed: stays
        self.assertEqual(run(thread, "resolve-thread", result="Thread resolved"), (0, "Thread resolved\n", ""))
        self.assertEqual(cn.Feed.load().find(thread)["status"], "resolved")  # done: resolved, so the dock lets it go
        self.assertEqual(run(alert, "approve", result="Approved"), (1, "", "That item isn't on GitHub\n"))
        self.assertEqual(run(alert, "rm -rf")[0], 2)
        self.assertEqual(run("no-such-item", "reply", "x")[0], 1)
        self.assertEqual(len(pressed), 4)

    def test_a_replys_text_comes_on_stdin(self) -> None:
        def main(action, data: bytes):
            stdin = types.SimpleNamespace(buffer=__import__("io").BytesIO(data), isatty=lambda: False)
            with unittest.mock.patch.object(sys, "argv", ["courier-notify", "action", "item-1", action]), \
                    unittest.mock.patch.object(sys, "stdin", stdin), unittest.mock.patch.object(cn, "dock_action", return_value=0) as acted, \
                    unittest.mock.patch("sys.stderr", new_callable=__import__("io").StringIO):
                code = cn.main()
            return code, acted

        code, acted = main("reply", "नमस्ते, merged 👍".encode())
        self.assertEqual((code, acted.call_args[0]), (0, ("item-1", "reply", "नमस्ते, merged 👍")))
        code, acted = main("reply", b"x" * (cn.REPLY_MOST + 1))
        self.assertEqual(code, 2)  # too long: refused, never cut
        acted.assert_not_called()
        code, acted = main("react-plus1", b"ignored")
        self.assertEqual(acted.call_args[0], ("item-1", "react-plus1", None))

    def test_after_sync_reads_github_apart(self) -> None:
        cn.start_enrich.reset_mock()
        self.after_sync([self.ci(1)], alive=True)
        cn.start_enrich.assert_called_once_with()  # not waited for: its own unit
        cn.start_enrich.reset_mock()
        self.after_sync([self.ci(1)], alive=False)
        cn.start_enrich.assert_not_called()  # no dock, no reading

    def test_only_githubs_own_mail_acts_on_github(self) -> None:
        # A taught template (any sender) with a GitHub link: no GitHub target,
        # nothing read, no GitHub button.
        taught = note("comment", {"author": "x", "repo": "o/r", "number": "1", "title": "T",
                                  "link": "https://github.com/o/r/pull/1#discussion_r5"}, "Re: [o/r] T (PR #1)", n=1,
                      github={"Reason": "author"}, sender="News <news@example.test>", builtin=False)
        with cn.locked_state():
            feed = cn.Feed(version=2)
            self.dispatch(feed, taught)
            feed.save()
        [item] = cn.Feed.load().items
        self.assertEqual((item["github"], item["kind"]), ({}, "comment"))
        self.assertFalse([a for a in cn.item_actions(item, 2) if a["id"] in ("reply", "react-plus1", "resolve-thread")])
        self.assertEqual(self.enrich({})[1], [])
        with unittest.mock.patch.dict(courier_github.ACTIONS, {"reply": unittest.mock.Mock(side_effect=AssertionError("gh"))}), \
                unittest.mock.patch("sys.stderr", new_callable=__import__("io").StringIO):
            self.assertEqual(cn.dock_action(item["id"], "reply", "hi"), 1)
        # GitHub's own: the link rebuilt from its parts (Open shows what the buttons act on).
        made = self.review_comment(2, 1520)
        made.link = "https://github.com/lumenlabs/lumen-app/pull/268/files?w=1#discussion_r1520"
        feed = cn.Feed()
        self.dispatch(feed, made)
        self.assertEqual(feed.items[0]["link"], "https://github.com/lumenlabs/lumen-app/pull/268#discussion_r1520")

    def test_rich_text_is_inert_too(self) -> None:
        item = {"title": "t", "image": "https://evil.example/p.png",
                "body": "See ![x](https://evil.example/a.png) and <img src=https://evil.example/b.png> [here](https://evil.example)\n\n"
                        "> quoted\n\n```ts\nconst ok = a < b && list.length > 0\nfunction f(): Promise<void> {}\n```\u202e\x07",
                "thread": [{"who": "<b>Eve</b>", "time": "t", "avatar": "https://evil.example/c.png", "body": "<a href=x>hi</a>"},
                           {"who": "Sam", "time": "t", "avatar": "file:///cache/sam.png", "body": "ok"}, "junk"],
                "context": {"file": "<i>x</i>.ts", "line": "42", "hunk": ["@@ -1 +1 @@", "+<script>alert(1)</script>", 7]},
                "log": ["error <b>x</b>", "a\nb", None], "meta": {"ci": "<b>failing</b>", "files": "", "head": "main"}}
        cn.make_inert(item)
        body = item["body"]
        self.assertNotIn("<img", body)
        self.assertNotIn("](", body)
        # A shortcut reference finds no definition (each would be one line in a body).
        for markup in ("![r]\n\n[r]: https://evil.example/a.png", "> ![r]\n>\n> [r]: https://evil.example/a.png",
                       "- ![r]\n\n  [r]:\n  https://evil.example/a.png \"t\"", "![r][]\n\n[r]: <https://evil.example/a.png>"):
            made = cn.inert_markup(markup)
            self.assertNotRegex(made, r"\]:|\]\[|<h", markup)
            self.assertIn("![r]", made)  # shown as typed
        self.assertNotIn("\u202e", body)
        self.assertNotIn("\x07", body)
        self.assertIn("> quoted", body)  # the markup subset stays
        self.assertIn("const ok = a < b && list.length > 0", body)  # and code reads as written
        self.assertIn("Promise‹void>", body)  # but no tag can open
        self.assertEqual(item["image"], "")  # a local file only
        self.assertEqual([t["who"] for t in item["thread"]], ["‹b›Eve‹/b›", "Sam"])
        self.assertNotIn("avatar", item["thread"][0])
        self.assertEqual(item["thread"][1]["avatar"], "file:///cache/sam.png")
        self.assertEqual(item["thread"][0]["body"], "‹a href=x>hi‹/a>")
        self.assertEqual(item["context"], {"file": "‹i›x‹/i›.ts", "line": 0, "hunk": ["@@ -1 +1 @@", "+‹script>alert(1)‹/script>"]})
        self.assertEqual(item["log"], ["error ‹b>x‹/b>", "a b"])
        self.assertEqual(item["meta"], {"ci": "‹b›failing‹/b›", "head": "main"})
        again = json.loads(json.dumps(item))
        cn.make_inert(again)
        self.assertEqual(again, item)  # once inert, it stays as it is

    def v3_rules(self, version: int = 3) -> Path:
        path = Path(self.folder.name) / "courier" / "notify-rules.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"dock_version": version}))
        return path

    def bill(self, n: int = 1, subject: str = "Your credit card bill of ₹18,240 is due on 28 Nov 2026"):
        made = mail(subject, "Total amount due ₹18,240\nMinimum amount due ₹910", "Example Bank <alerts@bank.example>", n=n)
        made.address, made.html = "alerts@bank.example", '<a href="https://netbanking.bank.example/cards/pay">Pay now</a>'
        return cn.note_for(made, {"kind": "service", "builtin": True, "service": "bank", "brand": "Example Bank", "domain": "bank.example",
                                  "alerts": ["alerts@bank.example"]}, {"status": "ok", "values": {}})

    def invite_mail(self, method: str = "REQUEST", uid: str = "u-1@google.com", n: int = 9, organizer: str = "priya@example.com",
                    sender: str = "priya@example.com"):
        import email.message

        ics = "\r\n".join(["BEGIN:VCALENDAR", f"METHOD:{method}", "BEGIN:VEVENT", "DTSTART:20261126T093000Z", "DTEND:20261126T101500Z",
                            f"UID:{uid}", "SUMMARY:Design review", f"ORGANIZER;CN=Priya Natarajan:mailto:{organizer}",
                            "ATTENDEE;CN=Priya Natarajan:mailto:priya@example.com", "ATTENDEE;CN=Alex:mailto:alex@example.com",
                            "LOCATION:Google Meet", "END:VEVENT", "END:VCALENDAR"])
        parsed = email.message.EmailMessage()
        parsed["Subject"] = "Invitation: Design review"
        parsed.set_content("You're invited")
        parsed.add_attachment(ics.encode(), maintype="text", subtype="calendar", filename="invite.ics")
        return types.SimpleNamespace(id=f"m{n}@example.test", account="personal", sender=f"Priya Natarajan <{sender}>",
                                     address=sender, subject="Invitation: Design review", text="", html="", epoch=T0, parsed=parsed)

    def test_new_kinds_reach_only_a_version_3_dock(self) -> None:
        bill = self.bill()
        self.assertEqual((bill.kind, bill.unit, bill.card["amount"], bill.card["due"]), ("bill", "bill:bank:due", 18240.0, "2026-11-28"))
        self.assertEqual(bill.card["pay"], "https://netbanking.bank.example/cards/pay")
        rules = cn.load_rules(Path("/nonexistent"))
        for kind in ("bill", "statement", "invoice", "parcel", "deploy", "invite"):
            made = cn.Note(kind=kind, title="t", body="b", message_id="m")
            self.assertEqual(cn.decide(rules, made)[0], "silent", kind)  # version 2, or the desktop: as before
            self.assertEqual(cn.decide(rules | {"_cards": True}, made)[0], "normal", kind)
        # after_sync: no invite read, no bill card at version 2; both at 3.
        self.after_sync([bill], alive=True)
        self.assertEqual((self.asked_invites[-1], cn.Feed.load().items), (False, []))
        self.v3_rules()
        self.after_sync([bill], alive=True)
        self.assertTrue(self.asked_invites[-1])
        [item] = cn.Feed.load().items
        self.assertEqual((item["kind"], item["card"]["amount"]), ("bill", 18240.0))
        written = json.loads(cn.dock_path().read_text())
        self.assertEqual(written["version"], 3)
        [card] = written["items"]
        self.assertEqual((card["component"], card["kind"], card["jkind"], card["lane"]), ("DataTable", "Bill", "bill", "action"))
        self.assertEqual([a["id"] for a in card["actions"]], ["pay", "mark-paid", "open-junco", "mark-read"])
        # The desktop (no dock): silent, as before.
        self.after_sync([self.bill(2)], alive=False)
        self.assertFalse(self.asked_invites[-1])

    def test_a_version_3_feed_reads_back(self) -> None:
        self.v3_rules()
        with cn.locked_state():
            feed = cn.Feed()
            self.dispatch(feed, self.ci(1), self.service(2, "Security alert: new sign-in from Lisbon, Portugal", "Google", "google-com",
                                                            "google.com"))
            feed.save()
        written = json.loads(cn.dock_path().read_text())
        self.assertEqual(sorted(i["component"] for i in written["items"]), ["DecisionPanel", "StatusSummary"])
        feed = cn.Feed.load()
        self.assertEqual(sorted(i["kind"] for i in feed.items), ["ci-failed", "security-alert"])  # Junco's own again
        self.assertFalse(any("component" in i or "jkind" in i for i in feed.items))
        self.v3_rules(2)
        cn.Feed.load().save()
        self.assertEqual(json.loads(cn.dock_path().read_text())["version"], 2)  # back to version 2: v2 items
        self.assertFalse(any("component" in i for i in json.loads(cn.dock_path().read_text())["items"]))

    def test_card_buttons(self) -> None:
        import contextlib
        import io

        self.v3_rules()
        alert = self.service(2, "Security alert: new sign-in", "Google", "google-com", "google.com")
        alert.card = {"secure": "https://myaccount.google.com/notifications"}
        invite = cn.invite_note(self.invite_mail())
        with cn.locked_state():
            feed = cn.Feed()
            self.dispatch(feed, alert, self.bill(3), invite, cards=True)
            feed.save()
        items = {i["kind"]: i["id"] for i in cn.Feed.load().items}

        def run(item_id, action, raises=None, result="You said yes"):
            out, err = io.StringIO(), io.StringIO()
            calls = []

            def respond(invite, answer):
                calls.append((invite["uid"], answer))
                if raises:
                    raise raises
                return result

            import courier_calendar

            with unittest.mock.patch.object(courier_calendar, "respond", respond), unittest.mock.patch.object(cn, "open_link") as opened, \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cn.dock_action(item_id, action)
            return code, out.getvalue().strip(), err.getvalue().strip(), calls, opened

        code, out, _, _, opened = run(items["security-alert"], "secure")
        self.assertEqual((code, out), (0, "Opened"))
        self.assertEqual(opened.call_args[0][0], {"link": "https://myaccount.google.com/notifications", "builtin": True, "domain": "google.com"})
        self.assertEqual(run(items["security-alert"], "its-me")[:2], (0, "Marked as you"))
        self.assertEqual(cn.Feed.load().find(items["security-alert"])["status"], "resolved")
        code, out, _, _, opened = run(items["bill"], "pay")
        self.assertEqual(opened.call_args[0][0]["link"], "https://netbanking.bank.example/cards/pay")  # opens; never pays
        self.assertEqual(run(items["bill"], "mark-paid")[:2], (0, "Marked paid"))
        import courier_calendar

        code, out, err, calls, _ = run(items["invite"], "maybe", result="You said maybe")
        self.assertEqual((code, out, calls), (0, "You said maybe", [("u-1@google.com", "maybe")]))
        self.assertEqual(cn.Feed.load().find(items["invite"])["status"], "open")  # maybe: still open
        code, out, err, calls, _ = run(items["invite"], "accept", raises=courier_calendar.CalendarError(
            "Junco may only read your calendar: run courier-auth add <account> --calendar-write"))
        self.assertEqual((code, out, err), (1, "", "Junco may only read your calendar: run courier-auth add <account> --calendar-write"))
        self.assertEqual(cn.Feed.load().find(items["invite"])["status"], "open")  # failed: stays
        self.assertEqual(run(items["invite"], "accept")[:2], (0, "You said yes"))
        self.assertEqual(cn.Feed.load().find(items["invite"])["status"], "resolved")
        code, _, err, calls, _ = run(items["bill"], "decline")
        self.assertEqual((code, err, calls), (1, "That item isn't an invitation", []))

    def test_invite_notes(self) -> None:
        note = cn.invite_note(self.invite_mail())
        invite = note.card["invite"]
        self.assertEqual((note.kind, note.unit, note.source, invite["title"], invite["account"]),
                         ("invite", "invite:priya@example.com:u-1@google.com", "Calendar", "Design review", "personal"))
        self.assertEqual([a["name"] for a in invite["attendees"]], ["Priya Natarajan", "Alex"])
        self.assertTrue(invite["start"].endswith(("+05:30", "+00:00")) or "+" in invite["start"] or "-" in invite["start"][10:])
        self.assertIsNone(cn.invite_note(self.invite_mail("REPLY")))
        # Only the organiser's own address speaks for the meeting: not a colleague at the same domain, nor a subdomain.
        self.assertIsNone(cn.invite_note(self.invite_mail(sender="mallory@example.com")))
        self.assertIsNone(cn.invite_note(self.invite_mail(sender="invites@calendar.example.com")))
        self.assertIsNotNone(cn.invite_note(self.invite_mail(organizer="Priya@Example.com")))  # the same address, any case
        # A cancellation takes the invitation's card away.
        self.v3_rules()
        feed = cn.Feed()
        self.dispatch(feed, note, cards=True)
        [item] = feed.items
        # Someone else (verified as themselves) cancelling the same id: a unit of their own, so nothing happens.
        # Their invite naming Priya as organiser: refused outright.
        self.assertIsNone(cn.invite_note(self.invite_mail("CANCEL", n=11, sender="mallory@evil.example")))
        forged = cn.invite_note(self.invite_mail("CANCEL", n=12, organizer="mallory@evil.example", sender="mallory@evil.example"))
        self.assertEqual(forged.unit, "invite:mallory@evil.example:u-1@google.com")
        feed.resolve(forged, T0)
        self.assertEqual(item["status"], "open")
        feed.resolve(cn.invite_note(self.invite_mail("CANCEL", n=10)), T0)
        self.assertEqual(item["status"], "resolved")  # the organiser's own cancellation

    def test_demo_at_version_3_never_reaches_calendar_or_bank(self) -> None:
        import courier_calendar

        self.v3_rules()
        cn.demo()
        written = json.loads(cn.dock_path().read_text())
        self.assertEqual(sorted(i["component"] for i in written["items"]),
                         ["CommentPanel", "DataTable", "DecisionPanel", "DecisionPanel", "ReviewPanel", "SchedulingPanel", "StatusSummary",
                          "Timeline"])
        self.assertEqual({a["url"] for i in written["items"] for a in i["actions"] if a.get("url")} |
                         {i["original"]["url"] for i in written["items"] if i.get("original")}, {"https://example.com"})
        invite = next(i["id"] for i in written["items"] if i["component"] == "SchedulingPanel")
        bill = next(i["id"] for i in written["items"] if i["component"] == "DataTable")
        with unittest.mock.patch.object(courier_calendar, "respond", side_effect=AssertionError("calendar")), \
                unittest.mock.patch.object(cn, "open_link") as opened, unittest.mock.patch("sys.stdout", new_callable=__import__("io").StringIO):
            self.assertEqual(cn.dock_action(invite, "accept"), 0)
            self.assertEqual(cn.dock_action(bill, "pay"), 0)
        self.assertEqual(opened.call_args[0][0]["link"], "https://example.com")
        self.assertIsNone(cn.Feed.load().find(invite))  # accepted: out of the dock, nothing sent

    def test_delivery_and_the_heartbeat(self) -> None:
        rules = cn.load_rules(Path("/nonexistent"))
        self.assertEqual(rules["delivery"], "auto")
        self.assertEqual(cn.channel(rules, T0), "desktop")  # no dock: a desktop notification, nothing lost
        alive = cn.dock_alive_path()
        alive.parent.mkdir(parents=True)
        alive.write_text("now")
        os.utime(alive, (T0 - 30, T0 - 30))
        self.assertEqual(cn.channel(rules, T0), "dock")
        os.utime(alive, (T0 - 91, T0 - 91))
        self.assertEqual(cn.channel(rules, T0), "desktop")  # the dock stopped 91 s ago
        self.assertEqual(cn.channel(rules | {"delivery": "dock"}, T0), "dock")
        os.utime(alive, (T0, T0))
        self.assertEqual(cn.channel(rules | {"delivery": "notify"}, T0), "desktop")
        path = Path(self.folder.name) / "rules.json"
        path.write_text(json.dumps({"delivery": "dock"}))
        self.assertEqual(cn.load_rules(path)["delivery"], "dock")
        path.write_text(json.dumps({"delivery": "pager"}))
        with unittest.mock.patch("sys.stderr"):
            self.assertEqual(cn.load_rules(path)["delivery"], "auto")

    def put(self, *notes):
        with cn.locked_state() as state:
            feed = cn.Feed.load()
            dispatcher = cn.Dispatcher(cn.load_rules(Path("/nonexistent")), state, feed.send, T0, most=10**6)
            for n in notes:
                dispatcher.dispatch(n)
            dispatcher.finish()
            feed.take_ids(state["sent"])
            feed.save(now=T0)

    def test_commands(self) -> None:
        self.put(self.ci(1), self.service(2, "Security alert: new sign-in", "Google", "google-com", "google.com"))
        ci_id, alert_id = "ci:lumenlabs/lumen-app:main", "alert:google-com:security-alert"
        with unittest.mock.patch.object(cn, "open_in_courier") as opened, unittest.mock.patch.object(cn, "mark_read") as marked, \
                unittest.mock.patch.object(cn, "open_link") as linked, unittest.mock.patch("sys.stderr"):
            self.assertEqual(cn.dock_action(ci_id, "open-junco"), 0)
            self.assertEqual(opened.call_args[0][0], "m1@example.test")
            self.assertEqual(cn.dock_action(ci_id, "open"), 0)
            self.assertEqual(linked.call_args[0][0]["link"], "https://github.com/lumenlabs/lumen-app/actions/runs/1")
            self.assertEqual(cn.dock_action(ci_id, "mark-read"), 0)
            self.assertEqual(marked.call_args[0][0]["ids"], ["m1@example.test"])
            self.assertIsNone(cn.Feed.load().find(ci_id))  # handled: out of the dock
            self.assertEqual(cn.dock_action("no-such-item", "open-junco"), 1)
            self.assertEqual(cn.dock_action(alert_id, "rm -rf"), 2)
            self.assertEqual(cn.dock_dismiss(alert_id), 0)
            self.assertEqual(cn.dock_dismiss(alert_id), 1)
        self.assertEqual(cn.Feed.load().items, [])
        with cn.locked_state() as state:
            self.assertEqual(state["groups"], {})  # the next email of the group starts a new item

    def after_sync(self, notes, alive: bool):
        """courier_notify.after_sync with a stand-in mail index and desktop."""
        self.asked_invites = getattr(self, "asked_invites", [])
        alive_file = cn.dock_alive_path()
        if alive:
            alive_file.parent.mkdir(parents=True, exist_ok=True)
            alive_file.write_text("now")
            os.utime(alive_file, (T0, T0))
        elif alive_file.exists():
            os.utime(alive_file, (T0 - 600, T0 - 600))

        class Database:
            MODE = types.SimpleNamespace(READ_ONLY=0)

            def __init__(self, mode=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        desktop = Recorder()
        desktop.server = ":1.7"
        with unittest.mock.patch.dict(sys.modules, {"notmuch2": types.SimpleNamespace(Database=Database)}), \
                unittest.mock.patch.object(cn, "candidates", lambda db, ids, me, now: ids), \
                unittest.mock.patch.object(cn, "notes_for", lambda db, ids, invites=False: (self.asked_invites.append(invites), list(notes))[1]), \
                unittest.mock.patch.object(cn, "desktop_sender", lambda: desktop), \
                unittest.mock.patch.dict(os.environ, {"COURIER_NO_NOTIFY": ""}):
            handled = cn.after_sync([n.message_id for n in notes], set())
        return handled, desktop

    def test_after_sync_to_the_dock_or_the_desktop(self) -> None:
        # The dock running: the item goes in its feed, nothing to the desktop.
        handled, desktop = self.after_sync([self.ci(1)], alive=True)
        self.assertEqual((handled, desktop.calls), ({"m1@example.test"}, []))
        [item] = cn.Feed.load().items
        self.assertEqual((item["id"], item["status"]), ("ci:lumenlabs/lumen-app:main", "open"))
        # The dock down: a desktop notification, so nothing is lost; the feed
        # still hears the mail and resolves what it settles.
        merged = note("state", {"action": "Merged", "number": "274", "repo": "lumenlabs/lumen-app", "title": "T"},
                      "Re: [lumenlabs/lumen-app] T (PR #274)", n=2)
        alert = self.service(3, "Security alert: new sign-in", "Google", "google-com", "google.com")
        handled, desktop = self.after_sync([merged, alert], alive=False)
        self.assertEqual([c["title"] for c in desktop.calls], ["Google · Security alert"])
        self.assertEqual(len(cn.Feed.load().items), 1)  # the alert went to the desktop, not the feed

    def test_no_feed_while_the_dock_is_down(self) -> None:
        handled, desktop = self.after_sync([self.ci(1)], alive=False)
        self.assertEqual(len(desktop.calls), 1)
        self.assertFalse(cn.dock_path().exists())


class RealIndex(unittest.TestCase):
    """Mark read through the real code path, on a real (temporary) mail
    index, from a process that, like the dock's `courier-notify action` and
    the listener, has no NOTMUCH_CONFIG: Junco finds its own config."""

    def setUp(self) -> None:
        import courier_sync

        self.sync = courier_sync
        self.home = tempfile.TemporaryDirectory()
        root = Path(self.home.name)
        self.env = unittest.mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
                                                         "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"),
                                                         "COURIER_NO_NOTIFY": "1"})
        self.env.start()
        accounts = [{"id": "personal", "email": "someone@example.com"}]
        (root / "config" / "courier").mkdir(parents=True)
        (root / "config" / "courier" / "accounts.json").write_text(json.dumps({"accounts": accounts}))
        courier_sync.configure(accounts, {"personal": "[Gmail]/All Mail"})
        for n in (1, 2):
            folder = courier_sync.mail_dir() / "personal" / "all"
            for part in ("cur", "new", "tmp"):
                (folder / part).mkdir(parents=True, exist_ok=True)
            (folder / "cur" / f"{n}:2,").write_bytes(
                (f"Message-ID: <ci{n}@github.test>\nFrom: GitHub <notifications@github.com>\nTo: someone@example.com\n"
                 f"Subject: [o/r] Run failed: Build tag - v0.0.{n}\nDate: Wed, 25 Nov 2026 10:0{n}:00 +0530\n"
                 "Content-Type: text/plain; charset=utf-8\n\nA run failed.\n").encode())
        courier_sync.index(accounts)
        os.environ.pop("NOTMUCH_CONFIG", None)  # as the dock's process has it

    def tearDown(self) -> None:
        self.env.stop()
        self.home.cleanup()

    def unread(self) -> set[str]:
        import notmuch2

        os.environ["NOTMUCH_CONFIG"] = str(self.sync.config_dir() / "notmuch-config")
        try:
            with notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY) as db:
                return {m.messageid for m in db.messages("tag:unread")}
        finally:
            os.environ.pop("NOTMUCH_CONFIG", None)

    def test_the_docks_mark_read_with_no_notmuch_config(self) -> None:
        import contextlib
        import io

        self.assertEqual(self.unread(), {"ci1@github.test", "ci2@github.test"})
        with cn.locked_state():
            feed = cn.Feed()
            feed.items.append({"id": "ci:o/r:Build tag", "unit": "ci:o/r:Build tag", "status": "open", "kind": "ci-failed",
                               "updated": cn.iso(time.time()), "messages": ["ci1@github.test"], "fields": []})
            feed.save()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cn.dock_action("ci:o/r:Build tag", "mark-read"), 0)
        self.assertEqual((out.getvalue(), err.getvalue()), ("Done\n", ""))
        self.assertEqual(self.unread(), {"ci2@github.test"})  # its email read, the other untouched
        self.assertIsNone(cn.Feed.load().find("ci:o/r:Build tag"))  # and the item left the dock

    def test_the_desktop_notifications_mark_read_too(self) -> None:
        with cn.locked_state() as state:
            state["sent"] = {"7": {"ids": ["ci2@github.test"], "link": "", "at": time.time()}}
            state["server"] = ":1.5"
        self.assertEqual(cn.answer(7, cn.ACTION_READ, ":1.5"), cn.ACTION_READ)
        self.assertEqual(self.unread(), {"ci1@github.test"})

    def test_a_failure_is_one_clean_line(self) -> None:
        import contextlib
        import io

        (self.sync.config_dir() / "notmuch-config").unlink()  # no index config at all
        with cn.locked_state():
            feed = cn.Feed()
            feed.items.append({"id": "x", "unit": "x", "status": "open", "kind": "ci-failed", "updated": cn.iso(time.time()),
                               "messages": ["ci1@github.test"], "fields": []})
            feed.save()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cn.dock_action("x", "mark-read"), 1)
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("Mark read failed: "))
        self.assertNotIn("Traceback", err.getvalue())
        self.assertIsNotNone(cn.Feed.load().find("x"))  # failed: the item stays


class Safety(unittest.TestCase):
    def test_inert(self) -> None:
        text = cn.inert("<b>hi</b> [x](https://e.test) ![i][r]\n[r]: https://e.test\x07")
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
        self.assertNotIn("](", text)
        self.assertNotIn("][", text)
        self.assertNotIn("\n", text)
        self.assertNotIn("\x07", text)

    def test_payload(self) -> None:
        try:
            from gi.repository import GLib
        except ImportError:
            self.skipTest("no PyGObject")
        calls = []

        class Bus:
            def call_sync(self, *args):
                calls.append(args)
                return GLib.Variant("(u)", (7,))

        desktop = object.__new__(cn.Desktop)
        desktop.bus = Bus()
        hostile = comment(1, T0)
        nid = desktop.notify(hostile, "<i>@x</i> commented", "[click](https://evil.test)", "critical", 3)
        self.assertEqual(nid, 7)
        name, path, interface, method, params = calls[0][:5]
        self.assertEqual((name, method), ("org.freedesktop.Notifications", "Notify"))
        app, replaces, icon, summary, body, actions, hints, timeout = params.unpack()
        self.assertEqual((app, replaces, icon, timeout), ("Junco", 3, "courier", -1))
        self.assertNotIn("<", summary)
        self.assertNotIn("](", body)
        self.assertEqual(actions, [cn.ACTION_LINK, "Open on GitHub", cn.ACTION_OPEN, "Open in Junco", cn.ACTION_READ, "Mark read"])
        self.assertEqual(hints["urgency"], 2)
        self.assertEqual(hints["desktop-entry"], "courier")

    def test_no_link_button_for_a_link_courier_wont_open(self) -> None:
        bad = comment(1, T0)
        bad.link = "javascript:alert(1)"
        self.assertNotIn(cn.ACTION_LINK, cn.actions_for(bad))


class Buttons(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.env = unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.folder.name, "XDG_CONFIG_HOME": self.folder.name})
        self.env.start()
        with cn.locked_state() as state:
            state.update(server=":1.5", groups={"personal:comments:r:PR #1": {"id": 4, "last": T0}},
                         sent={"4": {"link": "https://github.com/o/r/pull/1", "ids": ["a@x", "b@x"], "builtin": True},
                               "5": {"link": "https://evil.test/", "ids": ["-rf@x"], "builtin": True}})

    def tearDown(self) -> None:
        self.env.stop()
        self.folder.cleanup()

    def test_only_our_server_and_our_notifications(self) -> None:
        self.assertEqual(cn.answer(4, cn.ACTION_LINK, ":1.9"), "not ours")
        self.assertEqual(cn.answer(99, cn.ACTION_LINK, ":1.5"), "not ours")

    def test_open_on_github(self) -> None:
        with unittest.mock.patch.object(cn.subprocess, "Popen") as popen:
            self.assertEqual(cn.answer(4, cn.ACTION_LINK, ":1.5"), cn.ACTION_LINK)
            self.assertEqual(popen.call_args[0][0], ["xdg-open", "https://github.com/o/r/pull/1"])
            # A built-in template's link goes to GitHub or nowhere.
            cn.answer(5, cn.ACTION_LINK, ":1.5")
            self.assertEqual(popen.call_count, 1)

    def test_open_in_courier_and_mark_read(self) -> None:
        with unittest.mock.patch.object(cn.subprocess, "run") as run, unittest.mock.patch.object(cn, "mark_read") as mark:
            run.return_value.returncode = 0
            cn.answer(4, cn.ACTION_OPEN, ":1.5")
            self.assertEqual(run.call_args[0][0][-3:], ["courier", "open", "b@x"])
            cn.answer(5, cn.ACTION_OPEN, ":1.5")  # an id like an option is never passed on
            self.assertEqual(run.call_count, 1)
            cn.answer(4, cn.ACTION_READ, ":1.5")
            self.assertEqual(mark.call_args[0][0]["ids"], ["a@x", "b@x"])

    def test_closing_forgets_and_restarts_the_group(self) -> None:
        cn.closed(4, ":1.5")
        with cn.locked_state() as state:
            self.assertNotIn("4", state["sent"])
            self.assertEqual(state["groups"], {})

    def test_no_notifications_when_turned_off(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"COURIER_NO_NOTIFY": "1"}):
            self.assertEqual(cn.after_sync(["x@y"], set()), set())


class BuiltinMatch(unittest.TestCase):
    FINGERPRINT = "notifications@github.com|…|0123456789"
    VERDICT = ("i=1; mx.google.com; dkim=pass header.i=@github.com header.s=pf2026 header.b=abc; spf=pass (google.com: domain of"
               " noreply@github.com designates 192.0.2.1 as permitted sender) smtp.mailfrom=noreply@github.com;"
               " dmarc=pass (p=QUARANTINE sp=REJECT dis=NONE) header.from=github.com")
    GMAIL = "from out-1.smtp.github.com (out-1.smtp.github.com. [192.0.2.1]) by mx.google.com with ESMTPS id x1"

    def setUp(self) -> None:
        self.templates = load("courier_templates")
        self.templates._builtins = {self.FINGERPRINT: {"id": "github.x", "kind": "comment", "surface": "html"}}

    def mail(self, *headers: tuple[str, str]):
        import email.message

        parsed = email.message.EmailMessage()
        for name, value in headers:
            parsed[name] = value
        return types.SimpleNamespace(fingerprint=self.FINGERPRINT, account="personal", address="notifications@github.com",
                                     parsed=parsed)

    def delivered(self, verdict: str | None = None, *below: tuple[str, str]):
        """Headers as Gmail writes them on delivery, then the sender's own."""
        return self.mail(("Delivered-To", "me@example.test"), ("Received", "by 2002:a05:7000:b250 with SMTP id x"),
                         ("ARC-Authentication-Results", verdict or self.VERDICT), ("Received", self.GMAIL),
                         ("Authentication-Results", (verdict or self.VERDICT).split(";", 1)[1]), *below,
                         ("From", "Someone <notifications@github.com>"))

    def test_verified_github_mail_gets_the_builtin(self) -> None:
        chosen = self.templates.match(self.delivered(), [])
        self.assertEqual((chosen["id"], chosen["builtin"]), ("github.x", True))

    def test_taught_template_wins_over_builtin(self) -> None:
        mine = {"id": "abc", "account": "personal", "fingerprint": self.FINGERPRINT}
        chosen = self.templates.match(self.delivered(), [mine])
        self.assertEqual((chosen["id"], chosen["kind"], chosen["builtin"]), ("abc", "comment", False))
        other = types.SimpleNamespace(fingerprint="someone@else|…|text", account="personal", address="someone@else", parsed=None)
        self.assertIsNone(self.templates.match(other, []))

    def test_taught_values_lie_over_the_builtins(self) -> None:
        """Taught over a built-in: the notification still has the built-in's
        fields, with the taught ones (names matched) over them."""
        mail = self.delivered()
        mine = {"id": "abc", "account": "personal", "fingerprint": self.FINGERPRINT}
        reads = {"github.x": {"status": "ok", "values": {"repo": "o/r", "branch": "main"}, "missing": []},
                 "abc": {"status": "partial", "values": {"Repo": "o/fork", "PR": "12", "Failed Job": "lint"}, "missing": []}}
        with unittest.mock.patch.object(self.templates, "read_fields", lambda learned, template, mail: reads[template["id"]]), \
                unittest.mock.patch.object(self.templates, "_learned", lambda template: None):
            template, fields = self.templates.fields_for(mail, [mine])
        self.assertEqual(template["id"], "abc")
        self.assertEqual(fields["values"], {"repo": "o/fork", "branch": "main", "number": "12", "failed job": "lint"})
        self.assertEqual(fields["status"], "ok")

    def test_forged_github_mail_gets_no_builtin(self) -> None:
        sender_written = ("ARC-Authentication-Results", self.VERDICT)
        forged = {
            "no verdict": self.mail(("Received", self.GMAIL), ("From", "x <notifications@github.com>")),
            "DMARC failed": self.delivered("i=1; mx.google.com; spf=softfail smtp.mailfrom=evil.test; dmarc=fail header.from=github.com"),
            # Gmail's own verdict says fail; the sender's, below it, says pass.
            "the sender's verdict": self.delivered("i=1; mx.google.com; dmarc=fail header.from=github.com", sender_written),
            # Never through Gmail's door: nothing is Gmail's word.
            "no Gmail Received": self.mail(sender_written, ("From", "x <notifications@github.com>")),
            "another server": self.delivered("i=1; mx.evil.test; dmarc=pass header.from=github.com"),
            "a quoted envelope sender": self.delivered(
                'i=1; mx.google.com; spf=pass smtp.mailfrom="a;dmarc=pass header.from=github.com"@evil.test;'
                " dmarc=fail header.from=github.com"),
            "a comment": self.delivered("i=1; mx.google.com; dmarc=fail (dmarc=pass header.from=github.com) header.from=evil.test"),
            "a longer domain": self.delivered("i=1; mx.google.com; dmarc=pass header.from=github.com.evil.test"),
            "another domain": self.delivered("i=1; mx.google.com; dmarc=pass header.from=evil.test"),
            "pass as a property": self.delivered("i=1; mx.google.com; dmarc=fail policy.x=dmarc=pass header.from=evil.test"),
        }
        for name, mail in forged.items():
            self.assertIsNone(self.templates.match(mail, []), name)

    def gmail(self, verdict: str):
        import email.message

        parsed = email.message.EmailMessage()
        parsed["ARC-Authentication-Results"] = verdict
        parsed["Received"] = self.GMAIL
        return parsed

    def test_a_subdomain_sender_of_a_verified_domain(self) -> None:
        """Gmail reports team@info.hostinger.com's DMARC pass as header.from=hostinger.com."""
        parsed = self.gmail("i=1; mx.google.com; dkim=pass header.i=@info.hostinger.com; dmarc=pass header.from=hostinger.com")
        mail = types.SimpleNamespace(address="team@info.hostinger.com", parsed=parsed)
        self.assertEqual(self.templates.verified_domain(mail), "info.hostinger.com")
        self.assertTrue(self.templates.vouched(mail, "hostinger.com"))
        self.assertFalse(self.templates.vouched(mail, "nger.com"))
        self.assertEqual(self.templates.verified_domain(types.SimpleNamespace(address="team@hostinger.com.evil.test", parsed=parsed)), "")

    def test_service_mail_by_sender_with_no_template(self) -> None:
        self.templates._services = {"team@info.hostinger.com": {"id": "hostinger-com", "brand": "Hostinger", "domain": "hostinger.com",
                                                                 "senders": ["team@info.hostinger.com"]}}
        parsed = self.gmail("i=1; mx.google.com; dmarc=pass header.from=hostinger.com")
        mail = types.SimpleNamespace(fingerprint="team@info.hostinger.com|…|abcdef0123", account="personal",
                                     address="team@info.hostinger.com", parsed=parsed)
        chosen = self.templates.match(mail, [])
        self.assertEqual((chosen["kind"], chosen["service"], chosen["brand"], chosen["domain"], chosen["id"]),
                         ("service", "hostinger-com", "Hostinger", "hostinger.com", "hostinger-com.mail"))
        mail.parsed = self.gmail("i=1; mx.google.com; dmarc=fail header.from=hostinger.com")
        self.assertIsNone(self.templates.match(mail, []))

    def test_private_services_come_from_their_own_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "private.json").write_text(json.dumps({"services": [
                {"id": "a-bank", "brand": "A Bank", "domain": "abank.example", "senders": ["alerts@abank.example"]}]}))
            with unittest.mock.patch.dict(os.environ, {"COURIER_PRIVATE_BUILTINS": folder}):
                fresh = load("courier_templates")
                self.assertEqual(fresh.services()["alerts@abank.example"]["brand"], "A Bank")

    def test_tokens(self) -> None:
        server, results = self.templates.auth_results('mx.google.com 1; spf=pass (a; b) smtp.mailfrom="x;y"@z; dmarc=pass header.from=a.b')
        self.assertEqual(server, "mx.google.com")
        self.assertEqual(results, [["spf=pass", "smtp.mailfrom=\"\"@z"], ["dmarc=pass", "header.from=a.b"]])


if __name__ == "__main__":
    unittest.main()
