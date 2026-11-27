#!/usr/bin/env python3
"""Courier's notifications for mail it reads fields from.

An email made from a template (a built-in GitHub one, or one you taught:
courier_templates) gets a notification written from its fields instead of
"New mail from X":

    CI failed · lumen-app · main               (critical)
    Review requested · PR #274 · by Priya
    @priya commented on PR #274 · lumen-app  first line of the comment

with Courier's icon and the sender's picture, an urgency per kind, and
buttons: Open on GitHub (the email's link field), Open in Courier, Mark
read. More comments or pushes on one PR within a few minutes update one
notification in place ("3 new comments on PR #274") instead of raising
more. Pushes are silent by default: no popup, only counted.

The rules are a profile, "quiet" (the default) or "all", with any changes
from ~/.config/courier/notify-rules.json over it:

    {"profile": "quiet",
     "window": 300,
     "bot_logins": ["my-deploy-app"],
     "kinds": {"comment": {"reasons": ["author", "mention"]},
               "push": {"urgency": "normal"}}}

- quiet: popups only for failed CI runs, security advisories, review
  requests, and comments and reviews by people (not bots, not you) on your
  own PRs and issues, grouped per PR. Everything else is silent.
- all: a popup for every kind, bots and all, but pushes and passed runs.

Per kind: urgency is "silent" (counted, no popup), "low", "normal" or
"critical"; group collapses a PR's (or issue's) notifications within
`window` seconds; bots and self give the urgency when a bot or you sent it;
reasons lists GitHub's X-GitHub-Reason values ("author": your own PR or
issue; "mention", "comment", "review_requested"…) that get `urgency`, and
otherwise is the urgency for the rest. Kinds: ci-failed, ci-passed,
security-advisory, review-requested, review, comment, issue-comment,
commit-comment, push, state, dependabot-digest, account-notice, taught (a
template you taught over no built-in one), and "*" for any other. A bot is
a login ending in [bot], one of BOT_LOGINS, or one in bot_logins.

Notifications go to the desktop's notification server over D-Bus
(org.freedesktop.Notifications.Notify), so they can be replaced in place
and carry buttons. The buttons are answered by `courier-notify listen`
(courier-notify.service), which waits for the server's ActionInvoked
signal. Text is made inert as courier_sync.desktop_notify makes it (no tag,
Markdown link or control character survives); without D-Bus, notify-send
is used, with "--" before the text, and no buttons.

    courier-notify listen        answer the buttons (the service runs this)
    courier-notify rules         the rules in force, as JSON
    courier-notify counts        the silent notifications counted, per day
    courier-notify action ITEM ACTION   a button in the notification dock
    courier-notify dismiss ITEM         take an item out of the dock
    courier-notify dock                 the dock's feed, as JSON

With "delivery" in the rules file ("dock", "notify" or "auto", the default),
the notes that pop up go to Caelestia's notification dock as cards
(~/.local/state/courier/dock.json, see Feed) instead of desktop
notifications; auto uses the dock while it's running.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import courier_sync as sync

HERE = Path(__file__).resolve().parent
SHELL = HERE.parent / "shell"

# People on your own PRs and issues: not bots, not you, and only where
# GitHub says the thread is yours ("author").
PEOPLE_ON_YOURS = {"urgency": "normal", "group": True, "reasons": ["author"], "otherwise": "silent", "bots": "silent",
                   "self": "silent"}
PROFILES: dict[str, dict] = {
    # Popups only for what needs you: a failed run, an advisory, a review
    # asked of you, and people (not bots) on your own PRs and issues.
    "quiet": {
        "window": 300,
        "kinds": {
            # A red branch alerts once; more failures on it within the hour
            # update that notification ("3 CI failures · lumen-app · main").
            "ci-failed": {"urgency": "critical", "group": True, "window": 3600},
            "security-advisory": {"urgency": "critical"},
            "review-requested": {"urgency": "normal"},
            "comment": dict(PEOPLE_ON_YOURS),
            "issue-comment": dict(PEOPLE_ON_YOURS),
            "review": dict(PEOPLE_ON_YOURS),
            # A template you taught: you asked for it.
            "taught": {"urgency": "normal"},
            # Other services' mail (courier_templates.services), by what it says.
            "security-alert": {"urgency": "critical", "group": True},
            "payment-failed": {"urgency": "critical", "group": True},
            "domain-expiring": {"urgency": "normal", "group": True},
            "incident": {"urgency": "critical", "group": True},
            # Cards for the v7 dock (feed version 3) only, never a popup:
            # a bill, a statement, a receipt, a parcel, a deploy, an invite.
            "bill": {"urgency": "normal", "dock": "v3"},
            "statement": {"urgency": "normal", "dock": "v3"},
            "invoice": {"urgency": "normal", "dock": "v3"},
            "parcel": {"urgency": "normal", "dock": "v3"},
            "deploy": {"urgency": "normal", "dock": "v3"},
            "invite": {"urgency": "normal", "dock": "v3"},
            "*": {"urgency": "silent"},
        },
    },
    # A popup for everything but pushes and passed runs.
    "all": {
        # Seconds within which more of a PR's comments (or pushes) update its
        # notification instead of raising another.
        "window": 300,
        "kinds": {
            # A red branch alerts once; more failures on it within the hour
            # update that notification ("3 CI failures · lumen-app · main").
            "ci-failed": {"urgency": "critical", "group": True, "window": 3600},
            "security-advisory": {"urgency": "critical"},
            "review-requested": {"urgency": "normal"},
            "review": {"urgency": "normal"},
            "comment": {"urgency": "normal", "group": True},
            "issue-comment": {"urgency": "normal", "group": True},
            "commit-comment": {"urgency": "normal", "group": True},
            "push": {"urgency": "silent", "group": True},
            "ci-passed": {"urgency": "silent"},
            # Other services' mail (courier_templates.services), by what it says.
            "security-alert": {"urgency": "critical", "group": True},
            "payment-failed": {"urgency": "critical", "group": True},
            "domain-expiring": {"urgency": "normal", "group": True},
            "incident": {"urgency": "critical", "group": True},
            "*": {"urgency": "normal"},
        },
    },
}
DEFAULT_PROFILE = "quiet"
# Where a note that pops up goes: Caelestia's notification dock (a feed
# file it reads), a desktop notification, or the dock while it's running.
DELIVERIES = ("dock", "notify", "auto")

# What another service's email is, from what it says (its subject): the
# first that fits, in this order. Words, not anyone's mail: the same for
# every service. Marketing ("your offer", "50% off") is checked right after
# the alerts, so "your deal expires soon" is never an expiring domain.
SERVICE_KINDS: list[tuple[str, str, str, str]] = [
    ("security-alert", "Security alert", "security alerts",
     r"security alert|new (?:sign[- ]?in|log[- ]?in|login|device)|(?:sign[- ]?in|log[- ]?in|login) (?:from|attempt|alert)"
     r"|password (?:changed|reset|was)|two[- ]?factor|2-?step verification|suspicious|unusual (?:activity|sign)"
     r"|recovery (?:email|phone)|account (?:locked|compromised)"),
    ("payment-failed", "Payment failed", "failed payments",
     r"payment (?:was |is )?(?:unsuccessful|failed|declined)|(?:card|charge|transaction|debit) (?:was |is )?(?:declined|failed|unsuccessful)"
     r"|auto-?renewals? (?:have |has )?failed|could(?:n't| not) (?:charge|process|renew)"
     r"|(?:payment|invoice|bill)s? (?:is |are )?(?:past due|overdue)|payment (?:issue|problem)"),
    # A parcel's progress before marketing: a product can be called "Sugar Free".
    ("parcel", "Parcel", "parcels",
     r"^(?:ordered|shipped|out for delivery|delivered|dispatched)\s*:|out for delivery|has been (?:shipped|delivered|dispatched)"
     r"|your (?:order|package|parcel|shipment) (?:has |is )?(?:shipped|delivered|out for delivery|on (?:its|the) way|arriving)"),
    ("marketing", "Offer", "offers",
     r"\boffers?\b|\bdeals?\b|\bsale\b|discount|% off|\bsave\b|limited time|upgrade to|\bfree\b|premium|exclusive|invite"),
    ("domain-expiring", "Expiring soon", "expiry notices",
     r"expiring soon|(?:domain|service|plan|subscription|certificate)s?(?:\(s\))? (?:is |are |will )?(?:expir|about to expire)"
     r"|\bexpires? (?:on|in)\b|pending delete|suspended|time to renew|ssl certificates?"),
    ("incident", "Incident", "incidents",
     r"incident|outage|downtime|degraded (?:performance|service)|(?:service|site|website|server|api) (?:is )?down"
     r"|deploy(?:ment)? (?:has )?failed|build failed|failed to deploy"
     r"|limit exceeded|quota exceeded"),
    ("deploy", "Deploy", "deploys",
     r"deploy(?:ment)?s? (?:is |was |has )?(?:ready|live|succeeded|successful|completed?|started|queued|building|in progress|promoted)"
     r"|(?:build|deployment) (?:started|succeeded|completed|ready)|is now live|deployed to"),
    ("bill", "Bill", "bills",
     r"(?:invoice|bill|payment|statement|dues?)\b.{0,40}\b(?:is |are )?(?:due|overdue)\b|\bdue (?:today|tomorrow|on|by|date|soon)\b"
     r"|payment due|amount due|minimum (?:amount )?due|pay (?:by|before)"),
    ("statement", "Statement", "statements", r"statement|contract note"),
    ("invoice", "Invoice", "invoices",
     r"invoice|receipt|payment (?:received|successful|confirmed)|renewal is confirmed|auto-?renew|order (?:confirmed|placed|shipped|delivered)"),
    ("digest", "Digest", "digests",
     r"digest|weekly|monthly|newsletter|job alert|jobs? (?:for you|matching|you might)|is hiring|recommend"),
]


# The kinds that pop up, and so may come only from a service's alert senders.
ALERT_KINDS = {"security-alert", "payment-failed", "domain-expiring", "incident"}


def service_kind(text: str) -> tuple[str, str, str]:
    """A service email's kind, label and plural from its subject:
    ("security-alert", "Security alert", "security alerts"), else a
    plain notice."""
    for kind, label, many, pattern in SERVICE_KINDS:
        if re.search(pattern, text or "", re.I):
            return kind, label, many
    return "notice", "Update", "updates"
# Apps that comment and review under a login without "[bot]".
BOT_LOGINS = {"copilot", "codex", "chatgpt-codex-connector", "github-actions", "dependabot", "renovate"}
URGENCY = {"low": 0, "normal": 1, "critical": 2}
URGENCIES = ("silent", *URGENCY)
# At most this many popups per sync; the rest become one "N more" summary.
MOST = 4
# Mail older than this when it arrives (a first sync, a laptop waking up)
# never notifies.
FRESH = sync.NOTIFY_WITHIN
# Sent notifications and groups are forgotten after this long.
KEEP = 3 * 24 * 60 * 60

ACTION_LINK = "courier.open-link"
ACTION_OPEN = "courier.open"
ACTION_READ = "courier.mark-read"


# Rules ----------------------------------------------------------------------------


def rules_path() -> Path:
    return sync.config_dir() / "notify-rules.json"


def profile_rules(name: str = DEFAULT_PROFILE) -> dict:
    """A profile's rules, as a fresh copy."""
    base = PROFILES[name]
    return {"profile": name, "window": base["window"], "bot_logins": [], "delivery": "auto", "dock_version": 1,
            "kinds": {kind: dict(rule) for kind, rule in base["kinds"].items()}}


def load_rules(path: Path | None = None) -> dict:
    """The profile the rules file names (DEFAULT_PROFILE when none), with
    the file's changes over it. A value that makes no sense is left as the
    profile has it, with a word on stderr."""
    path = path or rules_path()
    try:
        mine = json.loads(path.read_text())
    except FileNotFoundError:
        return profile_rules()
    except (OSError, ValueError) as problem:
        print(f"courier-notify: {path}: {problem}; using the default rules", file=sys.stderr)
        return profile_rules()
    if not isinstance(mine, dict):
        return profile_rules()
    name = mine.get("profile", DEFAULT_PROFILE)
    if name not in PROFILES:
        print(f"courier-notify: no profile {name!r} (there are {', '.join(PROFILES)}); using {DEFAULT_PROFILE}", file=sys.stderr)
        name = DEFAULT_PROFILE
    rules = profile_rules(name)
    # The dock's contract: 1 until the v5 dock is live (the v4 dock would run
    # an input action without its text), then 2.
    if mine.get("dock_version") in (1, 2, 3):
        rules["dock_version"] = mine["dock_version"]
    if mine.get("delivery") in DELIVERIES:
        rules["delivery"] = mine["delivery"]
    elif "delivery" in mine:
        print(f"courier-notify: delivery {mine['delivery']!r} isn't dock, notify or auto; using auto", file=sys.stderr)
    window = mine.get("window")
    if isinstance(window, (int, float)) and not isinstance(window, bool) and 0 <= window <= 24 * 60 * 60:
        rules["window"] = window
    logins = mine.get("bot_logins")
    if isinstance(logins, list):
        rules["bot_logins"] = [login.strip().lstrip("@").lower() for login in logins if isinstance(login, str) and login.strip()]
    for kind, rule in (mine.get("kinds") or {}).items() if isinstance(mine.get("kinds"), dict) else []:
        if not isinstance(rule, dict):
            continue
        kept = rules["kinds"].setdefault(str(kind), {})
        for key in ("urgency", "bots", "self", "otherwise"):
            if rule.get(key) in URGENCIES:
                kept[key] = rule[key]
            elif key in rule:
                print(f"courier-notify: {kind}: {key} {rule[key]!r} isn't silent, low, normal or critical", file=sys.stderr)
        if isinstance(rule.get("group"), bool):
            kept["group"] = rule["group"]
        if isinstance(rule.get("window"), (int, float)) and not isinstance(rule.get("window"), bool) and 0 <= rule["window"] <= 86400:
            kept["window"] = rule["window"]
        if isinstance(rule.get("reasons"), list) and all(isinstance(reason, str) for reason in rule["reasons"]):
            kept["reasons"] = [reason.strip().lower() for reason in rule["reasons"]]
        elif rule.get("reasons") is None and "reasons" in rule:
            kept.pop("reasons", None)  # null: every reason
        elif "reasons" in rule:
            print(f"courier-notify: {kind}: reasons must be a list of GitHub's reasons", file=sys.stderr)
    return rules


