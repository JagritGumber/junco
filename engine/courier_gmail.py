"""Changes made in Gmail itself: archive, back to the inbox, delete, spam, and
the undo of each.

Courier's local copy only pulls from Gmail (mbsync pushes nothing but read and
starred flags), so these go straight to Gmail over IMAP, the same OAuth
sign-in sync uses. Emails are found by their Message-ID with Gmail's own
search (X-GM-RAW "rfc822msgid:"), labels change with X-GM-LABELS, and Trash
and Spam are reached with MOVE into the folders Gmail marks \\Trash and \\Junk.
The next sync then brings the local copy in line.
"""

from __future__ import annotations

import imaplib
import json
import re
import time

import courier_sync as sync

# action -> (folder the email is in now, what to do there)
ACTIONS = {
    "archive": ("\\All", ("store", "-X-GM-LABELS", "(\\Inbox)")),
    "inbox": ("\\All", ("store", "+X-GM-LABELS", "(\\Inbox)")),
    "trash": ("\\All", ("move", "\\Trash")),
    "untrash": ("\\Trash", ("move", "INBOX")),
    "spam": ("\\All", ("move", "\\Junk")),
    "unspam": ("\\Junk", ("move", "INBOX")),
    # Like Gmail's "Move to": the label on, out of the inbox.
    "move": ("\\All", ("label",)),
}

# Folders that are Gmail's own, by their special-use flag.
SPECIAL = {"\\All", "\\Trash", "\\Junk", "\\Sent", "\\Drafts", "\\Flagged", "\\Important"}

# Gmail search queries stay short enough with this many IDs each.
BATCH = 30

LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) (?P<name>.+)$')


class GmailError(RuntimeError):
    pass


def quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def connect(account: dict) -> imaplib.IMAP4_SSL:
    token = sync.auth_token(account["id"])
    sasl = f"user={account['email']}\x01auth=Bearer {token}\x01\x01".encode()
    imap = imaplib.IMAP4_SSL(sync.IMAP_HOST, timeout=60)
    # A non-empty challenge is Gmail's error report; XOAUTH2 answers it empty.
    imap.authenticate("XOAUTH2", lambda challenge: b"" if challenge else sasl)
    return imap


def special_folders(imap) -> dict[str, str]:
    """Gmail's special folders by their flag (\\All, \\Trash, \\Junk...). The
    names follow the account's language, so they're asked for, not assumed."""
    typ, lines = imap.list()
    if typ != "OK":
        raise GmailError("Gmail wouldn't list its folders.")
    folders = {"INBOX": "INBOX"}
    for line in lines:
        match = LIST_LINE.match(line or b"")
        if not match:
            continue
        name = match["name"].decode()
        if name.startswith('"'):
            name = re.sub(r"\\(.)", r"\1", name[1:-1])
        for flag in match["flags"].decode().split():
            folders.setdefault(flag, name)
    return folders


# Gmail's folder names barely change; asking for them costs a round trip.
FOLDER_CACHE_SECONDS = 24 * 60 * 60


def folders_for(imap, account: dict, fresh: bool = False) -> dict[str, str]:
    """special_folders, remembered per account for a day."""
    path = sync.state_dir() / "gmail-folders.json"
    try:
        cache = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        cache = {}
    entry = cache.get(account["email"])
    if not fresh and entry and time.time() - entry.get("checked", 0) < FOLDER_CACHE_SECONDS:
        return entry["folders"]
    folders = special_folders(imap)
    cache[account["email"]] = {"folders": folders, "checked": time.time()}
    sync.write_private(path, json.dumps(cache, indent=1) + "\n")
    return folders


# A Message-ID goes into Gmail's search only if it is made of plain
# Message-ID characters. The sender writes it, and whitespace, quotes, a
# backslash, brackets, braces, a colon or "|" could turn "rfc822msgid:<id>"
# into a wider search ("a)OR(in:inbox") whose every match the action would
# then archive, delete or report. (All 14,070 IDs in a real mailbox fit, on
# 2026-11-23.)
SEARCHABLE_ID = re.compile(r"[A-Za-z0-9.!#$%&*+/=?^_~@-]+")


