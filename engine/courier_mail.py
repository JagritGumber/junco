#!/usr/bin/env python3
"""Courier's mail reader: what the app shows, as JSON, from the notmuch index.

    courier-mail accounts                 signed-in accounts
    courier-mail conversations            people, updates and newsletters, newest first
    courier-mail thread <conversation>    one conversation's messages, oldest first
    courier-mail read <conversation>      mark it read; Gmail hears on the next sync
    courier-mail act <action> <ids…>      archive, inbox, trash, untrash, spam, unspam (in Gmail)
    courier-mail compose …                write a new email, a reply or a forward
    courier-mail draft <mode> <id>        who a reply, reply-all or forward goes to
    courier-mail contacts                 addresses you write to, for suggestions

Conversation ids: "p:<address>" is a person, "u:<domain>" one sender of
updates, "n:all" every newsletter together. Mailboxes read like
conversations: "m:starred", "m:sent", "m:archive", "m:all", and "s:<words>"
searches every email.
"""

from __future__ import annotations

import argparse
import base64
import collections
import email
import email.header
import email.message
import email.policy
import email.utils
import hashlib
import html
import html.parser
import itertools
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import courier_gmail as gmail  # noqa: E402
import courier_html  # noqa: E402
import courier_later as later  # noqa: E402
import courier_sync as sync  # noqa: E402
import courier_templates as templates  # noqa: E402
import courier_views as views  # noqa: E402

# Newest messages read to build the conversation list.
SCAN = 4000
LIST_LIMIT = 300
THREAD_LIMIT = 80
BODY_LIMIT = 4000
LOGOS = {"github.com": "github", "linear.app": "linear"}
# Second-level labels under country codes: amazon.co.uk keeps three labels.
SHARED_SECOND_LEVEL = {"ac", "co", "com", "edu", "gov", "net", "org"}


def cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "courier"


def remember(name: str, data) -> None:
    """Keeps the last answer for the app to show instantly next time, while
    it fetches a fresh one. Threads are named by the md5 of their id, which
    the app computes the same way (Qt.md5)."""
    try:
        sync.write_private(cache_dir() / name, json.dumps(data, ensure_ascii=False))
    except OSError:
        pass  # A cache that can't be written only costs speed.


def decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(value)))
    except (UnicodeError, LookupError, email.errors.HeaderParseError):
        return value


def address_of(value: str | None) -> tuple[str, str]:
    name, address = email.utils.parseaddr(decode(value))
    return name.strip().strip('"'), address.lower()


def base_domain(domain: str) -> str:
    labels = domain.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SHARED_SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def nice_name(address: str) -> str:
    """A readable name for a sender who sent none: the site for role boxes
    ("contact@lumenlabs.example" -> "Lumenlabs"), else the mailbox
    ("riya.kapoor@" -> "Riya Kapoor")."""
    local, _, domain = address.partition("@")
    if not domain:  # Already a domain (an updates sender).
        return address.split(".")[0].capitalize()
    if local in sync.ROLE_WORDS or sync.ROBOT_SENDER.search(local):
        return base_domain(domain).split(".")[0].capitalize()
    return " ".join(part.capitalize() for part in re.split(r"[._+-]+", local) if part) or address


def quoted(text: str) -> str:
    return '"' + text.replace('"', "") + '"'


def short_time(epoch: int) -> str:
    moment = datetime.fromtimestamp(epoch)
    today = date.today()
    if moment.date() == today:
        return clock(moment)
    if moment.date() == today - timedelta(days=1):
        return "Yesterday"
    if today - moment.date() < timedelta(days=7):
        return moment.strftime("%a")
    if moment.year == today.year:
        return f"{moment.day} {moment.strftime('%b')}"
    return moment.strftime("%d/%m/%y")


def day_label(epoch: int) -> str:
    moment = datetime.fromtimestamp(epoch)
    today = date.today()
    if moment.date() == today:
        return "Today"
    if moment.date() == today - timedelta(days=1):
        return "Yesterday"
    if today - moment.date() < timedelta(days=7):
        return moment.strftime("%A")
    if moment.year == today.year:
        return f"{moment.day} {moment.strftime('%B')}"
    return f"{moment.day} {moment.strftime('%B %Y')}"


def bucket(epoch: int) -> str:
    """The list section an email sits in: Today, Yesterday or Earlier."""
    day = datetime.fromtimestamp(epoch).date()
    today = date.today()
    return "Today" if day == today else "Yesterday" if day == today - timedelta(days=1) else "Earlier"


def clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0").lower()


def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} B"


# Message text ------------------------------------------------------------------


class _HtmlText(html.parser.HTMLParser):
    """HTML mail as readable text; by default without the quoted history."""

    BLOCKS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article"}
    HIDDEN = {"script", "style", "head", "title"}

    def __init__(self, keep_quotes: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0
        self.quote_depth = 0
        self.keep_quotes = keep_quotes

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class") or ""
        if not self.keep_quotes and (self.quote_depth or tag == "blockquote" or "gmail_quote" in classes):
            self.quote_depth += 1 if tag not in {"br", "img", "hr", "meta", "link", "input"} else 0
            return
        if tag in self.HIDDEN:
            self.hidden += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")

    def handle_endtag(self, tag: str) -> None:
        if self.quote_depth:
            self.quote_depth -= 1
            return
        if tag in self.HIDDEN and self.hidden:
            self.hidden -= 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden and not self.quote_depth:
            self.parts.append(data)


def html_to_text(markup: str, keep_quotes: bool = False) -> str:
    parser = _HtmlText(keep_quotes)
    try:
        parser.feed(markup)
        parser.close()
    except (AssertionError, ValueError):
        pass
    return "".join(parser.parts)


REPLY_HEADER = re.compile(r"^(On\s.{4,300}?wrote:|-----\s*Original Message\s*-----|_{20,})\s*$", re.M | re.S)


def tidy(text: str, limit: int | None = BODY_LIMIT) -> str:
    """The new part of a reply: quoted history, signature and filler removed."""
    text = text.replace("\r\n", "\n").replace(" ", " ")
    match = REPLY_HEADER.search(text)
    if match:
        text = text[: match.start()]
    lines = [line.rstrip() for line in text.split("\n") if not line.lstrip().startswith(">")]
    if "-- " in lines:
        lines = lines[: lines.index("-- ")]
    text = "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() for line in lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if limit is None or len(text) <= limit else text[:limit].rstrip() + " …"


def tidy_whitespace(text: str) -> str:
    """Readable whole text: trimmed lines, no runs of blank lines."""
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.replace("\r\n", "\n").replace("\u00a0", " ").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def read_message(path: str) -> tuple[str, list[dict]]:
    try:
        with open(path, "rb") as handle:
            message = email.message_from_binary_file(handle, policy=email.policy.default)
    except OSError:
        return "", []
    body = ""
    for kind in ("plain", "html"):
        part = message.get_body(preferencelist=(kind,))
        if part is None:
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, KeyError):
            content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        body = tidy(content if kind == "plain" else html_to_text(content))
        if body:
            break
    attachments = []
    for part in message.iter_attachments():
        name = part.get_filename()
        if not name or (part.get_content_disposition() == "inline" and part.get("Content-ID")):
            continue
        raw = part.get_payload()
        size = len(raw) if isinstance(raw, str) else 0
        if str(part.get("Content-Transfer-Encoding", "")).lower() == "base64":
            size = size * 3 // 4
        attachments.append({"name": decode(name), "size": human_size(size)})
    return body, attachments


def parse_file(path: str):
    try:
        with open(path, "rb") as handle:
            return email.message_from_binary_file(handle, policy=email.policy.default)
    except OSError:
        return None


def part_text(part) -> str:
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, KeyError):
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    return content if isinstance(content, str) else content.decode("utf-8", "replace")


def attachment_parts(message) -> list:
    """The files a reader would call attachments (not images drawn inside the mail)."""
    return [
        part for part in message.iter_attachments()
        if part.get_filename() and not (part.get_content_disposition() == "inline" and part.get("Content-ID"))
    ]


def preview_of(path: str, fallback: str) -> str:
    body, attachments = read_message(path)
    line = next((line for line in body.split("\n") if line.strip()), "")
    if not line and attachments:
        line = f"📎 {attachments[0]['name']}"
    return (line or fallback)[:160]


# Reading the index --------------------------------------------------------------


# Deleted, spam and drafts (courier_sync.HIDDEN).
HIDDEN = sync.HIDDEN


class Index:
    def __init__(self, writable: bool = False) -> None:
        import notmuch2

        self.notmuch = notmuch2
        os.environ["NOTMUCH_CONFIG"] = str(sync.config_dir() / "notmuch-config")
        self.accounts = sync.load_accounts()
        self.me = {account["email"].lower() for account in self.accounts}
        mode = notmuch2.Database.MODE.READ_WRITE if writable else notmuch2.Database.MODE.READ_ONLY
        self.db = notmuch2.Database(mode=mode)
        # One account's mail only, when the app shows one account (a notmuch
        # query, e.g. "tag:account/work"); "" for every account.
        self.scope = ""

    def close(self) -> None:
        self.db.close()

    def newest_first(self, query: str):
        # Deleted and spam emails vanish at once; the next sync removes them.
        visible = HIDDEN if query.strip() == "*" else f"({query}) and {HIDDEN}"
        if self.scope:
            visible = f"({visible}) and ({self.scope})"
        return self.db.messages(visible, sort=self.notmuch.Database.SORT.NEWEST_FIRST)


def lane_of(tags: set[str]) -> str:
    return next((lane for lane in sync.LANES if lane in tags), "updates")


def account_of(tags: set[str]) -> str:
    return next((tag.split("/", 1)[1] for tag in tags if tag.startswith("account/")), "")


def conversation_key(index: Index, message, lane: str) -> tuple[str, str, str] | None:
    """(conversation id, display name, address) for one message."""
    name, sender = address_of(header_or_empty(message, "from"))
    if lane == "newsletters":
        return "n:all", name or sender, sender
    if lane == "people":
        if sender in index.me:
            try:
                to = message.header("to")
            except LookupError:
                return None
            others = [(n, a.lower()) for n, a in email.utils.getaddresses([decode(to)]) if a and a.lower() not in index.me]
            if not others:
                return None
            name, sender = others[0]
            name = name.strip().strip('"')
        return f"p:{sender}", name, sender
    if sender in index.me:
        return None  # Your unsubscribe requests and other mail to robots.
    domain = base_domain(sender.rpartition("@")[2])
    return f"u:{domain}", name, domain


