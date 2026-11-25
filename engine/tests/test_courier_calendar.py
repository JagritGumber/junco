"""courier-calendar against a fake Google Calendar API.

Run from the engine folder:  python3 -m unittest discover tests
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import unittest.mock
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE.parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync = load("courier_sync")
calendar = load("courier_calendar")
calendar.sync = sync


class FakeCalendar:
    def __init__(self) -> None:
        now = datetime.now().astimezone().replace(second=0, microsecond=0)
        self.meeting_start = now + timedelta(minutes=40)
        tomorrow = (now + timedelta(days=1)).date()
        self.disabled = False
        self.calendars = [
            {"id": "me@example.com", "summary": "me@example.com", "primary": True, "selected": True, "backgroundColor": "#7986cb",
             "defaultReminders": [{"method": "popup", "minutes": 30}]},
            {"id": "holidays#x", "summary": "Holidays", "selected": False},
        ]
        self.events = [
            {"id": "standup", "summary": "Standup", "status": "confirmed", "hangoutLink": "https://meet.google.com/abc",
             "start": {"dateTime": self.meeting_start.isoformat()}, "end": {"dateTime": (self.meeting_start + timedelta(minutes=30)).isoformat()},
             "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}, {"method": "email", "minutes": 60}]}},
            {"id": "trip", "summary": "Trip", "start": {"date": tomorrow.isoformat()}, "end": {"date": (tomorrow + timedelta(days=1)).isoformat()},
             "reminders": {"useDefault": True}},
            {"id": "cake", "summary": "Deval's birthday", "eventType": "birthday", "start": {"date": tomorrow.isoformat()},
             "end": {"date": (tomorrow + timedelta(days=1)).isoformat()}},
            {"id": "gone", "summary": "Cancelled", "status": "cancelled", "start": {"date": tomorrow.isoformat()}, "end": {"date": tomorrow.isoformat()}},
            {"id": "no", "summary": "Declined", "attendees": [{"self": True, "responseStatus": "declined"}],
             "start": {"dateTime": self.meeting_start.isoformat()}, "end": {"dateTime": self.meeting_start.isoformat()}},
        ]
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = urllib.parse.urlsplit(self.path).path
                if fake.disabled:
                    status, body = 403, {"error": {"code": 403, "message": "Google Calendar API has not been used in project 1 before or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview?project=1 then retry."}}
                elif path.endswith("/calendarList"):
                    status, body = 200, {"items": fake.calendars}
                elif path == "/calendars/me%40example.com/events":
                    status, body = 200, {"items": fake.events}
                else:
                    status, body = 404, {"error": {"message": f"unexpected {path}"}}
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


class CourierCalendarTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        root = Path(self.home.name)
        self.env = unittest.mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"), "COURIER_NO_NOTIFY": "1",
        })
        self.env.start()
        (root / "config" / "courier").mkdir(parents=True)
        (root / "config" / "courier" / "accounts.json").write_text(json.dumps({"accounts": [{"id": "personal", "email": "me@example.com"}]}))
        self.google = FakeCalendar()
        self.patches = [
            unittest.mock.patch.object(calendar, "API", self.google.url),
            unittest.mock.patch.object(sync, "auth_token", lambda account: "token"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in self.patches:
            patch.stop()
        self.env.stop()
        self.google.server.shutdown()
        self.google.server.server_close()
        self.home.cleanup()

    def test_sync_keeps_what_you_see_in_google_calendar(self) -> None:
        self.assertEqual(calendar.main(["sync"]), 0)
        events = {e["id"]: e for e in calendar.all_events()}
        self.assertEqual(set(events), {"standup", "trip", "cake"})  # cancelled, declined and hidden calendars are left out
        self.assertEqual(events["standup"]["reminders"], [10])  # only pop-up reminders
        self.assertEqual(events["trip"]["reminders"], [30])  # the calendar's default
        self.assertEqual(events["standup"]["where"], "Google Meet")
        self.assertTrue(events["trip"]["allDay"])

    def test_agenda(self) -> None:
        calendar.main(["sync"])
        agenda = calendar.agenda()
        self.assertEqual(agenda["upNext"]["title"], "Standup")
        self.assertTrue(agenda["upNext"]["until"].startswith("IN "))
        titles_tomorrow = [e["title"] for e in agenda["tomorrow"]]
        self.assertIn("Trip", titles_tomorrow)
        self.assertEqual(next(e for e in agenda["tomorrow"] if e["title"] == "Trip")["start"], "All day")
        self.assertEqual(agenda["status"]["state"], "ok")

    def test_reminder_fires_once_when_due(self) -> None:
        calendar.main(["sync"])
        due = self.google.meeting_start - timedelta(minutes=10)
        self.assertEqual(calendar.remind(due - timedelta(minutes=1)), [])
        self.assertEqual(calendar.remind(due + timedelta(seconds=20)), ["Standup"])
        self.assertEqual(calendar.remind(due + timedelta(seconds=80)), [])

    def test_a_reminder_title_is_never_an_option_or_markup(self) -> None:
        self.google.events[0]["summary"] = "-u low <img src=https://t.example/p.png>"
        calendar.main(["sync"])
        due = self.google.meeting_start - timedelta(minutes=10)
        calls = []
        with unittest.mock.patch.dict(os.environ, {"COURIER_NO_NOTIFY": ""}), \
                unittest.mock.patch("subprocess.run", side_effect=lambda args, **kwargs: calls.append(list(args))):
            calendar.remind(due + timedelta(seconds=20))
        [args] = [args for args in calls if args and args[0] == "notify-send"]
        self.assertIn("--", args)
        self.assertEqual(args[args.index("--") + 1], "-u low \u2039img src=https://t.example/p.png\u203a")

    def test_calendars_and_the_month_range(self) -> None:
        calendar.main(["sync"])
        names = {c["name"]: c for c in calendar.calendars()}
        self.assertEqual(set(names), {"Personal", "Birthdays", "On this PC"})  # main calendar named after the account
        tomorrow = (datetime.now() + timedelta(days=1)).date()
        events = calendar.events_between(tomorrow, tomorrow + timedelta(days=1))
        cake = next(e for e in events if e["title"] == "Deval's birthday")
        self.assertEqual((cake["calendarId"], cake["kind"], cake["time"]), ("birthdays", "birthday", "All day"))
        self.assertEqual((cake["startDay"], cake["endDay"]), (tomorrow.isoformat(), tomorrow.isoformat()))

    def test_events_on_this_pc(self) -> None:
        start = (datetime.now().astimezone() + timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
        made = calendar.add_event({"title": "Dentist", "start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat(),
                                   "where": "Bandra", "reminders": [60]})
        [found] = [e for e in calendar.events_between(start.date(), start.date() + timedelta(days=1)) if e["id"] == made["id"]]
        self.assertEqual((found["local"], found["startMinutes"], found["endMinutes"], found["calendar"]), (True, 900, 960, "On this PC"))
        calendar.update_event(made["id"], made | {"title": "Dentist (moved)"})
        self.assertEqual(calendar.load_local()["events"][0]["title"], "Dentist (moved)")
        with self.assertRaises(calendar.EventError):
            calendar.update_event("standup", {"title": "x", "start": start.isoformat(), "end": start.isoformat()})
        with self.assertRaises(calendar.EventError):
            calendar.add_event({"title": "Backwards", "start": start.isoformat(), "end": (start - timedelta(hours=1)).isoformat()})
        work = calendar.add_calendar("Work")
        self.assertEqual([c["name"] for c in calendar.load_local()["calendars"]], ["On this PC", "Work"])
        self.assertNotEqual(work["color"], calendar.load_local()["calendars"][0]["color"])
        calendar.delete_event(made["id"])
        self.assertEqual(calendar.load_local()["events"], [])

    def test_api_turned_off_says_how_to_fix_it(self) -> None:
        self.google.disabled = True
        self.assertEqual(calendar.main(["sync"]), 1)
        status = calendar.read_status()
        self.assertEqual(status["state"], "error")
        self.assertIn("Turn on the Google Calendar API", status["message"])
        self.assertTrue(status["action"].startswith("https://console.developers.google.com/apis/api/calendar-json"))


class EventLinkTest(unittest.TestCase):
    """An event's Join and Open links reach the app only as web links:
    other people write events (invites), and the app hands these links to
    Qt.openUrlExternally."""

    CALENDAR = {"id": "me@example.com", "summary": "me@example.com"}
    BASE = {"id": "e1", "summary": "Review", "start": {"dateTime": "2026-11-24T10:00:00+05:30"},
            "end": {"dateTime": "2026-11-24T11:00:00+05:30"}}
    BAD = ("file:///etc/passwd", "javascript:alert(1)", "smb://host/share", "steam://run/10",
           "https://user:pw@evil.example/j", "data:text/html,hi", "https:///no-host")

    def record(self, **fields) -> dict:
        return calendar.event_record(dict(self.BASE, **fields), "personal", self.CALENDAR, [])

    def test_only_web_links_are_kept_from_google(self) -> None:
        for bad in self.BAD:
            event = self.record(hangoutLink=bad, htmlLink=bad)
            self.assertEqual((event["video"], event["link"]), ("", ""), bad)
        event = self.record(conferenceData={"entryPoints": [{"entryPointType": "video", "uri": "x-app://join/1"}]},
                            htmlLink="https://www.google.com/calendar/event?eid=1")
        self.assertEqual((event["video"], event["link"]), ("", "https://www.google.com/calendar/event?eid=1"))
        self.assertEqual(self.record(hangoutLink="https://meet.google.com/abc-defg-hij")["video"], "https://meet.google.com/abc-defg-hij")

    def test_events_saved_before_the_check_are_checked_on_the_way_out(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        with unittest.mock.patch.dict(os.environ, {"XDG_DATA_HOME": home.name, "XDG_STATE_HOME": home.name,
                                                   "XDG_CONFIG_HOME": home.name, "XDG_CACHE_HOME": home.name}):
            folder = calendar.calendar_dir()
            folder.mkdir(parents=True, exist_ok=True)
            start = datetime.now().astimezone().replace(microsecond=0) + timedelta(hours=1)
            saved = {"id": "old", "account": "personal", "calendarId": "personal:me@example.com", "calendar": "me",
                     "title": "Old invite", "start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat(),
                     "allDay": False, "reminders": [], "video": "file:///home/someone/.ssh", "link": "smb://evil.example/x"}
            (folder / "google.json").write_text(json.dumps({"calendars": [], "events": [saved]}))
            between = calendar.events_between(start.date(), start.date() + timedelta(days=1))
            agenda = calendar.agenda()
        self.assertEqual([(e["video"], e["link"]) for e in between], [("", "")])
        shown = [e for section in agenda.values() if isinstance(section, list) for e in section if isinstance(e, dict) and e.get("title") == "Old invite"]
        self.assertTrue(shown)
        self.assertEqual({(e["video"], e["link"]) for e in shown}, {("", "")})


if __name__ == "__main__":
    unittest.main()
