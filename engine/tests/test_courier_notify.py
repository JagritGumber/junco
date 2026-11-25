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