def conversations(index: Index) -> list[dict]:
    found: dict[str, dict] = {}
    names: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    newsletter_senders: list[str] = []
    for scanned, message in enumerate(index.newest_first("*")):
        if scanned >= SCAN:
            break
        tags = set(message.tags)
        lane = lane_of(tags)
        key = conversation_key(index, message, lane)
        if key is None:
            continue
        conversation_id, name, address = key
        if name:
            names[conversation_id][name] += 1
        if lane == "newsletters" and name and name not in newsletter_senders:
            newsletter_senders.append(name)
        entry = found.get(conversation_id)
        if entry is None:
            domain = address.rpartition("@")[2] or address
            entry = found[conversation_id] = {
                "id": conversation_id,
                "kind": "person" if lane == "people" else "lane",
                "lane": lane,
                "account": account_of(tags),
                "name": name or address,
                "address": address,
                "epoch": int(message.date),
                "time": short_time(int(message.date)),
                "unread": 0,
                "logo": LOGOS.get(domain, ""),
                "icon": "newspaper" if lane == "newsletters" else "",
                "_latest": str(message.path),
                "_subject": header_or_empty(message, "subject"),
                "_mine": address_of(header_or_empty(message, "from"))[1] in index.me,
            }
        if "unread" in tags:
            entry["unread"] += 1
        if "inbox" in tags:
            entry["_inbox"] = True

    # Like Gmail's inbox: a conversation shows while any of its emails is in
    # the inbox. Archiving them all hides it until someone writes again.
    ordered = sorted((e for e in found.values() if e.get("_inbox")), key=lambda entry: -entry["epoch"])[:LIST_LIMIT]
    import courier_avatars

    pictures = courier_avatars.load_index()
    for entry in ordered:
        entry["avatar"] = courier_avatars.picture_for(entry["id"], pictures)
        if entry["lane"] == "people":
            text = preview_of(entry["_latest"], entry["_subject"])
            entry["preview"] = f"You: {text}" if entry["_mine"] else text
            entry["name"] = names[entry["id"]].most_common(1)[0][0] if names[entry["id"]] else nice_name(entry["address"])
        elif entry["lane"] == "updates":
            entry["preview"] = entry["_subject"]
            entry["name"] = names[entry["id"]].most_common(1)[0][0] if names[entry["id"]] else nice_name(entry["address"])
        else:
            entry["name"] = "Newsletters"
            shown = newsletter_senders[:3]
            more = len(newsletter_senders) - len(shown)
            entry["preview"] = ", ".join(shown) + (f" and {more} more" if more > 0 else "")
            entry["address"] = f"{len(newsletter_senders)} senders"
        for private in ("_latest", "_subject", "_mine", "_inbox"):
            entry.pop(private, None)
    return ordered


# Mailboxes beside the inbox's conversations. Archive is everything out of the
# inbox that you didn't send yourself.
MAILBOXES = {
    "starred": "tag:flagged",
    # Gmail's one-click unsubscribe sends an email titled exactly "unsubscribe"
    # for you; those aren't mail you wrote.
    "sent": 'tag:sent and not subject:"/^unsubscribe$/"',
    "archive": "not tag:inbox and not tag:sent",
    "all": "*",
}


def conversation_query(conversation_id: str) -> str:
    kind, _, value = conversation_id.partition(":")
    if kind == "p" and value:
        # Only the conversation itself: their newsletters stay in their lane.
        return f"(from:{quoted(value)} or to:{quoted(value)}) and tag:people"
    # A sender's updates and the newsletters list their inbox emails, so
    # archiving one takes it off the list; a person's chat keeps its history.
    if kind == "u" and value:
        return f"tag:updates and tag:inbox and from:{quoted(value)}"
    if kind == "n":
        return "tag:newsletters and tag:inbox"
    if kind == "m" and value in MAILBOXES:
        return MAILBOXES[value]
    if kind == "s" and value.strip():
        return value.strip()
    raise SystemExit(f"courier-mail: unknown conversation {conversation_id!r}")


GITHUB_REPO = re.compile(r"\[([^\]]+)\]\s*")


# What an email is about, from its subject, as a Material Symbols icon; the
# first match wins. Measured on his mail: security and codes, sales, jobs,
# shipping, renewals and invoices are the common kinds.
TOPIC_ICONS = [
    (("verification code", "otp", "one-time", "verify", " code"), "pin"),
    (("security", "sign-in", "signin", "login", "log in", "new device", "password", "2fa"), "shield_lock"),
    (("invoice", "receipt", "payment", "paid", "billing", "charged", "refund"), "receipt_long"),
    (("order", "shipped", "shipping", "delivery", "delivered", "package", "dispatch"), "local_shipping"),
    (("renew", "subscription", "expir", "your plan", "trial"), "autorenew"),
    (("% off", "sale", "offer", "deal", "discount", "coupon", "save "), "sell"),
    (("webinar", "event", "invite", "invitation", "meeting", "rsvp", "join us"), "event"),
    (("job", "hiring", "career", "role at", "apply now", "interview"), "work"),
    (("alert", "outage", "incident", "downtime", "warning", "action required"), "notification_important"),
    (("report", "traffic", "analytics", "insight", "stats", "performance"), "insights"),
    (("welcome", "getting started", "thanks for signing", "thank you for signing"), "waving_hand"),
    (("newsletter", "digest", "weekly", "monthly", "edition", "issue #"), "newspaper"),
    (("new", "release", "changelog", "introducing", "launch", "update", "what's new", "now available"), "new_releases"),
]


def topic_icon(subject: str) -> str:
    lowered = f" {subject.lower()}"
    return next((icon for words, icon in TOPIC_ICONS if any(word in lowered for word in words)), "mail")


def update_card(message, subject: str, sender_name: str) -> dict:
    lowered = subject.lower()
    status, icon = "info", topic_icon(subject)
    try:
        reason = (message.header("x-github-reason") or "").lower()
    except LookupError:
        reason = ""
    if "merged" in lowered:
        status, icon = "merged", "merge"
    elif any(word in lowered for word in ("failed", "failure", "error", "declined", "suspended")):
        status, icon = "failed", "error"
    elif reason == "review_requested" or "review request" in lowered:
        status, icon = "review", "rate_review"
    elif reason in {"comment", "mention"} or lowered.startswith("re:"):
        icon = "chat_bubble"
    meta = sender_name
    repo = GITHUB_REPO.search(subject)
    if repo:
        meta = repo.group(1)
        subject = GITHUB_REPO.sub("", subject, count=1)
    return {"kind": "update", "status": status, "icon": icon, "title": subject, "meta": meta}


def thread(index: Index, conversation_id: str) -> list[dict]:
    import courier_avatars

    try:
        messages = list(itertools.islice(index.newest_first(conversation_query(conversation_id)), THREAD_LIMIT))
    except index.notmuch.NotmuchError:
        raise SystemExit("courier-mail: couldn't search for that") from None
    pictures = courier_avatars.load_index()
    items = []
    previous_subject = None
    for message in reversed(messages):
        epoch = int(message.date)
        subject = header_or_empty(message, "subject")
        sender_name, sender = address_of(header_or_empty(message, "from"))
        base = {"id": message.messageid, "day": day_label(epoch), "time": clock(datetime.fromtimestamp(epoch))}
        if not conversation_id.startswith("p:"):
            tags = set(message.tags)
            label = sender_name or nice_name(sender)
            if sender in index.me:
                # Your own email reads by who it went to.
                to_name, to_address = address_of(header_or_empty(message, "to"))
                sender, label = to_address or sender, f"To {to_name or nice_name(to_address)}" if to_address else "You"
            items.append(base | update_card(message, subject, sender_name or sender) | {
                "sender": label,
                "inbox": "inbox" in tags,
                "avatar": courier_avatars.picture_for_key(f"d:{base_domain(sender.rpartition('@')[2])}", pictures),
                "snippet": preview_of(str(message.path), ""),
                "unread": "unread" in tags,
                "starred": "flagged" in tags,
                # Which of your accounts it came to; one sender can write to several.
                "account": account_of(tags),
                "epoch": epoch,
                "bucket": bucket(epoch),
                # Older emails need their date, not just a time of day.
                "time": base["time"] if bucket(epoch) != "Earlier" else short_time(epoch),
            })
            continue
        body, attachments = read_message(str(message.path))
        plain_subject = re.sub(r"^((re|fwd?|aw)\s*:\s*)+", "", subject, flags=re.I).strip()
        item = base | {"from": "me" if sender in index.me else "them", "body": body, "attachments": attachments}
        if plain_subject and plain_subject != previous_subject:
            item["subject"] = plain_subject
        previous_subject = plain_subject
        items.append(item)
    return items


def theme_of(text: str):
    """The app's colours from --theme (JSON), or None."""
    if not text:
        return None
    import courier_theme

    try:
        return courier_theme.Theme.from_json(json.loads(text))
    except (ValueError, AttributeError):
        raise MailError("--theme is JSON: {\"surface\", \"text\", \"muted\", \"link\"}") from None


def find_message(index: Index, message_id: str):
    message = index.db.find(message_id)
    parsed = parse_file(str(message.path))
    if parsed is None:
        raise SystemExit("courier-mail: that message's file is gone; it may have been deleted in Gmail")
    return message, parsed


def message_text(parsed) -> str:
    """The email as plain text: its text/plain part with whitespace tidied,
    else its HTML as text (quotes kept). The one string the reader's plain
    view shows and teach mode reads ("full" and "plain")."""
    plain = parsed.get_body(preferencelist=("plain",))
    if plain is not None and part_text(plain).strip():
        return tidy_whitespace(part_text(plain))
    rich = parsed.get_body(preferencelist=("html",))
    if rich is not None:
        return tidy_whitespace(html_to_text(part_text(rich), keep_quotes=True))
    return ""


# Headers machine mail carries: a forge's or tracker's own (X-GitHub-Reason,
# X-GitLab-Project…), or a mailing list's and bulk mail's.
MACHINE_PREFIXES = ("x-github-", "x-gitlab-", "x-gitea-", "x-forgejo-", "x-bitbucket-", "x-jira-", "x-linear-", "x-sentry-",
                    "x-circleci", "x-buildkite", "x-jenkins", "x-travis", "x-phabricator-", "x-gerrit-", "x-launchpad-")


