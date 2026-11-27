#!/usr/bin/env python3
"""Mail sync for Courier.

Pulls each signed-in Google account over IMAP into a local Maildir (mbsync),
indexes it (notmuch) and sorts new mail into Courier's lanes. A systemd user
timer runs it; running it by hand is safe:

    courier-sync                 sync, index, sort
    courier-sync --configure     rewrite the generated configs and stop

Accounts come from courier-auth. Every connection signs in through
`courier-auth token <account>`, so nothing here writes a password or token.

While Courier is young it touches Gmail gently: new mail, Gmail-side
deletions and read/starred state come down; only read/starred state goes
up. Courier never deletes or moves anything in Gmail.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HEADER_PARSER = None


def _header_parser():
    global _HEADER_PARSER
    if _HEADER_PARSER is None:
        import email.parser
        import email.policy

        _HEADER_PARSER = email.parser.BytesHeaderParser(policy=email.policy.default)
    return _HEADER_PARSER

ENGINE = Path(__file__).resolve().parent
AUTH = ENGINE / "courier_auth.py"
IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
# Newest messages kept per Gmail folder. Older mail stays in Gmail; raise
# this (0 keeps everything) and run `mbsync --pull-old` to fetch it later.
HISTORY = 10000

# Machine mail Courier groups by sender instead of mixing with people.
UPDATE_DOMAINS = {"github.com", "linear.app"}
# Only mail this recent notifies; a first sync of old mail stays quiet.
NOTIFY_WITHIN = 2 * 60 * 60
LANES = ("people", "updates", "newsletters")
# Categories beside the lanes, for Courier's smart views. A message can have
# several: an IGNOU invite is both college and meeting.
CATEGORIES = ("meeting", "dev", "college")
# Developer tools whose mail is project activity, matched on the sender's
# domain and its subdomains (notify.cloudflare.com).
DEV_DOMAINS = {
    "github.com", "gitlab.com", "linear.app", "vercel.com", "netlify.com", "cloudflare.com", "huggingface.co",
    "notion.so", "stripe.com", "convex.dev", "clerk.dev", "clerk.com", "figma.com", "sentry.io", "supabase.com",
    "supabase.io", "railway.app", "render.com", "fly.io", "anthropic.com", "openai.com", "docker.com", "npmjs.com",
    "atlassian.net", "atlassian.com", "jetbrains.com", "postman.com", "digitalocean.com", "heroku.com", "aws.amazon.com",
}
# Colleges and universities: India's .ac.in and .edu.in, and .edu anywhere.
COLLEGE_SUFFIXES = (".ac.in", ".edu.in", ".edu", ".ac.uk", ".edu.au")
# Mailboxes nobody reads replies at, anywhere in the address
# ("azure-noreply@", "drive-shares-dm-noreply@").
ROBOT_SENDER = re.compile(r"no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|alerts?|mailer-daemon|postmaster|bounces?")
# Where Gmail's Unsubscribe button sends its request on your behalf.
UNSUBSCRIBE = re.compile(r"unsub|leave|remove|opt-?out|bounce", re.I)
# Role mailboxes speak for a company, not a person, unless you have written to them.
ROLE_WORDS = {
    "account", "accounts", "admin", "billing", "careers", "community", "confirm", "contact", "dailyjobs",
    "deals", "digest", "discuss", "events", "feedback", "hello", "help", "hi", "info", "invoice", "invoices",
    "jobmessenger", "jobs", "mail", "marketing", "membership", "msa", "news", "newsletter", "offers", "order",
    "orders", "practice", "product-updates", "promo", "receipts", "rewards", "sales", "security", "service",
    "shipment", "shipment-tracking", "store", "support", "survey", "team", "tracking", "update", "updates",
    "verify", "welcome", "teams", "mailer", "myaccount", "report", "reports",
}
# Subdomains sending services use ("notifications.microsoft.com", "e.amazon.in").
# Not "mail." or "email.": universities give students addresses there.
MACHINE_SUBDOMAINS = {
    "notifications", "notification", "notify", "alerts", "alert", "news", "newsletter", "newsletters", "updates",
    "update", "marketing", "mkt", "bounce", "bounces", "mailer", "comms", "communications", "info", "e", "em", "mg",
}
# Headers that bulk and transactional senders stamp and people's mail almost
# never carries (measured on the first sync: 1 of 68 messages from people
# you've written to, against hundreds of the rest).
MACHINE_HEADERS = (
    "feedback-id", "x-auto-response-suppress", "x-ses-outgoing", "x-mailgun-sid", "x-sg-eid", "x-mc-user",
    "x-notifications", "x-csa-complaints", "x-campaign",
)


class SyncError(RuntimeError):
    pass


class SignedOut(RuntimeError):
    pass


def xdg(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback)


def config_dir() -> Path:
    return xdg("XDG_CONFIG_HOME", ".config") / "courier"


def mail_dir() -> Path:
    return xdg("XDG_DATA_HOME", ".local/share") / "courier" / "mail"


def state_dir() -> Path:
    return xdg("XDG_STATE_HOME", ".local/state") / "courier"


def load_accounts() -> list[dict]:
    try:
        return json.loads((config_dir() / "accounts.json").read_text())["accounts"]
    except FileNotFoundError:
        return []


def web_link(url: str) -> str:
    """A link the app may hand to the system to open, or "": http(s) to a
    real host and nothing else. Invites and calendar events are written by
    other people, so a file:, smb: or javascript: link, or any app's own
    scheme, never reaches Qt.openUrlExternally (Join, Open event, Join the
    call, Open in Google Calendar)."""
    import urllib.parse

    url = (url or "").strip()
    if not url or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for a bad port
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"https", "http"} or not parts.hostname or parts.username is not None or parts.password is not None:
        return ""
    return url


def desktop_notify(summary: str, body: str, *options: str) -> None:
    """A desktop notification about mail or an event, whose text other
    people write (sender names, subjects, invite titles).

    "--" ends notify-send's options, so a subject like "-u critical" or
    "--icon=..." stays text. The notification server here (Caelestia) draws
    a summary with a tag in it as styled text, and a body with any of
    < * _ ` # [ ] as Markdown, both with images and links. So: newlines and
    other control characters become spaces (a Markdown reference definition
    needs a line of its own); no "<" or ">" goes in (they become the
    look-alikes ‹ ›, so no tag can form); and a Markdown link or image,
    inline "](" or by reference "][", is broken with an invisible space.
    The text reads the same and loads nothing."""
    def inert(text: str) -> str:
        text = re.sub(r"[\x00-\x1f\x7f\u2028\u2029]+", " ", text)
        return text.replace("<", "\u2039").replace(">", "\u203a").replace("](", "]\u200b(").replace("][", "]\u200b[")

    import subprocess

    subprocess.run(["notify-send", *options, "--", inert(summary), inert(body)], capture_output=True)


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
    os.replace(temporary, path)


# Signing in -------------------------------------------------------------------


def token_command(account: str) -> str:
    import shlex

    return f"{shlex.quote(str(AUTH))} token {shlex.quote(account)}"


def auth_token(account: str) -> str:
    import subprocess

    result = subprocess.run([str(AUTH), "token", account], capture_output=True, text=True)
    if result.returncode == 2:
        raise SignedOut(account)
    if result.returncode != 0:
        raise SyncError(result.stderr.strip() or f"courier-auth token {account} failed")
    return result.stdout.strip()


LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) (?P<name>.+)$')


def detect_all_mail(account: dict) -> str:
    """Asks Gmail which folder is All Mail. Its name follows the account's
    language ("[Gmail]/All Mail", "[Google Mail]/All Mail", ...)."""
    found = special_folders(account)
    if "\\All" not in found:
        raise SyncError(f"{account['email']} has no All Mail folder over IMAP. A Workspace admin may have turned IMAP off.")
    return found["\\All"]


def special_folders(account: dict) -> dict[str, str]:
    """Gmail's own folders by their special use ("\\All", "\\Drafts"), named
    in the account's language. Read-only: one LIST."""
    import imaplib

    token = auth_token(account["id"])
    sasl = f"user={account['email']}\x01auth=Bearer {token}\x01\x01".encode()
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)
        try:
            # A non-empty challenge is Gmail's error report; XOAUTH2 answers it empty.
            imap.authenticate("XOAUTH2", lambda challenge: b"" if challenge else sasl)
            _, lines = imap.list()
        finally:
            imap.logout()
    except (imaplib.IMAP4.error, OSError) as error:
        raise SyncError(f"Gmail IMAP refused {account['email']}: {error}") from None
    found = {}
    for line in lines:
        match = LIST_LINE.match(line or b"")
        if not match:
            continue
        name = match["name"].decode()
        if name.startswith('"'):
            name = re.sub(r"\\(.)", r"\1", name[1:-1])
        for use in ("\\All", "\\Drafts"):
            if use.encode() in match["flags"].split():
                found[use] = name
    return found


def first_download_size(account: dict, all_mail: str) -> int | None:
    """How many emails an account's first download brings (its Inbox and All
    Mail, each capped at HISTORY), asked of Gmail once, so the app can show
    progress. None once the account has finished a full download."""
    if (state_dir() / f"downloaded-{account['id']}").exists():
        return None
    import imaplib

    token = auth_token(account["id"])
    sasl = f"user={account['email']}\x01auth=Bearer {token}\x01\x01".encode()
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)
        try:
            imap.authenticate("XOAUTH2", lambda challenge: b"" if challenge else sasl)
            total = 0
            for folder in ("INBOX", all_mail):
                _, data = imap.select('"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"', readonly=True)
                total += min(int(data[0] or 0), HISTORY) if HISTORY else int(data[0] or 0)
            return total
        finally:
            imap.logout()
    except (imaplib.IMAP4.error, OSError, ValueError):
        return None


def journal_activity(account: str) -> float:
    """When mbsync last wrote its state for this account (its journal while a
    run works, the state when it finishes), across the account's folders."""
    latest = 0.0
    for folder in ("inbox", "all", "drafts"):
        for name in (".mbsyncstate", ".mbsyncstate.journal", ".mbsyncstate.new"):
            try:
                latest = max(latest, (mail_dir() / account / folder / name).stat().st_mtime)
            except OSError:
                pass
    return latest


def downloaded(account: str) -> int:
    """Emails on this PC for an account (both folders, as mbsync files them)."""
    count = 0
    for folder in ("inbox", "all"):
        for part in ("cur", "new"):
            try:
                count += sum(1 for _ in os.scandir(mail_dir() / account / folder / part))
            except FileNotFoundError:
                pass
    return count


def all_mail_folders(accounts: list[dict]) -> dict[str, str]:
    cache_path = state_dir() / "folders.json"
    try:
        cache = json.loads(cache_path.read_text())
    except FileNotFoundError:
        cache = {}
    changed = False
    for account in accounts:
        if account["id"] not in cache:
            cache[account["id"]] = detect_all_mail(account)
            changed = True
    if changed:
        write_private(cache_path, json.dumps(cache, indent=2) + "\n")
    return cache


def drafts_folders(accounts: list[dict]) -> dict[str, str]:
    """Each account's Gmail Drafts folder (its name follows the account's
    language), asked of Gmail once and kept. An account Gmail couldn't be
    asked about is left out this time, so its drafts channel waits a sync."""
    cache_path = state_dir() / "drafts-folders.json"
    try:
        cache = json.loads(cache_path.read_text())
    except (FileNotFoundError, ValueError):
        cache = {}
    changed = False
    for account in accounts:
        if account["id"] in cache:
            continue
        try:
            cache[account["id"]] = special_folders(account).get("\\Drafts", "")
            changed = True
        except (SyncError, SignedOut):
            continue
    if changed:
        write_private(cache_path, json.dumps(cache, indent=2) + "\n")
    return {name: folder for name, folder in cache.items() if folder}


# Generated configs -----------------------------------------------------------


# Pull new mail, upgrades and Gmail-side deletions; sync read/starred both
# ways; push nothing else. Expunge only the local copy.
CHANNEL_OPTIONS = f"""Create Near
Sync PullNew PullUpgrade PullGone Flags
Expunge Near
SyncState *
CopyArrivalDate yes
MaxMessages {HISTORY}
ExpireUnread yes"""

# Gmail's Drafts, pulled only (nothing is ever pushed back), so a message
# that is a draft has a copy in <account>/drafts while Gmail keeps it there,
# and that copy goes when the draft is sent or discarded. Gmail shows a draft
# in All Mail too, but with only its \Draft label, not the IMAP \Draft flag,
# so a copy there can't tell it is one.
DRAFTS_OPTIONS = """Create Near
Sync Pull
Expunge Near
SyncState *
CopyArrivalDate yes"""


def mbsync_config(accounts: list[dict], folders: dict[str, str], drafts: dict[str, str] | None = None) -> str:
    blocks = ["# Written by courier-sync from accounts.json. Edits are overwritten.\n"]
    for account in accounts:
        name, root = account["id"], mail_dir() / account["id"]
        all_mail = folders[name].replace("\\", "\\\\").replace('"', '\\"')
        blocks.append(
            f"""
IMAPAccount {name}
Host {IMAP_HOST}
Port 993
TLSType IMAPS
User {account['email']}
AuthMechs XOAUTH2
PassCmd "{token_command(name)}"
Timeout 120

IMAPStore {name}-remote
Account {name}

MaildirStore {name}-local
Path {root}/
Inbox {root}/inbox
SubFolders Verbatim

Channel {name}-inbox
Far :{name}-remote:INBOX
Near :{name}-local:INBOX
{CHANNEL_OPTIONS}

Channel {name}-all
Far :{name}-remote:"{all_mail}"
Near :{name}-local:all
{CHANNEL_OPTIONS}
"""
        )
        drafts_folder = (drafts or {}).get(name, "").replace("\\", "\\\\").replace('"', '\\"')
        if drafts_folder:
            blocks.append(
                f"""
Channel {name}-drafts
Far :{name}-remote:"{drafts_folder}"
Near :{name}-local:drafts
{DRAFTS_OPTIONS}
"""
            )
        blocks.append(f"\nGroup {name}\nChannel {name}-inbox\nChannel {name}-all\n" + (f"Channel {name}-drafts\n" if drafts_folder else ""))
    return "".join(blocks)


def msmtp_config(accounts: list[dict]) -> str:
    lines = [
        "# Written by courier-sync from accounts.json. Edits are overwritten.",
        "defaults",
        "tls on",
        f"logfile {state_dir() / 'msmtp.log'}",
    ]
    for account in accounts:
        lines += [
            "",
            f"account {account['id']}",
            f"host {SMTP_HOST}",
            "port 465",
            "tls_starttls off",
            f"from {account['email']}",
            f"user {account['email']}",
            "auth xoauth2",
            f'passwordeval "{token_command(account["id"])}"',
        ]
    return "\n".join(lines) + "\n"


def notmuch_config(accounts: list[dict]) -> str:
    emails = [account["email"] for account in accounts]
    return "\n".join(
        [
            "# Written by courier-sync from accounts.json. Edits are overwritten.",
            "[database]",
            f"path={mail_dir()}",
            "[user]",
            f"primary_email={emails[0] if emails else ''}",
            f"other_email={';'.join(emails[1:])}",
            "[new]",
            "tags=new;",
            "ignore=.mbsyncstate;.mbsyncstate.journal;.mbsyncstate.new;.mbsyncstate.lock;.uidvalidity",
            "[search]",
            "exclude_tags=deleted;spam;",
            "[maildir]",
            "synchronize_flags=true",
            "",
        ]
    )


def configure(accounts: list[dict], folders: dict[str, str], drafts: dict[str, str] | None = None) -> None:
    for account in accounts:
        (mail_dir() / account["id"]).mkdir(parents=True, exist_ok=True)
    write_private(config_dir() / "mbsyncrc", mbsync_config(accounts, folders, drafts))
    write_private(config_dir() / "msmtprc", msmtp_config(accounts))
    write_private(config_dir() / "notmuch-config", notmuch_config(accounts))
    os.environ["NOTMUCH_CONFIG"] = str(config_dir() / "notmuch-config")


# Lanes -----------------------------------------------------------------------


def lane(headers: dict[str, str], sender: str, me: set[str], correspondents: set[str]) -> str:
    """Which lane a message belongs in: "people", "updates" or "newsletters".

    People are conversations; machine mail gets its own lanes so it never
    buries a human. The strongest sign of a person is that you have written
    to them (`correspondents`); after that, bulk mail gives itself away in
    its headers. This is Courier's most opinionated rule: tune it.
    """
    headers = {key.lower(): value for key, value in headers.items()}
    if sender in me:
        # Unsubscribe requests and other mail to robots aren't conversations.
        return "people" if human_recipients(headers) else "updates"
    local, _, domain = sender.partition("@")
    if domain in UPDATE_DOMAINS or any(domain.endswith("." + known) for known in UPDATE_DOMAINS):
        return "updates"
    # Bulk mail stays bulk even from someone you've written to; their own
    # replies carry no list headers and still land in People.
    if "list-unsubscribe" in headers or "list-id" in headers or headers.get("precedence", "").lower() in {"bulk", "list", "junk"}:
        return "newsletters"
    robot = ROBOT_SENDER.search(local) is not None
    # A reply once sent to a no-reply address doesn't make it a person.
    if sender in correspondents and not robot:
        return "people"
    if robot or is_machine(headers, local, domain):
        return "updates"
    return "people"


def is_machine(headers: dict[str, str], local: str, domain: str) -> bool:
    if headers.get("auto-submitted", "no").strip().lower() != "no":
        return True
    if any(name in headers for name in MACHINE_HEADERS):
        return True
    # Sending services bounce to their own domain; a person's mail bounces home.
    import email.utils

    bounce = email.utils.parseaddr(headers.get("return-path", ""))[1].lower()
    if bounce and bounce.rpartition("@")[2] != domain:
        return True
    if local in ROLE_WORDS or not ROLE_WORDS.isdisjoint(re.split(r"[.\-_+]", local)):
        return True
    labels = domain.split(".")
    if not MACHINE_SUBDOMAINS.isdisjoint(labels[:-2]):
        return True
    # A brand's own name in the mailbox ("microsoftanswers@microsoft.com") is
    # the company talking; people's addresses rarely carry their employer.
    brand = labels[-3] if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"co", "com", "net", "org", "ac"} else (labels[-2] if len(labels) >= 2 else "")
    return len(brand) >= 4 and brand in local.replace(".", "").replace("-", "")


def read_headers(paths: list[str]) -> dict[str, str]:
    parser = _header_parser()
    for path in paths:
        try:
            with open(path, "rb") as handle:
                parsed = parser.parse(handle)
            return {key: str(value) for key, value in parsed.items()}
        except FileNotFoundError:
            continue
    return {}


# Indexing --------------------------------------------------------------------


def ids(db, query: str) -> list[str]:
    """Message ids for a query, collected before any tag changes (changing
    tags while iterating the same query is unsafe in Xapian)."""
    import notmuch2

    return [message.messageid for message in db.messages(query, omit_excluded=notmuch2.Database.EXCLUDE.FALSE)]


# What no view shows: deleted and spam mail until the next sync removes it,
# and Gmail drafts, which are never mail anyone sent. Courier tags those
# "unsent", not "draft": notmuch keeps "draft" in step with the maildir D
# flag (synchronize_flags), so it would strip that tag from copies without D
# and could even set D for mbsync to push to Gmail. "draft" is hidden too,
# in case a copy ever does carry D.
HIDDEN = "not tag:trash and not tag:spam and not tag:unsent and not tag:draft"


def index(accounts: list[dict]) -> dict[str, int]:
    """Indexes new files, mirrors Gmail's inbox, and sorts new mail into lanes.
    Returns how many new messages each account got."""
    import email.utils
    import notmuch2  # Ships with the notmuch package.
    import subprocess

    result = subprocess.run(["notmuch", "new", "--quiet"], capture_output=True, text=True)
    if result.returncode != 0:
        raise SyncError(f"notmuch new failed: {result.stderr.strip()}")

    me = {account["email"].lower() for account in accounts}
    root = mail_dir()
    counts = {account["id"]: 0 for account in accounts}
    in_inbox = " or ".join(f"path:{account['id']}/inbox/**" for account in accounts) or "NOT *"
    in_drafts = " or ".join(f"path:{account['id']}/drafts/**" for account in accounts) or "NOT *"

    with notmuch2.Database(mode=notmuch2.Database.MODE.READ_WRITE) as db:
        with db.atomic():
            # A message is in the inbox exactly while Gmail keeps it there.
            for message_id in ids(db, f"({in_inbox}) and not tag:inbox"):
                db.find(message_id).tags.add("inbox")
            for message_id in ids(db, f"tag:inbox and not ({in_inbox})"):
                db.find(message_id).tags.discard("inbox")
            # Archive, delete and the like from actions that found the index busy.
            apply_retag_queue(db)

            known = correspondents(db, "tag:sent")
            written = set(known)
            new_ids = ids(db, "tag:new")
            # A message is a draft exactly while Gmail keeps it in Drafts.
            drafts = set(ids(db, f"({in_drafts})"))
            # Mail you just sent counts before anything is sorted, so a reply
            # and the message it answers land in the same lane. (Queries inside
            # this transaction don't see tags added in it, so collect directly.)
            # A draft was never sent, to anyone.
            for message_id in new_ids:
                message = db.find(message_id)
                headers = read_headers(message_paths(message))
                if message_id not in drafts and email.utils.parseaddr(headers.get("From", ""))[1].lower() in me:
                    message.tags.add("sent")
                    written |= human_recipients(headers)
            mirror_drafts(db, drafts, me)

            fresh: list[tuple[str, str, str]] = []
            for message_id in new_ids:
                message = db.find(message_id)
                files = message_paths(message)
                headers = read_headers(files)
                name, sender = email.utils.parseaddr(headers.get("From", ""))
                sender = sender.lower()
                for account in {Path(path).relative_to(root).parts[0] for path in files} & counts.keys():
                    message.tags.add(f"account/{account}")
                    counts[account] += 1
                chosen = lane(headers, sender, me, written)
                set_lane(message, chosen)
                message.tags.discard("new")
                if chosen == "people" and sender not in me and "unread" in message.tags and time.time() - message.date < NOTIFY_WITHIN:
                    fresh.append((name or sender, headers.get("Subject", ""), message_id))

            # Writing to someone new moves their earlier mail to People.
            for address in sorted(written - known):
                if '"' not in address:
                    relane(db, f'from:"{address}" and not tag:people', me, written)
            # Meeting, dev and college, for the smart views. (The query sees
            # the index, which notmuch new already wrote; the new tags here
            # don't matter to it.)
            for start in range(0, len(new_ids), 200):
                categorize(db, " or ".join(f"id:{quote_id(message_id)}" for message_id in new_ids[start : start + 200]))
    # Mail a template makes (GitHub's, or one you taught) gets a notification
    # written from its fields; the rest of the people lane gets "New mail".
    handled = notify_fields(new_ids, me)
    notify([(name, subject) for name, subject, message_id in fresh if message_id not in handled])
    read_fields(new_ids)
    apply_expiry_rules(new_ids)
    return counts


def notify_fields(message_ids: list[str], me: set[str]) -> set[str]:
    """Notifications written from the fields of new mail a template makes
    (courier_notify). Returns the Message-IDs it handled. It only reads the
    index, and a problem there never stops mail coming in."""
    if not message_ids:
        return set()
    try:
        import courier_notify

        return courier_notify.after_sync(message_ids, me)
    except Exception as problem:  # noqa: BLE001 - mail first, notifications second
        print(f"courier-sync: notify: {problem}", file=sys.stderr)
        return set()


def read_fields(message_ids: list[str]) -> None:
    """Teach fields: new mail from a sender whose template you taught gets
    its fields read now (courier_templates). It only reads the index, and a
    problem there never stops mail coming in."""
    if not message_ids:
        return
    try:
        import notmuch2

        import courier_templates

        with notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY) as db:
            courier_templates.after_sync(db, message_ids)
    except Exception as problem:  # noqa: BLE001 - mail first, fields second
        print(f"courier-sync: fields: {problem}", file=sys.stderr)


def apply_expiry_rules(message_ids: list[str]) -> None:
    """Auto-expiry: apply enabled provider notification rules to newly synced
    mail (courier_expiry). No-ops in O(1) when no rules are enabled, and a
    problem there never stops mail coming in."""
    if not message_ids:
        return
    try:
        import courier_expiry

        courier_expiry.after_sync(message_ids)
    except Exception as problem:  # noqa: BLE001 - mail first, expiry second
        print(f"courier-sync: expiry: {problem}", file=sys.stderr)


def mirror_drafts(db, drafts: set[str], me: set[str]) -> None:
    """Gmail drafts (messages with a copy in <account>/drafts) are tagged
    "unsent" and never "sent": every view hides them, and they never count as
    mail you wrote to someone. One that left Drafts (sent or discarded in
    Gmail) loses the tag and, if it is yours, becomes sent mail. (Not the
    tag "draft": see HIDDEN.)"""
    import email.utils

    for message_id in drafts:
        message = db.find(message_id)
        message.tags.add("unsent")
        message.tags.discard("sent")
    for message_id in set(ids(db, "tag:unsent")) - drafts:
        message = db.find(message_id)
        message.tags.discard("unsent")
        headers = read_headers(message_paths(message))
        if email.utils.parseaddr(headers.get("From", ""))[1].lower() in me:
            message.tags.add("sent")


def notify(fresh: list[tuple[str, str]]) -> None:
    """A desktop notification for new mail from people (never for newsletters
    or machine mail). A burst becomes one summary."""
    if not fresh or os.environ.get("COURIER_NO_NOTIFY"):
        return
    if len(fresh) <= 3:
        notes = [(name, subject or "New message") for name, subject in fresh]
    else:
        names = list(dict.fromkeys(name for name, _ in fresh))
        notes = [(f"{len(fresh)} new messages", ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else ""))]
    for title, body in notes:
        desktop_notify(title, body, "-a", "Junco", "-i", "mail-message-new", "-c", "email.arrived")


def message_paths(message) -> list[str]:
    return [str(path) for path in message.filenames()]


def recipients(headers: dict[str, str]) -> set[str]:
    import email.utils

    lookup = {key.lower(): value for key, value in headers.items()}
    # Python 3.13+ parses strictly: one empty field makes the whole result empty.
    fields = [value for name in ("to", "cc", "bcc") if (value := lookup.get(name))]
    return {address.lower() for _, address in email.utils.getaddresses(fields) if address}


def human_recipients(headers: dict[str, str]) -> set[str]:
    """Recipients who could be people: not an unsubscribe robot or a no-reply box."""
    subject = next((value for key, value in headers.items() if key.lower() == "subject"), "")
    if subject.strip().lower() == "unsubscribe":
        return set()
    return {
        address
        for address in recipients(headers)
        if not UNSUBSCRIBE.search(address.partition("@")[0]) and not ROBOT_SENDER.search(address.partition("@")[0])
    }


def correspondents(db, query: str) -> set[str]:
    """Everyone the messages matching `query` were addressed to."""
    addresses = set()
    for message_id in ids(db, query):
        addresses |= human_recipients(read_headers(message_paths(db.find(message_id))))
    return addresses


def set_lane(message, name: str) -> None:
    with message.frozen():
        for other in LANES:
            if other != name:
                message.tags.discard(other)
        message.tags.add(name)


def categories_of(sender: str) -> set[str]:
    """The categories a sender's domain puts its mail in (meeting comes from
    the content, in categorize())."""
    domain = sender.rpartition("@")[2].lower()
    found = set()
    if any(domain == known or domain.endswith("." + known) for known in DEV_DOMAINS):
        found.add("dev")
    if domain.endswith(COLLEGE_SUFFIXES):
        found.add("college")
    return found


def categorize(db, query: str) -> int:
    """Sets the dev, college and meeting tags on mail matching `query`.
    Meetings are emails carrying a calendar invite (text/calendar)."""
    import email.utils

    changed = 0
    invites = "(mimetype:text/calendar or from:calendar-notification@google.com)"
    # notmuch's "*" means everything only on its own, never inside brackets.
    meetings = set(ids(db, invites if query.strip() == "*" else f"({query}) and {invites}"))
    for message_id in ids(db, query):
        message = db.find(message_id)
        try:
            sender = email.utils.parseaddr(message.header("from"))[1]
        except LookupError:
            sender = ""
        wanted = categories_of(sender) | ({"meeting"} if message_id in meetings else set())
        for tag in CATEGORIES:
            if (tag in wanted) != (tag in message.tags):
                message.tags.add(tag) if tag in wanted else message.tags.discard(tag)
                changed += 1
    return changed


def queue_retag(message_ids: list[str], added: list[str], removed: list[str]) -> None:
    """Tag changes from an action that found the index busy; index() applies
    them on its next run. One file per action, so writers never clash."""
    folder = state_dir() / "retag"
    folder.mkdir(parents=True, exist_ok=True)
    write_private(folder / f"{time.time_ns()}.json", json.dumps({"ids": message_ids, "add": added, "remove": removed}))


def apply_retag_queue(db) -> int:
    applied = 0
    folder = state_dir() / "retag"
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            change = json.loads(path.read_text())
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        for message_id in change.get("ids", []):
            try:
                message = db.find(message_id)
            except LookupError:
                continue
            for tag in change.get("add", []):
                message.tags.add(tag)
            for tag in change.get("remove", []):
                message.tags.discard(tag)
            applied += 1
        path.unlink(missing_ok=True)
    return applied


def quote_id(message_id: str) -> str:
    return '"' + message_id.replace('"', '""') + '"'


def relane(db, query: str, me: set[str], written: set[str]) -> dict[str, int]:
    """Sorts already-indexed mail again; returns how many messages each lane got."""
    import email.utils

    totals = dict.fromkeys(LANES, 0)
    for message_id in ids(db, query):
        message = db.find(message_id)
        headers = read_headers(message_paths(message))
        sender = email.utils.parseaddr(headers.get("From", ""))[1].lower()
        name = lane(headers, sender, me, written)
        set_lane(message, name)
        totals[name] += 1
    return totals


def relane_all(accounts: list[dict]) -> dict[str, int]:
    import notmuch2

    me = {account["email"].lower() for account in accounts}
    with notmuch2.Database(mode=notmuch2.Database.MODE.READ_WRITE) as db:
        with db.atomic():
            totals = relane(db, "*", me, correspondents(db, "tag:sent"))
            categorize(db, "*")
            return totals


# Running ---------------------------------------------------------------------


# A run is stopped when nothing new has arrived for STALL_TIMEOUT, or after
# RUN_LIMIT in all; the next one carries on from mbsync's journal. (A flat
# 10-minute limit cut a big first download into lumps.)
STALL_TIMEOUT = 3 * 60
RUN_LIMIT = 2 * 60 * 60
# How often a running mbsync is checked on, and how long a stopped one gets
# to finish its journal before it is killed.
POLL = 5
STOP_GRACE = 10
# While a download runs, how often what has arrived is indexed and shown.
INDEX_EVERY = 60


def run_mbsync(account: str, progress=None) -> None:
    """Runs mbsync for one account. While it runs, progress(have) is called
    every few seconds with how many emails are on this PC."""
    import subprocess
    import tempfile

    with tempfile.TemporaryFile("w+") as errors:
        process = subprocess.Popen(["mbsync", "-c", str(config_dir() / "mbsyncrc"), "-q", account],
                                   stdout=subprocess.DEVNULL, stderr=errors, text=True)
        start = changed = time.monotonic()
        have, busy = downloaded(account), journal_activity(account)
        while True:
            try:
                process.wait(timeout=POLL)
                break
            except subprocess.TimeoutExpired:
                pass
            # Progress is new mail, or mbsync writing its journal: removing
            # what Gmail removed and changing flags bring no new files, and a
            # run doing only that must not be cut short (what Gmail removed
            # would then stay on this PC until a run gets through).
            now, active = downloaded(account), journal_activity(account)
            if now != have or active != busy:
                have, busy, changed = now, active, time.monotonic()
            if progress:
                progress(have)
            if time.monotonic() - changed > STALL_TIMEOUT or time.monotonic() - start > RUN_LIMIT:
                # Asked to stop first, so it can finish what it is writing.
                process.terminate()
                try:
                    process.wait(timeout=STOP_GRACE)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise SyncError("Gmail was slow; this sync stopped early and the next one continues")
        errors.seek(0)
        lines = [line for line in errors.read().splitlines() if line.strip()]
    if process.returncode != 0:
        raise SyncError("; ".join(lines[-3:]) or "mbsync failed")


def write_status(accounts: dict[str, dict]) -> None:
    status = {"finished": datetime.now(timezone.utc).isoformat(timespec="seconds"), "accounts": accounts}
    write_private(state_dir() / "sync.json", json.dumps(status, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    import argparse
    import fcntl

    parser = argparse.ArgumentParser(prog="courier-sync", description="Sync Junco's mail.")
    parser.add_argument("--configure", action="store_true", help="rewrite the generated configs and stop")
    parser.add_argument("--relane", action="store_true", help="sort all downloaded mail into lanes again, without syncing")
    args = parser.parse_args(argv)

    accounts = load_accounts()
    if not accounts:
        print("No accounts yet. Run: courier-auth add <name>", file=sys.stderr)
        return 0

    state_dir().mkdir(parents=True, exist_ok=True)
    with open(state_dir() / "sync.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another sync is running.", file=sys.stderr)
            return 0
        if args.relane:
            os.environ["NOTMUCH_CONFIG"] = str(config_dir() / "notmuch-config")
            totals = relane_all(accounts)
            print("  ".join(f"{name} {count}" for name, count in totals.items()))
            return 0
        return sync_all(accounts, configure_only=args.configure)


def sync_all(accounts: list[dict], configure_only: bool) -> int:
    status: dict[str, dict] = {}
    try:
        folders = all_mail_folders(accounts)
    except SignedOut as expired:
        print(f"courier-sync: '{expired.args[0]}' needs signing in again: courier-auth add {expired.args[0]}", file=sys.stderr)
        return 2
    except SyncError as error:
        print(f"courier-sync: {error}", file=sys.stderr)
        return 1
    configure(accounts, folders, drafts_folders(accounts))
    if configure_only:
        print(f"Wrote mbsyncrc, msmtprc and notmuch-config to {config_dir()}.")
        return 0

    last_index = time.monotonic()

    for account in accounts:
        name = account["id"]
        try:
            auth_token(name)  # Refresh once up front, so mbsync's PassCmd is instant.
            expected = first_download_size(account, folders[name])

            def progress(have: int, name: str = name, expected: int | None = expected) -> None:
                # A first download shows as it arrives: index what's here every
                # minute and tell the app how far along it is.
                nonlocal last_index
                if expected is None or time.monotonic() - last_index < INDEX_EVERY:
                    return
                last_index = time.monotonic()
                status[name] = {"state": "downloading", "have": have, "expected": expected}
                try:
                    index(accounts)
                except SyncError as error:
                    print(f"courier-sync: {error}", file=sys.stderr)
                write_status(status)

            if expected is not None:
                status[name] = {"state": "downloading", "have": downloaded(name), "expected": expected}
                write_status(status)
            run_mbsync(name, progress)
            (state_dir() / f"downloaded-{name}").touch()
            status[name] = {"state": "ok"}
        except SignedOut:
            status[name] = {"state": "signed-out"}
        except SyncError as error:
            status[name] = {"state": "error", "message": str(error)}

    try:
        counts = index(accounts)
    except SyncError as error:
        print(f"courier-sync: {error}", file=sys.stderr)
        write_status(status)
        return 1
    for name, count in counts.items():
        status.setdefault(name, {"state": "ok"})["new"] = count
    write_status(status)
    # Pictures for new senders, in the background so new mail never waits.
    import subprocess

    subprocess.run(["systemctl", "--user", "start", "--no-block", "courier-avatars.service"], capture_output=True)

    for name, entry in status.items():
        detail = entry.get("message", "") or f"{entry.get('new', 0)} new"
        print(f"{name:<12}{entry['state']:<12}{detail}")
    if any(entry["state"] == "signed-out" for entry in status.values()):
        return 2
    return 1 if any(entry["state"] == "error" for entry in status.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
