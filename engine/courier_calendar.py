#!/usr/bin/env python3
"""Courier's calendar: every Google calendar copied to this PC, plus events
kept only here, with desktop reminders.

    courier-calendar sync      copy each account's calendars (7 days back, 120 ahead)
    courier-calendar agenda    JSON for the app: today, tomorrow, upcoming days, the month
    courier-calendar remind    notify about reminders that are due (run every minute)

Google events land in ~/.local/share/courier/calendar/google.json; events
made on this PC live in local.json beside it. Read-only towards Google, but
for one thing: answering an invitation from the notification dock's button
(respond), which needs the calendar.events permission
(courier-auth add <account> --calendar-write).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import courier_sync as sync  # noqa: E402

API = "https://www.googleapis.com/calendar/v3"
# The month view can page back two months and a year ahead.
DAYS_BACK = 60
DAYS_AHEAD = 365
UPCOMING_DAYS = 30
# A reminder that comes due while the PC sleeps still shows if this recent.
LATE_GRACE = 10 * 60


class CalendarError(RuntimeError):
    def __init__(self, message: str, action: str = ""):
        super().__init__(message)
        self.action = action


def calendar_dir() -> Path:
    return sync.mail_dir().parent / "calendar"


def status_path() -> Path:
    return sync.state_dir() / "calendar.json"


def next_meeting_path() -> Path:
    return sync.state_dir() / "next-meeting.json"


def actionables_db_path() -> Path:
    return calendar_dir() / "actionables.db"


def write_atomic_private(path: Path, text: str) -> None:
    """Atomically write a private file (0600) with a PID-scoped temp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


# Meeting link extraction -------------------------------------------------------

URL_PATTERN = re.compile(r"https?://[^\s<>\"'`\)\]\}]+" , re.I)
TRAILING_URL_PUNCT = ".,;:!?)'\"]}>"
ZOOM_PATH_RE = re.compile(r"^/(j|w|my|s|wc/join)/.+")
WEBEX_JOIN_RE = re.compile(r"/(meet|join)/.+")
WEBEX_JPHP_RE = re.compile(r"^/[^/]+/j\.php")


def _match_meeting_provider(url: str) -> str:
    """Return the provider label if `url` is a validated meeting link, else ''."""
    clean = sync.web_link(url)
    if not clean:
        return ""
    import urllib.parse

    parts = urllib.parse.urlsplit(clean)
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    path_lower = path.lower()
    if host == "meet.google.com" and len(path.strip("/")) > 0:
        return "Google Meet"
    if (host == "zoom.us" or host.endswith(".zoom.us") or host.endswith(".zoom.gov")) and ZOOM_PATH_RE.match(
        path_lower
    ):
        return "Zoom"
    if host == "teams.microsoft.com" and (path_lower.startswith("/l/meetup-join") or path_lower.startswith("/meet/")):
        return "Microsoft Teams"
    if host == "teams.live.com" and path_lower.startswith("/meet/"):
        return "Microsoft Teams"
    if (host == "app.slack.com" or host.endswith(".slack.com")) and path_lower.startswith("/huddle/"):
        return "Slack Huddle"
    if host == "meet.jit.si" and len(path.strip("/")) > 0:
        return "Jitsi Meet"
    if (host == "webex.com" or host.endswith(".webex.com")) and (
        WEBEX_JOIN_RE.search(path_lower) or path_lower.endswith("/j.php") or "/j.php" in path_lower or WEBEX_JPHP_RE.match(path_lower)
    ):
        return "Webex"
    return ""


def meeting_provider_name(url: str) -> str:
    """Friendly name for a known meeting URL, or '' if generic/empty."""
    return _match_meeting_provider(url)


def extract_meeting_url_from_text(text: str) -> str:
    """Extract the first validated known meeting link from arbitrary text."""
    if not text:
        return ""
    for match in URL_PATTERN.finditer(text):
        candidate = match.group(0).rstrip(TRAILING_URL_PUNCT)
        clean = sync.web_link(candidate)
        if clean and _match_meeting_provider(clean):
            return clean
    return ""


def extract_meeting_url(event: dict) -> str:
    """Auto-extract a validated meeting join URL from hangoutLink,
    conferenceData, saved video field, location/where, or description/notes."""
    if not isinstance(event, dict):
        return ""
    hangout = sync.web_link(event.get("hangoutLink") or "")
    if hangout:
        return hangout
    conf = event.get("conferenceData") or {}
    if isinstance(conf, dict):
        for entry in conf.get("entryPoints") or []:
            if isinstance(entry, dict) and entry.get("entryPointType") == "video":
                uri = sync.web_link(entry.get("uri") or "")
                if uri:
                    return uri
    existing_video = sync.web_link(event.get("video") or "")
    if existing_video:
        return existing_video
    for field in ("location", "where", "description", "notes"):
        value = event.get(field)
        if isinstance(value, str) and value:
            found = extract_meeting_url_from_text(value)
            if found:
                return found
    return ""


# Google ------------------------------------------------------------------------


def api_get(token: str, path: str, params: dict) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request

    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get("error", {})
        except ValueError:
            detail = {}
        message = detail.get("message", str(error))
        if error.code == 403 and ("has not been used" in message or "is disabled" in message):
            link = next((word for word in message.split() if word.startswith("https://console.developers.google.com")), "")
            raise CalendarError("Turn on the Google Calendar API for your Cloud project.", link.rstrip(".")) from None
        raise CalendarError(f"Google Calendar said: {message}") from None
    except urllib.error.URLError as error:
        raise CalendarError(f"Can't reach Google Calendar: {error.reason}") from None


