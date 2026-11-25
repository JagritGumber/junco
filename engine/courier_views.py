"""What Courier's mail window shows: the folders with their counts, the smart
list (threads, and machine mail folded per sender per day), and the details
beside an open email (its meeting, thread, related files, snooze, reminder
and retention).
"""

from __future__ import annotations

import email.errors
import email.header
import email.utils
import itertools
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import courier_later as later
import courier_sync as sync

# Folders in the sidebar: id -> (name, description, icon, notmuch query).
# Snoozed, Scheduled, Expiring and Trash aren't notmuch queries; see below.
FOLDERS = {
    "smart": ("Inbox", "Everything in your inbox, newest first", "inbox", "tag:inbox"),
    "meetings": ("Meetings", "Invites and the mail around them", "calendar_month", "tag:meeting"),
    "dev": ("Dev Updates", "From the tools you build with", "code", "tag:dev and tag:inbox"),
    "college": ("College", "From your college and courses", "school", "tag:college"),
    "all": ("All Mail", "Everything, newest first", "mail", "*"),
    "starred": ("Starred", "Mail you starred, here and in Gmail", "star", "tag:flagged"),
    "sent": ("Sent", "Mail you wrote", "send", 'tag:sent and not subject:"/^unsubscribe$/"'),
    "snoozed": ("Snoozed", "Back in your inbox when it's time", "schedule", None),
    "scheduled": ("Scheduled", "Waiting to be sent", "schedule_send", None),
    "reminders": ("Reminders", "Emails you asked to be reminded about", "notifications", None),
    "expiring": ("Expiring", "Set to delete themselves soon", "hourglass_empty", None),
    "archive": ("Archive", "Out of the inbox, still yours", "archive", "not tag:inbox and not tag:sent"),
    "trash": ("Trash", "Deleted in Gmail; restore within 30 days", "delete", None),
}
# Emails read to build one list, and the most rows it shows.
SCAN = 1500
ROWS = 150
# Expiring shows emails set to delete within this many days.
EXPIRING_DAYS = 30
# Issue and pull request numbers worth a chip: "#1429", "STU-128".
NUMBER = re.compile(r"#(\d{1,6})\b|\b([A-Z][A-Z0-9]{1,5}-\d{1,6})\b")


def visible(query: str) -> str:
    return sync.HIDDEN if query.strip() == "*" else f"({query}) and {sync.HIDDEN}"


def unread(index, query: str) -> int:
    return index.db.count_messages(f"{visible(query)} and tag:unread")


def ids_query(message_ids: list[str]) -> str:
    return " or ".join(f"id:{sync.quote_id(m)}" for m in message_ids) if message_ids else "id:none-at-all"


def expiring_ids(now: float | None = None) -> list[str]:
    limit = (now or time.time()) + EXPIRING_DAYS * 86400
    return [message_id for message_id, item in later.retention().items() if item["until"] <= limit]


def folder_query(folder: str) -> str:
    if folder == "snoozed":
        return ids_query([item["id"] for item in later.snoozed()])
    if folder == "expiring":
        return ids_query(expiring_ids())
    if folder == "reminders":
        return ids_query([item["id"] for item in later.reminders()])
    if folder not in FOLDERS or FOLDERS[folder][3] is None:
        raise ValueError(f"unknown folder {folder!r}")
    return FOLDERS[folder][3]


def account_query(account: str) -> str:
    return f"tag:account/{account}" if account else ""


def folders(index, account: str = "") -> dict:
    """Every folder with its badge: unread for mail views, a count for the
    rest. With an account, only that account's mail counts."""
    found = []
    only = f" and {account_query(account)}" if account else ""
    for folder, (name, description, icon, query) in FOLDERS.items():
        if folder in {"smart", "meetings", "dev", "college"}:
            badge = unread(index, f"({query}) and tag:inbox{only}")
        elif folder == "snoozed":
            badge = len(later.snoozed())
        elif folder == "scheduled":
            badge = len(later.scheduled())
        elif folder == "expiring":
            badge = len(expiring_ids())
        elif folder == "reminders":
            badge = len(later.reminders())
        else:
            badge = 0
        found.append({"id": folder, "name": name, "description": description, "icon": icon, "count": badge})
    return {"folders": found, "rules": len([r for r in later.rules() if r["enabled"]])}