def rule_for(rules: dict, kind: str) -> dict:
    return {"urgency": "normal", "group": False} | rules["kinds"].get("*", {}) | rules["kinds"].get(kind, {})


def is_bot(login: str, more=()) -> bool:
    login = (login or "").strip().lstrip("@").lower()
    return bool(login) and (login.endswith("[bot]") or login in BOT_LOGINS or login in more)


def decide(rules: dict, note: Note) -> tuple[str, bool]:
    """A note's urgency and whether it groups, by its kind's rule: a bot's,
    your own, or one on a thread GitHub gives another reason for may each
    have an urgency of their own. A rule with "dock": "v3" is a card for
    the v7 dock only: silent unless this sync writes a version-3 dock feed
    (rules["_cards"], set by after_sync)."""
    rule = rule_for(rules, note.kind)
    group = bool(rule.get("group"))
    if rule.get("dock") == "v3" and not rules.get("_cards"):
        return "silent", group
    if (note.bot or is_bot(note.login, rules.get("bot_logins", ()))) and "bots" in rule:
        return rule["bots"], group
    if note.mine and "self" in rule:
        return rule["self"], group
    if "reasons" in rule and note.reason not in rule["reasons"]:
        return rule.get("otherwise", "silent"), group
    return rule["urgency"], group


# What a notification says ------------------------------------------------------------


@dataclasses.dataclass
class Note:
    """One email's notification, before rules: what it says and does."""

    kind: str
    title: str
    body: str
    message_id: str
    account: str = ""
    link: str = ""
    link_label: str = "Open on GitHub"
    # Grouping: one PR's (or issue's, or commit's) comments, or its pushes.
    group: str = ""
    ref: str = ""  # "PR #274"
    repo: str = ""  # "lumen-app"
    who: str = ""  # "@priya"
    excerpt: str = ""
    commits: int = 0
    picture: str = ""
    at: float = 0.0
    builtin: bool = True
    # A built-in's link opens only to this domain (or under it).
    domain: str = ""
    # A service's group notification: "3 security alerts from Google".
    brand: str = ""
    many: str = ""
    # From GitHub's own headers: why you got it ("author": your PR or
    # issue), who did it, a bot or you.
    reason: str = ""
    login: str = ""
    bot: bool = False
    mine: bool = False
    # The card's values, for the dock: [("repo", "Repo", "lumen-app"), …]
    # (key, label, value: a string, or a list of them).
    fields: list = dataclasses.field(default_factory=list)
    # Where it came from, for the dock: "GitHub", "Google", a template's name.
    source: str = ""
    # The unit of work it's about, one tile in the dock: a repo and branch's
    # CI, a PR, a service's alerts, a card, a domain.
    unit: str = ""
    # The service it's from (courier_templates.services), and what resolves
    # work: a PR's merge, a renewal, his own review.
    service: str = ""
    action: str = ""
    # From one of the service's alert senders: only those raise its alerts
    # or settle its renewals and payments.
    trusted: bool = False
    # The email's own text of it (a comment's whole body, an alert's whole
    # message): the dock's body until GitHub's own is read.
    text_body: str = ""
    # What its card needs that its fields don't hold (courier_cards): the
    # pages to secure an account or pay a bill on, an amount, a due day, a
    # run's jobs, an invite, a parcel's step.
    card: dict = dataclasses.field(default_factory=dict)


def with_fields(note: Note, *triples) -> Note:
    """A note with its card's fields, the empty ones left out."""
    def clean(value):
        return [shorten(str(v), 160) for v in value if v] if isinstance(value, list) else shorten(str(value), 160)

    note.fields = [(key, label, clean(value)) for key, label, value in triples if value not in (None, "", [], 0)]
    return note


# What a service's alert says, read from its subject (only alert senders'
# subjects get here: the service's own words). A value not found is left out.
DEVICE = re.compile(r"\b(?:an? )?((?:Chrome|Firefox|Safari|Edge|Opera|Brave)(?: Mobile)?(?: on (?:Windows|macOS|Mac|Linux|Android|iOS))?"
                    r"|(?:Linux|Windows|Mac|macOS|Android|iOS|iPhone|iPad|Pixel|Samsung)\b(?: (?:laptop|phone|desktop|computer|tablet|device))?)")
PLACE = re.compile(r"\b(?:from|in|near) ([A-Z][a-z]+(?:, [A-Z][a-z]+(?: [A-Z][a-z]+)?)+)")
IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f]{1,4}(?::[0-9a-f]{0,4}){3,7})\b", re.I)
AMOUNT = re.compile(r"((?:Rs\.?|INR|₹|\$|€|£|USD|EUR|GBP)\s?\d[\d,]*(?:\.\d+)?)")
CARD = re.compile(r"ending (?:with |in )?(?:x+)?(\d{4})\b", re.I)
MERCHANT = re.compile(r"\bat ([A-Z][\w&.'-]*(?: [A-Z][\w&.'-]*){0,3})")
DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.I)
EXPIRY = re.compile(r"\b(?:expires?|expiring|expiry|expired)\b(?: (?:on|in|by))? (\d+ days?|[A-Z][a-z]{2,8} \d{1,2}(?:, \d{4})?|\d{4}-\d{2}-\d{2}|soon|today|tomorrow)")


def when(at: float) -> str:
    """ "09:41" (today), "Yesterday 18:02", "Nov 23 09:41"."""
    if not at:
        return ""
    day = time.strftime("%Y-%m-%d", time.localtime(at))
    if day == time.strftime("%Y-%m-%d", time.localtime(time.time())):
        return time.strftime("%H:%M", time.localtime(at))
    if day == time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)):
        return time.strftime("Yesterday %H:%M", time.localtime(at))
    return time.strftime("%b %-d %H:%M", time.localtime(at))


# What a security alert is about, in two words: "New sign-in".
EVENTS = [(r"new sign[- ]?in|sign[- ]?in (?:from|attempt|detected)|signed in", "New sign-in"),
          (r"new log[- ]?in|log[- ]?in (?:from|attempt|detected)|logged in", "New login"),
          (r"new device|device (?:registration|logged)", "New device"), (r"password", "Password change"),
          (r"two[- ]?factor|2-?step|2fa", "Two-factor change"), (r"recovery (?:email|phone)", "Recovery change"),
          (r"suspicious|unusual", "Unusual activity")]


def event_of(notice: str, label: str) -> str:
    return next((name for pattern, name in EVENTS if re.search(pattern, notice or "", re.I)), label)


def card_facts(kind: str, mail, domain: str, at: float) -> dict:
    """A service email's card facts (courier_cards.mail_facts): only for the
    kinds a card reads them for; never fatal."""
    if kind not in ("security-alert", "bill", "payment-failed", "statement", "invoice", "domain-expiring", "parcel", "deploy", "incident"):
        return {}
    try:
        import courier_cards

        return courier_cards.mail_facts(kind, mail.subject or "", getattr(mail, "html", "") or "", mail.text or "", domain, at or time.time())
    except Exception as problem:  # noqa: BLE001 - a card without its extras is still a card
        print(f"courier-notify: card facts: {problem!r}", file=sys.stderr)
        return {}


def service_fields(kind: str, brand: str, domain: str, notice: str, at: float) -> list[tuple[str, str]]:
    def first(pattern: re.Pattern, text: str = notice) -> str:
        match = pattern.search(text)
        return match.group(1).strip() if match else ""

    if kind == "security-alert":
        return [("service", "Service", brand), ("event", "Event", event_of(notice, "Security alert")), ("device", "Device", first(DEVICE)),
                ("place", "Place", first(PLACE)), ("at", "When", when(at)), ("ip", "IP address", first(IP)), ("notice", "Notice", notice)]
    if kind == "payment-failed":
        card = first(CARD)
        return [("merchant", "Merchant", first(MERCHANT) or brand), ("amount", "Amount", first(AMOUNT)),
                ("card", "Card", f"ending {card}" if card else ""), ("service", "Service", brand), ("event", "Event", notice)]
    if kind == "domain-expiring":
        return [("domain", "Domain", domain_in(notice, domain)), ("expires", "Expires", expiry_words(first(EXPIRY))),
                ("service", "Service", brand), ("notice", "Notice", notice)]
    if kind == "incident":
        return [("service", "Service", brand), ("event", "Event", notice), ("at", "When", when(at))]
    return [("service", "Service", brand), ("notice", "Notice", notice), ("at", "When", when(at))]


def expiry_words(text: str) -> str:
    """ "Dec 3" for "December 3, 2026" or "2026-12-03"; else as said ("soon",
    "in 7 days")."""
    import datetime

    for form in ("%B %d, %Y", "%B %d", "%b %d, %Y", "%b %d", "%Y-%m-%d"):
        try:
            day = datetime.datetime.strptime(text, form)
            return f"{day.strftime('%b')} {day.day}"
        except ValueError:
            continue
    return f"in {text}" if re.fullmatch(r"\d+ days?", text or "") else text


def domain_in(notice: str, own: str) -> str:
    """The first domain a notice names that isn't the service's own."""
    names = [name for name in DOMAIN.findall(notice or "") if not (name.lower() == own or name.lower().endswith("." + own))]
    return names[0].lower() if names else ""


def shorten(text: str, most: int = 120) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def excerpt(text: str, skip: tuple[str, ...] = ()) -> str:
    """The first line of what someone wrote in a notification's text part:
    past GitHub's own header line, Markdown's HTML and quoted lines, up to
    the "-- " that starts GitHub's footer."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line in ("--", "—") or line.startswith(("Reply to this email directly", "View it on GitHub")):
            break
        if not line or line.startswith((">", "```", "|")):
            continue
        line = re.sub(r"<[^>]*>", " ", line)
        line = re.sub(r"^#+\s+|^[-*+]\s+", "", line.strip())
        line = re.sub(r"\s+", " ", line).strip()
        if not line or any(re.search(pattern, line) for pattern in skip):
            continue
        return shorten(line)
    return ""


GITHUB_HEADER = re.compile(r"^@?\S+ (?:left a comment \(|commented on this|approved this|requested changes on this|reviewed this"
                           r"|dismissed)")


def comment_text(text: str) -> str:
    """A GitHub email's comment or review, as the email has it: past its
    header line, up to its footer ("-- " and "Reply to this email…")."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and GITHUB_HEADER.match(lines[0].strip()):
        lines.pop(0)
    kept = []
    for line in lines:
        if line.strip() in ("--", "—") or line.startswith(("Reply to this email directly", "View it on GitHub", "You are receiving this")):
            break
        kept.append(line.rstrip())
    return "\n".join(kept).strip()[:20000]


def display_name(sender: str) -> str:
    import email.utils

    name = email.utils.parseaddr(sender or "")[0].strip()
    return re.sub(r"\[bot\]$", "", name).strip()


def handle(author: str) -> str:
    author = (author or "").strip()
    return "" if not author else author if author.startswith("@") else "@" + author


def ref_of(subject: str, number: str | None, kind: str) -> str:
    """ "PR #274", "Issue #12" (from the subject's trailer), or "#274"."""
    import courier_fields as cf

    trailer = cf.subject_parts(subject)[2]
    match = re.fullmatch(r"(PR|Issue) #(\d+)", trailer)
    if match:
        return f"{match.group(1)} #{match.group(2)}"
    if number:
        return f"{'Issue' if kind == 'issue-comment' else 'PR'} #{number}"
    return ""


def short_repo(repo: str | None) -> str:
    return (repo or "").rstrip("/").rsplit("/", 1)[-1]


def plural(count: int, noun: str, many: str = "") -> str:
    return f"{count} {noun if count == 1 else many or noun + 's'}"


