"""Courier's built-in GitHub templates (engine/builtin_templates/): they
must hold GitHub's own boilerplate and structure, never anything from the
mail they were learned on (no repo, person, hash, number or subject).

The shape checks and the reviewed allowlist run always. Scanning the file
against the real mail it was learned from needs that mail, so it runs only
with COURIER_SCAN_REAL_MAIL=1 (read-only: tools/build_builtin_templates.py
--check)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))


import courier_fields as fields  # noqa: E402 - as test_courier_fields (its dataclasses need it registered)

# GitHub's templates (the other file, services.json, is checked below).
FILES = [ENGINE / "builtin_templates" / "github.json"]
SERVICES = ENGINE / "builtin_templates" / "services.json"

KINDS = {"comment", "issue-comment", "commit-comment", "review", "review-requested", "state", "push", "ci-failed",
         "security-advisory", "dependabot-digest", "account-notice"}
# GitHub's own words, as its notification emails say them, reviewed by
# hand: every fixed text, link label and landmark the built-ins hold must
# be one of these. A rebuild that learns new text fails here until someone
# reads it and adds it. ("0" is any number; the address is GitHub's.)
BOILERPLATE = {
    ", or", ".", "·", "—", "•", "・", "or", "Closed", "Job", "Note:", "Status", "Terms", "Privacy", "Version", "Dependency",
    "Annotations", "Vulnerabilities", "repository", "unsubscribe", "Unsubscribe", "Thanks!", "Contact us", "You can",
    "Hello there!", "Upgrade to", "Defined in", "CVE-0-0", "High severity", "Moderate severity",
    "0 Colin P Kelly Jr St.", "0 Colin P Kelly Jr Street", "San Francisco, CA 0", "GitHub, Inc.",
    "GitHub, Inc. ・0 Colin P Kelly Jr Street ・San Francisco, CA 0",
    "Affected Repositories", "Button not working?", "Change how you receive security alert emails in your",
    "Copy and paste this link into your browser:", "Email preferences", "Getting a 0 error?", "GitHub Actions Usage",
    "Known security vulnerabilities detected", "Learn more about this alert",
    "Link not working? Paste the following link into your browser:", "Make sure you’re signed in as", "Manage budgets",
    "Manage your GitHub Actions notifications", "Manage your GitHub email preferences", "Notification settings",
    "Reply to this email directly,", "Review all vulnerable dependencies", "Sign in to GitHub", "Sign into GitHub",
    "This invitation was intended for", "This invitation will expire in 0 day.", "Updated Permissions Request",
    "View all alerts", "View billing settings", "View invitation", "View it on GitHub", "view it on GitHub",
    "View workflow run", "You are receiving this because you are subscribed to this thread.",
    "You are receiving this because your review was requested.", "accept or decline", "as completed.", "block them",
    "commented on this pull request.", "contact support.", "left a comment", "notification preferences",
    "pushed 0 commit.", "report abuse", "repository security updates from", "requested your review on:",
    "security alert digest", "the week of", "this invitation. You can also visit", "to learn a bit more about them.",
}
# The words an anchor may hold (GitHub's subject and body wording).
ANCHOR_WORDS = {"advisory", "affects", "at", "commit", "for", "issue", "least", "of", "on", "one", "pr", "pull", "pushed",
                "request", "run", "security", "severity", "the", "this", "week", "workflow"}
SHAPES = {*fields.SHAPES, r"[\s\S]+", r"https?://\S+|mailto:\S+"}
FINGERPRINT = re.compile(r"(?:notifications|noreply|support)@github\.com\|(?:\[\*\] )?…(?: \((?:PR #0|Issue #0|h)\))?\|[0-9a-f]{10}")


def anchor_words(regex: str) -> set[str]:
    plain = re.sub(r"\\[a-zA-Z]|\[[^\]]*\]|[(){}?*+|^$\\]", " ", regex or "")
    return {word.lower() for word in re.findall(r"[^\W\d_]{2,}", plain)}


def strings(data) -> list[str]:
    """Every string in the file (keys too), its fingerprints and ids aside:
    hashes of markup, with GitHub's own sender addresses."""
    if isinstance(data, dict):
        return [text for key, value in data.items() if key not in ("fingerprints", "id") for text in [key, *strings(value)]]
    if isinstance(data, list):
        return [text for item in data for text in strings(item)]
    return [data] if isinstance(data, str) else []