def automated(parsed, sender: str) -> bool:
    """Whether a machine sent the email (a forge, CI, a tracker, a list)."""
    names = {key.lower(): str(value) for key, value in parsed.items()}
    if any(name.startswith(MACHINE_PREFIXES) for name in names):
        return True
    if names.get("auto-submitted", "no").strip().lower() not in {"", "no"}:
        return True
    if names.get("precedence", "").strip().lower() in {"bulk", "list", "junk", "auto_reply"} or "list-id" in names:
        return True
    return bool(sync.ROBOT_SENDER.search(sender.partition("@")[0]))


# The lines a notification ends with: how to reply, where to view it, why it
# came and how to stop it.
FOOTER_LINE = re.compile(
    r"reply to this email directly|view it on (?:github|gitlab|gitea|bitbucket)|\bunsubscribe\b|notification settings"
    r"|you are receiving this|you(?:'re| are)? (?:receiving|getting) this|you received this|manage (?:your )?(?:notification|email|subscription)"
    r"|mute (?:this )?(?:thread|notifications)|to stop receiving|(?:email|notification) preferences|this (?:email|message) was sent (?:to|by)",
    re.I)
SEPARATOR = re.compile(r"^\s*(?:—|–|--|-- |_{3,}|-{3,}|={3,}|\*{3,})\s*$")
FOOTER_LINES = 14


def footer_start(text: str) -> int:
    """Where a notification's footer begins in `text` (message_text), or -1:
    the first of its last FOOTER_LINES lines that says how to reply, view,
    or unsubscribe, with the rule and blank lines just above it."""
    lines = text.split("\n")
    starts = list(itertools.accumulate((len(line) + 1 for line in lines), initial=0))
    first = next((number for number in range(max(0, len(lines) - FOOTER_LINES), len(lines)) if FOOTER_LINE.search(lines[number])), None)
    if first is None:
        return -1
    while first > 0 and (not lines[first - 1].strip() or SEPARATOR.match(lines[first - 1])):
        first -= 1
    while first < len(lines) - 1 and not lines[first].strip():
        first += 1
    return starts[first] if first > 0 else -1


# A text part that only points at the HTML.
STUB = re.compile(r"view (?:this|it|the) (?:email|message|newsletter)? ?(?:in|on) (?:your|a|the) (?:web )?browser|does(?:n't| not) support html"
                  r"|html version|enable html", re.I)
WORD = re.compile(r"[^\W\d_]{2,}")
HTML_TAG = re.compile(r"</?(?:html|head|body|p|br|div|span|table|tr|td|ul|ol|li|strong|b|a)\b[^<>]*>", re.I)
HTML_START = re.compile(r"\s*<(?:!doctype|html|head|body|meta)\b", re.I)


def substantive(text: str, footer: int, rich) -> bool:
    """Whether the text part says the email properly (not a stub pointing at
    the HTML, nor a fraction of it)."""
    body = text if footer < 0 else text[:footer]
    words = WORD.findall(re.sub(r"https?://\S+|<[^<>\s]+>", " ", body))
    # Some senders put their HTML's source in the text part (a pull request's
    # text quoting a little HTML is still text).
    tags = len(HTML_TAG.findall(body))
    if HTML_START.match(body) or (tags >= 12 and tags > 0.2 * len(words)):
        return False
    if len(words) < 6 or (STUB.search(body) and len(words) < 40):
        return False
    if rich is not None:
        whole = len(WORD.findall(html_to_text(part_text(rich))))
        if whole and len(words) < 0.3 * whole:
            return False
    return True


# A text part mostly made of web addresses (social and job alerts' tracking
# links) reads worse than its HTML: measured on a real mailbox, GitHub's
# notices are 14% addresses (median, 55% at the 90th percentile), LinkedIn's,
# Indeed's and Pinterest's 86-89%.
MOSTLY_LINKS = 0.6


def readable(text: str, footer: int) -> bool:
    """Whether the text part (before its footer) is words more than links."""
    body = text if footer < 0 else text[:footer]
    chars = len(re.sub(r"\s", "", body)) or 1
    return sum(len(url) for url in re.findall(r"https?://\S+", body)) / chars <= MOSTLY_LINKS


# A file a review comment is about ("In apps/api/src/seal.ts:"), on a line
# of its own in the HTML's text.
FILE_LINE = re.compile(r"In\s+(\S{1,200}\.\S{1,20}):")
# How much of the HTML html_only_code() reads, and how many code blocks.
CODE_SCAN = 2 * 1024 * 1024
CODE_BLOCKS = 20


def html_only_code(markup: str, text: str) -> bool:
    """Whether the HTML shows code the text part leaves out: a file it is
    about ("In apps/api/src/seal.ts:", as GitHub's review comments say) or a
    code block (<pre>) whose code the text doesn't have. Such an email reads
    better as its HTML (in the app's colours) than as text."""
    markup = markup[:CODE_SCAN]
    for line in html_to_text(markup).splitlines():
        line = line.strip()
        found = FILE_LINE.fullmatch(line) if len(line) <= 240 else None
        if found and found.group(1) not in text:
            return True
    squashed = re.sub(r"\s+", "", html.unescape(text))
    lower = markup.lower()
    at = 0
    for _ in range(CODE_BLOCKS):
        start = lower.find("<pre", at)
        if start < 0:
            break
        end = lower.find("</pre>", start)
        if end < 0:
            break
        code = re.sub(r"\s+", "", html.unescape(re.sub(r"<[^<>]*>", "", markup[start:end])))
        if len(code) >= 20 and code not in squashed:
            return True
        at = end + 6
    return False


# How each sender's mail is shown, as chosen in the reader's menu:
# colours "dark" | "original" (else by the email), plain "always" |
# "original" (else plain text for machine mail with a proper text part).
READER_CHOICES = {"colours": {"auto", "dark", "original"}, "plain": {"auto", "always", "original"}}


def reader_prefs() -> dict:
    return later.load("reader.json", {})


def set_reader_pref(sender: str, colours: str = "", plain: str = "") -> dict:
    sender = sender.strip().lower()
    if not sender:
        raise MailError("Which sender?")
    prefs = reader_prefs()
    entry = dict(prefs.get(sender, {}))
    for key, value in (("colours", colours), ("plain", plain)):
        if not value:
            continue
        if value not in READER_CHOICES[key]:
            raise MailError(f"{key} is one of {', '.join(sorted(READER_CHOICES[key]))}.")
        if value == "auto":
            entry.pop(key, None)
        else:
            entry[key] = value
    if entry:
        prefs[sender] = entry
    else:
        prefs.pop(sender, None)
    later.save("reader.json", prefs)
    return {"sender": sender, "colours": entry.get("colours", "auto"), "plain": entry.get("plain", "auto")}


def reading(parsed, tags: set[str], sender: str, theme=None) -> dict:
    """How the reader shows an email: its views and which one to open.

    - "plain": the text part, drawn natively (links, lists, quotes and code
      formatted lightly, the footer folded into a line), by default for
      machine mail whose text part says it properly, unless its HTML is
      designed; always or never, per sender, by choice.
    - "themed": simple HTML (courier_html.classify) in the app's colours
      (courier_theme), or any HTML whose sender was set to "dark".
    - "designed": the HTML on its own paper, as made.
    - "text": mail from people, as text with its quoted history folded."""
    plain = parsed.get_body(preferencelist=("plain",))
    rich = parsed.get_body(preferencelist=("html",))
    prefs = reader_prefs().get(sender.lower(), {})
    colours, choice = prefs.get("colours", "auto"), prefs.get("plain", "auto")
    rendered, markdown = rendered_view(parsed, plain, rich, theme, colours)
    text = message_text(parsed)
    has_plain = plain is not None and part_text(plain).strip() != ""
    footer = footer_start(text) if has_plain else -1
    plain_ok = has_plain and substantive(text, footer, rich)
    auto_plain = (plain_ok and readable(text, footer) and automated(parsed, sender)
                  and (rendered is None or rendered.get("kind") == "simple")
                  and not (rich is not None and html_only_code(part_text(rich), text)))
    if plain_ok and (choice == "always" or (choice == "auto" and auto_plain)):
        view = "plain"
    elif rendered and ("people" not in tags or markdown):
        view = "themed" if rendered.get("themed") else "designed"
    else:
        view = "text"
    return {
        "html": rendered["html"] if rendered else "",
        "htmlBackground": rendered["background"] if rendered else "",
        "view": view,
        "kind": rendered.get("kind", "") if rendered else "",
        "themed": bool(rendered and rendered.get("themed")),
        "plain": text if plain_ok else "",
        "plainFooter": footer if plain_ok else -1,
        "plainAuto": auto_plain,
        "prefs": {"sender": sender.lower(), "colours": colours, "plain": choice},
    }


def open_message(index: Index, message_id: str, theme=None) -> dict:
    """One whole email for the reader: the new text, the full text with any
    quoted history, its views (reading()), who it's from and to, and its
    attachments. `theme` (courier_theme.Theme) is the app's colours."""
    message, parsed = find_message(index, message_id)
    rich = parsed.get_body(preferencelist=("html",))
    full = message_text(parsed)
    new = tidy(full, limit=None)
    name, sender = address_of(header_or_empty(message, "from"))
    epoch = int(message.date)
    moment = datetime.fromtimestamp(epoch)
    tags = set(message.tags)
    view = reading(parsed, tags, sender, theme)
    return view | {
        "id": message_id,
        "subject": header_or_empty(message, "subject") or "(no subject)",
        "fromName": name or nice_name(sender),
        "fromAddress": sender,
        "mine": sender in index.me,
        "to": header_or_empty(message, "to"),
        "cc": header_or_empty(message, "cc"),
        "date": f"{moment.strftime('%A')}, {moment.day} {moment.strftime('%B %Y')}, {clock(moment)}",
        "body": new or full,
        "full": full if full != new else "",
        "hasOriginal": rich is not None,
        "details": views.details(index, message, parsed),
        # Fields you taught for this email's template (courier_templates).
        "fields": fields_card(index, message),
        "inbox": "inbox" in set(message.tags),
        "unread": "unread" in set(message.tags),
        "account": account_of(set(message.tags)),
        "epoch": epoch,
        "avatar": sender_picture(sender),
        "starred": "flagged" in set(message.tags),
        "attachments": [
            {"index": number, "name": decode(part.get_filename()), "size": human_size(len(part.get_payload(decode=True) or b"")), "type": part.get_content_type()}
            for number, part in enumerate(attachment_parts(parsed))
        ],
    }


def fields_card(index: Index, message) -> dict | None:
    """The fields read from this email, when its template was taught. A
    problem there never stops the email opening."""
    try:
        return templates.fields_of(index.db, message)
    except Exception as problem:  # noqa: BLE001 - the email matters more than its fields
        print(f"courier-mail: fields: {problem}", file=sys.stderr)
        return None