def note_for(mail, template: dict, fields: dict) -> Note | None:
    """An email's notification from its template's fields. `mail` is a
    courier_templates.Mail (or anything with id, account, sender, subject,
    text, epoch)."""
    import email.utils

    kind = template.get("kind", "taught")
    values = fields.get("values", {}) if fields.get("status") != "reteach" else {}
    who_name = display_name(mail.sender)
    parsed = getattr(mail, "parsed", None)

    def header(name: str) -> str:
        return re.sub(r"\s+", " ", str(parsed.get(name, "") or "")).strip() if parsed is not None else ""

    # GitHub's own headers (built-in templates only match mail Gmail
    # verified as GitHub's): who did it, and why you got it.
    login = header("X-GitHub-Sender")
    recipient = header("X-GitHub-Recipient")
    # The From's display name as written ("greptile-apps[bot]"); an unquoted
    # one with brackets doesn't parse as an address.
    shown_name = email.utils.parseaddr(mail.sender or "")[0] or (mail.sender or "").split("<", 1)[0].strip().strip('"')
    base = {"message_id": mail.id, "account": getattr(mail, "account", ""), "at": float(getattr(mail, "epoch", 0) or 0),
            "builtin": bool(template.get("builtin", True)), "reason": header("X-GitHub-Reason").lower(), "login": login,
            "mine": bool(login) and login.lower() == recipient.lower(),
            "bot": is_bot(login) or is_bot(shown_name)}
    base["domain"] = template.get("domain") or (mail.address.rpartition("@")[2] if base["builtin"] else "")
    if kind == "service":
        brand = template.get("brand") or who_name or mail.address
        notice = shorten(re.sub(r"^(?:(?:re|fwd?|aw)\s*:\s*)+", "", re.sub(r"\s+", " ", mail.subject or "").strip(), flags=re.I))
        kind, label, many = service_kind(notice)
        trusted = mail.address.lower() in {a.lower() for a in template.get("alerts", [])}
        if kind in ALERT_KINDS and not trusted:
            # Alert words from an address that doesn't send this service's
            # alerts (a relayed message, a newsletter): someone's words,
            # never a critical popup.
            kind, label, many = "notice", "Update", "updates"
        link = values.get("link") if isinstance(values.get("link"), str) else ""
        service = template.get("service", brand)
        card = CARD.search(notice)
        facts = card_facts(kind, mail, base["domain"], base["at"])
        thing = re.sub(r"[^a-z0-9]+", "-", str(facts.get("product") or facts.get("merchant") or "").lower()).strip("-")[:60]
        unit = {"payment-failed": f"payment:{service}", "domain-expiring": f"domain:{domain_in(notice, base['domain']) or service}",
                "parcel": f"parcel:{service}:{thing}" if thing else f"parcel:{service}", "bill": f"bill:{service}:{thing or 'due'}",
                # A merchant's invoice and its reminders are one bill.
                "statement": f"statement:{service}", "invoice": f"bill:{service}:{thing}" if thing else f"invoice:{service}",
                "deploy": f"deploy:{service}",
                }.get(kind, f"alert:{service}:{kind}")
        # One parcel (or one merchant's bill) per item: never grouped with another.
        group = f"service:{service}:bill:{thing}" if kind in ("bill", "invoice") and thing else \
            f"service:{service}:{kind}:{thing}" if kind == "parcel" and thing else f"service:{service}:{kind}"
        return with_fields(Note(kind=kind, title=f"{brand} · {label}", body=notice, link=link, link_label=f"Open on {brand}",
                                group=group, excerpt=notice, brand=brand, many=many,
                                source=brand, unit=unit, service=service, trusted=trusted,
                                text_body=(mail.text or "").replace("\r\n", "\n").strip()[:20000], card=facts, **base),
                           *service_fields(kind, brand, base["domain"], notice, base["at"]))
    # The dock's tab: GitHub for GitHub's mail, taught or built-in; else the
    # brand or the sender's name (never a taught template's own name).
    sender_domain = mail.address.rpartition("@")[2].lower()
    base["source"] = "GitHub" if sender_domain == "github.com" or sender_domain.endswith(".github.com") \
        else template.get("brand") or who_name or mail.address
    if not values:
        # Its template's fields couldn't be read (GitHub changed the
        # email): the sender and subject, as any notification would say.
        return with_fields(Note(kind=kind, title=who_name or mail.address, body=shorten(mail.subject), unit=f"mail:{mail.id}", **base),
                           ("from", "From", who_name or mail.address), ("subject", "Subject", mail.subject))

    def value(name: str) -> str:
        item = values.get(name)
        return item if isinstance(item, str) else ""

    # Groups key on the whole owner/repo (a fork and its upstream both have
    # an "app" with a PR #12); notifications say the short name.
    full = value("repo") or (value("ref").split("#")[0] if "#" in value("ref") else "")
    repo = short_repo(full)
    number = value("number") or (value("ref").split("#", 1)[1] if "#" in value("ref") else "")
    ref = ref_of(mail.subject, number, kind)
    link = value("link")
    title_text = value("title")
    author = handle(value("author"))
    common = base | {"link": link, "ref": ref, "repo": repo, "who": author or who_name, "bot": base["bot"] or is_bot(author),
                     "unit": f"pr:{full}#{number}" if full and number else f"mail:{mail.id}"}
    hashed = f"#{number}" if number else ""

    if kind in ("comment", "issue-comment"):
        said = excerpt(mail.text, (r"left a comment \([^)]*\)$", r"^@\S+ commented on this"))
        title = f"{author or who_name} commented on {ref}" if (author or who_name) else f"New comment on {ref}"
        return with_fields(Note(kind=kind, title=title + (f" · {repo}" if repo else ""), body=said or title_text,
                                group=f"comments:{full}:{ref}" if ref else "", excerpt=said, text_body=comment_text(mail.text), **common),
                           ("who", "Who", author or who_name), ("pr", "Issue" if kind == "issue-comment" else "PR", hashed),
                           ("pr-title", "Title", title_text), ("repo", "Repo", repo), ("comment", "Comment", said))
    if kind == "commit-comment":
        commit = value("commit")[:7]
        said = excerpt(mail.text)
        return with_fields(Note(kind=kind, title=f"{who_name or 'Someone'} commented on {commit}" + (f" · {repo}" if repo else ""),
                                body=said or title_text, group=f"comments:{full}:{commit}", excerpt=said, text_body=comment_text(mail.text),
                                **(common | {"ref": commit, "unit": f"commit:{full}@{commit}"})),
                           ("who", "Who", who_name or author), ("commit", "Commit", commit), ("repo", "Repo", repo),
                           ("comment", "Comment", said))
    if kind == "review-requested":
        return with_fields(Note(kind=kind, title=f"Review requested · {ref} · by {who_name or author}",
                                body=f"{repo}: {title_text}" if repo else title_text, **common),
                           ("who", "Who", who_name or author), ("pr", "PR", hashed), ("pr-title", "Title", title_text),
                           ("repo", "Repo", repo))
    if kind == "review":
        action = value("action") or "reviewed"
        # In its PR's comment group when the rules say "group" for reviews.
        return with_fields(Note(kind=kind, title=f"{who_name or author} {action} {ref}", body=f"{repo}: {title_text}" if repo else title_text,
                                group=f"comments:{full}:{ref}" if ref else "", action=action, text_body=comment_text(mail.text), **common),
                           ("who", "Who", who_name or author), ("verdict", "Review", action), ("pr", "PR", hashed),
                           ("pr-title", "Title", title_text), ("repo", "Repo", repo),
                           ("comment", "Comment", excerpt(mail.text, (r"^@\S+ \w[\w ]* this pull request\.?$",))))
    if kind == "push":
        count = int(value("count") or 0) if value("count").isdigit() else len(values.get("hashes") or [])
        messages = [shorten(m, 90) for m in values.get("messages") or []]
        body = messages[0] + (f" (+{len(messages) - 1} more)" if len(messages) > 1 else "") if messages else title_text
        return with_fields(Note(kind=kind, title=f"{author or who_name} pushed {plural(count, 'commit')} to {ref}" + (f" · {repo}" if repo else ""),
                                body=body, group=f"pushes:{full}:{ref}" if ref else "", commits=count, excerpt=body, **common),
                           ("who", "Who", author or who_name), ("pr", "PR", hashed), ("repo", "Repo", repo),
                           ("commits", "Commits", str(count) if count else ""), ("message", "Message", messages[0] if messages else ""))
    if kind == "state":
        action = (value("action") or "updated").lower()
        return with_fields(Note(kind=kind, title=f"{ref} {action}" + (f" by {who_name}" if who_name else ""),
                                body=f"{repo}: {title_text}" if repo else title_text, action=action, **common),
                           ("pr", "PR", hashed), ("state", "State", action), ("who", "By", who_name), ("repo", "Repo", repo),
                           ("pr-title", "Title", title_text))
    if kind in ("ci-failed", "ci-passed"):
        status = value("status").lower()
        verb = re.sub(r"^(?:pr )?run\s+", "", status) or "failed"
        if verb in ("succeeded", "passed", "completed successfully"):
            kind = "ci-passed"
        jobs = values.get("jobs") or []
        results = values.get("results") or []
        failed = [job for job, result in zip(jobs, results) if not re.match(r"(?i)succeeded|skipped", result)] or jobs
        workflow = value("workflow") or "CI"
        target = shorten(value("branch"), 48)
        title = " · ".join(part for part in (f"{workflow} {verb}", repo, target) if part)
        body = (", ".join(failed[:3]) + (f" and {len(failed) - 3} more" if len(failed) > 3 else "") + f" {verb}") if failed else ""
        commit = value("commit")[:7]
        body = " · ".join(part for part in (body, commit) if part)
        states = [{"name": job, "state": "passed" if re.match(r"(?i)succeeded", result) else "skipped" if re.match(r"(?i)skipped", result)
                   else "failed"} for job, result in zip(jobs, results)]
        return with_fields(Note(kind=kind, title=title, body=body or mail.subject, group=f"ci:{full}:{value('branch')}" if full else "",
                                card={"jobs": [j for j in states if j["state"] != "skipped"]} if states else {},
                                excerpt=" · ".join(part for part in (f"{workflow} {verb}", body) if part),
                                **(common | {"who": "", "ref": target, "unit": ci_unit(full, value("branch"), status)})),
                           ("repo", "Repo", repo), ("branch", "Branch", value("branch")), ("commit", "Commit", commit),
                           ("workflow", "Workflow", workflow),
                           ("jobs", "Failed", [f"{job} · {result[:1].lower() + result[1:]}" if result else job
                                               for job, result in zip(failed, [dict(zip(jobs, results)).get(j, "") for j in failed])]))
    if kind == "security-advisory":
        severity = value("severity")
        repos = values.get("repos") or []
        title = f"Security advisory · {value('package')}" + (f" ({severity.lower()})" if severity else "")
        body = title_text + (f" · {plural(len(repos), 'repo')}" if repos else "")
        return with_fields(Note(kind=kind, title=title, body=body, **(common | {"unit": "alert:github:security-advisory"})),
                           ("package", "Package", value("package")), ("severity", "Severity", severity), ("advisory", "Advisory", title_text),
                           ("repos", "Repos", [short_repo(r) for r in repos]))
    if kind == "dependabot-digest":
        return with_fields(Note(kind=kind, title="Dependabot alerts", body=f"Weekly digest for {value('week')}",
                                **(common | {"unit": "dependabot-digest"})), ("week", "Week", value("week")))
    if kind == "account-notice":
        return with_fields(Note(kind=kind, title="GitHub", body=value("notice") or mail.subject,
                                **(common | {"unit": f"mail:{mail.id}"})), ("notice", "Notice", value("notice") or mail.subject))
    # A template you taught: its name, then its fields.
    shown = [f"{name}: {', '.join(item) if isinstance(item, list) else item}"
             for name, item in values.items() if name != "link" and item not in (None, "", [])]
    return with_fields(Note(kind=kind, title=template.get("name") or who_name, body=shorten(" · ".join(shown[:3]), 160),
                            link_label="Open link", **(common | {"unit": f"taught:{template.get('id', '')}:{mail.id}"})),
                       *[(re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), name, item) for name, item in values.items() if name != "link"])


# Deciding: rules, groups, bursts ---------------------------------------------------


def grouped(group: dict) -> tuple[str, str]:
    """A group's notification: "3 new comments on PR #274", "3 security
    alerts from Google"."""
    if group.get("brand"):
        return f"{group['count']} {group['many']} from {group['brand']}", group.get("excerpt", "")
    if group["kind"] in ("ci-failed", "ci-passed"):
        where = " · ".join(part for part in (group.get("repo"), group.get("ref")) if part)
        return f"{group['count']} CI failures · {where}", group.get("excerpt", "")
    where = group["ref"] + (f" · {group['repo']}" if group.get("repo") else "")
    people = ", ".join(group["who"][:3]) + (f" and {len(group['who']) - 3} more" if len(group["who"]) > 3 else "")
    if group["kind"] == "push":
        title = f"{plural(group['count'], 'push', 'pushes')} to {where}"
        return title, f"{plural(group['commits'], 'commit')} by {people}" if people else plural(group["commits"], "commit")
    what = "comments" if set(group.get("kinds", [group["kind"]])) <= {"comment", "issue-comment", "commit-comment"} else "comments and reviews"
    title = f"{group['count']} new {what} on {where}"
    return title, (f"{people}: {group['excerpt']}" if group.get("excerpt") else people)


@dataclasses.dataclass
class Event:
    """What happened with one note: "popup", "update" (a group's
    notification replaced in place), "silent", or "held" (past this sync's
    popups, folded into its "summary")."""

    action: str
    note: Note
    urgency: str
    title: str = ""
    body: str = ""
    id: int = 0


class Dispatcher:
    """Applies the rules to notes, keeps groups in `state`, and sends.

    `send(note, title, body, urgency, replaces) -> id` raises the
    notification (0 when it couldn't); tests and the replay pass their own,
    so nothing reaches the desktop."""

    def __init__(self, rules: dict, state: dict, send, now: float | None = None, most: int = MOST) -> None:
        self.rules = rules
        self.state = state
        self.send = send
        self.now = now
        self.most = most
        self.events: list[Event] = []
        self.popups = 0
        # Groups updated in this sync: sent once each, at finish().
        self.updated: dict[str, tuple[dict, Note, str]] = {}
        state.setdefault("groups", {})
        state.setdefault("sent", {})
        state.setdefault("counts", {})

    def _count(self, note: Note) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(note.at or self.now or time.time()))
        counts = self.state["counts"].setdefault(day, {})
        key = note.kind + (" by bots" if note.bot or is_bot(note.login, self.rules.get("bot_logins", ())) else "")
        counts[key] = counts.get(key, 0) + 1

    def _record(self, nid: int, note: Note, ids: list[str]) -> None:
        if nid:
            self.state["sent"][str(nid)] = {"link": note.link, "ids": ids, "account": note.account, "at": note.at or self.now,
                                            "builtin": note.builtin, "label": note.link_label, "domain": note.domain}

    def dispatch(self, note: Note) -> Event:
        urgency, groups = decide(self.rules, note)
        now = self.now or time.time()
        # A date in the future (a wrong clock, or a lie) counts as now.
        at = note.at = min(note.at or now, now)
        if urgency == "silent":
            self._count(note)
            return self._event(Event("silent", note, urgency))
        if groups and note.group:
            key = f"{note.account}:{note.group}"
            group = self.state["groups"].get(key)
            window = rule_for(self.rules, note.kind).get("window", self.rules["window"])
            if group and at - group["last"] <= window and group.get("id"):
                group["count"] += 1
                group["last"] = at
                group["commits"] += note.commits
                group["ids"] = (group["ids"] + [note.message_id])[-50:]
                group["kinds"] = sorted(set(group.get("kinds", [group["kind"]])) | {note.kind})
                if note.who and note.who not in group["who"]:
                    group["who"].append(note.who)
                if note.excerpt:
                    group["excerpt"] = note.excerpt
                title, body = grouped(group)
                self.updated[key] = (group, note, urgency)
                return self._event(Event("update", note, urgency, title, body, group["id"]))
        if self.popups >= self.most:
            return self._event(Event("held", note, urgency))
        nid = self.send(note, note.title, note.body, urgency, 0)
        self.popups += 1
        self._record(nid, note, [note.message_id])
        if groups and note.group:
            self.state["groups"][f"{note.account}:{note.group}"] = {
                "id": nid, "kind": note.kind, "kinds": [note.kind], "count": 1, "first": at, "last": at, "ref": note.ref, "repo": note.repo,
                "who": [note.who] if note.who else [], "commits": note.commits, "excerpt": note.excerpt,
                "ids": [note.message_id], "brand": note.brand, "many": note.many}
        return self._event(Event("popup", note, urgency, note.title, note.body, nid))

    def _event(self, event: Event) -> Event:
        self.events.append(event)
        return event

    def finish(self) -> Event | None:
        """Each updated group's notification, replaced once; then one
        notification for the popups past this sync's `most`."""
        for group, note, urgency in self.updated.values():
            title, body = grouped(group)
            group["id"] = self.send(note, title, body, urgency, group["id"]) or group["id"]
            self._record(group["id"], note, group["ids"])
        self.updated = {}
        held = [event for event in self.events if event.action == "held"]
        if not held:
            return None
        urgency = max((event.urgency for event in held), key=lambda u: URGENCY.get(u, 1))
        kinds: dict[str, int] = {}
        for event in held:
            kinds[event.note.title.split(" · ")[0]] = kinds.get(event.note.title.split(" · ")[0], 0) + 1
        body = ", ".join(f"{title} ×{n}" if n > 1 else title for title, n in list(kinds.items())[:4])
        note = dataclasses.replace(held[-1].note, link="", group="")
        github = all(e.note.builtin and e.note.domain in ("github.com", "") and not e.note.brand for e in held)
        title = f"{len(held)} more from GitHub" if github else f"{len(held)} more notifications"
        nid = self.send(note, title, body, urgency, 0)
        self._record(nid, note, [event.note.message_id for event in held])
        return self._event(Event("summary", note, urgency, title, body, nid))

    def prune(self) -> None:
        now = self.now or time.time()
        self.state["sent"] = {k: v for k, v in self.state["sent"].items() if now - (v.get("at") or 0) <= KEEP}
        self.state["groups"] = {k: v for k, v in self.state["groups"].items() if now - v["last"] <= KEEP}
        days = sorted(self.state["counts"])
        self.state["counts"] = {day: self.state["counts"][day] for day in days[-14:]}