class BuiltinTemplates(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(FILES, "no built-in templates shipped")
        self.files = {path.name: json.loads(path.read_text()) for path in FILES}

    def templates(self):
        for data in self.files.values():
            yield from data["templates"]

    def test_each_template_is_whole_and_loads(self) -> None:
        ids = set()
        for template in self.templates():
            self.assertIn(template["kind"], KINDS, template["id"])
            self.assertNotIn(template["id"], ids)
            ids.add(template["id"])
            self.assertEqual(template["surface"], "html")
            for fingerprint in template["fingerprints"]:
                self.assertRegex(fingerprint, f"^{FINGERPRINT.pattern}$")
            learned = fields.Template.from_json(template["learned"])
            self.assertTrue(learned.extractors, template["id"])
            self.assertEqual([f["name"] for f in template["fields"]], [e.name for e in learned.extractors])

    def test_only_reviewed_boilerplate(self) -> None:
        for template in self.templates():
            for text in template["learned"]["fixed"]:
                self.assertIn(text, BOILERPLATE, f"{template['id']}: fixed text not reviewed")
            for item in template["learned"]["fields"]:
                for text in (item["label"], item["landmark"]):
                    if text:
                        self.assertIn(text, BOILERPLATE, f"{template['id']} {item['name']}: label or landmark not reviewed")
                for side in (item["left"], item["right"]):
                    self.assertLessEqual(anchor_words(side), ANCHOR_WORDS, f"{template['id']} {item['name']}: anchor {side!r}")
                self.assertIn(item["shape"], SHAPES, f"{template['id']} {item['name']}: a shape the engine doesn't make")

    def test_no_values_in_any_shape(self) -> None:
        for name, data in self.files.items():
            text = "\n".join(strings(data))
            # No hash, no number of three digits or more, no address, no
            # owner/repo, no @login, no web address.
            self.assertIsNone(re.search(r"(?<![\w-])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])", text), name)
            self.assertIsNone(re.search(r"\d{3,}", text), name)
            self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), name)
            self.assertIsNone(re.search(r"https?://|www\.", text), name)
            self.assertIsNone(re.search(r"(?<![\\\w])@[A-Za-z][\w-]+", text), name)
            for template in data["templates"]:
                for text in template["learned"]["fixed"]:
                    self.assertIsNone(re.search(r"[\w.-]+/[\w.-]+", text), text)

    @unittest.skipUnless(os.environ.get("COURIER_SCAN_REAL_MAIL") == "1", "set COURIER_SCAN_REAL_MAIL=1 to scan against your own mail")
    def test_nothing_from_the_real_mail(self) -> None:
        tool = ENGINE.parent / "tools" / "build_builtin_templates.py"
        result = subprocess.run([sys.executable, "-I", str(tool), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


# A service's role addresses: never a person's.
ROLE = re.compile(r"(?:^|[._+-])(?:no-?reply|do-?not-?reply|notifications?|notify|alerts?|security|accounts?|team|em|"
                  r"updates?|news(?:letters)?|messages|messaging|digest|jobs?|jobalerts|recommendations|store|order|payments?|"
                  r"marketplace|analytics|cloudplatform|google|gemini|googleaistudio|googledev|googleplay|kaggle|meetings|"
                  r"playpartners|sc|stitch|pinterest)(?:$|[._+-])", re.I)
MONEY = re.compile(r"bank|broker|trad(?:e|ing)|invest|financ|fund|mutual|\bmf\b|insur|crypto|coin|exchange|wallet|pay|tax|loan|"
                   r"credit|stock|demat|capital|wealth|stripe", re.I)
DEDICATED = re.compile(r"(?:^|[._+-])(?:security|alerts?|auth|accounts?|payments?|billing|verify|verification|login|signin)"
                       r"(?:$|[._+-])", re.I)
# Generic senders reviewed by hand: only the service's own words.
REVIEWED_ALERTS = {"team@info.hostinger.com", "team@updates.hostinger.com", "noreply@notify.cloudflare.com", "no-reply@spotify.com"}
# The buttons a service template may read, reviewed by hand.
SERVICE_LABELS = {"Check activity", "View job", "See more", "see more", "See more on LinkedIn"}


class Services(unittest.TestCase):
    """services.json: mainstream services only, their role addresses, and
    templates whose only field is a call to action's link."""

    def setUp(self) -> None:
        self.data = json.loads(SERVICES.read_text())

    def test_services(self) -> None:
        ids = set()
        for service in self.data["services"]:
            self.assertRegex(service["id"], r"^[a-z0-9-]+$")
            self.assertNotIn(service["id"], ids)
            ids.add(service["id"])
            self.assertRegex(service["domain"], r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+$")
            self.assertIsNone(MONEY.search(service["domain"]), f"{service['domain']}: money stays out of the repo")
            self.assertTrue(service["brand"].strip())
            self.assertLessEqual(set(service.get("alerts", [])), set(service["senders"]), service["id"])
            for sender in service.get("alerts", []):
                # Dedicated to alerts by name, or reviewed by hand: a generic
                # notify@ may carry someone else's words.
                local, _, host = sender.partition("@")
                self.assertNotRegex(local, r"(?i)messag|comment|mention|discussion|community|invit")
                self.assertTrue(DEDICATED.search(local) or DEDICATED.search(host.split(".")[0]) or sender in REVIEWED_ALERTS,
                                f"{sender}: an alert sender that is neither dedicated nor reviewed")
            for sender in service["senders"]:
                local, _, domain = sender.partition("@")
                self.assertTrue(domain == service["domain"] or domain.endswith("." + service["domain"]), sender)
                self.assertRegex(local, ROLE, f"{sender}: not a role address")

    def test_templates_are_a_link_and_nothing_else(self) -> None:
        senders = {service["id"]: set(service["senders"]) for service in self.data["services"]}
        for template in self.data["templates"]:
            self.assertEqual(template["kind"], "service")
            self.assertIn(template["service"], senders)
            for fingerprint in template["fingerprints"]:
                self.assertIn(fingerprint.split("|", 1)[0], senders[template["service"]])
                self.assertRegex(fingerprint, r"^[^|]+\|[^|]*\|[0-9a-f]{10}$")
            learned = template["learned"]
            self.assertEqual(learned["fixed"], {}, template["id"])
            [field] = learned["fields"]
            self.assertTrue(field["link"])
            self.assertIn(field["label"], SERVICE_LABELS, f"{template['id']}: button words not reviewed")
            self.assertEqual((field["left"], field["right"], field["landmark"]), ("", "", ""))
            self.assertIn(field["shape"], SHAPES)
            fields.Template.from_json(learned)

    def test_no_values(self) -> None:
        text = "\n".join(strings(self.data))
        self.assertIsNone(re.search(r"(?<![\w-])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])", text))
        self.assertIsNone(re.search(r"https?://|www\.", text))
        addresses = {sender for service in self.data["services"] for sender in service["senders"]}
        for found in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
            self.assertIn(found, addresses)

    @unittest.skipUnless(os.environ.get("COURIER_SCAN_REAL_MAIL") == "1", "set COURIER_SCAN_REAL_MAIL=1 to scan against your own mail")
    def test_nothing_from_the_real_mail(self) -> None:
        tool = ENGINE.parent / "tools" / "build_service_templates.py"
        result = subprocess.run([sys.executable, "-I", str(tool), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
