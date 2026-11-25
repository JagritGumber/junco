#!/usr/bin/env python3
"""Courier's calendar: every Google calendar copied to this PC, plus events
kept only here, with desktop reminders.

    courier-calendar sync      copy each account's calendars (7 days back, 120 ahead)
    courier-calendar agenda    JSON for the app: today, tomorrow, upcoming days, the month
    courier-calendar remind    notify about reminders that are due (run every minute)

Google events land in ~/.local/share/courier/calendar/google.json; events
made on this PC live in local.json beside it. Read-only towards Google.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
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


# Google ------------------------------------------------------------------------


def api_get(token: str, path: str, params: dict) -> dict:
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
    video = event.get("hangoutLink") or next(
        (p.get("uri") for p in event.get("conferenceData", {}).get("entryPoints", []) if p.get("entryPointType") == "video"), ""
    )
    birthday = event.get("eventType") == "birthday" or "#contacts@" in calendar.get("id", "")
    return {
        "id": event["id"],
        "account": account,
        "calendarId": f"{account}:{calendar.get('id', '')}",
        "calendar": calendar.get("summaryOverride") or calendar.get("summary", ""),
        "color": calendar.get("backgroundColor", ""),
        "kind": "birthday" if birthday else "event",
        "title": event.get("summary") or "(No title)",
        "where": event.get("location") or ("Google Meet" if video else ""),
        "allDay": "date" in start,
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "reminders": minutes,
        # Other people write events (invites): only web links are kept.
        "video": sync.web_link(video),
        "link": sync.web_link(event.get("htmlLink", "")),
        # The invite's own id, so an email's invite can be matched to it.
        "uid": event.get("iCalUID", ""),
    }


def sync_calendars() -> dict:
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


def calendars() -> list[dict]:
    google = load_google()
    listed = list(google.get("calendars", []))
    if any(event.get("kind") == "birthday" for event in google.get("events", [])):
        listed.append(dict(BIRTHDAYS))
    return listed + [dict(c, source="local") for c in load_local()["calendars"]]


def all_events() -> list[dict]:
    events = []
    for event in load_google().get("events", []):
        event.setdefault("calendarId", f"{event.get('account', '')}:{event.get('calendar', '')}")
        if event.get("kind") == "birthday":
            event.update(calendarId=BIRTHDAYS["id"], calendar=BIRTHDAYS["name"], color=BIRTHDAYS["color"])
        events.append(event)
    local = load_local()
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
        return json.loads(status_path().read_text())
    except (FileNotFoundError, ValueError):
        return {"state": "never"}


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
    return shown


# The month, week and day views ----------------------------------------------------


def last_day(start: datetime, end: datetime, all_day: bool) -> date:
    """The last calendar day an event covers (ends are exclusive)."""
    if all_day or (end.time() == datetime.min.time() and end.date() > start.date()):
        return (end - timedelta(days=1)).date() if end > start else start.date()
    return end.date()


def occurrence(event: dict, start: datetime, end: datetime) -> dict:
    all_day = event.get("allDay", False)
    return {
        "id": event.get("id", ""),
        "title": event.get("title", ""),
        "where": event.get("where", ""),
        "video": sync.web_link(event.get("video", "")),
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
        "startDay": start.date().isoformat(),
        "endDay": last_day(start, end, all_day).isoformat(),
        "startMinutes": 0 if all_day else start.hour * 60 + start.minute,
        "endMinutes": 1440 if all_day else (1440 if end.date() > start.date() and end.time() == datetime.min.time() else end.hour * 60 + end.minute),
        "time": "All day" if all_day else f"{clock(start)} – {clock(end)}",
    }


def events_between(first: date, after_last: date) -> list[dict]:
    """Every event touching the days first ≤ day < after_last, earliest first."""
    window_start = datetime.combine(first, datetime.min.time()).astimezone()
    window_end = datetime.combine(after_last, datetime.min.time()).astimezone()
    found = []
    for event in all_events():
        try:
            start = moment(event["start"], event.get("allDay", False))
            end = moment(event["end"], event.get("allDay", False))
        except (KeyError, ValueError):
            continue
        if start < window_end and (end > window_start or start >= window_start):
            found.append((start, not event.get("allDay", False), occurrence(event, start, end)))
    return [item for _, _, item in sorted(found, key=lambda row: (row[0], row[1]))]


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
    return event


def update_event(event_id: str, payload: dict) -> dict:
    local = load_local()
    for number, event in enumerate(local["events"]):
        if event["id"] == event_id:
            local["events"][number] = {"id": event_id} | checked_event(payload, local)
            save_local(local)
            return local["events"][number]
    raise EventError("Only events on this PC can be edited here; open Google events in Google Calendar.")


def delete_event(event_id: str) -> dict:
    local = load_local()
    kept = [event for event in local["events"] if event["id"] != event_id]
    if len(kept) == len(local["events"]):
        raise EventError("Only events on this PC can be deleted here.")
    local["events"] = kept
    save_local(local)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="courier-calendar", description="Junco's calendar.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="copy Google calendars to this PC")
    commands.add_parser("agenda", help="today, tomorrow and the next 30 days, for the app")
    commands.add_parser("remind", help="notify about reminders that are due")
    commands.add_parser("calendars", help="every calendar, Google's and this PC's")
    span = commands.add_parser("range", help="events touching FIRST ≤ day < AFTER (YYYY-MM-DD)")
    span.add_argument("first")
    span.add_argument("after")
    commands.add_parser("add", help="add an event on this PC").add_argument("json")
    editor = commands.add_parser("update", help="change an event on this PC")
    editor.add_argument("id")
    editor.add_argument("json")
    commands.add_parser("delete", help="delete an event on this PC").add_argument("id")
    commands.add_parser("add-calendar", help="a new calendar on this PC").add_argument("name")
    args = parser.parse_args(argv)

    if args.command == "sync":
        try:
            status = sync_calendars()
        except sync.SignedOut as expired:
            status = {"state": "signed-out", "message": f"Sign in again: courier-auth add {expired.args[0]}"}
        except (CalendarError, sync.SyncError) as error:
            status = {"state": "error", "message": str(error), "action": getattr(error, "action", "")}
        status["checked"] = int(time.time())
        sync.write_private(status_path(), json.dumps(status) + "\n")
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
        elif args.command == "add":
            result = add_event(json.loads(args.json))
        elif args.command == "update":
            result = update_event(args.id, json.loads(args.json))
        elif args.command == "delete":
            result = delete_event(args.id)
        else:
            result = add_calendar(args.name)
    except (EventError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