# Sending ----------------------------------------------------------------------------


def inert(text: str) -> str:
    """Text the notification server can't read as markup: as
    courier_sync.desktop_notify makes it (no control characters, no "<"
    or ">", no Markdown link or image)."""
    text = re.sub(r"[\x00-\x1f\x7f  ]+", " ", text or "")
    return text.replace("<", "‹").replace(">", "›").replace("](", "]​(").replace("][", "]​[").replace("]:", "]​:")


def picture(address: str) -> str:
    """The sender's picture (for GitHub, GitHub's mark) as Courier keeps
    it, or ""."""
    try:
        import courier_avatars

        return courier_avatars.picture_for("p:" + address)
    except Exception:  # noqa: BLE001 - a picture is a nicety
        return ""


def actions_for(note: Note) -> list[str]:
    actions = []
    if sync.web_link(note.link):
        actions += [ACTION_LINK, note.link_label]
    return actions + [ACTION_OPEN, "Open in Junco", ACTION_READ, "Mark read"]


class Desktop:
    """The session's notification server, over D-Bus."""

    def __init__(self) -> None:
        from gi.repository import Gio

        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def _bus(self, method: str, *args: str) -> str:
        from gi.repository import GLib

        reply = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", method,
                                   GLib.Variant(f"({'s' * len(args)})", args), GLib.VariantType("(s)"), 0, 2000, None)
        return reply.unpack()[0]

    def identity(self, unique_name: str) -> str:
        """A notification server as "<bus id> <unique name>": a unique name
        alone can come round again on the next login's bus."""
        if not hasattr(self, "bus_id"):
            self.bus_id = self._bus("GetId")
        return f"{self.bus_id} {unique_name}"

    def server(self) -> str:
        """The server now running, so a later ActionInvoked can be told
        apart from a restarted server's reuse of the same notification id."""
        return self.identity(self._bus("GetNameOwner", "org.freedesktop.Notifications"))

    def notify(self, note: Note, title: str, body: str, urgency: str, replaces: int) -> int:
        from gi.repository import GLib

        hints = {"urgency": GLib.Variant("y", URGENCY.get(urgency, 1)), "desktop-entry": GLib.Variant("s", "courier"),
                 "category": GLib.Variant("s", "email.arrived")}
        if note.picture and Path(note.picture).is_file():
            hints["image-path"] = GLib.Variant("s", Path(note.picture).as_uri())
        reply = self.bus.call_sync(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
            GLib.Variant("(susssasa{sv}i)", ("Junco", replaces, "courier", inert(title), inert(body), actions_for(note), hints, -1)),
            GLib.VariantType("(u)"), 0, 5000, None)
        return int(reply.unpack()[0])

    def close(self, nid: int) -> None:
        from gi.repository import GLib

        with contextlib.suppress(Exception):
            self.bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                               "CloseNotification", GLib.Variant("(u)", (nid,)), None, 0, 2000, None)


def desktop_sender():
    """send() for a Dispatcher: over D-Bus, else notify-send (no buttons,
    no replacing)."""
    try:
        desktop = Desktop()
        server = desktop.server()
    except Exception:  # noqa: BLE001 - no session bus or no server: notify-send
        desktop, server = None, ""

    def send(note: Note, title: str, body: str, urgency: str, replaces: int) -> int:
        if desktop is not None:
            try:
                nid = desktop.notify(note, title, body, urgency, replaces)
                send.server = server
                return nid
            except Exception as problem:  # noqa: BLE001
                print(f"courier-notify: {problem}", file=sys.stderr)
        sync.desktop_notify(title, body, "-a", "Junco", "-i", "courier", "-u", urgency, "-c", "email.arrived")
        return 0

    send.server = server
    return send


# State ------------------------------------------------------------------------------


def state_path() -> Path:
    return sync.state_dir() / "notify.json"


@contextlib.contextmanager
def locked_state():
    """notify.json, read and written under a lock (courier-sync and the
    listener both change it)."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name("notify.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text())
        except (FileNotFoundError, ValueError):
            state = {}
        yield state
        sync.write_private(path, json.dumps(state, ensure_ascii=False, indent=1) + "\n")


# The dock's feed ---------------------------------------------------------------------
#
# Caelestia's notification dock (the bar at the bottom edge) shows real work:
# one tile per unit of work Junco's structured notes are about. Junco is the
# feed's only writer; the dock only reads it, and answers its buttons with
# `courier-notify action ITEM ACTION` and `courier-notify dismiss ITEM`. The
# contract is the dock's (notif-dock/CONTRACT.md, version 1, with "status"
# and "unit"):
#
#   ~/.local/state/courier/dock.json (0600, written to a temp file and renamed)
#   {"version": 1, "updated": "<ISO 8601>", "items": [{
#       "id": "ci:lumenlabs/lumen-app:main",  stable for the item's life
#       "unit": "ci:lumenlabs/lumen-app:main", its tile: ci:<repo>:<branch>,
#                                         pr:<repo>#<n>, alert:<service>:<kind>,
#                                         payment:<service>, domain:<domain>
#       "unitLabel": "lumen-app · main",   the tile's label
#       "status": "open",                     or "resolved"
#       "kind": "ci-failed", "urgency": "critical",   or "normal"
#       "source": "GitHub", "icon": "courier", "image": "",
#       "title": "…", "summary": "…",
#       "fields": [{"key": "repo", "label": "Repo", "value": "lumen-app"},
#                  {"key": "jobs", "label": "Failed", "value": ["test · failed in 2 minutes"]}],
#       "count": 1, "time": "<ISO 8601>", "updated": "<ISO 8601>",
#       "resolved": "<ISO 8601>" (once resolved), "group": "…" (Junco's own),
#       "actions": [{"id": "open", "label": "Open on GitHub", "url": "https://…"},
#                   {"id": "open-junco", "label": "Open in Junco"},
#                   {"id": "mark-read", "label": "Mark read", "resolves": true}]}]}
#
# A unit's items: a branch's CI failures, a service's alerts of one kind, its
# failed payments and a domain are one item each, growing ("count"); a PR's
# review request and its comments and reviews are two; each advisory's
# package is one, in GitHub's advisories tile.
#
# Work resolves from the mail Junco sees, popped up or silent: a CI run that
# passes on the same repo and branch; a PR merged or closed; your own review
# of a PR you were asked to review; a renewal or payment confirmed by the
# same service. Security alerts resolve only when you mark them read or
# dismiss them. Showing the bar changes nothing: read and seen change only
# through mark-read and dismiss, which take an item out of the feed.
#
# Bounds: a resolved item stays DOCK_RESOLVED (a minute), an open one DOCK_KEEP
# (three days); at most DOCK_MOST, newest first. An "open" action is there only when its address
# is one Junco would open itself; the dock opens it.

DOCK_KEEP = KEEP
# Resolved work stays a minute (its tile animates away), then drops out.
DOCK_RESOLVED = 60
DOCK_MOST = 50
# The dock writes this file while it runs; older than DOCK_ALIVE, it isn't.
DOCK_ALIVE = 90
# Kinds the dock lays out as given; the rest as "comment" or its own.
DOCK_KINDS = {"issue-comment": "comment"}
# A service's mail that settles a renewal or a payment ("Your renewal is
# confirmed", "Payment received"), and never a reminder of one.
SETTLED = re.compile(r"renewal (?:of \S+ )?(?:is |was |has been )?(?:confirmed|successful|completed?)\b|\brenewed\b"
                     r"|payment (?:was |is |has been )?(?:received|successful|confirmed|completed)\b|\breceipt\b"
                     r"|thank(?:s| you) for your payment|successfully (?:renewed|charged|paid)\b|charged successfully", re.I)
# Anything that says it didn't happen, or hasn't yet, never settles work.
NOT_SETTLED = re.compile(r"\bnot\b|n't\b|\bunable\b|incomplete|could not|cannot|action required|\bsoon\b|upcoming|reminder"
                         r"|\bwill\b|failed|unsuccessful|declined|\bdue\b", re.I)


def dock_path() -> Path:
    return sync.state_dir() / "dock.json"


def dock_alive_path() -> Path:
    return sync.xdg("XDG_STATE_HOME", ".local/state") / "caelestia" / "notifdock.alive"


def dock_alive(now: float | None = None) -> bool:
    try:
        return (now or time.time()) - dock_alive_path().stat().st_mtime <= DOCK_ALIVE
    except OSError:
        return False


def channel(rules: dict, now: float | None = None) -> str:
    """"dock" or "desktop": the rules' delivery, auto meaning the dock while
    it's running (its alive file fresh), a desktop notification otherwise,
    so nothing is lost."""
    delivery = rules.get("delivery", "auto")
    if delivery == "dock":
        return "dock"
    if delivery == "notify":
        return "desktop"
    return "dock" if dock_alive(now) else "desktop"


def iso(at: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds")


def epoch(text: str) -> float:
    import datetime

    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return 0.0


def safe_link(note: Note) -> str:
    """The note's link when Junco itself would open it (open_link's rule),
    else "": the dock opens what the feed says, so the feed says only that."""
    import urllib.parse

    url = sync.web_link(note.link)
    if not url:
        return ""
    if note.builtin:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        allowed = note.domain or "github.com"
        if not (host == allowed or host.endswith("." + allowed)):
            return ""
    return url


def icon_for(note: Note) -> str:
    """The source's logo, the same for all its items (its tab shows it): the
    brand's picture Junco keeps for its domain, the sender's, or a theme icon
    named after it ("github"); the dock shows Junco's own when that's missing."""
    try:
        import courier_avatars

        found = courier_avatars.picture_for_key(f"d:{note.domain}") if note.domain else ""
    except Exception:  # noqa: BLE001 - a logo is a nicety
        found = ""
    for path in (found, note.picture):
        if path and Path(path).is_file():
            return Path(path).as_uri()
    name = re.sub(r"[^a-z0-9]+", "", (note.source or note.brand or "").lower())
    return name or "courier"


def field_value(item: dict, key: str) -> str:
    return next((f.get("value", "") for f in item.get("fields", []) if f.get("key") == key), "")


def card_lines(item: dict) -> tuple[str, str]:
    """The card's headline and detail (the contract's table, per kind),
    from the item's fields; "" where the dock's own wording should do."""
    def get(key: str):
        return field_value(item, key)

    kind = item.get("kind")
    if kind in ("ci-failed", "ci-passed"):
        jobs = [job.split(" · ")[0] for job in (get("jobs") or [])]
        names = ", ".join(jobs[:-1]) + " and " + jobs[-1] if len(jobs) > 1 else "".join(jobs)
        return " · ".join(p for p in (get("repo"), get("branch")) if p), f"{names} failed" if names else ""
    if kind == "security-advisory":
        return " · ".join(p for p in (get("package"), get("severity")) if p), get("advisory")
    if kind in ("review-requested", "review", "comment", "review-comment"):
        headline = " · ".join(p for p in (f"PR {get('pr')}" if get("pr") else "", get("pr-title")) if p)
        if kind == "review-requested":
            return headline, f"{get('who')} asked for your review" if get("who") else ""
        if kind == "review":
            said = f": {get('comment')}" if get("comment") else ""
            return headline, f"{get('who')} {get('verdict') or 'reviewed'}{said}" if get("who") else ""
        return headline, f"{get('who')}: {get('comment')}" if get("who") and get("comment") else get("who")
    if kind == "security-alert":
        where = " · ".join(p for p in (get("place"), get("at")) if p)
        return " · ".join(p for p in (get("event"), get("device")) if p), where
    if kind == "payment-failed":
        amount, merchant = get("amount"), get("merchant")
        headline = f"{amount} at {merchant}" if amount and merchant else amount or f"Payment failed at {merchant}"
        return headline, f"card {get('card')}" if get("card") else get("event")
    if kind == "domain-expiring":
        if get("domain"):
            expires = get("expires")
            return f"{get('domain')} expires {expires}" if expires and expires != "soon" else f"{get('domain')} expiring soon", \
                f"renew with {get('service')}" if get("service") else ""
        return get("notice"), f"renew with {get('service')}" if get("service") else ""
    return item.get("title", ""), item.get("summary", "")


def ci_unit(repo: str, branch: str, status: str) -> str:
    """A CI run's unit: ci:<repo>:<branch>. A PR's run ("PR run failed") is
    named by the PR's title where a branch would be: its unit ends in
    " (PR run)", which no git branch can (refs hold no spaces), so a PR
    titled "main" can never stand for the main branch."""
    if not repo:
        return ""
    return f"ci:{repo}:{branch} (PR run)" if status.lower().startswith("pr run") else f"ci:{repo}:{branch}"


def ci_unit_of(note: Note) -> str:
    """The unit of a PR's own runs (only those: see ci_unit)."""
    repo = note.unit[3:].rsplit("#", 1)[0]
    title = next((value for key, _, value in note.fields if key == "pr-title"), "")
    return f"ci:{repo}:{title} (PR run)" if repo and title else ""


def dock_group(note: Note) -> Note:
    """In the dock, a review comment is its own group: each review thread is
    its own unit of work, though a desktop popup groups a PR's comments. (A
    reply joins its thread's item once GitHub says which: apply_details.)"""
    where = github_target(note.link) if note.kind in ("comment", "issue-comment", "review") and note.group else None
    if where and where.get("anchor") == "review-comment":
        note.group = f"{note.group}:r{where['id']}"
    return note


def github_target(link: str) -> dict | None:
    import courier_github

    return courier_github.parse(link) if link else None


