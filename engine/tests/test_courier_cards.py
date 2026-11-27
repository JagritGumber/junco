"""Cards for the notification dock (courier_cards.py): which component each
kind of work gets, its lane and due time, its sections and buttons, and
that every card stays inside the vocabulary: plain text, file:// pictures,
http(s) links, at most 3 buttons.

Made-up items only. The rules' own examples, written from his real mail,
are local to his machine (never in a repo): when that file is there,
Examples runs every one of them too."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import courier_cards as cards  # noqa: E402

NOW = dt.datetime(2026, 11, 25, 15, 0).astimezone().timestamp()


def at(hours: float = 0) -> str:
    return dt.datetime.fromtimestamp(NOW + hours * 3600).astimezone().isoformat(timespec="seconds")


def item(kind: str, fields: dict | None = None, **extra) -> dict:
    base = {"id": f"x:{kind}", "unit": f"x:{kind}", "status": "open", "kind": kind, "urgency": "normal", "source": "GitHub", "icon": "github",
            "title": "A title", "time": at(-0.2), "updated": at(-0.2), "domain": "github.com", "account": "personal", "messages": ["m1@x"],
            "fields": [{"key": k, "label": k, "value": v} for k, v in (fields or {}).items()]}
    base.update(extra)
    return base


def ids(made: dict) -> list[str]:
    return [a["id"] for a in made["actions"]]


def types(made: dict) -> list[str]:
    return [s["type"] for s in made["sections"]]


class Components(unittest.TestCase):
    """Each kind of work, its component."""

    def test_a_security_alert_asks_was_this_you(self) -> None:
        made = cards.card(item("security-alert", {"service": "Google", "event": "New sign-in", "device": "Linux laptop", "place": "Pune, India"},
                               source="Google", domain="google.com", body="We noticed a new sign-in from 203.0.113.9",
                               card={"secure": "https://myaccount.google.com/notifications"}), NOW)
        self.assertEqual((made["component"], made["lane"], made["due"]), ("DecisionPanel", "action", None))
        self.assertEqual(made["sections"][0]["text"], "Was this you?")
        self.assertEqual([f["label"] for f in made["sections"][1]["items"]], ["Device", "When", "Where", "Account"])
        self.assertEqual(ids(made), ["its-me", "secure"])
        self.assertEqual(made["actions"][0]["resolves"], True)
        self.assertEqual((made["actions"][1]["role"], made["actions"][1]["url"]), ("danger", "https://myaccount.google.com/notifications"))
        self.assertEqual(made["title"], "New sign-in on Linux laptop")
        self.assertEqual(made["badge"]["tone"], "tertiary")  # urgency is never error
        self.assertNotIn("tone", made["sections"][0])

    def test_a_secure_page_only_from_the_services_own_domain(self) -> None:
        for page in ("https://evil.example/google.com/security", "http://myaccount.google.com.evil.example/", "javascript:alert(1)", ""):
            made = cards.card(item("security-alert", {"service": "Google"}, source="Google", domain="google.com", card={"secure": page}), NOW)
            self.assertEqual(ids(made), ["its-me"], page)

    def test_a_review_request(self) -> None:
        made = cards.card(item("review-requested", {"who": "Priya Natarajan", "pr": "#274", "pr-title": "Team invites", "repo": "lumen-app"},
                               github={"owner": "o", "repo": "lumen-app", "kind": "pr", "number": "274"}, link="https://github.com/o/lumen-app/pull/274",
                               image="file:///cache/priya.png", body="Sends one invite per teammate.\n\n- batches 20",
                               meta={"files": "7", "additions": "214", "deletions": "38", "ci": "passing", "commits": "5", "base": "main",
                                     "head": "feature/invites"},
                               files=[{"path": f"src/f{n}.ts", "additions": n, "deletions": 0} for n in range(5)]), NOW)
        self.assertEqual((made["component"], made["lane"]), ("ReviewPanel", "action"))
        self.assertEqual(types(made), ["person", "status", "branch", "size", "stats", "files", "text"])
        self.assertEqual(ids(made), ["approve", "open", "comment"])
        self.assertEqual([a["type"] for a in made["actions"]], ["confirm", "url", "input"])
        files = next(s for s in made["sections"] if s["type"] == "files")
        self.assertEqual((len(files["items"]), files["more"]), (3, 2))
        self.assertEqual(made["sections"][0]["image"], "file:///cache/priya.png")

    def test_a_pr_comment_with_its_diff(self) -> None:
        made = cards.card(item("review-comment", {"who": "Tomas Ruiz", "pr": "#268", "repo": "lumen-app"},
                               github={"owner": "o", "repo": "lumen-app", "kind": "pr", "number": "268", "anchor": "review-comment", "id": "9"},
                               body="Could we batch these?\n\n```ts\nawait all()\n```",
                               context={"file": "src/x.ts", "line": 42, "hunk": ["@@ -38,4 +38,5 @@ fn", " a", "-b", "+c", "+d", " e"]},
                               thread=[{"who": "Priya", "time": at(-2), "body": "nit"}, {"who": "Sam", "time": at(-1), "body": "ok"}]), NOW)
        self.assertEqual((made["component"], made["lane"]), ("CommentPanel", "action"))
        diff = next(s for s in made["sections"] if s["type"] == "diff")
        self.assertEqual(diff["file"], "src/x.ts:42")
        self.assertEqual(diff["lines"], [{"n": 39, "kind": "add", "text": "c"}, {"n": 40, "kind": "add", "text": "d"},
                                         {"n": 41, "kind": "ctx", "text": "e"}])
        self.assertEqual(next(s for s in made["sections"] if s["type"] == "thread")["count"], 2)
        self.assertEqual(ids(made), ["reply", "react-plus1", "resolve-thread"])
        self.assertEqual(made["actions"][0]["hint"], "Reply to Tomas")
        # A comment on an issue: no thread to resolve.
        issue = cards.card(item("comment", {"who": "@sam"}, github={"owner": "o", "repo": "r", "kind": "issue", "number": "3",
                                                                   "anchor": "issue-comment", "id": "5"}, body="hi"), NOW)
        self.assertEqual(ids(issue), ["reply", "react-plus1"])

    def test_ci(self) -> None:
        failed = cards.card(item("ci-failed", {"repo": "lumen-app", "branch": "main", "workflow": "CI", "jobs": ["test · failed in 2 minutes"]},
                                 github={"owner": "o", "repo": "lumen-app", "kind": "run", "run": "9"}, link="https://github.com/o/lumen-app/actions/runs/9",
                                 card={"jobs": [{"name": "build", "state": "passed"}, {"name": "test", "state": "failed"}]},
                                 log=["── test: failure", " ✓ a", " ✗ sends one email per teammate", "   AssertionError: expected 3",
                                      "    ❯ src/send.test.ts:57:31"]), NOW)
        self.assertEqual((failed["component"], failed["lane"]), ("StatusSummary", "action"))
        self.assertEqual(failed["sections"][0], {"type": "status", "state": "failed", "label": "1 of 2 jobs failed"})
        failure = next(s for s in failed["sections"] if s["type"] == "failure")
        self.assertEqual((failure["title"], failure["location"]), ("sends one email per teammate", "src/send.test.ts:57:31"))
        self.assertEqual(ids(failed), ["rerun-failed", "open-run"])
        self.assertEqual(failed["badge"]["tone"], "error")
        # GitHub's own error annotation says what broke (not its generic exit line).
        annotated = cards.failure_of(["── build: failure", "env:", "##[endgroup]", "Upload starting",
                                      "##[error]Failed to CreateArtifact: Artifact storage quota has been hit.",
                                      "##[error]Process completed with exit code 1."])
        self.assertEqual(annotated["title"], "Failed to CreateArtifact: Artifact storage quota has been hit.")
        self.assertEqual(cards.failure_of(["##[error]Process completed with exit code 2."])["title"], "Process completed with exit code 2.")
        self.assertIsNone(cards.failure_of(["Tests: 12 passed, 0 failed", "done"]))
        passed = cards.card(item("ci-passed", {"repo": "r", "branch": "main"}), NOW)
        self.assertEqual((passed["component"], passed["lane"], ids(passed)), ("StatusSummary", "update", []))

    def test_money(self) -> None:
        bill = cards.card(item("bill", {"service": "Example Bank"}, source="Example Bank", domain="bank.example",
                               card={"amount": 18240.0, "currency": "INR", "due": "2026-11-28", "minimum": "₹910", "card": "4421",
                                     "pay": "https://netbanking.bank.example/pay"}), NOW)
        self.assertEqual((bill["component"], bill["lane"]), ("DataTable", "action"))
        self.assertEqual(bill["sections"][0], {"type": "amount", "value": 18240, "currency": "INR", "label": "Amount due"})
        self.assertEqual([r["label"] for r in bill["sections"][1]["rows"]], ["Due", "Minimum due", "Card"])
        self.assertFalse([r for r in bill["sections"][1]["rows"] if r.get("tone") == "error"])
        self.assertTrue(bill["due"].startswith("2026-11-28T23:59:59"))
        self.assertEqual(ids(bill), ["pay", "mark-paid"])
        self.assertEqual(bill["actions"][0]["url"], "https://netbanking.bank.example/pay")
        # Pay opens only the bank's own pages.
        elsewhere = cards.card(item("bill", source="Example Bank", domain="bank.example", card={"pay": "https://pay.evil.example/"}), NOW)
        self.assertEqual(ids(elsewhere), ["mark-paid"])
        failed = cards.card(item("payment-failed", {"merchant": "Spotify", "amount": "₹119", "card": "ending 4421"}, source="Spotify",
                                 domain="spotify.com", urgency="critical", card={"amount": 119.0, "currency": "INR"}), NOW)
        self.assertEqual((failed["component"], failed["lane"], failed["badge"]["text"]), ("DataTable", "action", "Failed"))
        statement = cards.card(item("statement", {"service": "Broker"}, source="Broker", card={"period": "01 Nov 2026 – 21 Nov 2026"}), NOW)
        self.assertEqual((statement["component"], statement["lane"], ids(statement), statement["due"]), ("DataTable", "update", [], None))
        owing = cards.card(item("statement", source="Card Co", domain="card.example",
                                card={"amount": 500, "currency": "USD", "due": "2026-12-02", "pay": "https://card.example/pay"}), NOW)
        self.assertEqual((owing["lane"], ids(owing)), ("action", ["pay", "mark-paid"]))
        receipt = cards.card(item("invoice", source="Cloudflare", card={"amount": 5, "currency": "USD"}), NOW)
        self.assertEqual((receipt["component"], receipt["lane"], ids(receipt)), ("DataTable", "update", []))

    def test_an_invitation_against_his_day(self) -> None:
        start = dt.datetime(2026, 11, 26, 15, 0).astimezone()
        invite = {"uid": "u1", "method": "REQUEST", "title": "Design review", "start": start.isoformat(),
                  "end": (start + dt.timedelta(minutes=45)).isoformat(), "organizer": {"name": "Priya", "email": "p@x"},
                  "attendees": [{"name": f"P{n}", "email": ""} for n in range(7)], "where": "", "conference": "https://meet.google.com/abc"}
        day = [{"title": "1:1", "start": (start + dt.timedelta(minutes=30)).isoformat(), "end": (start + dt.timedelta(hours=1)).isoformat()},
               {"title": "Lunch", "start": (start - dt.timedelta(hours=2)).isoformat(), "end": (start - dt.timedelta(hours=1)).isoformat()},
               {"title": "Design review", "uid": "u1", "response": "needsAction", "start": start.isoformat(),
                "end": (start + dt.timedelta(minutes=45)).isoformat()},
               {"title": "Holiday", "allDay": True, "start": "2026-11-26", "end": "2026-11-27"}]
        asked = []
        made = cards.card(item("invite", source="Calendar", card={"invite": invite}), NOW,
                          calendar=lambda first, last: asked.append((first, last)) or day, can_answer=lambda account: True)
        self.assertEqual(asked, [(dt.date(2026, 11, 26), dt.date(2026, 11, 27))])
        self.assertEqual((made["component"], made["lane"], made["due"]), ("SchedulingPanel", "action", start.isoformat()))
        self.assertEqual(made["clashes"], ["1:1"])  # not lunch, not the invite itself, not the all-day one
        self.assertEqual((made["badge"]["text"], made["badge"]["tone"]), ("Clashes with 1:1", "tertiary"))  # urgency, never error
        strip = next(s for s in made["sections"] if s["type"] == "day")
        self.assertEqual([e["title"] for e in strip["events"]], ["1:1", "Lunch"])
        self.assertLessEqual(strip["from"], 13)
        self.assertEqual(next(s for s in made["sections"] if s["type"] == "people")["summary"], "7 invited")
        self.assertEqual(next(s for s in made["sections"] if s["type"] == "place"), {"type": "place", "kind": "meet", "label": "Google Meet"})
        self.assertEqual(ids(made), ["accept", "maybe", "decline"])
        # Junco may only read his calendar (no calendar.events yet): no button that would fail; Google's own page instead.
        day[2]["link"] = "https://www.google.com/calendar/event?eid=abc"
        readonly = cards.card(item("invite", card={"invite": invite}), NOW, calendar=lambda a, b: day)
        self.assertEqual([(a["id"], a["type"], a["url"]) for a in readonly["actions"]],
                         [("answer-in-calendar", "url", "https://www.google.com/calendar/event?eid=abc")])
        day[2]["link"] = ""
        self.assertEqual(cards.card(item("invite", card={"invite": invite}), NOW, calendar=lambda a, b: day)["actions"], [])
        # Answered already (his calendar says so): news, no buttons.
        day[2]["response"] = "accepted"
        answered = cards.card(item("invite", card={"invite": invite}), NOW, calendar=lambda a, b: day, can_answer=lambda a: True)
        self.assertEqual((answered["lane"], ids(answered), answered["badge"]["text"]), ("update", [], "You said yes"))

    def test_a_parcel_and_a_deploy(self) -> None:
        parcel = cards.card(item("parcel", source="Amazon", card={"product": "Headphones", "steps": {"ordered": NOW - 86400, "shipped": NOW - 3600}}),
                            NOW)
        self.assertEqual((parcel["component"], parcel["lane"]), ("Timeline", "update"))
        self.assertEqual([(s["label"], s["state"]) for s in parcel["sections"][0]["items"]],
                         [("Ordered", "done"), ("Shipped", "current"), ("Out for delivery", "pending"), ("Delivered", "pending")])
        delivered = cards.card(item("parcel", card={"steps": {"shipped": NOW - 9000, "delivered": NOW}}), NOW)
        self.assertEqual(delivered["sections"][0]["items"][-1]["state"], "done")
        self.assertEqual(delivered["badge"]["text"], "Delivered")
        deploy = cards.card(item("deploy", {"event": "Deployment ready"}, source="Vercel", card={"steps": {"build": NOW - 60, "live": NOW}}), NOW)
        self.assertEqual((deploy["component"], deploy["lane"], deploy["badge"]["text"]), ("Timeline", "update", "Live"))

    def test_everything_else_is_a_summary(self) -> None:
        made = cards.card(item("notice", {"notice": "Security notice for services running Ruby", "service": "Render", "at": "09:41"},
                               source="Render", summary="Security notice for services running Ruby"), NOW)
        self.assertEqual((made["component"], made["lane"], ids(made)), ("Summary", "update", []))
        self.assertEqual(made["sections"][0], {"type": "facts", "items": [{"icon": "schedule", "label": "at", "value": "09:41"}]})
        self.assertEqual(made["subtitle"], "Security notice for services running Ruby")


class Safety(unittest.TestCase):
    """Whatever a rule (or later a model) proposes, the card stays in bounds."""

    def test_validate_keeps_the_vocabulary(self) -> None:
        made = cards.validate({"component": "MadeUpPanel", "lane": "urgent", "title": "<b>x</b>", "kind": "k",
                               "sections": [{"type": "text", "text": "<img src=https://evil.example/a.png> ![r]\n\n[r]: https://evil.example/b"},
                                            {"type": "script", "src": "x"}],
                               "actions": [{"id": "a", "label": "A", "type": "url", "url": "javascript:alert(1)"},
                                           {"id": "b", "label": "B", "type": "shell"},
                                           *[{"id": f"c{n}", "label": "C", "type": "command"} for n in range(5)]],
                               "badge": {"text": "x", "tone": "#ff0000"}, "original": {"label": "o", "url": "file:///etc/passwd"}}, {})
        self.assertEqual((made["component"], made["lane"]), ("Summary", "update"))
        self.assertEqual(made["title"], "‹b›x‹/b›")
        self.assertEqual(types(made), ["text"])
        text = made["sections"][0]["text"]
        self.assertNotIn("<img", text)
        self.assertNotRegex(text, r"\]:|\]\(")
        self.assertEqual(ids(made), ["c0", "c1", "c2"])  # no bad url, no unknown type, at most 3
        self.assertEqual(made["badge"]["tone"], "")
        self.assertIsNone(made["original"])

    def test_links_browsers_and_python_read_alike(self) -> None:
        for url in ("https://evil.example\\@google.com/x", "https://google.com@evil.example/", "https://user:pw@google.com/",
                    "https://evil.example\\.google.com/", "https://google.com:99999/", "ftp://google.com/"):
            self.assertEqual(cards.web(url), "", url)
            self.assertFalse(cards.on_domain(url, "google.com"), url)
        self.assertTrue(cards.on_domain("https://myaccount.google.com:443/security", "google.com"))
        self.assertFalse(cards.on_domain("https://notgoogle.com/", "google.com"))

    def test_pictures_are_local_files_only(self) -> None:
        made = cards.card(item("comment", {"who": "Eve"}, image="https://evil.example/eve.png", body="hi",
                               github={"owner": "o", "repo": "r", "kind": "pr", "number": "1", "anchor": "issue-comment", "id": "2"},
                               thread=[{"who": "Mal", "avatar": "http://evil.example/m.png", "time": "", "body": "x"}]), NOW)
        self.assertNotIn("image", made["sections"][0])
        thread = next(s for s in made["sections"] if s["type"] == "thread")
        self.assertNotIn("image", thread["people"][0])

    def test_every_card_is_slim(self) -> None:
        for kind in ("security-alert", "review-requested", "review-comment", "ci-failed", "bill", "invite", "parcel", "notice"):
            made = cards.card(item(kind, card={"invite": {"uid": "u", "start": at(20), "end": at(21)}}), NOW, calendar=lambda a, b: [])
            self.assertLessEqual(len(made["actions"]), 3, kind)
            for section in made["sections"]:
                self.assertLessEqual(len(section.get("items", [])), 12, kind)
                self.assertLessEqual(len(section.get("rows", [])), 4, kind)

    def test_reading_an_email_for_its_card(self) -> None:
        html = ('<a href="https://accounts.google.com/AccountChooser?continue=https://myaccount.google.com/notifications">Check activity</a>'
                '<a href="https://evil.example/security">Secure your account</a><a href="https://support.google.com/x">Help</a>')
        facts = cards.mail_facts("security-alert", "Security alert", html, "", "google.com", NOW)
        self.assertTrue(facts["secure"].startswith("https://accounts.google.com/AccountChooser"))
        bill = cards.mail_facts("bill", "Reminder: Your invoice from Deep Example Inc. #F7-0012 is due today",
                                '<a href="https://invoice.stripe.com/i/acct_1/live_x">Pay this invoice</a>',
                                "Amount due $12.50 USD\nDue November 25, 2026", "stripe.com", NOW)
        self.assertEqual((bill["amount"], bill["currency"], bill["due"], bill["merchant"]), (12.5, "USD", "2026-11-25", "Deep Example Inc"))
        self.assertTrue(bill["pay"].startswith("https://invoice.stripe.com/"))
        statement = cards.mail_facts("statement", "Account Statement of your Bank Account ***9012 for the period 01-Jun-2026 TO 31-Aug-2026",
                                     "", "", "bank.example", NOW)
        self.assertEqual((statement["card"], statement["number"], statement["period"]), ("9012", "account", "1 Jun – 31 Aug 2026"))
        weekly = cards.mail_facts("statement", "Weekly Account Statement for AB1234 2026-11-16 - 2026-11-21", "", "", "broker.example", NOW)
        self.assertEqual(weekly["period"], "16 Nov – 21 Nov 2026")
        receipt = cards.mail_facts("invoice", "Your receipt from Example Inc #1", "", "Amount paid $5.00", "stripe.com", NOW)
        self.assertTrue(receipt["paid"])
        parcel = cards.mail_facts("parcel", 'Out for delivery: "Boat Original 2 Pin USB..."', "", "", "amazon.in", NOW)
        self.assertEqual((parcel["step"], parcel["product"]), ("out", "Boat Original 2 Pin USB"))

    def test_dates_and_amounts_as_emails_write_them(self) -> None:
        for words, day in (("16 Nov 2026", "2026-11-16"), ("Nov 16, 2026", "2026-11-16"), ("16/11/2026", "2026-11-16"),
                           ("2026-11-16", "2026-11-16"), ("today", "2026-11-25"), ("tomorrow", "2026-11-26"), ("16-Nov-2026", "2026-11-16"),
                           ("December 3", "2026-12-03")):
            self.assertEqual(str(cards.date_in(words, NOW)), day, words)
        self.assertEqual(cards.money("Rs. 1,299.00 charged; total amount due ₹18,240"), (18240.0, "INR"))
        self.assertEqual(cards.money("You paid €9.99"), (9.99, "EUR"))
        self.assertIsNone(cards.money("no money here"))

    def test_a_v3_item_reads_back(self) -> None:
        made = cards.v3_item(item("ci-failed", {"repo": "r"}), NOW)
        self.assertEqual((made["kind"], made["jkind"], made["component"]), ("CI", "ci-failed", "StatusSummary"))
        # The dock's own Open in Junco and Mark read, after the card's buttons.
        self.assertEqual([a["id"] for a in made["actions"]][-2:], ["open-junco", "mark-read"])
        self.assertTrue(made["actions"][-1]["resolves"])
        back = cards.from_v3(json.loads(json.dumps(made)))
        self.assertEqual((back["kind"], back["title"]), ("ci-failed", "A title"))
        self.assertFalse(set(cards.V3_KEYS) & set(back))


EXAMPLES = Path(os.environ.get("COURIER_CARD_EXAMPLES") or Path.home() / ".local/share/courier/card-examples.json")


@unittest.skipUnless(EXAMPLES.is_file(), "the rules' examples live only on his machine")
class Examples(unittest.TestCase):
    """The human-authored examples, from his own mail: each says what the
    card must be. Read-only; nothing in them leaves this test."""

    def test_every_example(self) -> None:
        examples = json.loads(EXAMPLES.read_text())["examples"]
        self.assertGreaterEqual(len(examples), 20)
        self.assertEqual(oct(EXAMPLES.stat().st_mode & 0o777), "0o600")
        for example in examples:
            with self.subTest(example["id"]):
                want = example["expected"]
                day = example.get("calendar")
                # The examples describe the full card, with calendar write access.
                made = cards.card(example["input"], example["now"], calendar=(lambda a, b, day=day: day or []), can_answer=lambda a: True)
                self.assertEqual(made["component"], want["component"])
                self.assertEqual(made["lane"], want["lane"])
                self.assertEqual(ids(made), want["actions"])
                self.assertEqual(bool(made["due"]), want["due"])
                for section in want.get("sections", []):
                    self.assertIn(section, types(made))


if __name__ == "__main__":
    unittest.main()