def api_patch(token: str, path: str, params: dict, body: dict) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request

    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="PATCH",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get("error", {})
        except ValueError:
            detail = {}
        finally:
            error.close()
        reasons = " ".join(str(e.get("reason", "")) for e in detail.get("errors", []) if isinstance(e, dict)) + " " + str(detail.get("status", ""))
        if error.code == 403 and re.search(r"insufficient|SCOPE", reasons + " " + detail.get("message", ""), re.I):
            raise CalendarError("Junco may only read your calendar: run courier-auth add <account> --calendar-write") from None
        raise CalendarError(f"Google Calendar said: {detail.get('message', str(error))}") from None
    except urllib.error.URLError as error:
        raise CalendarError(f"Can't reach Google Calendar: {error.reason}") from None


ANSWERS = {"accept": "accepted", "maybe": "tentative", "decline": "declined"}
SAID = {"accepted": "You said yes", "tentative": "You said maybe", "declined": "You said no"}


def respond(invite: dict, answer: str) -> str:
    """Answers an invitation as you, on Google Calendar (only from the
    dock's own button): your response on the event the invite put on your
    calendar, and Google tells the organiser. Returns the one line the dock
    shows; raises CalendarError. COURIER_CALENDAR_DRY_RUN=1 changes nothing."""
    status = ANSWERS[answer]
    uid, account = invite.get("uid", ""), invite.get("account", "")

    def same_time(event: dict) -> bool:
        try:
            return datetime.fromisoformat(event["start"]).astimezone() == datetime.fromisoformat(invite["start"]).astimezone()
        except (KeyError, TypeError, ValueError):
            return False

    # The event at the card's own time (a series shares one id), on the
    # account the email came to.
    event = next((e for e in load_google().get("events", []) if uid and e.get("uid") == uid
                  and (not account or e.get("account") == account) and same_time(e)), None)
    if event is None:
        raise CalendarError("That invitation isn't on your calendar yet: try again after the next calendar sync")
    import urllib.parse

    calendar_id = str(event.get("calendarId", "")).split(":", 1)[-1]
    path = f"/calendars/{urllib.parse.quote(calendar_id, safe='')}/events/{urllib.parse.quote(str(event['id']), safe='')}"
    if os.environ.get("COURIER_CALENDAR_DRY_RUN") == "1":
        return f"dry run: {status} on {event['id']}"
    token = sync.auth_token(event["account"])
    current = api_get(token, path, {})
    # Only the meeting the card shows: Google's own copy has the card's
    # organiser (an invite reusing another meeting's id can't answer it).
    organiser = str((current.get("organizer") or {}).get("email", "")).lower()
    if organiser != str((invite.get("organizer") or {}).get("email", "")).lower():
        raise CalendarError("That invitation doesn't match the meeting on your calendar: nothing was answered")
    attendees = current.get("attendees") or []
    mine = [a for a in attendees if a.get("self")]
    if not mine:
        raise CalendarError("You're not on that invitation's guest list")
    for person in mine:
        person["responseStatus"] = status
    api_patch(token, path, {"sendUpdates": "all"}, {"attendees": attendees})
    return SAID[status]


def paged(token: str, path: str, params: dict) -> list[dict]:
    items, page = [], None
    while True:
        data = api_get(token, path, params | ({"pageToken": page} if page else {}))
        items += data.get("items", [])
        page = data.get("nextPageToken")
        if not page:
            return items


def popup_minutes(reminders: list[dict]) -> list[int]:
    return sorted({int(r["minutes"]) for r in reminders if r.get("method") == "popup" and "minutes" in r})


def event_record(event: dict, account: str, calendar: dict, defaults: list[int]) -> dict | None:
    if event.get("status") == "cancelled":
        return None
    if any(a.get("self") and a.get("responseStatus") == "declined" for a in event.get("attendees", [])):
        return None
    start, end = event.get("start", {}), event.get("end", {})
    reminders = event.get("reminders", {})
    minutes = defaults if reminders.get("useDefault", True) else popup_minutes(reminders.get("overrides", []))
    video = extract_meeting_url(event)
    birthday = event.get("eventType") == "birthday" or "#contacts@" in calendar.get("id", "")
    raw_attendees = [
        a for a in (event.get("attendees") or [])
        if isinstance(a, dict) and not a.get("resource") and a.get("responseStatus") != "declined"
    ]
    provider_label = meeting_provider_name(video)
    raw_location = (event.get("location") or "").strip()
    if raw_location and video and raw_location == video and provider_label:
        where_label = provider_label
    else:
        where_label = raw_location or provider_label or ("Video call" if video else "")
    return {
        "id": event["id"],
        "account": account,
        "calendarId": f"{account}:{calendar.get('id', '')}",
        "calendar": calendar.get("summaryOverride") or calendar.get("summary", ""),
        "color": calendar.get("backgroundColor", ""),
        "kind": "birthday" if birthday else "event",
        "title": event.get("summary") or "(No title)",
        "where": where_label,
        "allDay": "date" in start,
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "reminders": minutes,
        # Other people write events (invites): only web links are kept.
        "video": video,
        "link": sync.web_link(event.get("htmlLink", "")),
        # The invite's own id, so an email's invite can be matched to it.
        "uid": event.get("iCalUID", ""),
        # Your answer to it ("needsAction", "accepted", "tentative"), if invited.
        "response": next((a.get("responseStatus", "") for a in event.get("attendees", []) if a.get("self")), ""),
        "attendeeCount": len(raw_attendees),
    }