def github_link(where: dict) -> str:
    import courier_github

    return courier_github.canonical(where)


def github_text(value: str) -> str:
    import courier_github

    return courier_github.text(value)


def dock_version() -> int:
    """The contract version the feed is written in (notify-rules.json's
    "dock_version"; 1 until the v5 dock is live)."""
    return int(load_rules().get("dock_version", 1))


def item_actions(item: dict, version: int) -> list[dict]:
    """An item's buttons, in the dock's contract version. Version 1: Open on
    …, Open in Junco and Mark read only (a v4 dock would run an input action
    without its text). Version 2: per kind, as the contract orders them;
    GitHub's (reply, 👍, resolve the thread, re-run, approve) where the item
    has a GitHub target, and act only when pressed."""
    url = DEMO_LINK if item.get("demo") else item.get("link", "")
    label = inert(item.get("link_label") or "Open on GitHub")
    junco = {"id": "open-junco", "label": "Open in Junco"}
    read = {"id": "mark-read", "label": "Mark read", "resolves": True}
    if version < 2:
        return ([{"id": "open", "label": label, "url": url}] if url else []) + [junco, read]
    where = item.get("github") or {}
    kind = item.get("kind")
    anchor = where.get("anchor")
    name = (cn_field(item, "who") or "").split(",")[0].strip()
    first_name = name if name.startswith("@") else (name.split() or [""])[0]
    acts: list[dict] = []
    if kind in ("comment", "review-comment", "review") and anchor:
        acts.append({"id": "reply", "label": "Reply", "type": "input", "hint": f"Reply to {first_name}" if first_name else "Reply"})
        if anchor in ("issue-comment", "review-comment"):
            acts.append({"id": "react-plus1", "label": "👍", "type": "command"})
        if anchor == "review-comment":
            acts.append({"id": "resolve-thread", "label": "Resolve thread", "type": "command", "resolves": True})
    if kind == "ci-failed" and where.get("kind") == "run":
        acts.append({"id": "rerun-failed", "label": "Re-run failed jobs", "type": "command"})
    if url:
        name = "Open run" if kind == "ci-failed" else "Open PR" if kind == "review-requested" else label
        open_action = {"id": "open", "label": name, "type": "url", "url": url}
        acts.insert(0, open_action) if kind == "review-requested" or not acts else acts.append(open_action)
    if kind == "review-requested" and where.get("kind") == "pr":
        acts.append({"id": "approve", "label": "Approve", "type": "confirm", "resolves": True})
    return acts + [junco | {"type": "command"}, read | {"type": "command"}]


def cn_field(item: dict, key: str):
    return next((f.get("value") for f in item.get("fields", []) if f.get("key") == key), "")


def item_id_for(note: Note, unit: str) -> str:
    """An item's id within its unit: the unit itself, but a PR's review
    request and its comments are two items, and each advisory's package one."""
    if unit.startswith("pr:"):
        return f"{unit}:{'review-requested' if note.kind == 'review-requested' else 'comments'}"
    if note.kind == "security-advisory":
        package = next((value for key, _, value in note.fields if key == "package"), "")
        return f"{unit}:{package}"
    return unit


def unit_label(note: Note, unit: str) -> str:
    """The tile's short label: "lumen-app · main", "lumen-app #274", "Google"."""
    if unit.startswith("ci:"):
        return " · ".join(part for part in (note.repo, note.ref) if part)
    if unit.startswith("pr:"):
        return f"{note.repo} {unit.rsplit('#', 1)[-1] and '#' + unit.rsplit('#', 1)[-1]}".strip()
    if unit.startswith("pr-thread:"):
        number = unit.rsplit("#", 1)[-1].split(":")[0]
        return f"{note.repo} #{number} · review thread".strip()
    if unit.startswith("domain:") and "." in unit:
        return unit.split(":", 1)[1]
    if note.kind == "security-advisory":
        return "GitHub advisories"
    return note.source or note.brand or "Junco"


def inert_markup(text: str) -> str:
    """Text in the contract's markup subset (a body, a thread reply, a hunk
    or log line), inert whatever the dock renders it with: lines, code and
    "> " quotes kept, but no tag can open ("<" before a letter, "/", "!" or
    "?" becomes "‹"; "a < b" stays), no Markdown link or image ("](", "]["
    and "]:" get a zero-width space: no inline link, no full reference, and
    no definition for a shortcut "![r]" to use), and no control or
    direction character."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]", "", str(text or ""))
    text = re.sub(r"<(?=[A-Za-z/!?])", "‹", text)
    return text.replace("](", "]\u200b(").replace("][", "]\u200b[").replace("]:", "]\u200b:")


def file_url(value) -> str:
    """A picture's address for the dock: a local file only (the dock never
    fetches)."""
    return value if isinstance(value, str) and value.startswith("file:///") and not re.search(r"[\s\x00-\x1f]", value) else ""


def make_inert(item: dict) -> None:
    """Every text the dock shows, inert as on the desktop (inert(): no tag,
    Markdown link or control character), whatever the dock renders it with;
    the markup subset's texts (body, thread, hunk, log) by inert_markup."""
    for key in ("title", "summary", "headline", "detail", "unitLabel", "source"):
        if isinstance(item.get(key), str):
            item[key] = inert(item[key])
    if "image" in item:
        item["image"] = file_url(item["image"])
    if isinstance(item.get("body"), str):
        item["body"] = inert_markup(item["body"])
    if "thread" in item:
        thread = []
        for entry in item["thread"] if isinstance(item["thread"], list) else []:
            if isinstance(entry, dict):
                clean = {"who": inert(str(entry.get("who", ""))), "time": inert(str(entry.get("time", ""))),
                         "body": inert_markup(entry.get("body", ""))}
                if file_url(entry.get("avatar")):
                    clean["avatar"] = entry["avatar"]
                thread.append(clean)
        item["thread"] = thread
    if "context" in item:
        context = item["context"] if isinstance(item["context"], dict) else {}
        line = context.get("line")
        item["context"] = {"file": inert(str(context.get("file", ""))), "line": line if isinstance(line, int) else 0,
                           "hunk": [inert_markup(str(h)).replace("\n", " ") for h in context.get("hunk") or [] if isinstance(h, str)]}
    if "log" in item:
        item["log"] = [inert_markup(str(line)).replace("\n", " ") for line in item["log"] if isinstance(line, str)] \
            if isinstance(item["log"], list) else []
    if "jobs" in item:
        item["jobs"] = [{"name": inert(str(j.get("name", ""))), "state": j.get("state") if j.get("state") in ("passed", "failed", "running")
                         else "failed"} for j in item["jobs"] if isinstance(j, dict)] if isinstance(item["jobs"], list) else []
    if "files" in item:
        item["files"] = [{"path": inert(str(f.get("path", ""))), "additions": int(f.get("additions") or 0) if str(f.get("additions") or 0).isdigit() else 0,
                          "deletions": int(f.get("deletions") or 0) if str(f.get("deletions") or 0).isdigit() else 0}
                         for f in item["files"] if isinstance(f, dict)] if isinstance(item["files"], list) else []
    if "meta" in item:
        meta = item["meta"] if isinstance(item["meta"], dict) else {}
        item["meta"] = {inert(str(key)): inert(str(value)) for key, value in meta.items() if value not in (None, "")}
    for field in item.get("fields", []):
        value = field.get("value")
        field["label"] = inert(str(field.get("label", "")))
        field["value"] = [inert(str(v)) for v in value] if isinstance(value, list) else inert(str(value))
    for action in item.get("actions", []):
        action["label"] = inert(str(action.get("label", "")))


def merged_card(old: dict, new: dict, at: float) -> dict:
    """An item's card data with a new email's: newer facts win, and the
    steps a parcel or deploy has been through add up ({step: when})."""
    steps = dict(old.get("steps") or {}) if isinstance(old.get("steps"), dict) else {}
    if new.get("step"):
        steps.setdefault(str(new["step"]), float(new.get("at") or at))
    merged = {**old, **{key: value for key, value in new.items() if key not in ("step", "at")}}
    if steps:
        merged["steps"] = steps
    return merged


_writable: dict[str, bool] = {}


def calendar_writable(account: str) -> bool:
    """Whether Junco may answer invitations for this account: its sign-in
    holds calendar.events (courier-auth add <account> --calendar-write), as
    the token cache records Google's own grant. Unknown counts as no."""
    if account not in _writable:
        try:
            import courier_auth

            entry = json.loads(courier_auth.keyring_get("access", account) or "{}")
            granted = set(str(entry.get("scope", "")).split())
            _writable[account] = bool(granted & {"https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar"})
        except Exception:  # noqa: BLE001 - no keyring, no account: not writable
            _writable[account] = False
    return _writable[account]


def account_emails() -> dict[str, str]:
    """Junco's account names and their addresses (accounts.json), for a
    card's "Original email" link to Gmail on the web."""
    try:
        listed = json.loads((sync.config_dir() / "accounts.json").read_text()).get("accounts", [])
    except (OSError, ValueError, AttributeError):
        return {}
    return {str(a.get("id")): str(a.get("email")) for a in listed if isinstance(a, dict) and a.get("id") and a.get("email")}


class Feed:
    """dock.json, in memory: load it, change it, save it, under
    locked_state()'s lock (courier-sync and the dock's commands both
    change it)."""

    def __init__(self, data: dict | None = None, version: int | None = None) -> None:
        self.data = data if isinstance(data, dict) and isinstance(data.get("items"), list) else {"version": 1, "items": []}
        if self.data.get("version") == 3:
            import courier_cards

            self.data["items"] = [courier_cards.from_v3(item) for item in self.data["items"] if isinstance(item, dict)]
        self.version = version or dock_version()
        self.data["version"] = self.version
        self.data.setdefault("next", 1)
        self.resolved: list[dict] = []  # resolved since loaded (the replay counts them)

    @classmethod
    def load(cls, path: Path | None = None, version: int | None = None) -> Feed:
        try:
            return cls(json.loads((path or dock_path()).read_text()), version)
        except (OSError, ValueError):
            return cls(None, version)

    def save(self, path: Path | None = None, now: float | None = None) -> None:
        self.prune(now)
        # Each item's buttons in the version the dock reads (a switch from 1
        # to 2 shows on every item at the next write).
        self.data["version"] = self.version
        for item in self.items:
            item["actions"] = item_actions(item, self.version)
        self.data["updated"] = iso(now or time.time())
        data = self.data
        if self.version >= 3:
            # The task, not the email (courier_cards): each item's component,
            # lane, due, sections and actions, beside Junco's own keys.
            import courier_cards

            emails = account_emails()
            data = dict(self.data, items=[courier_cards.v3_item(dict(item, account_email=emails.get(item.get("account", ""), "")), now,
                                                                can_answer=calendar_writable) for item in self.items])
        sync.write_private(path or dock_path(), json.dumps(data, ensure_ascii=False, indent=1) + "\n")

    @property
    def items(self) -> list[dict]:
        return self.data["items"]

    def find(self, item_id: str) -> dict | None:
        return next((item for item in self.items if item.get("id") == str(item_id)), None)

    def by_nid(self, nid: int) -> dict | None:
        return next((item for item in self.items if item.get("nid") == nid), None)

    def remove(self, item_id: str) -> dict | None:
        item = self.find(item_id)
        if item is not None:
            self.items.remove(item)
        return item

    def prune(self, now: float | None = None) -> None:
        """Newest first; resolved for DOCK_RESOLVED, open for DOCK_KEEP, at
        most DOCK_MOST."""
        now = now or time.time()
        kept = [item for item in self.items
                if now - epoch(item.get("resolved") or item.get("updated", "")) <= (DOCK_RESOLVED if item.get("status") == "resolved" else DOCK_KEEP)]
        kept.sort(key=lambda item: epoch(item.get("updated", "")), reverse=True)
        self.data["items"] = kept[:DOCK_MOST]

    def open_count(self) -> int:
        return sum(1 for item in self.items if item.get("status") == "open")

    def send(self, note: Note, title: str, body: str, urgency: str, replaces: int) -> int:
        """A Dispatcher's send(): the unit's tile, new or updated in place
        (its id never changes; new work reopens a resolved one). Returns a
        number the Dispatcher keeps for the group."""
        at = note.at or time.time()
        unit = note.unit or f"mail:{note.message_id}"
        link = safe_link(note)
        # Only GitHub's own mail (a built-in template, its sender verified as
        # GitHub's) gets a GitHub target; its link is rebuilt from the parsed
        # parts, so Open shows what the buttons act on.
        where = github_target(link) if note.builtin and note.source == "GitHub" else None
        if where:
            link = github_link(where)
        kind = DOCK_KINDS.get(note.kind, note.kind)
        if where and where.get("anchor") == "review-comment" and note.kind in ("comment", "issue-comment", "review"):
            # A review comment is its thread's own unit of work (merged into
            # the thread's first comment's once GitHub says which that is).
            kind, unit = "review-comment", f"pr-thread:{where['owner']}/{where['repo']}#{where['number']}:r{where['id']}"
        item_id = unit if kind == "review-comment" else item_id_for(note, unit)
        item = self.find(item_id)
        if item is None and replaces and kind != "review-comment":
            # The group's item, but never a review thread's: each thread is
            # its own work, whatever else its PR's comment group holds.
            grouped = self.by_nid(replaces)
            item = grouped if grouped is not None and grouped.get("kind") != "review-comment" else None
        if item is None:
            nid = int(self.data["next"])
            self.data["next"] = nid + 1
            item = {"id": item_id, "unit": unit, "nid": nid, "time": iso(at), "count": 0, "messages": [], "kinds": []}
            self.items.insert(0, item)
        if item.get("status") == "resolved":
            # Resolved work that comes back (the branch fails again) is open
            # work again, counted afresh.
            item.update({"time": iso(at), "count": 0, "messages": [], "kinds": []})
            item.pop("resolved", None)
        count = int(item.get("count", 0)) + 1
        # Everyone in the unit's thread: "@priya-n, @tomas-r".
        who = list(dict.fromkeys(item.get("who", []) + ([note.who] if note.who else [])))
        fields = [{"key": key, "label": label, "value": ", ".join(who) if key == "who" and len(who) > 1 else value}
                  for key, label, value in note.fields]
        if count > 1:
            fields.append({"key": "count", "label": "Emails", "value": str(count)})
        item.update({
            "unitLabel": unit_label(note, unit),
            "status": "open", "group": note.group, "kind": kind,
            "urgency": "critical" if urgency == "critical" else "normal", "source": note.source or note.brand or "Junco",
            "icon": icon_for(note), "image": item.get("image", "") if item.get("enriched") == link else "", "title": title,
            "summary": shorten(body, 200), "fields": fields,
            "count": count, "updated": iso(at), "account": note.account, "domain": note.domain, "link": link,
            "link_label": note.link_label, "github": where or {},
            "builtin": note.builtin, "service": note.service, "kinds": sorted(set(item.get("kinds", [])) | {note.kind}),
            "messages": (item.get("messages", []) + [note.message_id])[-50:], "who": who})
        item["headline"], item["detail"] = card_lines(item)
        if not item["headline"]:
            item.pop("headline")
        if not item["detail"]:
            item.pop("detail")
        item["card"] = merged_card(item.get("card") if isinstance(item.get("card"), dict) else {}, note.card, at)
        if item.get("enriched") != link:
            # A new link is a new story: the old one's GitHub read goes, and
            # the email's own text stands until GitHub's is read (enrich_feed).
            for key in ("body", "context", "thread", "log", "meta", "jobs", "files", "gh", "enrich_tries"):
                item.pop(key, None)
            if note.text_body:
                item["body"] = github_text(note.text_body)
        make_inert(item)
        item["actions"] = item_actions(item, self.version)
        return int(item["nid"])

    def take_ids(self, sent: dict) -> None:
        """Each item's emails as the Dispatcher recorded them (a group's,
        all of them), so Open in Junco and Mark read act on every one."""
        for item in self.items:
            ids = (sent.get(str(item.get("nid"))) or {}).get("ids")
            # A review thread keeps its own emails: its PR's comment group
            # also holds other threads'.
            if ids and item.get("status") == "open" and item.get("kind") != "review-comment":
                item["messages"] = list(dict.fromkeys(item.get("messages", []) + ids))[-50:]

    def resolve(self, note: Note, now: float | None = None) -> list[dict]:
        """The open work this email settles (any email Junco reads, popped up
        or silent). Returns the items it resolved."""
        done = []

        def settle(item: dict) -> None:
            item["status"] = "resolved"
            item["resolved"] = iso(note.at or now or time.time())
            done.append(item)

        for item in [i for i in self.items if i.get("status") == "open"]:
            same = item.get("unit") == note.unit and bool(note.unit)
            kinds = set(item.get("kinds") or [item.get("kind")])
            if note.kind == "ci-passed" and same:
                settle(item)  # the branch is green again
            elif note.kind == "state" and note.action in ("merged", "closed") and same:
                settle(item)  # the PR (or issue) is done
            elif note.kind == "state" and note.action in ("merged", "closed") and item.get("kind") == "ci-failed" \
                    and note.unit.startswith("pr:") and item.get("unit") == ci_unit_of(note):
                settle(item)  # its PR's runs (GitHub names a PR run by the PR's title) are moot once it's merged or closed
            elif note.kind == "review" and note.mine and same and kinds <= {"review-requested"}:
                settle(item)  # you reviewed what you were asked to
            elif note.kind == "invite-cancel" and same:
                settle(item)  # the meeting is off
            elif note.trusted and note.service and note.service == item.get("service") and SETTLED.search(note.body) \
                    and not NOT_SETTLED.search(note.body):
                # Only the service's own alert senders settle its work.
                if item.get("kind") in ("payment-failed", "bill"):
                    settle(item)  # the service was paid after all
                elif item.get("kind") == "domain-expiring":
                    # A named domain is settled only by its own renewal.
                    named, mine = domain_in(note.body, note.domain), field_value(item, "domain")
                    if (named == mine) if mine else True:
                        settle(item)  # renewed
        self.resolved += done
        return done