def find_uids(imap, message_ids: list[str]) -> list[str]:
    """The selected folder's UIDs for these Message-IDs. A search matching
    more than two emails per ID asked for (a copy at most) meant something
    else, and is refused before anything changes."""
    uids: list[str] = []
    usable = [m for m in message_ids if m and SEARCHABLE_ID.fullmatch(m)]
    for start in range(0, len(usable), BATCH):
        batch = usable[start : start + BATCH]
        query = " OR ".join(f"rfc822msgid:{m}" for m in batch)
        typ, data = imap.uid("SEARCH", "X-GM-RAW", f'"{query}"')
        if typ != "OK":
            raise GmailError("Gmail's search failed.")
        found = (data[0] or b"").decode().split()
        if len(found) > 2 * len(batch):
            raise GmailError("Gmail matched more emails than asked for, so nothing was changed.")
        uids += found
    return uids


def labels(account: dict, imap=None) -> list[str]:
    """Your own Gmail labels (not Inbox, Sent and the other system folders)."""
    own = imap is None
    imap = imap or connect(account)
    try:
        typ, lines = imap.list()
        if typ != "OK":
            raise GmailError("Gmail wouldn't list its labels.")
        found = []
        for line in lines:
            match = LIST_LINE.match(line or b"")
            if not match or b"\\Noselect" in match["flags"]:
                continue
            flags = match["flags"].decode().split()
            name = match["name"].decode()
            if name.startswith('"'):
                name = re.sub(r"\\(.)", r"\1", name[1:-1])
            if name == "INBOX" or name.startswith("[Gmail]") or any(flag in SPECIAL for flag in flags):
                continue
            found.append(name)
        return sorted(found, key=str.lower)
    finally:
        if own:
            imap.logout()


def labels_of(account: dict, message_id: str, imap=None) -> list[str]:
    """The labels Gmail has on one email right now."""
    own = imap is None
    imap = imap or connect(account)
    try:
        folders = folders_for(imap, account)
        imap.select(quote(folders["\\All"]), readonly=True)
        uids = find_uids(imap, [message_id])
        if not uids:
            return []
        typ, data = imap.uid("FETCH", uids[0], "(X-GM-LABELS)")
        text = b" ".join(part if isinstance(part, bytes) else b" ".join(part) for part in data if part).decode("utf-8", "replace")
        inside = re.search(r"X-GM-LABELS \((.*?)\)", text)
        names = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', inside.group(1)) if inside else []
        found = [(quoted or bare).replace('\\"', '"').replace("\\\\", "\\") for quoted, bare in names]
        return [name for name in found if not name.startswith("\\")]
    finally:
        if own:
            imap.logout()


def apply(account: dict, action: str, message_ids: list[str], imap=None, label: str = "") -> int:
    """Does `action` to these emails in Gmail; returns how many Gmail found."""
    if action not in ACTIONS:
        raise GmailError(f"Unknown action {action!r}.")
    if action == "move" and not label:
        raise GmailError("Pick a label to move them to.")
    source_flag, (kind, *rest) = ACTIONS[action]
    own = imap is None
    try:
        imap = imap or connect(account)
    except (imaplib.IMAP4.error, OSError) as error:
        raise GmailError(f"Couldn't reach Gmail for {account['email']}: {error}") from None
    try:
        folders = folders_for(imap, account)
        source = folders.get(source_flag)
        typ = "NO"
        if source is not None:
            typ, _ = imap.select(quote(source))
        if typ != "OK":
            # The cached name may be stale (a language change): ask again once.
            folders = folders_for(imap, account, fresh=True)
            source = folders.get(source_flag)
            if source is None:
                raise GmailError(f"Gmail has no {source_flag.strip(chr(92))} folder over IMAP.")
            typ, _ = imap.select(quote(source))
            if typ != "OK":
                raise GmailError(f"Gmail wouldn't open {source}.")
        uids = find_uids(imap, message_ids)
        if not uids:
            return 0
        uid_set = ",".join(uids)
        if kind == "store":
            typ, _ = imap.uid("STORE", uid_set, *rest)
        elif kind == "label":
            typ, _ = imap.uid("STORE", uid_set, "+X-GM-LABELS", f"({quote(label)})")
            if typ == "OK":
                typ, _ = imap.uid("STORE", uid_set, "-X-GM-LABELS", "(\\Inbox)")
        else:
            target = folders.get(rest[0], rest[0])
            typ, _ = imap.uid("MOVE", uid_set, quote(target))
        if typ != "OK":
            raise GmailError(f"Gmail refused to {action} those emails.")
        return len(uids)
    except imaplib.IMAP4.error as error:
        raise GmailError(f"Gmail refused: {error}") from None
    finally:
        if own:
            try:
                imap.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
