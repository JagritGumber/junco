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
    ("marketing", "Offer", "offers",
     r"\boffers?\b|\bdeals?\b|\bsale\b|discount|% off|\bsave\b|limited time|upgrade to|\bfree\b|premium|exclusive|invite"),
    ("domain-expiring", "Expiring soon", "expiry notices",
     r"expiring soon|(?:domain|service|plan|subscription|certificate)s?(?:\(s\))? (?:is |are |will )?(?:expir|about to expire)"
     r"|pending delete|suspended|time to renew|ssl certificates?"),
    ("incident", "Incident", "incidents",
     r"incident|outage|downtime|degraded (?:performance|service)|(?:service|site|website|server|api) (?:is )?down"
     r"|deploy(?:ment)? (?:has )?failed|build failed|failed to deploy"
     r"|limit exceeded|quota exceeded"),
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
    return {"profile": name, "window": base["window"], "bot_logins": [],
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
    have an urgency of their own."""
    rule = rule_for(rules, note.kind)
    group = bool(rule.get("group"))
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
        if kind in ALERT_KINDS and mail.address.lower() not in {a.lower() for a in template.get("alerts", [])}:
            # Alert words from an address that doesn't send this service's
            # alerts (a relayed message, a newsletter): someone's words,
            # never a critical popup.
            kind, label, many = "notice", "Update", "updates"
        link = values.get("link") if isinstance(values.get("link"), str) else ""
        return Note(kind=kind, title=f"{brand} · {label}", body=notice, link=link, link_label=f"Open on {brand}",
                    group=f"service:{template.get('service', brand)}:{kind}", excerpt=notice, brand=brand, many=many, **base)
    if not values:
        # Its template's fields couldn't be read (GitHub changed the
        # email): the sender and subject, as any notification would say.
        return Note(kind=kind, title=who_name or mail.address, body=shorten(mail.subject), **base)

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
    common = base | {"link": link, "ref": ref, "repo": repo, "who": author or who_name, "bot": base["bot"] or is_bot(author)}

    if kind in ("comment", "issue-comment"):
        said = excerpt(mail.text, (r"left a comment \([^)]*\)$", r"^@\S+ commented on this"))
        title = f"{author or who_name} commented on {ref}" if (author or who_name) else f"New comment on {ref}"
        return Note(kind=kind, title=title + (f" · {repo}" if repo else ""), body=said or title_text,
                    group=f"comments:{full}:{ref}" if ref else "", excerpt=said, **common)
    if kind == "commit-comment":
        commit = value("commit")[:7]
        said = excerpt(mail.text)
        return Note(kind=kind, title=f"{who_name or 'Someone'} commented on {commit}" + (f" · {repo}" if repo else ""),
                    body=said or title_text, group=f"comments:{full}:{commit}", excerpt=said, **(common | {"ref": commit}))
    if kind == "review-requested":
        return Note(kind=kind, title=f"Review requested · {ref} · by {who_name or author}",
                    body=f"{repo}: {title_text}" if repo else title_text, **common)
    if kind == "review":
        action = value("action") or "reviewed"
        # In its PR's comment group when the rules say "group" for reviews.
        return Note(kind=kind, title=f"{who_name or author} {action} {ref}", body=f"{repo}: {title_text}" if repo else title_text,
                    group=f"comments:{full}:{ref}" if ref else "", **common)
    if kind == "push":
        count = int(value("count") or 0) if value("count").isdigit() else len(values.get("hashes") or [])
        messages = [shorten(m, 90) for m in values.get("messages") or []]
        body = messages[0] + (f" (+{len(messages) - 1} more)" if len(messages) > 1 else "") if messages else title_text
        return Note(kind=kind, title=f"{author or who_name} pushed {plural(count, 'commit')} to {ref}" + (f" · {repo}" if repo else ""),
                    body=body, group=f"pushes:{full}:{ref}" if ref else "", commits=count, excerpt=body, **common)
    if kind == "state":
        action = (value("action") or "updated").lower()
        return Note(kind=kind, title=f"{ref} {action}" + (f" by {who_name}" if who_name else ""),
                    body=f"{repo}: {title_text}" if repo else title_text, **common)
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
        return Note(kind=kind, title=title, body=body or mail.subject, group=f"ci:{full}:{value('branch')}" if full else "",
                    excerpt=" · ".join(part for part in (f"{workflow} {verb}", body) if part),
                    **(common | {"who": "", "ref": target}))
    if kind == "security-advisory":
        severity = value("severity")
        repos = values.get("repos") or []
        title = f"Security advisory · {value('package')}" + (f" ({severity.lower()})" if severity else "")
        body = title_text + (f" · {plural(len(repos), 'repo')}" if repos else "")
        return Note(kind=kind, title=title, body=body, **common)
    if kind == "dependabot-digest":
        return Note(kind=kind, title="Dependabot alerts", body=f"Weekly digest for {value('week')}", **common)
    if kind == "account-notice":
        return Note(kind=kind, title="GitHub", body=value("notice") or mail.subject, **common)
    # A template you taught: its name, then its fields.
    shown = [f"{name}: {', '.join(item) if isinstance(item, list) else item}"
             for name, item in values.items() if name != "link" and item not in (None, "", [])]
    return Note(kind=kind, title=template.get("name") or who_name, body=shorten(" · ".join(shown[:3]), 160),
                link_label="Open link", **common)


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
    return text.replace("<", "‹").replace(">", "›").replace("](", "]​(").replace("][", "]​[")


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
    return actions + [ACTION_OPEN, "Open in Courier", ACTION_READ, "Mark read"]


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
            GLib.Variant("(susssasa{sv}i)", ("Courier", replaces, "courier", inert(title), inert(body), actions_for(note), hints, -1)),
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
        sync.desktop_notify(title, body, "-a", "Courier", "-i", "courier", "-u", urgency, "-c", "email.arrived")
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


def notes_for(db, message_ids: list[str]) -> list[Note]:
    """Notes for the emails a template, built-in or taught, makes."""
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


def after_sync(message_ids: list[str], me: set[str]) -> set[str]:
    """Notifications for new mail made from a template. Returns the
    Message-IDs it handled (notified, updated or counted), so the people
    lane's "New mail from X" skips them."""
    if not message_ids or os.environ.get("COURIER_NO_NOTIFY"):
        return set()
    import notmuch2

    now = time.time()
    with notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY) as db:
        notes = notes_for(db, candidates(db, message_ids, me, now))
    if not notes:
        return set()
    send = desktop_sender()
    with locked_state() as state:
        state.setdefault("server", "")
        if state["server"] != send.server:
            # A new notification server (a restart): its ids start over.
            state["groups"], state["sent"], state["server"] = {}, {}, send.server
        dispatcher = Dispatcher(load_rules(), state, send, now)
        for note in notes:
            dispatcher.dispatch(note)
        dispatcher.finish()
        dispatcher.prune()
    return {note.message_id for note in notes}


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


def mark_read(entry: dict) -> None:
    """Marks read every email the notification covers that's still here
    (one deleted since doesn't stop the rest)."""
    import notmuch2

    import courier_mail

    ids = []
    with notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY) as db:
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
    parser = argparse.ArgumentParser(prog="courier-notify", description="Courier's notifications for mail it reads fields from.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("listen", help="answer the buttons on Courier's notifications (courier-notify.service)")
    commands.add_parser("rules", help="the rules in force, as JSON")
    commands.add_parser("counts", help="the silent notifications counted, per day and kind")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