def rendered_view(parsed, plain, rich, theme=None, colours: str = "auto") -> tuple[dict | None, bool]:
    """The email's designed version, and whether it came from Markdown: its
    HTML part, or for a plain-text email written in Markdown, that text
    rendered; in the theme's colours when courier_html.designed() says so."""
    if rich is not None:
        return courier_html.designed(parsed, part_text(rich), theme, colours), False
    text = part_text(plain) if plain is not None else ""
    if text and courier_html.looks_like_markdown(text):
        return courier_html.designed(parsed, courier_html.markdown_html(text), theme, colours), True
    return None, False


def sender_picture(sender: str) -> str:
    """The sender's logo or photo, when courier-avatars has one."""
    import courier_avatars

    if not sender or "@" not in sender:
        return ""
    return courier_avatars.picture_for_key(f"d:{base_domain(sender.rpartition('@')[2])}", courier_avatars.load_index())


# Only what an email needs to look right; no scripts, forms, frames or redirects.
ORIGINAL_POLICY = (
    "default-src 'none'; img-src * data:; style-src 'unsafe-inline' *; font-src * data:; media-src * data:; "
    "form-action 'none'; base-uri 'none'"
)


def show_original(index: Index, message_id: str) -> dict:
    """Writes the email's own HTML, with its embedded images, to a private
    file for the browser. A content security policy blocks every script."""
    _, parsed = find_message(index, message_id)
    rich = parsed.get_body(preferencelist=("html",))
    if rich is not None:
        markup = part_text(rich)
        # Images sent inside the mail (cid:) become data URIs so they show.
        for part in parsed.walk():
            content_id = (part.get("Content-ID") or "").strip("<> ")
            if content_id and part.get_content_maintype() == "image":
                data = base64.b64encode(part.get_payload(decode=True) or b"").decode()
                markup = markup.replace(f"cid:{content_id}", f"data:{part.get_content_type()};base64,{data}")
        # The browser obeys <meta http-equiv="refresh"> (a redirect to the
        # sender's page) and decodes its value however it is written
        # ("&#114;efresh"); only the attribute's name can't be disguised.
        # So every http-equiv in the email is renamed and ignored. The page's
        # own charset and policy, added after, are untouched.
        markup = re.sub(r"http-equiv", "data-courier-http-equiv", markup, flags=re.I)
    else:
        body = parsed.get_body(preferencelist=("plain",))
        text = part_text(body) if body is not None else ""
        markup = f"<pre style='white-space:pre-wrap;font:15px sans-serif'>{html.escape(text)}</pre>"
    head = f'<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{ORIGINAL_POLICY}">'
    folder = courier_html.private_dir("originals")
    path = folder / (hashlib.sha1(message_id.encode()).hexdigest()[:16] + ".html")
    sync.write_private(path, head + markup)
    return {"path": str(path)}


def safe_filename(name: str) -> str:
    name = re.sub(r"[\x00-\x1f/\\]", "_", name).strip().lstrip(".") or "attachment"
    return name[:180]


def save_attachment(index: Index, message_id: str, number: int) -> dict:
    """Saves one attachment to Downloads, never overwriting a file there."""
    _, parsed = find_message(index, message_id)
    parts = attachment_parts(parsed)
    if not 0 <= number < len(parts):
        raise SystemExit("courier-mail: no such attachment")
    part = parts[number]
    folder = Path(os.environ.get("XDG_DOWNLOAD_DIR") or Path.home() / "Downloads")
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_filename(decode(part.get_filename()))
    stem, dot, extension = name.rpartition(".") if "." in name else (name, "", "")
    target, copy = folder / name, 1
    while target.exists():
        target = folder / (f"{stem} ({copy}).{extension}" if dot else f"{name} ({copy})")
        copy += 1
    target.write_bytes(part.get_payload(decode=True) or b"")
    return {"path": str(target), "name": target.name}


def header_or_empty(message, name: str) -> str:
    try:
        return decode(message.header(name))
    except LookupError:
        return ""


def my_name(index: Index, address: str) -> str:
    """The display name your own sent mail already uses for this address."""
    for message in index.newest_first(f"tag:sent and from:{quoted(address)}"):
        name, sender = address_of(header_or_empty(message, "from"))
        if sender == address and name:
            return name
    return ""


def compose_reply(index: Index, conversation_id: str, body: str):
    """A reply to the newest message in a person's conversation, threaded
    the way Gmail and every other client expect."""
    kind, _, address = conversation_id.partition(":")
    if kind != "p" or not address:
        raise SystemExit("courier-mail: replies go to people (p:<address>)")
    latest = next(iter(index.newest_first(conversation_query(conversation_id))), None)
    account_id = account_of(set(latest.tags)) if latest is not None else ""
    account = next((a for a in index.accounts if a["id"] == account_id), index.accounts[0] if index.accounts else None)
    if account is None:
        raise SystemExit("courier-mail: no account to send from. Run: courier-auth add <name>")

    message = email.message.EmailMessage()
    message["From"] = email.utils.formataddr((my_name(index, account["email"]), account["email"]))
    their_name = ""
    if latest is not None:
        their_name, sender = address_of(header_or_empty(latest, "from"))
        if sender != address:
            their_name = ""
    message["To"] = email.utils.formataddr((their_name, address))
    subject = re.sub(r"^((re|fwd?|aw)\s*:\s*)+", "", header_or_empty(latest, "subject") if latest is not None else "", flags=re.I).strip()
    message["Subject"] = f"Re: {subject}" if subject else "Hello"
    if latest is not None:
        parent = f"<{latest.messageid}>"
        message["In-Reply-To"] = parent
        message["References"] = f"{header_or_empty(latest, 'references')} {parent}".strip()
    message["Date"] = email.utils.formatdate(localtime=True)
    message["Message-ID"] = email.utils.make_msgid(domain=account["email"].rpartition("@")[2])
    message.set_content(body.rstrip() + "\n")
    return account["id"], message