# Times -----------------------------------------------------------------------------


def clock(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def row_time(epoch: int, now: float | None = None) -> str:
    """10:24 for this morning's, 2h for a few hours back, then Tue, 2 Jun, 02/06/25."""
    now_moment = datetime.fromtimestamp(now or time.time())
    moment = datetime.fromtimestamp(epoch)
    if moment.date() == now_moment.date():
        hours = (now_moment - moment).total_seconds() / 3600
        if hours < 1:
            return f"{max(1, int(hours * 60))}m"
        return f"{int(hours)}h" if hours < 6 else clock(moment)
    if (now_moment.date() - moment.date()).days < 7:
        return moment.strftime("%a")
    if moment.year == now_moment.year:
        return f"{moment.day} {moment.strftime('%b')}"
    return moment.strftime("%d/%m/%y")


def section(epoch: int, now: float | None = None) -> str:
    today = datetime.fromtimestamp(now or time.time()).date()
    day = datetime.fromtimestamp(epoch).date()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return "Earlier"


def ago(epoch: float, now: float | None = None) -> str:
    days = int(((now or time.time()) - epoch) // 86400)
    if days < 1:
        return "today"
    if days < 7:
        return f"{days} day{'s' if days > 1 else ''} ago"
    if days < 60:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    months = days // 30
    return f"{months} months ago" if months < 24 else f"{days // 365} years ago"


def relative_day(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return day.strftime("%a %-d %b" if day.year == today.year else "%a %-d %b %Y")


# Calendar invites -------------------------------------------------------------------


def unfolded(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def ics_value(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def ics_time(params: dict, value: str) -> tuple[datetime | None, bool]:
    """A DTSTART/DTEND as a local datetime, and whether it's a whole day."""
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value[:8], "%Y%m%d"), True
        moment = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None, False
    if value.endswith("Z"):
        return moment.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None), False
    if "TZID" in params:
        try:
            zone = ZoneInfo(params["TZID"].strip('"'))
            return moment.replace(tzinfo=zone).astimezone().replace(tzinfo=None), False
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return moment, False


def parse_invite(text: str) -> dict | None:
    """The first VEVENT of a calendar invite, in the fields the app shows."""
    event: dict = {"attendees": []}
    inside = False
    for line in unfolded(text):
        if line.upper() == "BEGIN:VEVENT":
            inside = True
            continue
        if line.upper() == "END:VEVENT":
            break
        if not inside or ":" not in line:
            continue
        head, _, value = line.partition(":")
        name, *raw = head.split(";")
        params = dict(p.split("=", 1) for p in raw if "=" in p)
        name = name.upper()
        if name == "SUMMARY":
            event["title"] = ics_value(value)
        elif name in {"DTSTART", "DTEND"}:
            event[name], event[f"{name}_day"] = ics_time(params, value)
        elif name == "LOCATION":
            event["where"] = ics_value(value)
        elif name == "DESCRIPTION":
            event["description"] = ics_value(value)
        elif name == "UID":
            event["uid"] = value.strip()
        elif name == "URL":
            event["url"] = value.strip()
        elif name in {"X-GOOGLE-CONFERENCE", "X-MICROSOFT-SKYPETEAMSMEETINGURL"}:
            event["conference"] = web_link(value)
        elif name in {"ATTENDEE", "ORGANIZER"}:
            address = re.sub(r"^mailto:", "", value.strip(), flags=re.I)
            person = {"name": params.get("CN", "").strip('"'), "email": address.lower()}
            if name == "ORGANIZER":
                event["organizer"] = person
            if person not in event["attendees"]:
                event["attendees"].append(person)
    if "DTSTART" not in event or event["DTSTART"] is None:
        return None
    return event


# A link the app may hand to the system to open (courier_sync.web_link).
web_link = sync.web_link


MEETING_LINK = re.compile(r"https://(?:meet\.google\.com/[\w-]+|[\w.-]*zoom\.us/(?:j|w|my|s)/\S+|teams\.microsoft\.com/l/meetup-join/\S+)")


def meeting_of(parsed, calendar_events: list[dict], now: float | None = None) -> dict | None:
    """The meeting an email invites to, if it carries an invite."""
    text = None
    for part in parsed.walk():
        if part.get_content_type() == "text/calendar":
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
            break
    if text is None:
        return None
    event = parse_invite(text)
    if event is None:
        return None
    start, end = event["DTSTART"], event.get("DTEND") or event["DTSTART"]
    all_day = event.get("DTSTART_day", False)
    today = datetime.fromtimestamp(now or time.time()).date()
    label = relative_day(start.date(), today)
    if all_day:
        when = f"{label}, {start.strftime('%a %-d %b')} · All day" if label in {"Today", "Tomorrow", "Yesterday"} else f"{label} · All day"
    else:
        minutes = int((end - start).total_seconds() // 60)
        length = f"{minutes} min" if minutes < 60 else (f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes // 60} h {minutes % 60} min")
        day = f"{label}, {start.strftime('%a %-d %b')}" if label in {"Today", "Tomorrow", "Yesterday"} else label
        when = f"{day} · {clock(start)} – {clock(end)} ({length})"
    link = event.get("conference") or ""
    if not link:
        found = MEETING_LINK.search(" ".join([event.get("description", ""), event.get("where", ""), event.get("url", "")]))
        link = found.group(0) if found else ""
    link = web_link(link)
    provider = "Google Meet" if "meet.google.com" in link else "Zoom" if "zoom.us" in link else "Microsoft Teams" if "teams.microsoft" in link else ""
    # Already on your calendar: the same invite id, or the same title at the same time.
    match = next((e for e in calendar_events if event.get("uid") and e.get("uid") == event.get("uid")), None) or next(
        (e for e in calendar_events if e.get("title") == event.get("title") and str(e.get("start", ""))[:16] == start.isoformat()[:16]), None
    )
    return {
        "title": event.get("title") or "Meeting",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "day": start.date().isoformat(),
        "allDay": all_day,
        "when": when,
        "short": f"{label}, {clock(start)}" if not all_day else label,
        "where": event.get("where", "") if not MEETING_LINK.fullmatch(event.get("where", "")) else "",
        "link": link,
        "provider": provider,
        "attendees": event["attendees"],
        "organizer": event.get("organizer"),
        "added": match is not None,
        "past": end < datetime.fromtimestamp(now or time.time()),
        "eventLink": web_link((match or {}).get("link", "")),
    }


def calendar_events() -> list[dict]:
    import json

    try:
        return json.loads((sync.mail_dir().parent / "calendar" / "google.json").read_text()).get("events", [])
    except (FileNotFoundError, ValueError):
        return []


# The smart list ----------------------------------------------------------------------


def header(message, name: str) -> str:
    try:
        return email.header.make_header(email.header.decode_header(message.header(name) or "")).__str__()
    except (LookupError, UnicodeError, email.errors.HeaderParseError):
        return ""


def category_of(tags: set[str]) -> str:
    for tag in ("meeting", "dev", "college"):
        if tag in tags:
            return tag
    return next((lane for lane in sync.LANES if lane in tags), "updates")


ICONS = {"meeting": "calendar_month", "dev": "code", "college": "school", "newsletters": "newspaper", "updates": "notifications", "people": ""}


def numbers_in(subject: str) -> list[str]:
    found = []
    for issue, key in NUMBER.findall(subject):
        token = key or f"#{issue}"
        if token not in found:
            found.append(token)
    return found


def summary(group: dict) -> str:
    """One line for several emails from one sender in one day."""
    reviews = group["_reviews"]
    if reviews and reviews == group["count"]:
        return f"{reviews} pull request{'s' if reviews > 1 else ''} need{'s' if reviews == 1 else ''} your review"
    return f"{group['count']} emails · {group['_latest']}"


def smart_list(index, folder: str, search: str = "", now: float | None = None, account: str = "") -> dict:
    """One folder's rows, newest first, under Today, Yesterday and Earlier:
    people, college and meetings by thread; machine mail folded per sender
    per day, so a morning of GitHub is one row."""
    import courier_avatars

    name, description, _, _ = FOLDERS[folder]
    query = folder_query(folder)
    if account:
        query = account_query(account) if query.strip() == "*" else f"({query}) and {account_query(account)}"
    if search.strip():
        query = f"({query}) and ({search.strip()})" if query.strip() != "*" else search.strip()
    pictures = courier_avatars.load_index()
    rows: dict[str, dict] = {}
    order: list[str] = []
    for message in itertools.islice(index.newest_first(query), SCAN):
        tags = set(message.tags)
        category = category_of(tags)
        sender_name, sender = email.utils.parseaddr(header(message, "from"))
        sender = sender.lower()
        domain = sender.rpartition("@")[2]
        epoch = int(message.date)
        subject = header(message, "subject") or "(no subject)"
        folded = category in {"updates", "newsletters", "dev"} and sender not in index.me
        day_key = datetime.fromtimestamp(epoch).date().isoformat()
        # The smart inbox reads a day's newsletters as one row.
        bundled = folded and folder == "smart" and category == "newsletters"
        if bundled:
            key = f"g:newsletters:{day_key}"
        elif folded:
            key = f"g:{domain}:{day_key}"
        else:
            key = f"t:{message.threadid}"
        row = rows.get(key)
        if row is None:
            if len(order) >= ROWS:
                continue
            mine = sender in index.me
            title = sender_name or sync_name(sender)
            if mine:
                to_name, to_address = email.utils.parseaddr(header(message, "to"))
                title = f"To {to_name or sync_name(to_address)}" if to_address else "You"
            row = rows[key] = {
                "id": key,
                "open": message.messageid,
                "ids": [],
                "kind": "group" if folded else "thread",
                "category": category,
                "title": title,
                "subtitle": subject,
                "time": row_time(epoch, now),
                "epoch": epoch,
                "section": section(epoch, now),
                "unread": 0,
                "starred": False,
                "count": 0,
                "chips": [],
                "icon": ICONS.get(category, ""),
                "avatar": courier_avatars.picture_for_key(f"d:{courier_domain(domain)}", pictures) if category != "people" or not mine else "",
                "attachment": "attachment" in tags,
                "account": next((t.split("/", 1)[1] for t in tags if t.startswith("account/")), ""),
                "members": [],
                "_reviews": 0,
                "_latest": subject,
                "_path": str(message.path),
                "_names": [],
                "_bundled": bundled,
            }
            if bundled:
                row["title"], row["icon"], row["avatar"] = "Newsletters", "newspaper", ""
            order.append(key)
        row["ids"].append(message.messageid)
        row["count"] += 1
        if folded and len(row["members"]) < 25:
            row["members"].append({"id": message.messageid, "title": sender_name or sync_name(sender), "subtitle": subject,
                                   "time": row_time(epoch, now), "unread": "unread" in tags})
        if bundled and (sender_name or sender) not in row["_names"]:
            row["_names"].append(sender_name or sync_name(sender))
        row["unread"] += "unread" in tags
        row["starred"] = row["starred"] or "flagged" in tags
        if folded:
            try:
                reason = (message.header("x-github-reason") or "").lower()
            except LookupError:
                reason = ""
            row["_reviews"] += reason == "review_requested" or "review request" in subject.lower()
            for token in numbers_in(subject):
                if token not in row["chips"]:
                    row["chips"].append(token)
    found = [rows[key] for key in order]
    events = None
    for row in found:
        if row["_bundled"]:
            names = row["_names"]
            row["subtitle"] = ", ".join(names[:2]) + (f" and {len(names) - 2} more" if len(names) > 2 else "")
        elif row["kind"] == "group" and row["count"] > 1:
            row["subtitle"] = summary(row)
        if row["count"] < 2:
            row["members"] = []
        if len(row["chips"]) > 2:
            row["chips"] = row["chips"][:2] + [f"+{len(row['chips']) - 2}"]
        if row["category"] == "meeting":
            # The invite's own title and time read better than the subject.
            events = events if events is not None else calendar_events()
            parsed = parse_file(row.pop("_path"))
            meeting = meeting_of(parsed, events, now) if parsed is not None else None
            if meeting:
                row["title"], row["subtitle"] = meeting["title"], " · ".join(p for p in (meeting["provider"], meeting["short"]) if p)
        for private in ("_reviews", "_latest", "_path", "_names", "_bundled"):
            row.pop(private, None)
    sections: list[dict] = []
    for row in found:
        if not sections or sections[-1]["name"] != row["section"]:
            sections.append({"name": row["section"], "rows": []})
        sections[-1]["rows"].append(row)
    return {
        "folder": folder,
        "title": name,
        "subtitle": description,
        "sections": sections,
        "rows": len(found),
        "more": len(found) >= ROWS,
    }


def sync_name(address: str) -> str:
    local = address.partition("@")[0]
    return " ".join(part.capitalize() for part in re.split(r"[._-]+", local) if part) or address


def courier_domain(domain: str) -> str:
    import courier_mail

    return courier_mail.base_domain(domain)


def parse_file(path: str):
    import email as email_module
    import email.policy

    try:
        with open(path, "rb") as handle:
            return email_module.message_from_binary_file(handle, policy=email.policy.default)
    except OSError:
        return None


# Beside an open email ------------------------------------------------------------------


def details(index, message, parsed, now: float | None = None) -> dict:
    """What the panel beside an email shows."""
    import courier_mail

    now = now or time.time()
    thread_messages = list(itertools.islice(index.newest_first(f"thread:{message.threadid}"), 30))
    thread = []
    related_files = []
    for other in reversed(thread_messages):
        name, sender = email.utils.parseaddr(header(other, "from"))
        thread.append({
            "id": other.messageid,
            "fromName": name or sync_name(sender),
            "mine": sender.lower() in index.me,
            "time": row_time(int(other.date), now),
            "subject": header(other, "subject"),
            "current": other.messageid == message.messageid,
            "unread": "unread" in set(other.tags),
        })
        if other.messageid != message.messageid and "attachment" in set(other.tags):
            other_parsed = parse_file(str(other.path))
            if other_parsed is not None:
                for number, part in enumerate(courier_mail.attachment_parts(other_parsed)):
                    related_files.append({
                        "id": other.messageid,
                        "index": number,
                        "name": courier_mail.decode(part.get_filename()),
                        "size": courier_mail.human_size(len(part.get_payload(decode=True) or b"")),
                        "age": ago(int(other.date), now),
                    })
    _, sender = email.utils.parseaddr(header(message, "from"))
    from_sender = []
    if sender:
        for other in itertools.islice(index.newest_first(f'from:"{sender}" and not id:{sync.quote_id(message.messageid)}'), 8):
            from_sender.append({"id": other.messageid, "subject": header(other, "subject") or "(no subject)", "time": row_time(int(other.date), now)})
    snooze = next((item for item in later.snoozed() if item["id"] == message.messageid), None)
    reminder = next((item for item in later.reminders() if item["id"] == message.messageid), None)
    kept = later.retention().get(message.messageid)
    rule = None
    for candidate in later.rules():
        if candidate["enabled"] and candidate["kind"] == "delete":
            query = f"id:{sync.quote_id(message.messageid)} and ({later.rule_query(dict(candidate, afterDays=0))})"
            if index.db.count_messages(query):
                rule = {"text": later.describe(candidate), "until": int(message.date) + candidate["afterDays"] * 86400}
                break
    to_me = any(plain_address(address) in index.me for _, address in email.utils.getaddresses([header(message, "to"), header(message, "cc")]))
    return {
        "threadId": message.threadid,
        "thread": thread,
        "relatedFiles": related_files[-6:],
        "fromSender": from_sender,
        "meeting": meeting_of(parsed, calendar_events(), now),
        "snoozedUntil": snooze["until"] if snooze else 0,
        "remindAt": reminder["at"] if reminder else 0,
        "retention": {"period": kept["period"], "until": kept["until"], "name": later.PERIOD_NAMES[kept["period"]]} if kept else None,
        "ruleRetention": rule,
        "toMe": to_me,
        "category": category_of(set(message.tags)),
    }


def plain_address(address: str) -> str:
    """you+cloudflare@gmail.com is still you@gmail.com."""
    local, _, domain = address.lower().partition("@")
    return f"{local.split('+')[0]}@{domain}" if domain else local


def preview_path(name: str) -> Path:
    """Where an attachment's preview copy goes: a private folder of this
    user's (courier_html.private_dir), never a shared /tmp."""
    import courier_html

    return courier_html.private_dir("preview") / name