# After a sync -----------------------------------------------------------------------


def candidates(db, message_ids: list[str], me: set[str], now: float) -> list[str]:
    """New mail that may notify: unread, fresh, not yours, not hidden."""
    import courier_fields as cf

    out = []
    for message_id in message_ids:
        try:
            message = db.find(message_id)
            if message is None:
                continue
            tags = set(message.tags)
            if "unread" not in tags or tags & {"trash", "spam", "unsent", "draft", "sent"} or now - message.date > FRESH:
                continue
            headers = sync.read_headers([str(path) for path in message.filenames()])
            if cf.sender_of(headers.get("From", "")) in me:
                continue
        except Exception as problem:  # noqa: BLE001 - one odd email never costs the others
            print(f"courier-notify: {message_id}: {problem!r}", file=sys.stderr)
            continue
        out.append(message_id)
    return out


def notes_for(db, message_ids: list[str], invites: bool = False) -> list[Note]:
    """Notes for the emails a template, built-in or taught, makes; with
    `invites` (a version-3 dock), also for calendar invites from anyone."""
    import courier_fields as cf
    import courier_templates as ct

    taught = ct.all_templates()
    senders = ct.builtin_senders() | {t.get("sender") for t in taught}
    notes = []
    for message_id in message_ids:
        try:
            message = db.find(message_id)
            headers = sync.read_headers([str(path) for path in message.filenames()])
            if cf.sender_of(headers.get("From", "")) not in senders:
                if invites and re.search(r"multipart|text/calendar", headers.get("Content-Type", ""), re.I):
                    mail = ct.read_mail(db, message_id)
                    # Only an invite Gmail verified as its sender's (DMARC): a
                    # forged one never reaches the dock.
                    if ct.vouched(mail, mail.address.rpartition("@")[2]):
                        note = invite_note(mail)
                        if note is not None:
                            notes.append(note)
                continue
            mail = ct.read_mail(db, message_id)
            found = ct.fields_for(mail, [t for t in taught if t.get("account") == mail.account])
            note = note_for(mail, *found) if found is not None else None
        except ct.TemplateError:
            continue
        except Exception as problem:  # noqa: BLE001 - markup nested past Python's limit, say: never costs the others
            print(f"courier-notify: {message_id}: {problem!r}", file=sys.stderr)
            continue
        if note is not None:
            note.picture = picture(mail.address)
            notes.append(note)
    return sorted(notes, key=lambda note: note.at)


def invite_note(mail) -> Note | None:
    """A calendar invite's note (an email carrying text/calendar): REQUEST
    is an invitation (its card answers it: courier_cards), CANCEL takes the
    invitation's card away. Anything else (a reply, a publish) is no note,
    and so is an invite whose organiser isn't its sender, exactly: the
    sender is the one Gmail verified (notes_for), so nobody, not even
    someone at the same domain, can speak for another organiser's meeting.
    Its unit is the organiser's and the invite's own id: only that
    organiser's update or cancellation reaches it."""
    import courier_views

    text = ""
    for part in mail.parsed.walk():
        if part.get_content_type() == "text/calendar":
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")[:200000]
            break
    method = re.search(r"^METHOD:\s*(\w+)", text, re.I | re.M)
    method = method.group(1).upper() if method else ""
    if method not in ("REQUEST", "CANCEL"):
        return None
    event = courier_views.parse_invite(text)
    if not event or not event.get("uid"):
        return None
    start, end = event["DTSTART"], event.get("DTEND") or event["DTSTART"]
    organizer = event.get("organizer") or {}
    owner = str(organizer.get("email", "")).lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", owner) or owner != str(mail.address or "").lower():
        return None
    title = shorten(event.get("title") or "Invitation", 90)
    invite = {"uid": event["uid"], "method": method, "title": title, "start": start.astimezone().isoformat(timespec="seconds"),
              "end": end.astimezone().isoformat(timespec="seconds"), "all_day": bool(event.get("DTSTART_day")),
              "where": shorten(event.get("where", ""), 120), "conference": sync.web_link(event.get("conference", "")),
              "organizer": {"name": shorten(organizer.get("name", ""), 60), "email": organizer.get("email", "")},
              "attendees": [{"name": shorten(a.get("name", ""), 60), "email": a.get("email", "")} for a in event.get("attendees", [])][:40],
              "account": getattr(mail, "account", "")}
    who = organizer.get("name") or display_name(mail.sender) or mail.address
    note = Note(kind="invite" if method == "REQUEST" else "invite-cancel", title=f"Invitation: {title}" if method == "REQUEST" else
                f"Cancelled: {title}", body=start.strftime("%a %-d %b, %H:%M"), message_id=mail.id, account=getattr(mail, "account", ""),
                at=float(getattr(mail, "epoch", 0) or 0), builtin=False, link="", link_label="", who=shorten(who, 60),
                source="Calendar", brand="Calendar", unit=f"invite:{owner}:{event['uid'][:200]}", group=f"invite:{owner}:{event['uid'][:200]}",
                card={"invite": invite})
    return with_fields(note, ("who", "Who", who), ("when", "When", note.body), ("title", "Title", title))


def after_sync(message_ids: list[str], me: set[str]) -> set[str]:
    """Notifications for new mail made from a template. Returns the
    Message-IDs it handled (notified, updated or counted), so the people
    lane's "New mail from X" skips them."""
    if not message_ids or os.environ.get("COURIER_NO_NOTIFY"):
        return set()
    now = time.time()
    rules = load_rules()
    to_dock = channel(rules, now) == "dock"
    # Cards (and the kinds only a card shows: bills, parcels, invites…)
    # only while the dock reads version 3.
    rules["_cards"] = to_dock and int(rules.get("dock_version", 1)) >= 3
    with mail_index() as db:
        notes = notes_for(db, candidates(db, message_ids, me, now), invites=rules["_cards"])
    if not notes:
        return set()
    send = None if to_dock else desktop_sender()
    with locked_state() as state:
        # The feed hears every note: popped up or silent, the work it settles
        # resolves, even while the dock is down and notes go to the desktop.
        feed = Feed.load() if to_dock or dock_path().exists() else None
        if feed is not None:
            for note in notes:
                feed.resolve(note, now)
        # The dock's items, or a notification server's ids: a new one (the
        # other, or a restarted server) starts every group afresh.
        server = f"dock:{dock_path()}" if to_dock else send.server
        state.setdefault("server", "")
        if state["server"] != server:
            state["groups"], state["sent"], state["server"] = {}, {}, server
        # Cards in the dock don't crowd the screen: no "N more" folding.
        dispatcher = Dispatcher(rules, state, feed.send if to_dock else send, now, most=10**6 if to_dock else MOST)
        for note in notes:
            dispatcher.dispatch(dock_group(note) if to_dock else note)
        dispatcher.finish()
        dispatcher.prune()
        if to_dock:
            feed.take_ids(state["sent"])
        if feed is not None:
            feed.save(now=now)
        unread = to_dock and bool(to_enrich(feed))
    if unread:
        # GitHub is read apart from the sync, so the people lane's popups
        # never wait on it.
        start_enrich()
    return {note.message_id for note in notes}


# Reading the whole item from GitHub ----------------------------------------------------

# Items read per sync: the rest wait for the next one.
ENRICH_MOST = 3
ENRICH_TRIES = 2


def to_enrich(feed: Feed) -> list[dict]:
    """The open items whose GitHub story isn't read yet (never a made-up one,
    and none that gh failed on twice)."""
    return [item for item in feed.items
            if item.get("status") == "open" and not item.get("demo") and item.get("github")
            and item.get("enriched") != item.get("link") and int(item.get("enrich_tries", 0)) < ENRICH_TRIES]