def sync_calendars() -> dict:
    import urllib.parse

    now = datetime.now().astimezone()
    window = {
        "timeMin": (now - timedelta(days=DAYS_BACK)).isoformat(),
        "timeMax": (now + timedelta(days=DAYS_AHEAD)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 2500,
    }
    events: list[dict] = []
    calendars: list[dict] = []
    for account in sync.load_accounts():
        token = sync.auth_token(account["id"])
        for calendar in paged(token, "/users/me/calendarList", {"minAccessRole": "reader"}):
            if calendar.get("hidden") or not calendar.get("selected", calendar.get("primary", False)):
                continue
            name = calendar.get("summaryOverride") or calendar.get("summary", "")
            calendars.append({
                "id": f"{account['id']}:{calendar['id']}",
                # Google names your main calendar after your address; show the account.
                "name": account["id"].capitalize() if name == account["email"] or "@" in name else name,
                "color": calendar.get("backgroundColor", ""),
                "account": account["id"],
                "email": account["email"],
                "source": "google",
            })
            defaults = popup_minutes(calendar.get("defaultReminders", []))
            path = f"/calendars/{urllib.parse.quote(calendar['id'], safe='')}/events"
            for event in paged(token, path, window):
                if record := event_record(event, account["id"], calendar, defaults):
                    events.append(record)
    calendar_dir().mkdir(parents=True, exist_ok=True)
    sync.write_private(
        calendar_dir() / "google.json", json.dumps({"synced": int(time.time()), "calendars": calendars, "events": events}) + "\n"
    )
    write_next_meeting_feed()
    return {"state": "ok", "calendars": len(calendars), "events": len(events), "synced": int(time.time())}


# Reading ------------------------------------------------------------------------


# Calendars on this PC: new ones take the next colour.
LOCAL_COLOURS = ["#9fa8da", "#f48fb1", "#80cbc4", "#ffcc80", "#ce93d8", "#a5d6a7", "#90caf9", "#ef9a9a"]
DEFAULT_LOCAL = {"id": "local:this-pc", "name": "On this PC", "color": LOCAL_COLOURS[0], "source": "local"}


def load_local() -> dict:
    try:
        data = json.loads((calendar_dir() / "local.json").read_text())
    except (FileNotFoundError, ValueError):
        data = {}
    data.setdefault("calendars", [])
    if not data["calendars"]:
        data["calendars"].append(dict(DEFAULT_LOCAL))
    data.setdefault("events", [])
    return data


def save_local(data: dict) -> None:
    calendar_dir().mkdir(parents=True, exist_ok=True)
    sync.write_private(calendar_dir() / "local.json", json.dumps(data, indent=1) + "\n")


def load_google() -> dict:
    try:
        return json.loads((calendar_dir() / "google.json").read_text())
    except (FileNotFoundError, ValueError):
        return {}


# Google keeps birthdays inside your main calendar; Courier shows them as their
# own calendar so they can be hidden on their own.
BIRTHDAYS = {"id": "birthdays", "name": "Birthdays", "color": "#80cbc4", "source": "google"}


def calendars(google: dict | None = None, local: dict | None = None) -> list[dict]:
    google = load_google() if google is None else google
    local = load_local() if local is None else local
    listed = list(google.get("calendars", []))
    if any(event.get("kind") == "birthday" for event in google.get("events", [])):
        listed.append(dict(BIRTHDAYS))
    return listed + [dict(c, source="local") for c in local["calendars"]]


def all_events(google: dict | None = None, local: dict | None = None) -> list[dict]:
    events = []
    google = load_google() if google is None else google
    for event in google.get("events", []):
        event.setdefault("calendarId", f"{event.get('account', '')}:{event.get('calendar', '')}")
        if event.get("kind") == "birthday":
            event.update(calendarId=BIRTHDAYS["id"], calendar=BIRTHDAYS["name"], color=BIRTHDAYS["color"])
        events.append(event)
    local = load_local() if local is None else local
    by_id = {c["id"]: c for c in local["calendars"]}
    for event in local["events"]:
        calendar = by_id.get(event.get("calendarId"), local["calendars"][0])
        events.append(dict(event, account="local", local=True, calendarId=calendar["id"], calendar=calendar["name"],
                           color=calendar["color"], kind=event.get("kind", "event")))
    for event in events:
        event.setdefault("reminders", [10])
    return events


def moment(value: str, all_day: bool) -> datetime:
    if all_day:
        return datetime.combine(date.fromisoformat(value), datetime.min.time()).astimezone()
    return datetime.fromisoformat(value).astimezone()


def clock(when: datetime) -> str:
    return when.strftime("%I:%M %p").lstrip("0").lower()


def day_title(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    return f"{day.strftime('%A')}, {day.day} {day.strftime('%B')}"


def until(start: datetime, now: datetime) -> str:
    minutes = int((start - now).total_seconds() // 60)
    if minutes <= 0:
        return "NOW"
    if minutes < 60:
        return f"IN {minutes} MIN"
    if start.date() == now.date():
        hours, rest = divmod(minutes, 60)
        return f"IN {hours} H {rest} MIN" if rest else f"IN {hours} H"
    return "TOMORROW" if start.date() == now.date() + timedelta(days=1) else start.strftime("%a").upper()


def agenda() -> dict:
    now = datetime.now().astimezone()
    today = now.date()
    rows = []
    for event in all_events():
        try:
            start, end = moment(event["start"], event.get("allDay", False)), moment(event["end"], event.get("allDay", False))
        except (KeyError, ValueError):
            continue
        rows.append((start, end, event))
    rows.sort(key=lambda row: (row[0], not row[2].get("allDay", False)))

    def item(start: datetime, end: datetime, event: dict) -> dict:
        all_day = event.get("allDay", False)
        minutes = event.get("reminders") or []
        return {
            "id": event.get("id", ""),
            "title": event.get("title", ""),
            "account": event.get("account", "local"),
            "calendar": event.get("calendar", ""),
            "color": event.get("color", ""),
            "where": event.get("where", ""),
            # Checked again on the way out: events saved before the check.
            "video": sync.web_link(event.get("video", "")),
            "link": sync.web_link(event.get("link", "")),
            "allDay": all_day,
            "start": "All day" if all_day else clock(start),
            "end": "" if all_day else clock(end),
            "past": end <= now,
            "reminder": f"Reminder {minutes[0]} min before" if minutes and minutes[0] < 60 else
                        (f"Reminder {minutes[0] // 60} h before" if minutes else ""),
        }

    def on(day: date) -> list[dict]:
        # All-day events end at the next midnight (exclusive).
        return [item(s, e, ev) for s, e, ev in rows if s.date() <= day and (e.date() > day or (s.date() == day and e.date() == day))]

    upcoming = []
    for offset in range(UPCOMING_DAYS):
        day = today + timedelta(days=offset)
        if events := on(day):
            upcoming.append({"day": day_title(day, today), "date": day.isoformat(), "events": events})

    next_up = next(((s, e, ev) for s, e, ev in rows if not ev.get("allDay") and e > now and s.date() <= today + timedelta(days=1)), None)
    month_start = today.replace(day=1)
    days_with_events = sorted({s.day for s, _, _ in rows if s.year == today.year and s.month == today.month})
    return {
        "today": on(today),
        "tomorrow": on(today + timedelta(days=1)),
        "upcoming": upcoming,
        "eventDays": days_with_events,
        "month": month_start.isoformat(),
        "upNext": (item(*next_up) | {"until": until(next_up[0], now)}) if next_up else None,
        "status": read_status(),
    }


def read_status() -> dict:
    try:
        data = json.loads(status_path().read_text())
    except (FileNotFoundError, ValueError):
        return {"state": "never"}
    if not isinstance(data, dict):
        return {"state": "never"}
    account = signed_out_account(data)
    if account and data.get("account") != account:
        return dict(data, account=account)
    return data


ACCOUNT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
REAUTH_CMD_RE = re.compile(r"(?:^|\s)courier-auth\s+add\s+([^\s]+)(?:\s+--calendar-write)?\s*\Z")


def valid_account_id(account: object) -> str:
    """Return a validated Courier account id matching courier_auth.ACCOUNT_ID, or ''."""
    if not isinstance(account, str):
        return ""
    value = account.strip()
    return value if ACCOUNT_ID_RE.fullmatch(value) else ""


def parse_reauth_account(message: object) -> str:
    """Safely extract a validated account id from a re-auth error message."""
    if not isinstance(message, str) or not message:
        return ""
    match = REAUTH_CMD_RE.search(message)
    if not match:
        return ""
    token = match.group(1)
    if token.endswith("."):
        token = token[:-1]
    return valid_account_id(token)


def signed_out_account(status: dict | None) -> str:
    """Return the validated account id requiring re-authentication, or ''."""
    if not isinstance(status, dict):
        return ""
    direct = valid_account_id(status.get("account", ""))
    if direct:
        return direct
    return parse_reauth_account(status.get("message", ""))


def _auth_command() -> str:
    import shutil

    found = shutil.which("courier-auth")
    if found:
        return found
    local = Path.home() / ".local/bin/courier-auth"
    if local.exists():
        return str(local)
    return str(sync.AUTH)


def _write_sync_status(status: dict) -> dict:
    out = dict(status)
    out["checked"] = int(time.time())
    sync.write_private(status_path(), json.dumps(out) + "\n")
    return out


def run_sync_status() -> dict:
    try:
        status = sync_calendars()
    except sync.SignedOut as expired:
        raw_account = str(expired.args[0]) if expired.args else ""
        account = valid_account_id(raw_account)
        status = {
            "state": "signed-out",
            "account": account,
            "message": f"Sign in again: courier-auth add {raw_account}",
        }
    except (CalendarError, sync.SyncError) as error:
        status = {"state": "error", "message": str(error), "action": getattr(error, "action", "")}
        account = parse_reauth_account(status["message"])
        if account:
            status["account"] = account
    return _write_sync_status(status)


def reauth_account(account: str, *, run_sync: bool = True) -> dict:
    """Re-authenticate an account via courier-auth add (browser OAuth flow),
    then optionally run a fresh calendar sync."""
    import ctypes
    import signal
    import subprocess

    clean = valid_account_id(account)
    if not clean:
        raise EventError("Invalid account name.")

    existing = next((a for a in sync.load_accounts() if a.get("id") == clean), None)
    email = str(existing.get("email", "")).strip() if isinstance(existing, dict) else ""
    cmd = [_auth_command(), "add", clean]
    if email and "@" in email and not email.startswith("-") and not any(ch.isspace() for ch in email):
        cmd.extend(["--email", email])

    def die_with_parent() -> None:
        # PR_SET_PDEATHSIG = 1: stop browser sign-in if parent exits or cancels.
        ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)

    auth = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=die_with_parent,
    )

    def cancel(signum, frame) -> None:
        auth.terminate()
        raise EventError("Sign-in cancelled.")

    previous_handler = signal.signal(signal.SIGTERM, cancel)
    try:
        out, err = auth.communicate()
    finally:
        signal.signal(signal.SIGTERM, previous_handler)

    if auth.returncode != 0:
        detail = (err or out).strip()
        raise EventError(detail.splitlines()[-1] if detail else "Sign-in didn't finish.")

    updated = next((a for a in sync.load_accounts() if a.get("id") == clean), None)
    resolved_email = str(updated.get("email", email)).strip() if isinstance(updated, dict) else email
    result: dict = {"ok": True, "account": clean, "email": resolved_email}
    if run_sync:
        result["status"] = run_sync_status()
    return result


# Reminders ------------------------------------------------------------------------


def remind(now: datetime | None = None) -> list[str]:
    """Shows every reminder that came due in the last few minutes, once."""
    now = now or datetime.now().astimezone()
    fired_path = sync.state_dir() / "reminders-fired.json"
    try:
        fired = json.loads(fired_path.read_text())
    except (FileNotFoundError, ValueError):
        fired = {}
    shown = []
    for event in all_events():
        try:
            start = moment(event["start"], event.get("allDay", False))
        except (KeyError, ValueError):
            continue
        for minutes in event.get("reminders") or []:
            due = start - timedelta(minutes=int(minutes))
            key = f"{event.get('id')}|{event['start']}|{minutes}"
            if key in fired or not (due <= now < due + timedelta(seconds=LATE_GRACE)):
                continue
            fired[key] = int(now.timestamp())
            lead = int((start - now).total_seconds() // 60)
            when = "now" if lead <= 0 else (f"in {lead} min" if lead < 120 else f"at {clock(start)}")
            body = " · ".join(part for part in (when, event.get("where", "")) if part)
            if not os.environ.get("COURIER_NO_NOTIFY"):
                sync.desktop_notify(event.get("title", "Event"), body, "-a", "Junco", "-i", "appointment-soon", "-u", "critical")
            shown.append(event.get("title", ""))
    cutoff = now.timestamp() - 3 * 86400
    sync.write_private(fired_path, json.dumps({k: v for k, v in fired.items() if v > cutoff}) + "\n")
    write_next_meeting_feed(now=now, only_if_changed=True)
    return shown


# The month, week and day views ----------------------------------------------------


def last_day(start: datetime, end: datetime, all_day: bool) -> date:
    """The last calendar day an event covers (ends are exclusive)."""
    if all_day or (end.time() == datetime.min.time() and end.date() > start.date()):
        return (end - timedelta(days=1)).date() if end > start else start.date()
    return end.date()


def occurrence(event: dict, start: datetime, end: datetime) -> dict:
    all_day = event.get("allDay", False)
    video = extract_meeting_url(event)
    provider_label = meeting_provider_name(video)
    raw_where = (event.get("where") or "").strip()
    where = provider_label if (raw_where and video and raw_where == video and provider_label) else (raw_where or provider_label)
    return {
        "id": event.get("id", ""),
        "title": event.get("title", ""),
        "where": where,
        "video": video,
        "link": sync.web_link(event.get("link", "")),
        "notes": event.get("notes", ""),
        "calendarId": event.get("calendarId", ""),
        "calendar": event.get("calendar", ""),
        "color": event.get("color", ""),
        "kind": event.get("kind", "event"),
        "local": event.get("local", False),
        "allDay": all_day,
        "reminders": event.get("reminders") or [],
        "start": event.get("start", ""),
        "end": event.get("end", ""),
        "uid": event.get("uid", ""),
        "response": event.get("response", ""),
        "attendeeCount": int(event.get("attendeeCount", 0) or 0),
        "startDay": start.date().isoformat(),
        "endDay": last_day(start, end, all_day).isoformat(),
        "startMinutes": 0 if all_day else start.hour * 60 + start.minute,
        "endMinutes": 1440 if all_day else (1440 if end.date() > start.date() and end.time() == datetime.min.time() else end.hour * 60 + end.minute),
        "time": "All day" if all_day else f"{clock(start)} – {clock(end)}",
    }


def events_between(first: date, after_last: date, *, preloaded: list[dict] | None = None) -> list[dict]:
    """Every event touching the days first ≤ day < after_last, earliest first."""
    window_start = datetime.combine(first, datetime.min.time()).astimezone()
    window_end = datetime.combine(after_last, datetime.min.time()).astimezone()
    found = []
    for event in (all_events() if preloaded is None else preloaded):
        try:
            start = moment(event["start"], event.get("allDay", False))
            end = moment(event["end"], event.get("allDay", False))
        except (KeyError, ValueError):
            continue
        if start < window_end and (end > window_start or start >= window_start):
            found.append((start, not event.get("allDay", False), occurrence(event, start, end)))
    return [item for _, _, item in sorted(found, key=lambda row: (row[0], row[1]))]


def bootstrap(first: date, after_last: date, selected: date, today: date | None = None) -> dict:
    """Single-shot startup payload for the Calendar UI: reads google.json and
    local.json once and returns calendars, accounts, status, visible span
    events, selected-day events, today's events, and selected-day actionables."""
    today_day = today or date.today()
    google = load_google()
    local = load_local()
    loaded_events = all_events(google=google, local=local)
    span_events = events_between(first, after_last, preloaded=loaded_events)
    if first <= selected < after_last:
        sel_iso = selected.isoformat()
        around = [ev for ev in span_events if ev["startDay"] <= sel_iso <= ev["endDay"]]
    else:
        around = events_between(selected, selected + timedelta(days=1), preloaded=loaded_events)
    if today_day == selected:
        today_events = around
    elif first <= today_day < after_last:
        today_iso = today_day.isoformat()
        today_events = [ev for ev in span_events if ev["startDay"] <= today_iso <= ev["endDay"]]
    else:
        today_events = events_between(today_day, today_day + timedelta(days=1), preloaded=loaded_events)
    return {
        "calendars": calendars(google=google, local=local),
        "accounts": sync.load_accounts(),
        "status": read_status(),
        "events": span_events,
        "around": around,
        "todayEvents": today_events,
        "actionables": list_actionables(selected.isoformat()),
    }


# Events on this PC -------------------------------------------------------------------


class EventError(ValueError):
    pass


def checked_event(payload: dict, local: dict) -> dict:
    title = str(payload.get("title", "")).strip()
    if not title:
        raise EventError("An event needs a title.")
    all_day = bool(payload.get("allDay", False))
    try:
        start = moment(payload["start"], all_day)
        end = moment(payload["end"], all_day)
    except (KeyError, ValueError):
        raise EventError("An event needs a start and an end.") from None
    if end <= start:
        raise EventError("An event has to end after it starts.")
    calendar_id = payload.get("calendarId") or local["calendars"][0]["id"]
    if calendar_id not in {c["id"] for c in local["calendars"]}:
        raise EventError("Events can only be added to calendars on this PC.")
    reminders = sorted({int(m) for m in payload.get("reminders", [10]) if int(m) >= 0})
    return {
        "title": title,
        "where": str(payload.get("where", "")).strip(),
        "notes": str(payload.get("notes", "")).strip(),
        "allDay": all_day,
        "start": payload["start"],
        "end": payload["end"],
        "calendarId": calendar_id,
        "reminders": reminders,
    }


def add_event(payload: dict) -> dict:
    local = load_local()
    event = {"id": f"local-{int(time.time() * 1000)}"} | checked_event(payload, local)
    local["events"].append(event)
    save_local(local)
    write_next_meeting_feed()
    return event


def update_event(event_id: str, payload: dict) -> dict:
    local = load_local()
    for number, event in enumerate(local["events"]):
        if event["id"] == event_id:
            local["events"][number] = {"id": event_id} | checked_event(payload, local)
            save_local(local)
            write_next_meeting_feed()
            return local["events"][number]
    raise EventError("Only events on this PC can be edited here; open Google events in Google Calendar.")


def delete_event(event_id: str) -> dict:
    local = load_local()
    kept = [event for event in local["events"] if event["id"] != event_id]
    if len(kept) == len(local["events"]):
        raise EventError("Only events on this PC can be deleted here.")
    local["events"] = kept
    save_local(local)
    write_next_meeting_feed()
    return {"deleted": event_id}


def add_calendar(name: str) -> dict:
    local = load_local()
    name = name.strip()
    if not name:
        raise EventError("A calendar needs a name.")
    calendar = {
        "id": f"local:{int(time.time() * 1000)}",
        "name": name,
        "color": LOCAL_COLOURS[len(local["calendars"]) % len(LOCAL_COLOURS)],
    }
    local["calendars"].append(calendar)
    save_local(local)
    return calendar


# Actionables (SQLite) --------------------------------------------------------------


ACTIONABLES_MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS calendar_actionables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_date TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                event_uid TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_calendar_actionables_due_date
            ON calendar_actionables(due_date)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_calendar_actionables_open
            ON calendar_actionables(completed, due_date)
            """,
        ),
    ),
]


ACTIONABLES_SCHEMA_VERSION = 1


def open_actionables_db():
    """Open the local SQLite actionables store and apply any pending migrations."""
    import sqlite3

    path = actionables_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA temp_store = MEMORY")
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if user_version < ACTIONABLES_SCHEMA_VERSION:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            applied_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
            for version, statements in ACTIONABLES_MIGRATIONS:
                if version in applied:
                    continue
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, applied_at),
                )
            conn.execute(f"PRAGMA user_version = {ACTIONABLES_SCHEMA_VERSION}")
    return conn


def _actionable_row(row, today_str: str) -> dict:
    completed = bool(row["completed"])
    due_date = row["due_date"]
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "dueDate": due_date,
        "completed": completed,
        "completedAt": row["completed_at"] or "",
        "eventUid": row["event_uid"] or "",
        "createdAt": row["created_at"],
        "carryOver": bool(due_date < today_str and not completed),
    }


def list_actionables(day: str | None = None, *, include_carryover: bool = True, now: datetime | None = None) -> list[dict]:
    """List actionables for `day` (default: today). When viewing today, uncompleted
    actionables from earlier days surface with carryOver=True (and carry-overs
    checked off today remain visible as completed for the rest of today)."""
    current = (now or datetime.now().astimezone()).replace(microsecond=0)
    today_str = current.date().isoformat()
    target = day or today_str
    date.fromisoformat(target)
    conn = open_actionables_db()
    try:
        if target == today_str and include_carryover:
            rows = conn.execute(
                """
                SELECT id, title, due_date, completed, completed_at, event_uid, created_at
                FROM calendar_actionables
                WHERE due_date = ?
                   OR (due_date < ? AND completed = 0)
                   OR (due_date < ? AND completed = 1 AND substr(completed_at, 1, 10) = ?)
                ORDER BY completed ASC,
                         CASE WHEN due_date < ? AND completed = 0 THEN 0 ELSE 1 END ASC,
                         due_date ASC,
                         id ASC
                """,
                (target, today_str, today_str, today_str, today_str),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, title, due_date, completed, completed_at, event_uid, created_at
                FROM calendar_actionables
                WHERE due_date = ?
                ORDER BY completed ASC, id ASC
                """,
                (target,),
            ).fetchall()
        return [_actionable_row(row, today_str) for row in rows]
    finally:
        conn.close()


def add_actionable(
    title: str,
    due_date: str | None = None,
    event_uid: str = "",
    *,
    now: datetime | None = None,
) -> dict:
    clean_title = str(title or "").strip()
    if not clean_title:
        raise EventError("An actionable needs a title.")
    current = (now or datetime.now().astimezone()).replace(microsecond=0)
    today_str = current.date().isoformat()
    target = (due_date or today_str).strip()
    try:
        date.fromisoformat(target)
    except ValueError:
        raise EventError("Due date must be YYYY-MM-DD.") from None
    clean_uid = str(event_uid or "").strip() or None
    conn = open_actionables_db()
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO calendar_actionables (title, due_date, completed, completed_at, event_uid, created_at)
                VALUES (?, ?, 0, NULL, ?, ?)
                """,
                (clean_title, target, clean_uid, current.isoformat()),
            )
            row = conn.execute(
                "SELECT id, title, due_date, completed, completed_at, event_uid, created_at FROM calendar_actionables WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        created = _actionable_row(row, today_str)
    finally:
        conn.close()
    write_next_meeting_feed(now=current)
    return created


def toggle_actionable(
    actionable_id: int,
    completed: bool | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    current = (now or datetime.now().astimezone()).replace(microsecond=0)
    today_str = current.date().isoformat()
    conn = open_actionables_db()
    try:
        with conn:
            row = conn.execute(
                "SELECT id, title, due_date, completed, completed_at, event_uid, created_at FROM calendar_actionables WHERE id = ?",
                (int(actionable_id),),
            ).fetchone()
            if row is None:
                raise EventError(f"Actionable {actionable_id} not found.")
            new_completed = (not bool(row["completed"])) if completed is None else bool(completed)
            completed_at = current.isoformat() if new_completed else None
            conn.execute(
                "UPDATE calendar_actionables SET completed = ?, completed_at = ? WHERE id = ?",
                (1 if new_completed else 0, completed_at, int(actionable_id)),
            )
            updated_row = conn.execute(
                "SELECT id, title, due_date, completed, completed_at, event_uid, created_at FROM calendar_actionables WHERE id = ?",
                (int(actionable_id),),
            ).fetchone()
        updated = _actionable_row(updated_row, today_str)
    finally:
        conn.close()
    write_next_meeting_feed(now=current)
    return updated


def delete_actionable(actionable_id: int, *, now: datetime | None = None) -> dict:
    current = (now or datetime.now().astimezone()).replace(microsecond=0)
    conn = open_actionables_db()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM calendar_actionables WHERE id = ?", (int(actionable_id),))
            if cursor.rowcount == 0:
                raise EventError(f"Actionable {actionable_id} not found.")
    finally:
        conn.close()
    write_next_meeting_feed(now=current)
    return {"deleted": int(actionable_id)}


# Zero-polling next-meeting state feed ---------------------------------------------


def _hidden_calendar_ids() -> set[str]:
    try:
        saved = json.loads((sync.state_dir() / "calendar-view.json").read_text())
        return {str(cid) for cid in (saved.get("hidden") or [])}
    except (FileNotFoundError, ValueError, TypeError):
        return set()


def _dedupe_visible_events(events: list[dict]) -> list[dict]:
    hidden = _hidden_calendar_ids()
    seen: set[tuple[str, str, str]] = set()
    kept: list[dict] = []
    for event in events:
        if event.get("calendarId", "") in hidden:
            continue
        key = (str(event.get("title", "")).strip().lower(), str(event.get("start", "")), str(event.get("end", "")))
        if key in seen:
            continue
        seen.add(key)
        kept.append(event)
    return kept


def build_next_meeting_feed(now: datetime | None = None) -> dict:
    """Build Today's focused meeting & actionables feed for top-bar widgets.
    Strictly scoped to today's date (never leaks tomorrow or next month)."""
    current = (now or datetime.now().astimezone()).replace(microsecond=0)
    today = current.date()
    today_str = today.isoformat()

    today_rows: list[tuple[datetime, datetime, dict, dict]] = []
    for event in _dedupe_visible_events(all_events()):
        all_day = bool(event.get("allDay", False))
        try:
            start_dt = moment(event["start"], all_day)
            end_dt = moment(event["end"], all_day)
        except (KeyError, ValueError):
            continue
        start_day = start_dt.date()
        end_day = last_day(start_dt, end_dt, all_day)
        if not (start_day <= today <= end_day):
            continue
        join_url = extract_meeting_url(event)
        provider_label = meeting_provider_name(join_url)
        raw_where = (event.get("where") or "").strip()
        location = provider_label if (raw_where and join_url and raw_where == join_url and provider_label) else (raw_where or provider_label)
        item = {
            "id": event.get("id", ""),
            "title": event.get("title", ""),
            "startIso": event.get("start", "") if all_day else start_dt.isoformat(),
            "endIso": event.get("end", "") if all_day else end_dt.isoformat(),
            "allDay": all_day,
            "joinUrl": join_url,
            "location": location,
            "calendarName": event.get("calendar", ""),
            "calendarColor": event.get("color", ""),
        }
        today_rows.append((start_dt, end_dt, event, item))

    today_rows.sort(key=lambda row: (row[0], not bool(row[2].get("allDay", False)), row[1]))
    today_events = [row[3] for row in today_rows]
    today_meeting_count = sum(1 for row in today_rows if not bool(row[2].get("allDay", False)))

    # Next upcoming or currently live timed meeting today.
    next_candidates = [
        (start_dt, end_dt, item)
        for start_dt, end_dt, event, item in today_rows
        if not bool(event.get("allDay", False)) and end_dt > current
    ]
    next_meeting: dict | None = None
    if next_candidates:
        next_start, next_end, base_item = next_candidates[0]
        next_meeting = {
            "id": base_item["id"],
            "title": base_item["title"],
            "startIso": base_item["startIso"],
            "endIso": base_item["endIso"],
            "allDay": False,
            "inProgress": bool(next_start <= current < next_end),
            "joinUrl": base_item["joinUrl"],
            "location": base_item["location"],
            "calendarName": base_item["calendarName"],
            "calendarColor": base_item["calendarColor"],
        }

    today_actionables = list_actionables(today_str, include_carryover=True, now=current)
    feed_actionables = [
        {
            "id": item["id"],
            "title": item["title"],
            "dueDate": item["dueDate"],
            "completed": item["completed"],
            "carryOver": item["carryOver"],
        }
        for item in today_actionables
    ]
    open_actionables_count = sum(1 for item in feed_actionables if not item["completed"])

    return {
        "updatedAt": current.isoformat(),
        "todayDate": today_str,
        "todayMeetingCount": today_meeting_count,
        "openActionablesCount": open_actionables_count,
        "nextMeeting": next_meeting,
        "todayEvents": today_events,
        "actionables": feed_actionables,
    }


def write_next_meeting_feed(now: datetime | None = None, *, only_if_changed: bool = False) -> dict:
    """Atomically write $XDG_STATE_HOME/courier/next-meeting.json."""
    payload = build_next_meeting_feed(now=now)
    target = next_meeting_path()
    if only_if_changed and target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            if {k: v for k, v in existing.items() if k != "updatedAt"} == {
                k: v for k, v in payload.items() if k != "updatedAt"
            }:
                return payload
        except (OSError, ValueError, TypeError):
            pass
    write_atomic_private(target, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="courier-calendar", description="Junco's calendar.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="copy Google calendars to this PC")
    commands.add_parser("agenda", help="today, tomorrow and the next 30 days, for the app")
    commands.add_parser("remind", help="notify about reminders that are due")
    commands.add_parser("calendars", help="every calendar, Google's and this PC's")
    span = commands.add_parser("range", help="events touching FIRST ≤ day < AFTER (YYYY-MM-DD)")
    span.add_argument("first")
    span.add_argument("after")
    boot = commands.add_parser("bootstrap", help="single-shot startup payload for the Calendar UI")
    boot.add_argument("first")
    boot.add_argument("after")
    boot.add_argument("selected")
    boot.add_argument("--today", default="")
    commands.add_parser("add", help="add an event on this PC").add_argument("json")
    editor = commands.add_parser("update", help="change an event on this PC")
    editor.add_argument("id")
    editor.add_argument("json")
    commands.add_parser("delete", help="delete an event on this PC").add_argument("id")
    commands.add_parser("add-calendar", help="a new calendar on this PC").add_argument("name")
    reauth_cmd = commands.add_parser("reauth", help="sign a Google account in again and sync calendars")
    reauth_cmd.add_argument("account")
    reauth_cmd.add_argument("--no-sync", action="store_true", help="skip syncing calendars after sign-in")

    next_cmd = commands.add_parser("next", help="next meeting and today's actionables feed")
    next_cmd.add_argument("--json", action="store_true", help="output JSON (default)")
    next_cmd.add_argument("--write", action="store_true", help="also refresh next-meeting.json")

    act = commands.add_parser("actionables", help="manage Today's actionables checklist")
    act_sub = act.add_subparsers(dest="actionables_command", required=True)
    act_list = act_sub.add_parser("list", help="list actionables for a day (default: today)")
    act_list.add_argument("--day", default=None, help="YYYY-MM-DD")
    act_add = act_sub.add_parser("add", help="add an actionable")
    act_add.add_argument("title")
    act_add.add_argument("--due", default=None, help="YYYY-MM-DD (default: today)")
    act_add.add_argument("--event-uid", default="", help="optional meeting UID link")
    act_toggle = act_sub.add_parser("toggle", help="toggle or set actionable completion")
    act_toggle.add_argument("id", type=int)
    act_toggle.add_argument("--completed", choices=["true", "false"], default=None)
    act_del = act_sub.add_parser("delete", help="delete an actionable")
    act_del.add_argument("id", type=int)

    args = parser.parse_args(argv)

    if args.command == "sync":
        status = run_sync_status()
        print(json.dumps(status))
        return 0 if status["state"] == "ok" else 1
    if args.command == "remind":
        remind()
        return 0
    try:
        if args.command == "agenda":
            result = agenda()
        elif args.command == "calendars":
            result = {"calendars": calendars(), "status": read_status(), "accounts": sync.load_accounts()}
        elif args.command == "range":
            result = events_between(date.fromisoformat(args.first), date.fromisoformat(args.after))
        elif args.command == "bootstrap":
            result = bootstrap(
                date.fromisoformat(args.first),
                date.fromisoformat(args.after),
                date.fromisoformat(args.selected),
                date.fromisoformat(args.today) if args.today else None,
            )
        elif args.command == "add":
            result = add_event(json.loads(args.json))
        elif args.command == "update":
            result = update_event(args.id, json.loads(args.json))
        elif args.command == "delete":
            result = delete_event(args.id)
        elif args.command == "add-calendar":
            result = add_calendar(args.name)
        elif args.command == "reauth":
            result = reauth_account(args.account, run_sync=not args.no_sync)
        elif args.command == "next":
            result = write_next_meeting_feed() if args.write else build_next_meeting_feed()
        elif args.command == "actionables":
            if args.actionables_command == "list":
                result = list_actionables(args.day)
            elif args.actionables_command == "add":
                result = add_actionable(args.title, args.due, args.event_uid)
            elif args.actionables_command == "toggle":
                flag = None if args.completed is None else (args.completed == "true")
                result = toggle_actionable(args.id, flag)
            else:
                result = delete_actionable(args.id)
        else:
            raise ValueError(f"Unknown command: {args.command}")
    except (EventError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