def send(conversation_id: str, body: str, dry_run: bool) -> dict:
    if not body.strip():
        raise SystemExit("courier-mail: nothing to send")
    index = Index()
    try:
        account_id, message = compose_reply(index, conversation_id, body)
    finally:
        index.close()
    data = message.as_bytes(policy=email.policy.SMTP)
    if dry_run:
        return {"account": account_id, "message": data.decode("utf-8", "replace")}
    result = subprocess.run(
        ["msmtp", "-C", str(sync.config_dir() / "msmtprc"), "-a", account_id, "-t"], input=data, capture_output=True
    )
    if result.returncode != 0:
        raise SystemExit(f"courier-mail: sending failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    # Gmail files the sent copy; sync now so it shows up without waiting for the timer.
    subprocess.run(["systemctl", "--user", "start", "--no-block", "courier-sync.service"], capture_output=True)
    return {"sent": message["Message-ID"], "account": account_id}


# What `mark` can change. Each maps onto a maildir flag, so mbsync passes it to
# Gmail: unread is the missing Seen flag, starred is Flagged.
MARKS = {"read": ("unread", False), "unread": ("unread", True), "star": ("flagged", True), "unstar": ("flagged", False)}


def mark(action: str, message_ids: list[str]) -> int:
    tag, add = MARKS[action]
    for _ in range(40):
        try:
            index = Index(writable=True)
        except Exception as error:  # The sync holds the write lock; wait for it.
            if "lock" not in str(error).lower():
                raise
            time.sleep(0.25)
            continue
        try:
            changed = 0
            with index.db.atomic():
                for message_id in message_ids:
                    message = index.db.find(message_id)
                    if (tag in message.tags) != add:
                        message.tags.add(tag) if add else message.tags.discard(tag)
                        message.tags.to_maildir_flags()
                        changed += 1
            return changed
        finally:
            index.close()
    raise SystemExit("courier-mail: the mail index stayed locked; try again in a moment")


def mark_read(conversation_id: str, account: str = "") -> int:
    """Marks read exactly what opening the conversation shows (its newest
    THREAD_LIMIT messages, of one account when one is shown), never the whole
    lane behind it."""
    query = conversation_query(conversation_id)
    for _ in range(40):
        try:
            index = Index(writable=True)
        except Exception as error:  # The sync holds the write lock; wait for it.
            if "lock" not in str(error).lower():
                raise
            time.sleep(0.25)
            continue
        index.scope = views.account_query(account)
        try:
            changed = 0
            shown = [m.messageid for m in itertools.islice(index.newest_first(query), THREAD_LIMIT)]
            with index.db.atomic():
                for message_id in shown:
                    message = index.db.find(message_id)
                    if "unread" in message.tags:
                        message.tags.discard("unread")
                        message.tags.to_maildir_flags()
                        changed += 1
            return changed
        finally:
            index.close()
    raise SystemExit("courier-mail: the mail index stayed locked; try again in a moment")


class MailError(Exception):
    """A problem to show in the app, printed as {"error": ...}."""


class EmptyMessage(MailError):
    """An email with no text of yours, refused unless asked for (--empty-ok),
    so the app can ask first. Printed as {"error": ..., "empty": true}."""


def writable_index() -> Index:
    """The index for writing, waiting while a sync holds its lock."""
    for _ in range(40):
        try:
            return Index(writable=True)
        except Exception as error:
            if "lock" not in str(error).lower():
                raise
            time.sleep(0.25)
    raise MailError("The mail index stayed locked; try again in a moment.")


def start_sync() -> None:
    subprocess.run(["systemctl", "--user", "start", "--no-block", "courier-sync.service"], capture_output=True)


# What each Gmail action does to the local copy straight away, so the app
# shows it before the next sync confirms it: (tags to add, tags to remove).
RETAG = {
    "archive": ((), ("inbox",)),
    "inbox": (("inbox",), ()),
    "trash": (("trash",), ()),
    "untrash": (("inbox",), ("trash",)),
    "spam": (("spam",), ()),
    "unspam": (("inbox",), ("spam",)),
    "move": ((), ("inbox",)),
}


def retag(message_ids: list[str], added, removed) -> None:
    """Shows a Gmail change in the local index at once. A sync that holds the
    index gets it queued instead (courier_sync applies the queue), so an
    action never waits for a sync to finish."""
    try:
        index = Index(writable=True)
    except Exception as error:
        if "lock" not in str(error).lower():
            raise
        sync.queue_retag(message_ids, list(added), list(removed))
        return
    try:
        with index.db.atomic():
            for message_id in message_ids:
                try:
                    message = index.db.find(message_id)
                except LookupError:
                    continue
                for tag in added:
                    message.tags.add(tag)
                for tag in removed:
                    message.tags.discard(tag)
    finally:
        index.close()


def conversation_ids(conversation_id: str, account: str = "") -> list[str]:
    """Every inbox email of a conversation (of one account, when one is
    shown), for archiving it whole."""
    index = Index()
    index.scope = views.account_query(account)
    try:
        query = f"({conversation_query(conversation_id)}) and tag:inbox"
        return [message.messageid for message in index.newest_first(query)]
    finally:
        index.close()


def act(action: str, message_ids: list[str], label: str = "") -> dict:
    """Archive, delete, mark as spam or move to a label in Gmail itself, or
    undo that."""
    if action not in gmail.ACTIONS:
        raise MailError(f"Unknown action {action!r}.")
    index = Index()
    # Rows for the saved Trash, from this PC's copy before it goes.
    trashed = []
    try:
        accounts = index.accounts
        if not accounts:
            raise MailError("No account. Run: courier-auth add <name>")
        by_account: dict[str, list[str]] = collections.defaultdict(list)
        for message_id in message_ids:
            try:
                message = index.db.find(message_id)
                tags = set(message.tags)
                owner = account_of(tags) or accounts[0]["id"]
                by_account[owner].append(message_id)
                if action == "trash":
                    name, sender = email.utils.parseaddr(header_or_empty(message, "from"))
                    trashed.append({"id": message_id, "title": name or sender, "subtitle": header_or_empty(message, "subject") or "(no subject)",
                                    "time": views.row_time(int(message.date)), "epoch": int(message.date), "account": owner})
            except LookupError:
                # Already gone from this PC (deleted, then synced): ask every account.
                for account in accounts:
                    by_account[account["id"]].append(message_id)
    finally:
        index.close()
    done = 0
    try:
        for account in accounts:
            if by_account.get(account["id"]):
                done += gmail.apply(account, action, by_account[account["id"]], label=label)
    except (gmail.GmailError, sync.SignedOut, sync.SyncError) as error:
        message = f"Sign in again: courier-auth add {error.args[0]}" if isinstance(error, sync.SignedOut) else str(error)
        raise MailError(message) from None

    added, removed = RETAG[action]
    retag(message_ids, added, removed)
    if action == "trash":
        remember_trash(added=trashed)
    elif action == "untrash":
        remember_trash(removed=message_ids)
    start_sync()
    return {"done": done, "action": action, "ids": message_ids}


# Writing ------------------------------------------------------------------------


def addresses(values: list[str]) -> list[tuple[str, str]]:
    found = []
    for name, address in email.utils.getaddresses([v for v in values if v and v.strip()]):
        address = address.strip()
        if not address:
            continue
        if "@" not in address or " " in address:
            raise MailError(f"“{address}” isn't an email address.")
        found.append((name.strip().strip('"'), address))
    return found


def formatted(people: list[tuple[str, str]]) -> str:
    return ", ".join(email.utils.formataddr(person) for person in people)


def plain_subject(subject: str) -> str:
    return re.sub(r"^((re|fwd?|aw|fw)\s*:\s*)+", "", subject, flags=re.I).strip()


def account_for(index: Index, account_id: str, message=None) -> dict:
    if not index.accounts:
        raise MailError("No account to send from. Run: courier-auth add <name>")
    wanted = account_id or (account_of(set(message.tags)) if message is not None else "")
    return next((a for a in index.accounts if a["id"] == wanted), index.accounts[0])


def original_text(parsed) -> str:
    plain = parsed.get_body(preferencelist=("plain",))
    rich = parsed.get_body(preferencelist=("html",))
    if plain is not None and part_text(plain).strip():
        return tidy_whitespace(part_text(plain))
    if rich is not None:
        return tidy_whitespace(html_to_text(part_text(rich), keep_quotes=True))
    return ""


def draft(index: Index, mode: str, message_id: str) -> dict:
    """Who a reply, reply-all or forward goes to, and its subject."""
    message, parsed = find_message(index, message_id)
    account = account_for(index, "", message)
    subject = plain_subject(header_or_empty(message, "subject"))
    from_person = address_of(header_or_empty(message, "from"))
    to = addresses([header_or_empty(message, "to")])
    cc = addresses([header_or_empty(message, "cc")])
    mine = lambda person: views.plain_address(person[1]) in index.me  # noqa: E731
    if mode == "forward":
        return {"mode": mode, "id": message_id, "account": account["id"], "to": [], "cc": [], "subject": f"Fwd: {subject}" if subject else "Fwd:",
                "attachments": [decode(part.get_filename()) for part in attachment_parts(parsed)]}
    if mine(from_person):
        # Replying to your own email goes to the people it went to (or back
        # to you, for a note to yourself).
        primary = [p for p in to if not mine(p)] or to or [from_person]
    else:
        reply_to = addresses([header_or_empty(message, "reply-to")])
        primary = reply_to or [from_person]
    recipients, copies = list(primary), []
    if mode == "replyall":
        taken = {p[1].lower() for p in recipients}
        for person in to:
            if not mine(person) and person[1].lower() not in taken:
                recipients.append(person)
                taken.add(person[1].lower())
        for person in cc:
            if not mine(person) and person[1].lower() not in taken:
                copies.append(person)
                taken.add(person[1].lower())
    return {"mode": mode, "id": message_id, "account": account["id"], "to": [email.utils.formataddr(p) for p in recipients],
            "cc": [email.utils.formataddr(p) for p in copies], "subject": f"Re: {subject}" if subject else "Re:", "attachments": []}


def compose(index: Index, *, account_id: str, to: list[str], cc: list[str], bcc: list[str], subject: str, body: str,
            reply_to: str = "", forward: str = "", attach: list[str] = (), empty_ok: bool = False) -> tuple[str, email.message.EmailMessage]:
    """A new email, a reply (threaded under `reply_to`, quoting it) or a
    forward (the original's text and attachments under yours). An email
    with no text of yours is refused (EmptyMessage) unless `empty_ok`; a
    forward is never empty, it carries the forwarded email."""
    if not body.strip() and not forward and not empty_ok:
        raise EmptyMessage("This email has no text.")
    original = parsed = None
    if reply_to or forward:
        original, parsed = find_message(index, reply_to or forward)
    account = account_for(index, account_id, original)
    recipients, copies, blind = addresses(to), addresses(cc), addresses(bcc)
    if not (recipients or copies or blind):
        raise MailError("Add someone to send it to.")

    message = email.message.EmailMessage()
    message["From"] = email.utils.formataddr((my_name(index, account["email"]), account["email"]))
    if recipients:
        message["To"] = formatted(recipients)
    if copies:
        message["Cc"] = formatted(copies)
    if blind:
        message["Bcc"] = formatted(blind)  # msmtp sends to them and removes this header.
    message["Subject"] = subject.strip()
    message["Date"] = email.utils.formatdate(localtime=True)
    message["Message-ID"] = email.utils.make_msgid(domain=account["email"].rpartition("@")[2])

    text = body.rstrip() + "\n"
    if original is not None:
        name, sender = address_of(header_or_empty(original, "from"))
        when = datetime.fromtimestamp(int(original.date))
        stamp = f"{when.strftime('%a')}, {when.day} {when.strftime('%b %Y')} at {clock(when)}"
        if reply_to:
            parent = f"<{original.messageid}>"
            message["In-Reply-To"] = parent
            message["References"] = f"{header_or_empty(original, 'references')} {parent}".strip()
            quoted_lines = "\n".join(f"> {line}" if line else ">" for line in original_text(parsed).splitlines())
            text += f"\nOn {stamp}, {email.utils.formataddr((name, sender))} wrote:\n{quoted_lines}\n"
        else:
            text += (
                "\n---------- Forwarded message ---------\n"
                f"From: {email.utils.formataddr((name, sender))}\n"
                f"Date: {stamp}\n"
                f"Subject: {header_or_empty(original, 'subject')}\n"
                f"To: {header_or_empty(original, 'to')}\n"
                + (f"Cc: {header_or_empty(original, 'cc')}\n" if header_or_empty(original, "cc") else "")
                + f"\n{original_text(parsed)}\n"
            )
    message.set_content(text)

    if forward and parsed is not None:
        for part in attachment_parts(parsed):
            data = part.get_payload(decode=True) or b""
            maintype, _, subtype = part.get_content_type().partition("/")
            message.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=decode(part.get_filename()))
    for path in attach:
        file = Path(path).expanduser()
        try:
            data = file.read_bytes()
        except OSError as error:
            raise MailError(f"Couldn't attach {file.name}: {error.strerror}.") from None
        kind, _ = mimetypes.guess_type(file.name)
        maintype, _, subtype = (kind or "application/octet-stream").partition("/")
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=file.name)
    return account["id"], message