def start_enrich() -> None:
    """`courier-notify enrich` in a unit of its own (niced, idle IO), not
    waited for. The fixed name keeps it to one at a time: while one runs, the
    next start is refused, and the next sync starts it again."""
    binary = Path.home() / ".local/bin/courier-notify"
    try:
        subprocess.run(["systemd-run", "--user", "--no-block", "--collect", "--quiet", "--unit=courier-enrich", "--nice=19",
                        "--property=IOSchedulingClass=idle", "--description=Junco: read new dock items from GitHub",
                        str(binary), "enrich"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as problem:
        # The cards keep the email's text; the next sync tries again.
        print(f"courier-notify: reading from GitHub: {problem!r}", file=sys.stderr)


def enrich_feed(limit: int = ENRICH_MOST) -> int:
    """Reads, with your gh, the whole of up to `limit` open dock items with a
    GitHub target not yet read (courier_github.details): a comment's body and
    thread, a review comment's diff, a run's failed logs, a PR's description.
    Each item once (again only when a newer email changes its link); never a
    silent note (they aren't in the feed) nor a made-up one. The lock is held
    only to read and to write the feed, never while gh runs. Returns how many
    were read."""
    import courier_github

    with locked_state():
        feed = Feed.load()
        todo = [(item["id"], item.get("link", ""), dict(item["github"])) for item in to_enrich(feed)][:limit]
    done = 0
    for item_id, link, where in todo:
        try:
            found = courier_github.details(where)
        except courier_github.GitHubError as problem:
            found = {"error": str(problem)}
        except Exception as problem:  # noqa: BLE001 - one item never stops the rest, nor the sync
            found = {"error": repr(problem)}
        with locked_state():
            feed = Feed.load()
            item = feed.find(item_id)
            if item is not None and item.get("link") == link:
                apply_details(feed, item, found, link)
                feed.save()
                done += 1
        courier_github.pause()
    return done


def apply_details(feed: Feed, item: dict, found: dict, link: str) -> None:
    """GitHub's whole story into an item (the email's text stays when gh
    couldn't): body, context, thread, log, meta, the author's picture; a
    review comment joins its thread's item."""
    if "error" in found:
        item["enrich_tries"] = int(item.get("enrich_tries", 0)) + 1
        if item["enrich_tries"] >= ENRICH_TRIES:
            item["enriched"] = link  # tried enough: the email's text it is
        return
    for key in ("body", "context", "thread", "log", "meta", "jobs", "files"):
        if found.get(key):
            item[key] = found[key]
    if found.get("image"):
        item["image"] = found["image"]
    item["gh"] = (item.get("gh") or {}) | (found.get("github") or {})
    if found.get("who") and item.get("kind") in ("comment", "review-comment", "review", "review-requested"):
        for field in item.get("fields", []):
            if field.get("key") == "who" and "," not in str(field.get("value")):
                field["value"] = inert(found["who"])
    if found.get("body") and item.get("kind") in ("comment", "review-comment", "review"):
        # The card's lines say what was written, as GitHub has it.
        said = next((line.strip() for line in found["body"].split("\n") if line.strip() and not line.startswith("```")), "")
        item["summary"] = inert(shorten(said, 200))
        comment = next((f for f in item.get("fields", []) if f.get("key") == "comment"), None)
        if comment is None and said:
            item.setdefault("fields", []).append({"key": "comment", "label": "Comment", "value": inert(shorten(said))})
        elif comment is not None and not comment.get("value"):
            comment["value"] = inert(shorten(said))
    context = found.get("context") or {}
    if item.get("kind") == "review-comment" and context.get("file") and found.get("who"):
        item["title"] = inert(f"{found['who']} commented on {context['file']}")
    item["enriched"] = link
    item.pop("enrich_tries", None)
    item["headline"], item["detail"] = card_lines(item)
    for key in ("headline", "detail"):
        if not item[key]:
            item.pop(key)
    make_inert(item)
    root = (found.get("github") or {}).get("thread_root")
    where = item.get("github") or {}
    if item.get("kind") == "review-comment" and root and root != where.get("id"):
        # A reply: the thread's item (its first comment's) takes it.
        root_id = f"pr-thread:{where['owner']}/{where['repo']}#{where['number']}:r{root}"
        first = feed.find(root_id)
        if first is None:
            item["id"] = item["unit"] = root_id
        elif first is not item:
            for key in ("body", "context", "thread", "image", "title", "summary", "fields", "updated", "link", "github", "gh",
                        "enriched", "headline", "detail"):
                if key in item:
                    first[key] = item[key]
            first["count"] = int(first.get("count", 1)) + int(item.get("count", 1))
            first["messages"] = list(dict.fromkeys(first.get("messages", []) + item.get("messages", [])))[-50:]
            first["status"] = "open"
            first.pop("resolved", None)
            feed.remove(item["id"])


# The dock's buttons -------------------------------------------------------------------

REPLY_MOST = 65536
# GitHub's buttons (courier_github.ACTIONS; "comment" is a reply on the PR).
GITHUB_ACTIONS = ("reply", "comment", "react-plus1", "react-+1", "resolve-thread", "resolve", "rerun-failed", "approve")
# A card's own (contract v3): its answer, a page to open, an invitation's answer.
CARD_ACTIONS = ("its-me", "mark-paid", "secure", "pay", "open-run", "answer-in-calendar", "accept", "maybe", "decline")
DOCK_ACTIONS = ("open", "open-junco", "mark-read") + GITHUB_ACTIONS + CARD_ACTIONS
# Text from stdin: a reply, a comment.
INPUT_ACTIONS = {"reply", "comment"}
# Actions that settle the item once they succeed.
SETTLING = {"resolve-thread", "resolve", "approve", "its-me", "mark-paid", "accept", "decline"}
# Pages a card opens (the dock usually opens them itself).
OPENS = {"open", "secure", "pay", "open-run", "answer-in-calendar"}


def dock_item(item_id: str) -> dict | None:
    with locked_state():
        return Feed.load().find(item_id)


def forget(item_id: str) -> dict | None:
    """Takes an item out of the feed, and its group out of notify.json, so
    the next email of that group starts a new item."""
    with locked_state() as state:
        feed = Feed.load()
        item = feed.remove(item_id)
        if item is not None:
            nid = item.get("nid")
            state["groups"] = {key: group for key, group in state.get("groups", {}).items() if group.get("id") != nid}
            state.get("sent", {}).pop(str(nid), None)
            feed.save()
        return item


def settle(item_id: str) -> None:
    """An item's work done by its own action (a thread resolved, a PR
    approved): resolved, so the dock lets it go."""
    with locked_state():
        feed = Feed.load()
        item = feed.find(item_id)
        if item is not None and item.get("status") == "open":
            item["status"] = "resolved"
            item["resolved"] = iso(time.time())
            feed.save()


def one_line(problem: BaseException) -> str:
    """An error as the dock shows it: one line, no traceback."""
    text = next((line.strip() for line in str(problem).splitlines() if line.strip()), "") or type(problem).__name__
    return text[:200]


def dock_action(item_id: str, action: str, given: str | None = None) -> int:
    """The dock's button, whatever goes wrong: one line on stderr and exit
    1 (the item stays), never a traceback."""
    try:
        return run_action(item_id, action, given)
    except Exception as problem:  # noqa: BLE001 - the dock shows this line on the card
        label = {"mark-read": "Mark read", "open-junco": "Open in Junco"}.get(action, action)
        print(f"{label} failed: {one_line(problem)}", file=sys.stderr)
        return 1


def run_action(item_id: str, action: str, given: str | None = None) -> int:
    """`courier-notify action ITEM ACTION`: the dock's buttons, run only when
    pressed. A reply's text comes on stdin (`given`). Prints one line: the
    result on stdout (exit 0), or why not on stderr (1: no such item, or it
    failed; 2: no such action, or nothing to send)."""
    if action not in DOCK_ACTIONS:
        print(f"No action {action!r}", file=sys.stderr)
        return 2
    item = dock_item(item_id)
    if item is None:
        print(f"No item {item_id!r} in the dock", file=sys.stderr)
        return 1
    if action in INPUT_ACTIONS and not (given or "").strip():
        print("Nothing to send", file=sys.stderr)
        return 2
    if is_demo(item_id):
        # A made-up item stands for no mail and nothing on GitHub or his
        # calendar: its buttons never reach any.
        if action in OPENS:
            open_link({"link": DEMO_LINK, "builtin": False})
        elif action == "mark-read" or action in SETTLING:
            forget(item_id)
        print("Demo: nothing sent" if action not in OPENS | {"open-junco", "mark-read"} else "Done")
        return 0
    if action in ("its-me", "mark-paid"):
        # His answer is the whole of it: the item is done.
        settle(item_id)
        print("Marked as you" if action == "its-me" else "Marked paid")
        return 0
    if action in ("secure", "pay", "open-run", "answer-in-calendar"):
        import courier_cards

        url = next((a.get("url", "") for a in courier_cards.card(item).get("actions", []) if a.get("id") == action and a.get("type") == "url"), "")
        if not url:
            print("That item has no page to open", file=sys.stderr)
            return 1
        domain = {"open-run": "github.com", "answer-in-calendar": "google.com"}.get(action, item.get("domain", ""))
        open_link({"link": url, "builtin": True, "domain": domain})
        print("Opened")
        return 0
    if action in ("accept", "maybe", "decline"):
        import courier_calendar

        invite = (item.get("card") or {}).get("invite") if isinstance(item.get("card"), dict) else None
        if not isinstance(invite, dict) or item.get("kind") != "invite":
            print("That item isn't an invitation", file=sys.stderr)
            return 1
        try:
            result = courier_calendar.respond(invite, action)
        except (courier_calendar.CalendarError, sync.SyncError, sync.SignedOut) as problem:
            print(str(problem).splitlines()[0] if str(problem) else "Google Calendar said no", file=sys.stderr)
            return 1
        if action in SETTLING:
            settle(item_id)
        print(result)
        return 0
    if action not in ("open", "open-junco", "mark-read"):
        import courier_github

        where = item.get("github") or {}
        if not where or not item.get("builtin"):
            print("That item isn't on GitHub", file=sys.stderr)
            return 1
        try:
            result = courier_github.ACTIONS["reply" if action == "comment" else action](where, item.get("gh") or {}, given or "")
        except courier_github.GitHubError as problem:
            print(str(problem) or "GitHub said no", file=sys.stderr)
            return 1
        if action in SETTLING:
            settle(item_id)
        print(result)
        return 0
    messages = [m for m in item.get("messages", []) if safe_id(m)]
    if action == "open":
        url = next((a.get("url", "") for a in item.get("actions", []) if a.get("id") == "open"), "")
        if not url:
            print("courier-notify: that item has no address to open", file=sys.stderr)
            return 1
        open_link({"link": url, "builtin": item.get("builtin", True), "domain": item.get("domain", "")})
    elif action == "open-junco":
        if messages:
            open_in_courier(messages[-1])
    elif action == "mark-read":
        mark_read({"ids": messages})
        # Handled: out of the dock.
        forget(item_id)
    print("Done")
    return 0


def dock_dismiss(item_id: str) -> int:
    """`courier-notify dismiss ITEM`: out of the dock, its mail untouched."""
    try:
        gone = forget(item_id)
    except Exception as problem:  # noqa: BLE001 - one line for the dock
        print(f"Dismiss failed: {one_line(problem)}", file=sys.stderr)
        return 1
    if gone is None:
        print(f"courier-notify: no item {item_id!r} in the dock", file=sys.stderr)
        return 1
    return 0


# Made-up items, to see the dock --------------------------------------------------------
#
# `courier-notify demo` puts four made-up items in the feed (a failed CI run,
# a review request, Google and Cloudflare security alerts), with "demo:" ids
# and https://example.com links. They are ordinary items to the dock; to
# Junco they stand for no mail: their buttons never mark, open or touch any,
# and ✓, × or `courier-notify demo --clear` take them out. Nothing else in
# Junco's state changes.

DEMO = "demo:"
DEMO_LINK = "https://example.com"


def is_demo(item_id: str) -> bool:
    return str(item_id).startswith(DEMO)


def demo_notes() -> list[tuple[Note, str]]:
    """The made-up notes (as tools/notify_examples.py's), with their urgency."""
    import email.message
    import types

    def mail(n: int, subject: str, sender: str, address: str, text: str = "", github: dict | None = None):
        parsed = email.message.EmailMessage()
        for name, value in (github or {}).items():
            parsed[f"X-GitHub-{name}"] = value
        return types.SimpleNamespace(id=f"{DEMO}{n}@courier.example", account="demo", sender=sender, address=address, subject=subject,
                                     text=text, epoch=time.time(), parsed=parsed)

    repo = "lumenlabs/lumen-app"
    ci = note_for(mail(1, f"[{repo}] Run failed: CI - main (4f2a9c1)", "GitHub <notifications@github.com>", "notifications@github.com",
                       github={"Reason": "ci_activity", "Sender": "you-example", "Recipient": "you-example"}),
                  {"kind": "ci-failed", "builtin": True},
                  {"status": "ok", "values": {"repo": repo, "workflow": "CI", "status": "Run failed", "branch": "main", "commit": "4f2a9c1",
                                              "jobs": ["build", "test (22.x)", "lint"],
                                              "results": ["Succeeded in 41 seconds", "Failed in 2 minutes", "Failed in 9 seconds"],
                                              "link": DEMO_LINK}})
    review = note_for(mail(2, f"Re: [{repo}] Team invites: one email per teammate (PR #274)", "Priya Natarajan <notifications@github.com>",
                           "notifications@github.com", github={"Reason": "review_requested", "Sender": "priya-n", "Recipient": "you-example"}),
                      {"kind": "review-requested", "builtin": True},
                      {"status": "ok", "values": {"author": "@priya-n", "ref": f"{repo}#274", "repo": repo, "number": "274",
                                                  "title": "Team invites: one email per teammate", "link": DEMO_LINK}})

    thread = note_for(mail(5, f"Re: [{repo}] Onboarding checklist (PR #268)", "Tomas Ruiz <notifications@github.com>",
                           "notifications@github.com", github={"Reason": "comment", "Sender": "tomas-r", "Recipient": "you-example"}),
                      {"kind": "comment", "builtin": True},
                      {"status": "ok", "values": {"author": "@tomas-r", "ref": f"{repo}#268", "repo": repo, "number": "268",
                                                  "title": "Onboarding checklist",
                                                  # Only read for its shape (a review thread): the item opens example.com.
                                                  "link": "https://github.com/lumenlabs/lumen-app/pull/268#discussion_r1520"}})

    def alert(n: int, subject: str, brand: str, service: str, domain: str, address: str, text: str) -> Note:
        return note_for(mail(n, subject, f"{brand} <{address}>", address, text),
                        {"kind": "service", "builtin": True, "service": service, "brand": brand, "domain": domain, "alerts": [address]},
                        {"status": "ok", "values": {"link": DEMO_LINK}})

    google = alert(3, "Security alert: new sign-in on a Linux laptop", "Google", "google-com", "google.com", "no-reply@accounts.google.com",
                   DEMO_GOOGLE)
    cloudflare = alert(4, "[Alert] New login from Lisbon, Portugal", "Cloudflare", "cloudflare-com", "cloudflare.com",
                       "noreply@notify.cloudflare.com", DEMO_CLOUDFLARE)
    return [(ci, "critical"), (review, "normal"), (thread, "normal"), (google, "critical"), (cloudflare, "critical")]


def demo_card_notes() -> list[tuple[Note, str]]:
    """Made-up notes only a version-3 dock shows: a card bill, an invitation
    that clashes with a made-up meeting, a parcel out for delivery."""
    import datetime as dt
    import email.message
    import types

    now = time.time()
    due = (dt.date.today() + dt.timedelta(days=3)).strftime("%-d %b %Y")
    bill_mail = types.SimpleNamespace(id=f"{DEMO}6@courier.example", account="demo", sender="Example Bank <alerts@bank.example>",
                                      address="alerts@bank.example", subject=f"Your credit card bill of ₹18,240 is due on {due}",
                                      text=f"Total amount due ₹18,240\nMinimum amount due ₹910\nPayment due date {due}\nCard ending 4421",
                                      html="", epoch=now - 1800, parsed=email.message.EmailMessage())
    bill = note_for(bill_mail, {"kind": "service", "builtin": True, "service": "bank-example", "brand": "Example Bank", "domain": "bank.example",
                                "alerts": ["alerts@bank.example"]}, {"status": "ok", "values": {}})
    start = dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(15, 0)).astimezone()
    end = start + dt.timedelta(minutes=45)
    at = lambda hours, minutes=0: (start + dt.timedelta(hours=hours, minutes=minutes)).isoformat()  # noqa: E731
    invite = Note(kind="invite", title="Invitation: Design review: notification dock", body=start.strftime("%a %-d %b, %H:%M"),
                  message_id=f"{DEMO}7@courier.example", account="demo", at=now - 600, builtin=False, who="Priya Natarajan",
                  source="Calendar", brand="Calendar", unit="invite:demo-design-review", group="invite:demo-design-review",
                  card={"invite": {"uid": "demo-design-review", "method": "REQUEST", "title": "Design review: notification dock",
                                   "start": start.isoformat(), "end": end.isoformat(), "all_day": False, "where": "Google Meet",
                                   "organizer": {"name": "Priya Natarajan", "email": "priya@example.com"},
                                   "attendees": [{"name": n, "email": ""} for n in ("Priya Natarajan", "Tomas Ruiz", "Sam Okafor", "You")],
                                   # Made-up meetings that day (a real invite reads his calendar).
                                   "events": [{"title": "Lunch", "start": at(-2), "end": at(-1)},
                                              {"title": "1:1 with Tomas", "start": at(0, 30), "end": at(1)},
                                              {"title": "Focus time", "start": at(2), "end": at(4)}]}})
    parcel = Note(kind="parcel", title="Example Store · Parcel", body="Out for delivery", message_id=f"{DEMO}8@courier.example",
                  account="demo", at=now - 900, builtin=False, source="Example Store", brand="Example Store",
                  unit="parcel:demo:headphones", group="parcel:demo:headphones",
                  card={"product": "Noise-cancelling headphones",
                        "steps": {"ordered": now - 2 * 86400, "shipped": now - 86400, "out": now - 900}})
    return [(bill, "normal"), (invite, "normal"), (parcel, "normal")]


# What GitHub would tell about the made-up items (as enrich_feed reads it).
DEMO_GOOGLE = """A new sign-in on Linux

you.example@gmail.com

We noticed a new sign-in to your Google Account on a Linux device. If this was you, you don't need to do anything. If not, we'll help you secure your account.

Device: Linux laptop · Firefox
Where: Lisbon, Portugal (approximate)
When: today, 09:41

You received this email to let you know about important changes to your Google Account and services."""

DEMO_CLOUDFLARE = """New login to your Cloudflare account

A new login to your account was detected.

When: today 09:41 (UTC+05:30)
Where: Lisbon, Portugal
Device: Firefox on Linux
IP address: 203.0.113.24

If this was you, no action is needed. If you don't recognise this login, reset your password now and review your account's active sessions under My Profile → Sessions."""

DEMO_REVIEW_COMMENT = """Could we load these in one go instead of awaiting each member in turn? With 40+ teammates this loop makes the checklist page take ~6 s on staging, and it'll only get worse as teams grow.

A few thoughts:

- one query per team, not one per member
- keep the steps ordered by `position`, so the progress bar doesn't jump around
- `isDone` can take the progress set, instead of reading it from the closure

Something like:

```ts
export async function loadChecklist(team: Team, progress: Progress[]) {
  const steps = await db.checklistSteps.findMany({
    where: { teamId: team.id },
    orderBy: { position: "asc" },
  })
  const done = new Set(progress.map((p) => p.stepId))
  return steps.map((step) => ({ ...step, done: done.has(step.id) }))
}
```

> We did the same in `billing/plan.ts` last month and it took that page from 4 s to about 300 ms.

Not blocking, but I'd like it in before we turn on `ONBOARDING_V2` for everyone. Happy to pair on it this afternoon."""

DEMO_STORIES = {
    "ci-failed": {
        "github": {"owner": "lumenlabs", "repo": "lumen-app", "kind": "run", "run": "9182736450"},
        "found": {"log": ["── test (22.x): failure",
                          "> lumen-app@2.4.0 test",
                          "> vitest run --reporter=dot",
                          " ✓ src/billing/plan.test.ts (12 tests) 41ms",
                          " ✓ src/invites/token.test.ts (8 tests) 22ms",
                          " ✗ src/invites/send.test.ts > sends one email per teammate",
                          "   AssertionError: expected 3 calls to send, got 1",
                          "    ❯ src/invites/send.test.ts:57:31",
                          " Test Files  1 failed | 23 passed (24)",
                          "      Tests  1 failed | 211 passed (212)",
                          "Error: Process completed with exit code 1.",
                          "── lint: failure",
                          "src/invites/send.ts",
                          "  44:9  error  'retries' is assigned a value but never used  @typescript-eslint/no-unused-vars",
                          "✖ 1 problem (1 error, 0 warnings)",
                          "Error: Process completed with exit code 1."],
                  "meta": {"ci": "failing", "head": "main"},
                  "github": {"run_id": "9182736450", "failing": ["test (22.x)", "lint"]}}},
    "review-requested": {
        "github": {"owner": "lumenlabs", "repo": "lumen-app", "kind": "pr", "number": "274"},
        "found": {"body": "Sends one invite email per teammate, instead of one email to the whole team.\n\n"
                          "- `sendInvites()` batches recipients 20 at a time\n"
                          "- retries on 429 with a jittered backoff (3 tries at most)\n"
                          "- a new `invite_sent` event for the audit log\n\n"
                          "Closes #251.\n\n"
                          "> Needs the `INVITES_V2` flag on staging before it merges.",
                  "who": "Priya Natarajan",
                  "meta": {"files": "7", "additions": "214", "deletions": "38", "ci": "passing", "commits": "5", "base": "main",
                           "head": "feature/team-invites"},
                  "github": {"title": "Team invites: one email per teammate"}}},
    "review-comment": {
        "found": {"body": DEMO_REVIEW_COMMENT, "who": "Tomas Ruiz",
                  "context": {"file": "src/onboarding/checklist.ts", "line": 42, "hunk": [
                      "@@ -31,14 +31,19 @@ export async function loadChecklist(team: Team) {",
                      "   const members = await db.members.findMany({ where: { teamId: team.id } })",
                      "-  const steps = []",
                      "-  for (const member of members) {",
                      "-    steps.push(await db.checklistSteps.findFirst({ where: { memberId: member.id } }))",
                      "-  }",
                      "-  return steps",
                      "+  const steps: ChecklistStep[] = []",
                      "+  for (const member of members) {",
                      "+    const step = await db.checklistSteps.findFirst({",
                      "+      where: { memberId: member.id },",
                      "+      orderBy: { position: \"asc\" },",
                      "+    })",
                      "+    if (step) steps.push(step)",
                      "+  }",
                      "+  return steps.map((step) => ({ ...step, done: isDone(step) }))",
                      " }"]},
                  "thread": [{"who": "Priya Natarajan", "time": "", "body": "Looks good overall. One nit: `isDone` reads `progress` from the "
                                                                          "closure, so it's easy to call it before progress loads."},
                             {"who": "Sam Okafor", "time": "", "body": "Fair, I'll pass it in. Leaving the loop as is for now:\n\n"
                                                                     "```ts\nif (step) steps.push(step)\n```"}],
                  "github": {"login": "tomas-r", "comment_id": "1520", "thread_root": "1520", "thread_id": "PRRT_demo",
                             "thread_resolved": False}}},
}


def demo(clear: bool = False) -> list[dict]:
    """`courier-notify demo [--clear]`: the made-up items in the feed (anew,
    with a fresh "updated"), or out of it. Returns the items put in."""
    with locked_state():
        feed = Feed.load()
        feed.data["items"] = [item for item in feed.items if not is_demo(item.get("id", ""))]
        added = []
        if not clear:
            # Made in a feed of their own, so a made-up note can never update
            # a real item that happens to share its unit.
            scratch = Feed({"version": 1, "items": [], "next": feed.data["next"]})
            # A version-3 dock also gets a bill, an invitation and a parcel.
            for note, urgency in demo_notes() + (demo_card_notes() if feed.version >= 3 else []):
                nid = scratch.send(note, note.title, note.body, urgency, 0)
                item = scratch.by_nid(nid)
                item.update({"demo": True, "messages": [], "builtin": False})
                story = DEMO_STORIES.get(item["kind"])
                if story:
                    # As enrich_feed would have it after reading GitHub.
                    item["github"] = story.get("github") or item["github"]
                    stamp = iso(time.time() - 3600)
                    found = json.loads(json.dumps(story["found"]))
                    for entry in found.get("thread", []):
                        entry["time"], stamp = stamp, iso(epoch(stamp) + 1500)
                    apply_details(scratch, item, found, item.get("link", ""))
                # Every button opens example.com, or does nothing (dock_action).
                item.update({"id": DEMO + item["id"], "link": DEMO_LINK, "enriched": DEMO_LINK, "domain": "example.com"})
                if item["kind"] in ("security-alert", "bill"):
                    item["card"] = dict(item.get("card") or {}, **({"secure": DEMO_LINK} if item["kind"] == "security-alert" else {"pay": DEMO_LINK}))
                item["actions"] = item_actions(item, scratch.version)
                added.append(item)
            feed.data["next"] = scratch.data["next"]
            feed.data["items"] = added + feed.items
        feed.save()
    return added


# The buttons ------------------------------------------------------------------------


def safe_id(message_id: str) -> bool:
    return bool(message_id) and not message_id.startswith("-") and not re.search(r"[\x00-\x20\x7f]", message_id)


def open_in_courier(message_id: str) -> None:
    """Shows the email in Courier, starting Courier first if need be."""
    if not safe_id(message_id):
        return
    call = ["qs", "ipc", "-p", str(SHELL), "call", "courier", "open", message_id]
    if subprocess.run(call, capture_output=True).returncode == 0:
        return
    subprocess.run(["qs", "-n", "-d", "-p", str(SHELL)], capture_output=True)
    for _ in range(40):
        time.sleep(0.25)
        if subprocess.run(call, capture_output=True).returncode == 0:
            return


def open_link(entry: dict) -> None:
    """The email's link in the browser: http(s) only (courier_sync.web_link),
    and only to github.com for a built-in template's."""
    import urllib.parse

    url = sync.web_link(entry.get("link", ""))
    if not url:
        return
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    allowed = entry.get("domain") or "github.com"
    if entry.get("builtin", True) and not (host == allowed or host.endswith("." + allowed)):
        return
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def mail_index():
    """Junco's mail index, read-only, from any process: NOTMUCH_CONFIG is
    Junco's own notmuch-config, as courier_mail.Index sets it (the dock's
    `courier-notify action` and the listener inherit no such setting, and
    notmuch has no default config)."""
    import notmuch2

    os.environ["NOTMUCH_CONFIG"] = str(sync.config_dir() / "notmuch-config")
    return notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY)


def mark_read(entry: dict) -> None:
    """Marks read every email the notification covers that's still here
    (one deleted since doesn't stop the rest)."""
    import courier_mail

    ids = []
    with mail_index() as db:
        for message_id in entry.get("ids", []):
            if not safe_id(message_id):
                continue
            try:
                if db.find(message_id) is not None:
                    ids.append(message_id)
            except LookupError:
                continue
    if not ids:
        return
    try:
        courier_mail.mark("read", ids)
    except SystemExit as stop:  # the index stayed locked (a long sync)
        raise RuntimeError(str(stop.code)) from None


def answer(nid: int, action: str, sender: str, desktop: Desktop | None = None) -> str:
    """One button pressed on notification `nid`; `sender` is the server the
    signal came from (Desktop.identity). Returns what was done."""
    with locked_state() as state:
        entry = state.get("sent", {}).get(str(nid))
        server = state.get("server", "")
    if entry is None or (server and sender != server):
        return "not ours"
    if action == ACTION_LINK:
        open_link(entry)
    elif action == ACTION_OPEN:
        open_in_courier((entry.get("ids") or [""])[-1])
    elif action == ACTION_READ:
        mark_read(entry)
        if desktop is not None:
            desktop.close(nid)
    else:
        return "unknown action"
    return action


def closed(nid: int, sender: str) -> None:
    """A notification dismissed: forget it, and start its group afresh."""
    with locked_state() as state:
        if state.get("server") and sender != state["server"]:
            return
        state.get("sent", {}).pop(str(nid), None)
        state["groups"] = {key: group for key, group in state.get("groups", {}).items() if group.get("id") != nid}


def listen() -> None:
    """Answers the buttons on Courier's notifications until stopped."""
    from gi.repository import Gio, GLib

    desktop = Desktop()
    # The dock watches its feed from the start: an empty one until there's work.
    if not dock_path().exists():
        with locked_state():
            Feed().save()

    def on_signal(_bus, sender, _path, _interface, signal, parameters):
        try:
            server = desktop.identity(sender)
            if signal == "ActionInvoked":
                nid, action = parameters.unpack()
                answer(int(nid), str(action), server, desktop)
            elif signal == "NotificationClosed":
                closed(int(parameters.unpack()[0]), server)
        except KeyboardInterrupt:
            raise
        except BaseException as problem:  # noqa: BLE001 - one bad press (even a SystemExit) never stops the listener
            print(f"courier-notify: {signal}: {problem!r}", file=sys.stderr)

    for signal in ("ActionInvoked", "NotificationClosed"):
        desktop.bus.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications", signal,
                                     "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, on_signal)
    GLib.MainLoop().run()


def main() -> int:
    parser = argparse.ArgumentParser(prog="courier-notify", description="Junco's notifications for mail it reads fields from.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("listen", help="answer the buttons on Junco's notifications (courier-notify.service)")
    commands.add_parser("rules", help="the rules in force, as JSON")
    commands.add_parser("counts", help="the silent notifications counted, per day and kind")
    act = commands.add_parser("action", help="a button on an item in the notification dock (open, open-junco, mark-read; on "
                                             "GitHub: reply (its text on stdin), react-plus1, resolve-thread, rerun-failed, approve)")
    act.add_argument("item")
    act.add_argument("action")
    commands.add_parser("dismiss", help="take an item out of the notification dock").add_argument("item")
    commands.add_parser("dock", help="the dock's feed, as JSON")
    commands.add_parser("demo", help="made-up items in the dock, to see it (--clear: take them out)").add_argument(
        "--clear", action="store_true")
    commands.add_parser("enrich", help="read new dock items' whole story from GitHub, with gh (after a sync, by itself)")
    args = parser.parse_args()
    if args.command == "listen":
        listen()
    elif args.command == "rules":
        print(json.dumps(load_rules(), indent=1))
    elif args.command == "counts":
        try:
            counts = json.loads(state_path().read_text()).get("counts", {})
        except (FileNotFoundError, ValueError):
            counts = {}
        for day in sorted(counts):
            print(day, "  ".join(f"{kind} {n}" for kind, n in sorted(counts[day].items(), key=lambda item: -item[1])))
    elif args.command == "action":
        given = None
        if args.action in INPUT_ACTIONS and not sys.stdin.isatty():
            # A reply's text, on stdin from the dock, as UTF-8 (GitHub takes
            # 65,536 characters; more is refused, never cut).
            raw = sys.stdin.buffer.read(REPLY_MOST * 4 + 1)
            given = raw.decode("utf-8", "replace")
            if len(given) > REPLY_MOST:
                print("Too long to send", file=sys.stderr)
                return 2
        return dock_action(args.item, args.action, given)
    elif args.command == "dismiss":
        return dock_dismiss(args.item)
    elif args.command == "dock":
        print(json.dumps(Feed.load().data, ensure_ascii=False, indent=1))
    elif args.command == "enrich":
        os.nice(19)
        print(f"read {enrich_feed()} item(s) from GitHub")
    elif args.command == "demo":
        added = demo(args.clear)
        print("took the made-up items out of the dock" if args.clear else
              "in the dock: " + ", ".join(f"{item['id']} ({item.get('headline') or item['title']})" for item in added))
    return 0


if __name__ == "__main__":
    sys.exit(main())