def deliver(account_id: str, message: email.message.EmailMessage, dry_run: bool) -> dict:
    data = message.as_bytes(policy=email.policy.SMTP)
    if dry_run:
        return {"account": account_id, "message": data.decode("utf-8", "replace")}
    result = subprocess.run(["msmtp", "-C", str(sync.config_dir() / "msmtprc"), "-a", account_id, "-t"], input=data, capture_output=True)
    if result.returncode != 0:
        raise MailError(f"Sending failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    # Gmail files the sent copy; sync now so it shows up without waiting for the timer.
    start_sync()
    return {"sent": message["Message-ID"], "account": account_id}


def contacts(index: Index) -> list[dict]:
    """People you write to most, then people who write to you, for address
    suggestions. Robots (no-reply, notifications…) never appear."""
    score: collections.Counter = collections.Counter()
    names: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    def count(person: tuple[str, str], weight: int) -> None:
        name, address = person[0].strip().strip('"'), person[1].strip().lower()
        if not address or "@" not in address or address in index.me or sync.ROBOT_SENDER.search(address.partition("@")[0]):
            return
        score[address] += weight
        if name and "@" not in name:
            names[address][name] += 1

    for message in itertools.islice(index.newest_first("tag:sent"), 2000):
        for header in ("to", "cc"):
            for person in email.utils.getaddresses([header_or_empty(message, header)]):
                count(person, 3)
    for message in itertools.islice(index.newest_first("tag:people"), 2000):
        count(address_of(header_or_empty(message, "from")), 1)
    return [
        {"name": names[address].most_common(1)[0][0] if names[address] else "", "address": address}
        for address, _ in score.most_common(500)
    ]


# The rest of the mail window ------------------------------------------------------


def first_account() -> dict:
    accounts = sync.load_accounts()
    if not accounts:
        raise MailError("No account. Run: courier-auth add <name>")
    return accounts[0]


def storage() -> dict:
    """Each account's Gmail storage use (shared with Drive and Photos),
    checked at most every half hour."""
    cached = later.load("storage.json", {})
    # Fresh for half an hour, unless an account was added or removed since.
    same_accounts = {a.get("account") for a in cached.get("accounts", [])} == {a["id"] for a in sync.load_accounts()}
    if time.time() - cached.get("checked", 0) < 30 * 60 and "accounts" in cached and same_accounts:
        return cached
    found = []
    for account in sync.load_accounts():
        imap = gmail.connect(account)
        try:
            _, data = imap.getquotaroot("INBOX")
        finally:
            imap.logout()
        text = b" ".join(line if isinstance(line, bytes) else b" ".join(line) for group in data for line in group).decode()
        quota = re.search(r"STORAGE (\d+) (\d+)", text)
        if quota:
            found.append({"account": account["id"], "email": account["email"], "used": int(quota.group(1)) * 1024, "limit": int(quota.group(2)) * 1024})
    result = {"accounts": found, "checked": time.time()}
    later.save("storage.json", result)
    return result


def account_named(account_id: str) -> dict:
    accounts = sync.load_accounts()
    if not accounts:
        raise MailError("No account. Run: courier-auth add <name>")
    return next((a for a in accounts if a["id"] == account_id), accounts[0])


def gmail_labels(account_id: str = "") -> list[str]:
    """One account's own Gmail labels, asked for at most hourly."""
    account = account_named(account_id)
    cached = later.load("labels.json", {})
    entry = cached.get(account["email"], {}) if isinstance(cached.get(account["email"]), dict) else {}
    if time.time() - entry.get("checked", 0) < 60 * 60:
        return entry["labels"]
    found = gmail.labels(account)
    cached = {key: value for key, value in cached.items() if isinstance(value, dict)}
    cached[account["email"]] = {"labels": found, "checked": time.time()}
    later.save("labels.json", cached)
    return found


def trash_list(account_id: str = "", limit: int = 60) -> list[dict]:
    """The newest emails in Gmail's Trash (it isn't synced to this PC), for
    one account or all of them, read from each account at once. Gmail's
    sign-in alone takes over a second, so the result is also kept for the next
    look (`trash --cached`)."""
    import concurrent.futures

    accounts = [a for a in sync.load_accounts() if not account_id or a["id"] == account_id]
    found = []
    with concurrent.futures.ThreadPoolExecutor(max(1, len(accounts))) as pool:
        for rows in pool.map(lambda account: trash_rows(account, limit), accounts):
            found += rows
    found = sorted(found, key=lambda item: -item["epoch"])[:limit]
    if not account_id:
        sync.write_private(trash_cache_path(), json.dumps({"checked": int(time.time()), "rows": found}))
    return found


def trash_cache_path() -> Path:
    return sync.state_dir() / "trash.json"


def cached_trash() -> dict:
    """Trash as it was last seen, for showing at once while Gmail is asked
    again; times are recomputed for now."""
    try:
        saved = json.loads(trash_cache_path().read_text())
    except (OSError, ValueError):
        return {"rows": [], "cached": False}
    rows = [row | {"time": views.row_time(row["epoch"])} for row in saved.get("rows", [])]
    return {"rows": rows, "cached": True, "checked": saved.get("checked", 0)}


def remember_trash(added: list[dict] = (), removed: list[str] = ()) -> None:
    """Keeps the saved Trash in step with deletes and restores made here, so
    it's right the moment Trash opens."""
    saved = cached_trash()
    if not saved["cached"]:
        return
    rows = [row for row in saved["rows"] if row["id"] not in set(removed) and row["id"] not in {a["id"] for a in added}]
    rows = sorted(rows + list(added), key=lambda item: -item["epoch"])[:60]
    sync.write_private(trash_cache_path(), json.dumps({"checked": saved["checked"], "rows": rows}))


def trash_rows(account: dict, limit: int) -> list[dict]:
    imap = gmail.connect(account)
    try:
        folders = gmail.folders_for(imap, account)
        # SELECT already says how many emails there are, so the newest are
        # fetched by position without a SEARCH round trip (~0.3 s each).
        _, data = imap.select(gmail.quote(folders.get("\\Trash", "[Gmail]/Trash")), readonly=True)
        count = int(data[0] or 0)
        if not count:
            return []
        _, rows = imap.fetch(f"{max(1, count - limit + 1)}:{count}", "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
    finally:
        imap.logout()
    found = []
    for row in rows:
        if not isinstance(row, tuple):
            continue
        meta, raw = row
        headers = email.message_from_bytes(raw, policy=email.policy.default)
        stamp = re.search(rb'INTERNALDATE "([^"]+)"', meta)
        epoch = int(email.utils.mktime_tz(email.utils.parsedate_tz(stamp.group(1).decode().replace("-", " ")))) if stamp else 0
        name, sender = email.utils.parseaddr(str(headers.get("From", "")))
        found.append({
            "id": str(headers.get("Message-ID", "")).strip().strip("<>"),
            "title": name or sender,
            "subtitle": str(headers.get("Subject", "")) or "(no subject)",
            "time": views.row_time(epoch),
            "epoch": epoch,
            "account": account["id"],
        })
    return found


def trash_message(message_id: str, account_id: str = "") -> dict:
    """One email from Gmail's Trash, for the reader. It's read from Gmail,
    since deleted mail leaves this PC on the next sync."""
    for account in sync.load_accounts():
        if account_id and account["id"] != account_id:
            continue
        imap = gmail.connect(account)
        try:
            folders = gmail.folders_for(imap, account)
            imap.select(gmail.quote(folders.get("\\Trash", "[Gmail]/Trash")), readonly=True)
            uids = gmail.find_uids(imap, [message_id])
            if not uids:
                continue
            _, data = imap.uid("FETCH", uids[0], "(INTERNALDATE BODY.PEEK[])")
        finally:
            imap.logout()
        raw = next((part[1] for part in data if isinstance(part, tuple)), b"")
        stamp = re.search(rb'INTERNALDATE "([^"]+)"', next((part[0] for part in data if isinstance(part, tuple)), b""))
        parsed = email.message_from_bytes(raw, policy=email.policy.default)
        epoch = int(email.utils.mktime_tz(email.utils.parsedate_tz(stamp.group(1).decode().replace("-", " ")))) if stamp else int(time.time())
        return reader_view(parsed, message_id, epoch, {a["email"].lower() for a in sync.load_accounts()}) | {
            "inTrash": True,
            "account": account["id"],
            "inbox": False,
            "unread": False,
            "starred": False,
            "details": {"thread": [], "relatedFiles": [], "fromSender": [], "meeting": None, "snoozedUntil": 0, "remindAt": 0,
                        "retention": None, "ruleRetention": None, "toMe": True, "category": "trash"},
        }
    raise MailError("That email isn't in Trash anymore.")


def reader_view(parsed, message_id: str, epoch: int, me: set[str]) -> dict:
    """The reader's fields straight from a parsed email."""
    plain = parsed.get_body(preferencelist=("plain",))
    rich = parsed.get_body(preferencelist=("html",))
    if plain is not None and part_text(plain).strip():
        full = tidy_whitespace(part_text(plain))
    elif rich is not None:
        full = tidy_whitespace(html_to_text(part_text(rich), keep_quotes=True))
    else:
        full = ""
    new = tidy(full, limit=None)
    name, sender = address_of(str(parsed.get("From", "")))
    moment = datetime.fromtimestamp(epoch)
    rendered, markdown = rendered_view(parsed, plain, rich)
    return {
        "id": message_id,
        "subject": str(parsed.get("Subject", "")) or "(no subject)",
        "fromName": name or nice_name(sender),
        "fromAddress": sender,
        "mine": sender in me,
        "to": str(parsed.get("To", "")),
        "cc": str(parsed.get("Cc", "")),
        "date": f"{moment.strftime('%A')}, {moment.day} {moment.strftime('%B %Y')}, {clock(moment)}",
        "body": new or full,
        "full": full if full != new else "",
        "hasOriginal": False,
        "html": rendered["html"] if rendered else "",
        "htmlBackground": rendered["background"] if rendered else "",
        "view": "designed" if rendered and (rendered["layout"] or markdown) else "text",
        "epoch": epoch,
        "avatar": sender_picture(sender),
        "attachments": [
            {"index": number, "name": decode(part.get_filename()), "size": human_size(len(part.get_payload(decode=True) or b"")), "type": part.get_content_type()}
            for number, part in enumerate(attachment_parts(parsed))
        ],
    }


def add_account(name: str) -> dict:
    """Signs a Google account in (the browser opens), then sets sync and push
    up for it and starts its first sync."""
    import ctypes
    import signal

    def die_with_parent() -> None:
        # If this process goes (Cancel, or Courier closing), the sign-in goes
        # too, instead of waiting on in the background. PR_SET_PDEATHSIG = 1.
        ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)

    auth = subprocess.Popen([str(Path.home() / ".local/bin/courier-auth"), "add", name],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=die_with_parent)

    def cancel(signum, frame) -> None:
        auth.terminate()
        raise MailError("Sign-in cancelled.")

    signal.signal(signal.SIGTERM, cancel)
    out, err = auth.communicate()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    if auth.returncode != 0:
        raise MailError((err or out).strip().splitlines()[-1] if (err or out).strip() else "Sign-in didn't finish.")
    account = next((a for a in sync.load_accounts() if a["id"] == name), None)
    if account is None:
        raise MailError("Sign-in finished but the account wasn't saved.")
    subprocess.run([str(Path.home() / ".local/bin/courier-sync"), "--configure"], capture_output=True)
    subprocess.run(["systemctl", "--user", "restart", "courier-push.service"], capture_output=True)
    start_sync()
    return {"id": account["id"], "email": account["email"]}


def account_picture_path(account_id: str) -> Path:
    """The picture you chose for an account. Its own (Google photo or
    Gravatar) is courier_avatars.default_picture_path, beside it."""
    import courier_avatars

    return courier_avatars.accounts_dir() / f"{account_id}.png"


def account_info(account: dict, defaults: dict | None = None) -> dict:
    """An account for the app. `picture` is the one it shows: yours if you
    chose one, else the account's own, else "" (its initial).
    `pictureSource` says which ("custom", "google", "gravatar" or ""), and
    `defaultSource` what going back to the default would show."""
    import courier_avatars

    custom = account_picture_path(account["id"])
    default = courier_avatars.default_picture_path(account["id"])
    own = courier_avatars.default_source(account["id"], defaults)
    picture = custom if custom.exists() else default if own else None
    return {
        "id": account["id"],
        "email": account["email"],
        "label": account["id"].capitalize(),
        "picture": str(picture) if picture else "",
        "pictureSource": "custom" if custom.exists() else own,
        "defaultSource": own,
    }


def list_accounts(fetch: bool = False) -> list[dict]:
    """Every account; with fetch, first looks up any account's own picture
    not looked up yet (the network only for those)."""
    import courier_avatars

    if fetch:
        try:
            courier_avatars.fetch_account_pictures()
        except Exception as error:  # The list still comes back, with what's cached.
            print(f"courier-mail: account pictures: {error!r}", file=sys.stderr)
    defaults = courier_avatars.load_account_index()
    return [account_info(account, defaults) for account in sync.load_accounts()]


def parse_crop(text: str) -> tuple[int, int, int] | None:
    """--crop X,Y,SIZE: the square to keep, in the image's own pixels."""
    if not text:
        return None
    try:
        x, y, size = (int(round(float(part))) for part in text.split(","))
    except ValueError:
        raise MailError("--crop is X,Y,SIZE in pixels.") from None
    if size < 1 or x < 0 or y < 0:
        raise MailError("--crop is X,Y,SIZE in pixels.")
    return x, y, size


# Your own picture may be a big photo, but it's decoded at most this big. A
# JPEG decodes at 1/2 to 1/8 scale when the square you framed still fills
# the 160 px circle, so even a 200-megapixel photo decodes small. A file
# claiming more than PICTURE_FILE_PIXELS isn't opened at all.
PICTURE_PIXELS = 64_000_000
PICTURE_FILE_PIXELS = 16384 * 16384
PICTURE_TOO_BIG = "That picture is too big for Junco."


def set_account_picture(account_id: str, source: str, crop: tuple[int, int, int] | None = None) -> dict:
    """Sets the picture you chose for an account from any image: the `crop`
    square (in the upright image's pixels; a centred square without one),
    drawn as a 160 px circle (QML here can't clip images round). An empty
    source removes it, so the account shows its own picture again. The
    account's own picture is never touched."""
    accounts = {a["id"]: a for a in sync.load_accounts()}
    if account_id not in accounts:
        raise MailError(f"No account called {account_id}.")
    path = account_picture_path(account_id)
    if not source:
        path.unlink(missing_ok=True)
        return account_info(accounts[account_id])
    from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

    try:
        # Only the picture types the chooser offers; anything else Pillow
        # reads (an icon, PostScript it would hand to Ghostscript) isn't tried.
        with courier_html.pixel_limit(PICTURE_FILE_PIXELS), \
                Image.open(source, formats=courier_html.PICTURE_FORMATS) as image:
            full_width = image.width
            square = max(1, min(crop[2] if crop else min(image.size), *image.size))
            image.draft(None, (image.width * 160 // square + 1, image.height * 160 // square + 1))
            if image.width * image.height > PICTURE_PIXELS:
                raise MailError(PICTURE_TOO_BIG)
            scale = image.width / full_width
            upright = ImageOps.exif_transpose(image).convert("RGBA")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise MailError(PICTURE_TOO_BIG) from None
    except (OSError, UnidentifiedImageError):
        raise MailError("That file isn't a picture Junco can read.") from None
    if crop:
        # In the decoded picture's pixels (a JPEG may have decoded smaller).
        x, y, size = (round(value * scale) for value in crop)
        # Kept inside the image, as a square.
        size = min(size, upright.width, upright.height)
        x, y = min(x, upright.width - size), min(y, upright.height - size)
        upright = upright.crop((x, y, x + size, y + size))
    square = ImageOps.fit(upright, (160, 160), Image.LANCZOS)
    mask = Image.new("L", (640, 640), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 639, 639), fill=255)
    square.putalpha(mask.resize((160, 160), Image.LANCZOS))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp.png")
    square.save(temporary)
    os.replace(temporary, path)
    return account_info(accounts[account_id])


def add_task(index: Index, message_id: str) -> dict:
    """The email as a to-do for today in the Calendar app."""
    message = index.db.find(message_id)
    path = Path(os.environ.get("COURIER_TASKS") or sync.xdg("XDG_DATA_HOME", ".local/share") / "courier" / "tasks.json")
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        data = {"tasks": []}
    title = header_or_empty(message, "subject") or "Reply to an email"
    task = {"id": f"{int(time.time() * 1000)}", "title": title, "day": date.today().isoformat(), "done": False, "mail": message_id}
    data.setdefault("tasks", []).append(task)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    os.replace(temporary, path)
    return task


# What a preview may open, told by the file's own first bytes, never by the
# name or Content-Type the sender chose: pictures, PDFs and plain text, each
# opened as a copy with its own safe extension. Anything else (programs,
# scripts, .desktop entries, web pages, archives, office files) can only be
# saved and opened by hand.
PREVIEW_MAGIC = [
    (b"%PDF-", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
]
PREVIEW_TEXT_LIMIT = 2 * 1024 * 1024


def preview_kind(data: bytes) -> str | None:
    """The safe extension to preview these bytes as, or None for none."""
    for magic, extension in PREVIEW_MAGIC:
        if data.startswith(magic):
            return extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    # Plain text opens as .txt, in a text viewer: shown, never run.
    if len(data) <= PREVIEW_TEXT_LIMIT and b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return ".txt"
    return None


def preview_name(name: str, extension: str) -> str:
    """A plain name for a preview copy: the sender's name without its own
    extension, with only letters, digits, spaces and - _ ( ) left (no
    direction-flipping or invisible characters, nothing like # ? % that
    would bend the file:// link), then the safe extension."""
    stem = name.rsplit(".", 1)[0] if "." in name.strip(".") else name
    stem = re.sub(r"[^\w \-()]+", "_", stem).strip(" _") or "attachment"
    return stem[:80] + extension


def preview(index: Index, message_id: str, number: int) -> dict:
    """An attachment as a private copy for the system viewer, only if its
    bytes are a picture, a PDF or plain text (preview_kind), named with the
    extension those bytes call for. Returns its path and its file:// url."""
    _, parsed = find_message(index, message_id)
    parts = attachment_parts(parsed)
    if not 0 <= number < len(parts):
        raise MailError("That attachment is gone.")
    part = parts[number]
    data = part.get_payload(decode=True) or b""
    kind = preview_kind(data)
    if kind is None:
        raise MailError("Junco only previews pictures, PDFs and text. Save it to open it yourself.")
    target = views.preview_path(preview_name(decode(part.get_filename()) or "attachment", kind))
    # A fresh file, never written through anything left at that name.
    target.unlink(missing_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    return {"path": str(target), "url": target.as_uri()}


def subject_of(message_id: str) -> str:
    index = Index()
    try:
        return header_or_empty(index.db.find(message_id), "subject")
    except LookupError:
        return ""
    finally:
        index.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="courier-mail", description="Junco's mail, as JSON.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("accounts").add_argument(
        "--fetch", action="store_true", help="first look up any account's own picture (Google photo, Gravatar) not looked up yet")
    # --account: only that account's mail; every account's when left out.
    commands.add_parser("conversations").add_argument("--account", default="")
    threader = commands.add_parser("thread")
    threader.add_argument("conversation")
    threader.add_argument("--account", default="")
    reader = commands.add_parser("read")
    reader.add_argument("conversation")
    reader.add_argument("--account", default="")
    picture = commands.add_parser("account-picture", help="choose an account's picture (--clear: back to its own)")
    picture.add_argument("id")
    picture.add_argument("path", nargs="?", default="")
    picture.add_argument("--crop", default="", help="X,Y,SIZE: the square of the image to use, in its pixels")
    picture.add_argument("--clear", action="store_true")
    messenger = commands.add_parser("message", help="one whole email for the reader")
    messenger.add_argument("id")
    messenger.add_argument("--theme", default="", help='the app\'s colours, JSON {"surface", "text", "muted", "link"}')
    chooser = commands.add_parser("reader-pref", help="how one sender's mail shows: colours and plain text")
    chooser.add_argument("sender")
    chooser.add_argument("--colours", default="", choices=["", *sorted(READER_CHOICES["colours"])])
    chooser.add_argument("--plain", default="", choices=["", *sorted(READER_CHOICES["plain"])])
    teacher = commands.add_parser("teach-start", help="Teach fields: this email's template, its fields and its other emails")
    teacher.add_argument("id")
    teacher.add_argument("--surface", choices=["text", "html"], default="text", help="the reader's view: plain text or designed")
    commands.add_parser("teach-select", help="a selection in the reader (JSON on stdin) as a field's example").add_argument("id")
    commands.add_parser("teach-preview", help="fields as taught so far (JSON on stdin), read from the template's emails").add_argument("id")
    commands.add_parser("teach-save", help="keep a template as taught (JSON on stdin) and read all its emails").add_argument("id")
    commands.add_parser("template-delete", help="forget a taught template and its fields").add_argument("template")
    commands.add_parser("template-table", help="one template's emails as rows, its fields as columns").add_argument("template")
    commands.add_parser("templates", help="the templates you taught").add_argument("--account", default="")
    marker = commands.add_parser("mark", help="mark emails read, unread, starred or unstarred")
    marker.add_argument("action", choices=sorted(MARKS))
    marker.add_argument("ids", nargs="+")
    commands.add_parser("original", help="the email's HTML in a private file, for the browser").add_argument("id")
    saver = commands.add_parser("attachment", help="save an attachment to Downloads")
    saver.add_argument("id")
    saver.add_argument("number", type=int)
    sender = commands.add_parser("send", help="reply to a person; the text comes from --body or stdin")
    sender.add_argument("conversation")
    sender.add_argument("--body")
    sender.add_argument("--dry-run", action="store_true", help="print the message instead of sending it")
    actor = commands.add_parser("act", help="archive, inbox, trash, untrash, spam or unspam emails in Gmail")
    actor.add_argument("action", choices=sorted(gmail.ACTIONS))
    actor.add_argument("ids", nargs="*")
    actor.add_argument("--conversation", help="every inbox email of this conversation (archive only)")
    actor.add_argument("--label", default="", help="the label to move them to (move)")
    actor.add_argument("--account", default="", help="with --conversation: only this account's emails")
    writer = commands.add_parser("compose", help="send a new email, reply or forward; the text comes from --body or stdin")
    writer.add_argument("--account", default="")
    for field in ("to", "cc", "bcc"):
        writer.add_argument(f"--{field}", action="append", default=[])
    writer.add_argument("--subject", default="")
    writer.add_argument("--body")
    writer.add_argument("--reply-to", default="", help="the Message-ID this replies to")
    writer.add_argument("--forward", default="", help="the Message-ID this forwards")
    writer.add_argument("--attach", action="append", default=[])
    writer.add_argument("--dry-run", action="store_true", help="print the message instead of sending it")
    writer.add_argument("--at", default="", help="send later, at this local time (2026-11-22T09:00)")
    writer.add_argument("--empty-ok", action="store_true", help="send even though it has no text (the app asks first)")
    drafter = commands.add_parser("draft", help="recipients and subject for a reply, reply-all or forward")
    drafter.add_argument("mode", choices=["reply", "replyall", "forward"])
    drafter.add_argument("id")
    commands.add_parser("contacts", help="addresses to suggest when writing")
    commands.add_parser("folders", help="the sidebar's folders and their counts").add_argument("--account", default="")
    lister = commands.add_parser("list", help="one folder's rows, by day")
    lister.add_argument("folder", choices=[f for f in views.FOLDERS if f not in {"scheduled", "trash"}])
    lister.add_argument("--search", default="")
    lister.add_argument("--account", default="", help="only this account's mail")
    commands.add_parser("storage", help="Gmail storage used")
    commands.add_parser("labels", help="your Gmail labels").add_argument("--account", default="")
    commands.add_parser("labels-of", help="one email's Gmail labels").add_argument("id")
    snoozer = commands.add_parser("snooze", help="archive now, back in the inbox later")
    snoozer.add_argument("ids", nargs="+")
    snoozer.add_argument("--until", required=True)
    commands.add_parser("unsnooze", help="back to the inbox now").add_argument("ids", nargs="+")
    reminder = commands.add_parser("remind", help="a desktop reminder about an email")
    reminder.add_argument("id")
    reminder.add_argument("--at", required=True)
    commands.add_parser("unremind").add_argument("id")
    commands.add_parser("scheduled", help="emails waiting to be sent")
    commands.add_parser("later", help="reminders, snoozed and scheduled emails, soonest first")
    commands.add_parser("unschedule", help="cancel a scheduled email").add_argument("file")
    commands.add_parser("send-now", help="send a scheduled email now").add_argument("file")
    keeper = commands.add_parser("retention", help="delete an email after a while; an empty period keeps it")
    keeper.add_argument("id")
    keeper.add_argument("period", choices=["", *later.PERIODS])
    commands.add_parser("rules", help="automation rules with what each would touch now")
    commands.add_parser("rule-save", help="add or change a rule (JSON)").add_argument("json")
    commands.add_parser("rule-delete").add_argument("id")
    commands.add_parser("tick", help="do what's due: snoozes, reminders, scheduled sends, retention, rules")
    trash = commands.add_parser("trash", help="the newest emails in Gmail's Trash")
    trash.add_argument("--account", default="")
    trash.add_argument("--cached", action="store_true", help="as last seen, without asking Gmail")
    opener = commands.add_parser("trash-open", help="one email from Gmail's Trash, for the reader")
    opener.add_argument("id")
    opener.add_argument("--account", default="")
    commands.add_parser("account-add", help="sign a Google account in and start syncing it").add_argument("name")
    commands.add_parser("task", help="add an email to today's to-dos").add_argument("id")
    previewer = commands.add_parser("preview", help="an attachment in a private file, for the viewer")
    previewer.add_argument("id")
    previewer.add_argument("number", type=int)
    args = parser.parse_args(argv)
    try:
        return run_command(args)
    except EmptyMessage as error:
        print(json.dumps({"error": str(error), "empty": True}))
        return 1
    except (MailError, later.LaterError, templates.TemplateError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except (gmail.GmailError, sync.SyncError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except sync.SignedOut as error:
        print(json.dumps({"error": f"Sign in again: courier-auth add {error.args[0]}"}))
        return 1


def teach_command(args) -> dict:
    """Teach fields: the panel's calls. What the panel sends (a selection, the
    fields taught so far) comes as JSON on stdin, never in the arguments.
    The index is only read."""
    payload = {}
    if args.command in {"teach-select", "teach-preview", "teach-save"}:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            raise MailError("The panel sent something Junco can't read.") from None
        if not isinstance(payload, dict):
            raise MailError("The panel sent something Junco can't read.")
    index = Index()
    try:
        if args.command == "teach-start":
            return templates.start(index.db, args.id, args.surface)
        if args.command == "teach-select":
            return templates.select(index.db, args.id, payload)
        if args.command == "teach-preview":
            return templates.preview(index.db, args.id, payload)
        if args.command == "teach-save":
            return templates.save(index.db, args.id, payload)
        return templates.table(index.db, args.template)
    finally:
        index.close()


def run_command(args) -> int:
    if args.command == "accounts":
        result = list_accounts(args.fetch)
    elif args.command == "account-picture":
        if not args.clear and not args.path:
            raise MailError("Give a picture, or --clear to go back to the account's own.")
        result = set_account_picture(args.id, "" if args.clear else args.path, None if args.clear else parse_crop(args.crop))
    elif args.command == "read":
        result = {"read": mark_read(args.conversation, args.account)}
    elif args.command == "mark":
        result = {"changed": mark(args.action, args.ids)}
    elif args.command in {"teach-start", "teach-select", "teach-preview", "teach-save", "template-table"}:
        result = teach_command(args)
    elif args.command == "template-delete":
        result = templates.delete_template(args.template)
    elif args.command == "templates":
        result = {"templates": templates.listing(args.account)}
    elif args.command in {"message", "original", "attachment"}:
        index = Index()
        try:
            if args.command == "message":
                result = open_message(index, args.id, theme_of(args.theme))
            elif args.command == "original":
                result = show_original(index, args.id)
            else:
                result = save_attachment(index, args.id, args.number)
        finally:
            index.close()
    elif args.command == "send":
        result = send(args.conversation, args.body if args.body is not None else sys.stdin.read(), args.dry_run)
    elif args.command == "act":
        if args.conversation:
            if args.action != "archive":
                raise MailError("Only archiving works on a whole conversation.")
            ids = conversation_ids(args.conversation, args.account)
        else:
            ids = args.ids
        result = act(args.action, ids, args.label) if ids else {"done": 0, "action": args.action, "ids": []}
    elif args.command in {"compose", "draft", "contacts"}:
        index = Index()
        try:
            if args.command == "draft":
                result = draft(index, args.mode, args.id)
            elif args.command == "contacts":
                result = contacts(index)
            else:
                to, cc, subject = args.to, args.cc, args.subject
                if args.reply_to and not (to or cc or args.bcc):
                    # A quick reply from the reader: to whoever Reply would pick.
                    prefill = draft(index, "reply", args.reply_to)
                    to, cc, subject = prefill["to"], prefill["cc"], subject or prefill["subject"]
                account_id, message = compose(
                    index, account_id=args.account, to=to, cc=cc, bcc=args.bcc, subject=subject,
                    body=args.body if args.body is not None else sys.stdin.read(),
                    reply_to=args.reply_to, forward=args.forward, attach=args.attach, empty_ok=args.empty_ok,
                )
        finally:
            index.close()
        if args.command == "compose":
            result = later.schedule(account_id, message, args.at) if args.at and not args.dry_run else deliver(account_id, message, args.dry_run)
    elif args.command in {"folders", "list", "task", "preview", "rules"}:
        index = Index()
        try:
            if args.command == "folders":
                result = views.folders(index, args.account)
            elif args.command == "list":
                try:
                    result = views.smart_list(index, args.folder, args.search, account=args.account)
                except index.notmuch.NotmuchError:
                    raise MailError("Couldn't search for that.") from None
            elif args.command == "task":
                result = add_task(index, args.id)
            elif args.command == "preview":
                result = preview(index, args.id, args.number)
            else:
                result = {"rules": [dict(rule, text=later.describe(rule), matches=later.rule_count(index, rule)) for rule in later.rules()]}
        finally:
            index.close()
    elif args.command == "storage":
        result = storage()
    elif args.command == "labels":
        result = {"labels": gmail_labels(args.account)}
    elif args.command == "labels-of":
        index = Index()
        try:
            owner = account_of(set(index.db.find(args.id).tags))
        except LookupError:
            owner = ""
        finally:
            index.close()
        result = {"labels": gmail.labels_of(account_named(owner), args.id)}
    elif args.command == "snooze":
        result = later.snooze(lambda action, ids, label="": act(action, ids, label), args.ids, args.until, subject_of(args.ids[0]))
    elif args.command == "unsnooze":
        result = later.unsnooze(lambda action, ids, label="": act(action, ids, label), args.ids)
    elif args.command == "remind":
        result = later.remind(args.id, args.at, subject_of(args.id))
    elif args.command == "unremind":
        result = later.unremind(args.id)
    elif args.command == "scheduled":
        result = {"items": later.scheduled()}
    elif args.command == "later":
        result = {
            "reminders": sorted(later.reminders(), key=lambda item: item["at"]),
            "snoozed": sorted(later.snoozed(), key=lambda item: item["until"]),
            "scheduled": later.scheduled(),
        }
    elif args.command == "unschedule":
        result = later.unschedule(args.file)
    elif args.command == "send-now":
        result = later.send_now(args.file)
        start_sync()
    elif args.command == "retention":
        result = later.set_retention(args.id, args.period, subject_of(args.id))
    elif args.command == "rule-save":
        result = later.save_rule(json.loads(args.json))
        index = Index()
        try:
            result = dict(result, text=later.describe(result), matches=later.rule_count(index, result))
        finally:
            index.close()
    elif args.command == "rule-delete":
        result = later.delete_rule(args.id)
    elif args.command == "tick":
        result = later.tick(lambda action, ids, label="": act(action, ids, label), Index)
    elif args.command == "trash":
        result = cached_trash() if args.cached else {"rows": trash_list(args.account)}
    elif args.command == "reader-pref":
        result = set_reader_pref(args.sender, args.colours, args.plain)
    elif args.command == "trash-open":
        result = trash_message(args.id, args.account)
    elif args.command == "account-add":
        result = add_account(args.name)
    else:
        index = Index()
        index.scope = views.account_query(args.account)
        try:
            # The startup caches hold every account's view only.
            if args.command == "conversations":
                result = conversations(index)
                if not args.account:
                    remember("conversations.json", result)
            else:
                result = thread(index, args.conversation)
                if not args.account:
                    remember(f"threads/{hashlib.md5(args.conversation.encode()).hexdigest()}.json", result)
        finally:
            index.close()
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
