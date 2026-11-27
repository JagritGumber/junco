"""courier-calendar against a fake Google Calendar API.

Run from the engine folder:  python3 -m unittest discover tests
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import sqlite3
import stat
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
import urllib.parse
from datetime import datetime, timedelta, timezone
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
        self.read_only = False
        self.patches: list[tuple[str, str, dict]] = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def reply(self, status: int, body: dict) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_PATCH(self) -> None:
                parts = urllib.parse.urlsplit(self.path)
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                fake.patches.append((parts.path, parts.query, body))
                if fake.read_only:
                    self.reply(403, {"error": {"code": 403, "message": "Request had insufficient authentication scopes.",
                                               "errors": [{"reason": "insufficientPermissions"}], "status": "PERMISSION_DENIED"}})
                else:
                    self.reply(200, {"id": parts.path.rsplit("/", 1)[-1], **body})

            def do_GET(self) -> None:
                path = urllib.parse.urlsplit(self.path).path
                one = next((e for e in fake.events if path == f"/calendars/me%40example.com/events/{e['id']}"), None)
                if one is not None:
                    self.reply(200, one)
                    return
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


class FakeGoogle(unittest.TestCase):
    """A temporary home and the fake Google Calendar (no tests of its own)."""

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


class CourierCalendarTest(FakeGoogle):
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


class AnsweringInvites(FakeGoogle):
    """Accept, Maybe and Decline from the notification dock: his own answer
    on the event the invite put on his calendar, nothing else, only when
    asked. Against the fake Google Calendar on this machine only."""

    def setUp(self) -> None:
        super().setUp()
        start = self.google.meeting_start + timedelta(days=1)
        self.google.events.append({
            "id": "inv1", "iCalUID": "u-1@google.com", "summary": "Design review", "status": "confirmed",
            "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + timedelta(minutes=45)).isoformat()},
            "organizer": {"email": "priya@example.com"},
            "attendees": [{"email": "me@example.com", "self": True, "responseStatus": "needsAction"},
                          {"email": "priya@example.com", "organizer": True, "responseStatus": "accepted"}]})
        self.assertEqual(calendar.main(["sync"]), 0)
        self.invite = {"uid": "u-1@google.com", "account": "personal", "start": start.isoformat(),
                       "organizer": {"name": "Priya", "email": "Priya@example.com"}}

    def test_his_answer_goes_on_the_event(self) -> None:
        mine = next(e for e in calendar.all_events() if e["id"] == "inv1")
        self.assertEqual((mine["uid"], mine["response"]), ("u-1@google.com", "needsAction"))
        self.assertEqual(calendar.respond(self.invite, "accept"), "You said yes")
        [(path, query, body)] = self.google.patches
        self.assertEqual(path, "/calendars/me%40example.com/events/inv1")
        self.assertEqual(urllib.parse.parse_qs(query), {"sendUpdates": ["all"]})  # Google tells the organiser
        self.assertEqual(body, {"attendees": [{"email": "me@example.com", "self": True, "responseStatus": "accepted"},
                                              {"email": "priya@example.com", "organizer": True, "responseStatus": "accepted"}]})
        self.assertEqual(calendar.respond(self.invite, "maybe"), "You said maybe")
        self.assertEqual(self.google.patches[-1][2]["attendees"][0]["responseStatus"], "tentative")
        self.assertEqual(calendar.respond(self.invite, "decline"), "You said no")

    def test_read_only_permission_says_how_to_widen_it(self) -> None:
        self.google.read_only = True
        with self.assertRaises(calendar.CalendarError) as caught:
            calendar.respond(self.invite, "accept")
        self.assertIn("courier-auth add <account> --calendar-write", str(caught.exception))

    def test_dry_run_and_unknown_invites_change_nothing(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"COURIER_CALENDAR_DRY_RUN": "1"}):
            self.assertTrue(calendar.respond(self.invite, "accept").startswith("dry run: accepted"))
        with self.assertRaises(calendar.CalendarError):
            calendar.respond(dict(self.invite, uid="not-on-the-calendar"), "accept")
        with self.assertRaises(calendar.CalendarError):
            calendar.respond(dict(self.invite, account="work"), "accept")  # another account's
        with self.assertRaises(calendar.CalendarError):
            calendar.respond(dict(self.invite, start=(self.google.meeting_start + timedelta(days=2)).isoformat()), "accept")  # another time
        self.assertEqual(self.google.patches, [])

    def test_an_invite_reusing_a_meetings_id_answers_nothing(self) -> None:
        # Someone else's invitation, with the id (and time) of his real meeting: its organiser isn't the meeting's.
        with self.assertRaises(calendar.CalendarError) as caught:
            calendar.respond(dict(self.invite, organizer={"email": "mallory@evil.example"}), "decline")
        self.assertIn("doesn't match", str(caught.exception))
        self.assertEqual(self.google.patches, [])


IST = timezone(timedelta(hours=5, minutes=30))


class MeetingLinkExtractionTest(unittest.TestCase):
    """Auto-extraction of Meet, Zoom, Teams, Slack Huddle, Jitsi and Webex links
    across hangoutLink, conferenceData, location and description/notes, while
    rejecting untrusted or spoofed URLs."""

    CALENDAR = {"id": "work@example.com", "summary": "Work", "backgroundColor": "#ff6b9d"}
    BASE = {
        "id": "m1",
        "summary": "Sync",
        "start": {"dateTime": "2026-11-27T10:00:00+05:30"},
        "end": {"dateTime": "2026-11-27T10:30:00+05:30"},
    }

    def record(self, **fields) -> dict:
        return calendar.event_record(dict(self.BASE, **fields), "work", self.CALENDAR, [])

    def test_extracts_all_supported_providers_from_location_and_description(self) -> None:
        cases = [
            ("Google Meet", {"hangoutLink": "https://meet.google.com/abc-defg-hij"}, "https://meet.google.com/abc-defg-hij"),
            ("Google Meet", {"conferenceData": {"entryPoints": [
                {"entryPointType": "phone", "uri": "tel:+12345"},
                {"entryPointType": "video", "uri": "https://meet.google.com/xyz-mnop-qrs"},
            ]}}, "https://meet.google.com/xyz-mnop-qrs"),
            ("Zoom", {"location": "https://us05web.zoom.us/j/81234567890?pwd=secret"}, "https://us05web.zoom.us/j/81234567890?pwd=secret"),
            ("Microsoft Teams", {"description": "Please join (https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0)."}, "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0"),
            ("Slack Huddle", {"description": "Jump in: https://app.slack.com/huddle/T012345/C067890!"}, "https://app.slack.com/huddle/T012345/C067890"),
            ("Jitsi Meet", {"location": "https://meet.jit.si/JuncoWeeklyReview"}, "https://meet.jit.si/JuncoWeeklyReview"),
            ("Webex", {"description": "Room link: https://acme.webex.com/meet/alex.chen,"}, "https://acme.webex.com/meet/alex.chen"),
        ]
        for expected_provider, fields, expected_url in cases:
            rec = self.record(**fields)
            self.assertEqual(rec["video"], expected_url, expected_provider)
            self.assertEqual(rec["where"], expected_provider, expected_provider)

    def test_preserves_physical_room_when_link_is_in_description(self) -> None:
        rec = self.record(location="Room 4B", description="Remote link https://zoom.us/j/99887766")
        self.assertEqual(rec["video"], "https://zoom.us/j/99887766")
        self.assertEqual(rec["where"], "Room 4B")

    def test_rejects_spoofed_and_unsafe_meeting_links(self) -> None:
        bad_urls = [
            "javascript:alert(1)",
            "file:///etc/passwd",
            "https://user:pw@meet.google.com/abc-defg-hij",
            "https://evil.example/https://meet.google.com/abc-defg-hij",
            "https://evilzoom.us/j/12345",
            "https://meet.google.com/",
            "https://teams.microsoft.com/not-a-meeting",
        ]
        for bad in bad_urls:
            rec = self.record(location=bad, description=f"Join here: {bad}")
            self.assertEqual(rec["video"], "", bad)

    def test_counts_non_declined_non_resource_attendees(self) -> None:
        rec = self.record(attendees=[
            {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
            {"email": "alice@example.com", "responseStatus": "accepted"},
            {"email": "bob@example.com", "responseStatus": "needsAction"},
            {"email": "carol@example.com", "responseStatus": "declined"},
            {"email": "room-4b@resource.calendar.google.com", "resource": True, "responseStatus": "accepted"},
        ])
        self.assertEqual(rec["attendeeCount"], 3)


class IsolatedHomeTestCase(unittest.TestCase):
    """Base test case with isolated XDG directories so ~/.local/state is never touched."""

    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.root = Path(self.home.name)
        self.env = unittest.mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "COURIER_NO_NOTIFY": "1",
        })
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.home.cleanup()

    def write_google_events(self, events: list[dict], calendars: list[dict] | None = None) -> None:
        folder = calendar.calendar_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "google.json").write_text(json.dumps({
            "synced": 1795739400,
            "calendars": calendars or [{"id": "work:main", "name": "Work", "color": "#ff6b9d", "account": "work", "source": "google"}],
            "events": events,
        }))


class NextMeetingAndTodayFilterTest(IsolatedHomeTestCase):
    """Strict Today-only filtering (December never bleeds into November) and
    next-meeting selection across upcoming, in-progress, past, all-day, and empty."""

    def test_december_events_never_bleed_into_november_today_feed(self) -> None:
        now = datetime(2026, 11, 27, 6, 0, 0, tzinfo=IST)
        self.write_google_events([
            {
                "id": "nov-past", "calendarId": "work:main", "calendar": "Work", "color": "#ff6b9d",
                "title": "Early Deploy Check", "where": "Google Meet", "video": "https://meet.google.com/aaa-bbbb-ccc",
                "allDay": False, "start": "2026-11-27T05:00:00+05:30", "end": "2026-11-27T05:30:00+05:30",
            },
            {
                "id": "nov-next", "calendarId": "work:main", "calendar": "Work", "color": "#ff6b9d",
                "title": "Product Sync", "where": "Google Meet", "video": "https://meet.google.com/abc-defg-hij",
                "allDay": False, "start": "2026-11-27T06:30:00+05:30", "end": "2026-11-27T07:00:00+05:30",
            },
            {
                "id": "nov-tomorrow", "calendarId": "work:main", "calendar": "Work", "color": "#ff6b9d",
                "title": "Saturday Hike", "where": "", "video": "",
                "allDay": False, "start": "2026-11-28T09:00:00+05:30", "end": "2026-11-28T11:00:00+05:30",
            },
            {
                "id": "dec-visit", "calendarId": "work:main", "calendar": "Work", "color": "#7986cb",
                "title": "Someone Visiting in December", "where": "Airport", "video": "",
                "allDay": True, "start": "2026-12-11", "end": "2026-12-12",
            },
            {
                "id": "nov-yesterday-allday", "calendarId": "work:main", "calendar": "Work", "color": "#80cbc4",
                "title": "Yesterday All-Day", "where": "", "video": "",
                "allDay": True, "start": "2026-11-26", "end": "2026-11-27",
            },
        ])

        feed = calendar.build_next_meeting_feed(now=now)
        self.assertEqual(feed["todayDate"], "2026-11-27")
        self.assertEqual(feed["todayMeetingCount"], 2)
        self.assertEqual([e["id"] for e in feed["todayEvents"]], ["nov-past", "nov-next"])
        self.assertNotIn("dec-visit", [e["id"] for e in feed["todayEvents"]])
        self.assertNotIn("nov-tomorrow", [e["id"] for e in feed["todayEvents"]])
        self.assertNotIn("nov-yesterday-allday", [e["id"] for e in feed["todayEvents"]])
        self.assertEqual(feed["nextMeeting"]["id"], "nov-next")
        self.assertFalse(feed["nextMeeting"]["inProgress"])
        self.assertEqual(feed["nextMeeting"]["joinUrl"], "https://meet.google.com/abc-defg-hij")

    def test_in_progress_meeting_selected_until_it_ends(self) -> None:
        self.write_google_events([
            {
                "id": "live-1", "calendarId": "work:main", "calendar": "Work", "color": "#ff6b9d",
                "title": "Design Crit", "where": "Zoom", "video": "https://zoom.us/j/123456789",
                "allDay": False, "start": "2026-11-27T10:00:00+05:30", "end": "2026-11-27T10:45:00+05:30",
            },
            {
                "id": "later-2", "calendarId": "work:main", "calendar": "Work", "color": "#ff6b9d",
                "title": "1:1 with Sam", "where": "", "video": "",
                "allDay": False, "start": "2026-11-27T11:00:00+05:30", "end": "2026-11-27T11:30:00+05:30",
            },
        ])

        # Mid-meeting: live-1 is selected with inProgress=True.
        mid = datetime(2026, 11, 27, 10, 20, 0, tzinfo=IST)
        feed_mid = calendar.build_next_meeting_feed(now=mid)
        self.assertEqual(feed_mid["nextMeeting"]["id"], "live-1")
        self.assertTrue(feed_mid["nextMeeting"]["inProgress"])

        # Right when live-1 ends: advances to later-2 with inProgress=False.
        after_first = datetime(2026, 11, 27, 10, 45, 0, tzinfo=IST)
        feed_next = calendar.build_next_meeting_feed(now=after_first)
        self.assertEqual(feed_next["nextMeeting"]["id"], "later-2")
        self.assertFalse(feed_next["nextMeeting"]["inProgress"])

        # After all meetings end: nextMeeting is None.
        evening = datetime(2026, 11, 27, 18, 0, 0, tzinfo=IST)
        feed_done = calendar.build_next_meeting_feed(now=evening)
        self.assertIsNone(feed_done["nextMeeting"])
        self.assertEqual(feed_done["todayMeetingCount"], 2)

    def test_all_day_only_and_empty_day_return_null_next_meeting(self) -> None:
        now = datetime(2026, 11, 27, 9, 0, 0, tzinfo=IST)
        empty = calendar.build_next_meeting_feed(now=now)
        self.assertIsNone(empty["nextMeeting"])
        self.assertEqual(empty["todayMeetingCount"], 0)
        self.assertEqual(empty["todayEvents"], [])

        self.write_google_events([
            {
                "id": "allday-1", "calendarId": "work:main", "calendar": "Work", "color": "#80cbc4",
                "title": "Company Offsite", "where": "", "video": "",
                "allDay": True, "start": "2026-11-27", "end": "2026-11-28",
            },
        ])
        feed = calendar.build_next_meeting_feed(now=now)
        self.assertIsNone(feed["nextMeeting"])
        self.assertEqual(feed["todayMeetingCount"], 0)
        self.assertEqual(len(feed["todayEvents"]), 1)
        self.assertTrue(feed["todayEvents"][0]["allDay"])

    def test_dedupes_events_and_respects_hidden_calendars(self) -> None:
        now = datetime(2026, 11, 27, 8, 0, 0, tzinfo=IST)
        self.write_google_events([
            {
                "id": "dup-1", "calendarId": "work:main", "calendar": "Work", "color": "#ff6b9d",
                "title": "Standup", "where": "", "video": "",
                "allDay": False, "start": "2026-11-27T09:00:00+05:30", "end": "2026-11-27T09:15:00+05:30",
            },
            {
                "id": "dup-2", "calendarId": "personal:main", "calendar": "Personal", "color": "#7986cb",
                "title": "Standup", "where": "", "video": "",
                "allDay": False, "start": "2026-11-27T09:00:00+05:30", "end": "2026-11-27T09:15:00+05:30",
            },
            {
                "id": "hid-1", "calendarId": "hidden:cal", "calendar": "Noise", "color": "#cccccc",
                "title": "Hidden Sync", "where": "", "video": "",
                "allDay": False, "start": "2026-11-27T08:30:00+05:30", "end": "2026-11-27T08:45:00+05:30",
            },
        ])
        state = calendar.sync.state_dir()
        state.mkdir(parents=True, exist_ok=True)
        (state / "calendar-view.json").write_text(json.dumps({"view": "month", "hidden": ["hidden:cal"]}))
        feed = calendar.build_next_meeting_feed(now=now)
        self.assertEqual(feed["todayMeetingCount"], 1)
        self.assertEqual(feed["nextMeeting"]["title"], "Standup")


class ActionablesSqliteTest(IsolatedHomeTestCase):
    """SQLite calendar_actionables migration, CRUD, event links, and carry-over."""

    def test_migration_schema_and_crud(self) -> None:
        now = datetime(2026, 11, 27, 6, 15, 0, tzinfo=IST)
        created = calendar.add_actionable("Review PR #90 before standup", "2026-11-27", "uid-sync-1", now=now)
        self.assertEqual(created["title"], "Review PR #90 before standup")
        self.assertEqual(created["dueDate"], "2026-11-27")
        self.assertFalse(created["completed"])
        self.assertFalse(created["carryOver"])
        self.assertEqual(created["eventUid"], "uid-sync-1")

        # Verify SQLite table schema & migration record directly.
        conn = sqlite3.connect(str(calendar.actionables_db_path()))
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(calendar_actionables)")]
            self.assertEqual(cols, ["id", "title", "due_date", "completed", "completed_at", "event_uid", "created_at"])
            versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations")]
            self.assertEqual(versions, [1])
        finally:
            conn.close()

        # Toggle complete -> sets completed_at; toggle back -> clears completed_at.
        done = calendar.toggle_actionable(created["id"], now=now + timedelta(minutes=10))
        self.assertTrue(done["completed"])
        self.assertEqual(done["completedAt"], "2026-11-27T06:25:00+05:30")

        reopened = calendar.toggle_actionable(created["id"], now=now + timedelta(minutes=12))
        self.assertFalse(reopened["completed"])
        self.assertEqual(reopened["completedAt"], "")

        # Delete & validation errors.
        self.assertEqual(calendar.delete_actionable(created["id"], now=now), {"deleted": created["id"]})
        self.assertEqual(calendar.list_actionables("2026-11-27", now=now), [])
        with self.assertRaises(calendar.EventError):
            calendar.add_actionable("   ", "2026-11-27", now=now)
        with self.assertRaises(calendar.EventError):
            calendar.add_actionable("Bad date", "2026-99-99", now=now)
        with self.assertRaises(calendar.EventError):
            calendar.toggle_actionable(9999, now=now)
        with self.assertRaises(calendar.EventError):
            calendar.delete_actionable(9999, now=now)

    def test_carry_over_surfaces_in_today_until_checked_or_dismissed(self) -> None:
        day_25 = datetime(2026, 11, 25, 10, 0, 0, tzinfo=IST)
        day_27 = datetime(2026, 11, 27, 6, 0, 0, tzinfo=IST)
        day_28 = datetime(2026, 11, 28, 6, 0, 0, tzinfo=IST)

        old_open = calendar.add_actionable("Send Q4 notes", "2026-11-25", now=day_25)
        old_done = calendar.add_actionable("Already finished earlier", "2026-11-25", now=day_25)
        calendar.toggle_actionable(old_done["id"], True, now=day_25 + timedelta(hours=1))
        today_item = calendar.add_actionable("Prep slides", "2026-11-27", now=day_27)
        dec_item = calendar.add_actionable("December task", "2026-12-05", now=day_27)

        listed = calendar.list_actionables("2026-11-27", now=day_27)
        self.assertEqual([item["title"] for item in listed], ["Send Q4 notes", "Prep slides"])
        self.assertTrue(listed[0]["carryOver"])
        self.assertFalse(listed[1]["carryOver"])
        self.assertNotIn(dec_item["id"], [item["id"] for item in listed])

        # Viewing December only shows December's task (no carry-over leakage).
        dec_listed = calendar.list_actionables("2026-12-05", now=day_27)
        self.assertEqual([item["title"] for item in dec_listed], ["December task"])

        # Check off carry-over today: stays visible as done today, disappears tomorrow.
        calendar.toggle_actionable(old_open["id"], True, now=day_27 + timedelta(minutes=5))
        after_check = calendar.list_actionables("2026-11-27", now=day_27 + timedelta(minutes=6))
        checked_old = next(i for i in after_check if i["id"] == old_open["id"])
        self.assertTrue(checked_old["completed"])
        self.assertFalse(checked_old["carryOver"])

        next_day = calendar.list_actionables("2026-11-28", now=day_28)
        self.assertEqual([i["title"] for i in next_day], ["Prep slides"])  # only still-open item carries over


class NextMeetingFeedAndCliTest(IsolatedHomeTestCase):
    """Atomic next-meeting.json output, schema contract, sync/remind hooks, and CLI."""

    def test_atomic_write_schema_and_permissions(self) -> None:
        now = datetime(2026, 11, 27, 6, 0, 0, tzinfo=IST)
        self.write_google_events([
            {
                "id": "evt-1", "calendarId": "work:main", "calendar": "Work", "color": "#ff6b9d",
                "title": "Product Sync", "where": "Google Meet", "video": "https://meet.google.com/abc-defg-hij",
                "allDay": False, "start": "2026-11-27T06:30:00+05:30", "end": "2026-11-27T07:00:00+05:30",
            },
        ])
        calendar.add_actionable("Review PR #90 before standup", "2026-11-27", now=now)
        calendar.write_next_meeting_feed(now=now)

        feed_path = calendar.next_meeting_path()
        self.assertTrue(feed_path.exists())
        self.assertEqual(feed_path.parent, self.root / "state" / "courier")
        # Private 0600 permissions and no leftover temp files.
        self.assertEqual(stat.S_IMODE(feed_path.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in feed_path.parent.iterdir() if ".tmp" in p.name], [])

        data = json.loads(feed_path.read_text(encoding="utf-8"))
        self.assertEqual(set(data.keys()), {
            "updatedAt", "todayDate", "todayMeetingCount", "openActionablesCount",
            "nextMeeting", "todayEvents", "actionables",
        })
        self.assertEqual(data["todayDate"], "2026-11-27")
        self.assertEqual(data["todayMeetingCount"], 1)
        self.assertEqual(data["openActionablesCount"], 1)
        self.assertEqual(set(data["nextMeeting"].keys()), {
            "id", "title", "startIso", "endIso", "allDay", "inProgress",
            "joinUrl", "location", "calendarName", "calendarColor",
        })
        self.assertEqual(set(data["todayEvents"][0].keys()), {
            "id", "title", "startIso", "endIso", "allDay",
            "joinUrl", "location", "calendarName", "calendarColor",
        })
        self.assertEqual(set(data["actionables"][0].keys()), {
            "id", "title", "dueDate", "completed", "carryOver",
        })

    def test_remind_only_rewrites_feed_when_state_changes(self) -> None:
        self.write_google_events([
            {
                "id": "evt-1", "calendarId": "work:main", "calendar": "Work", "color": "#ff6b9d",
                "title": "Standup", "where": "Google Meet", "video": "https://meet.google.com/abc-defg-hij",
                "allDay": False, "start": "2026-11-27T09:00:00+05:30", "end": "2026-11-27T09:30:00+05:30",
            },
        ])
        t1 = datetime(2026, 11, 27, 8, 40, 0, tzinfo=IST)
        calendar.remind(t1)
        feed_path = calendar.next_meeting_path()
        first = json.loads(feed_path.read_text())
        self.assertFalse(first["nextMeeting"]["inProgress"])

        # Same state 1 minute later -> no rewrite (updatedAt unchanged).
        t2 = datetime(2026, 11, 27, 8, 41, 0, tzinfo=IST)
        calendar.remind(t2)
        second = json.loads(feed_path.read_text())
        self.assertEqual(second["updatedAt"], first["updatedAt"])

        # Meeting goes live -> rewritten with inProgress=True.
        t3 = datetime(2026, 11, 27, 9, 5, 0, tzinfo=IST)
        calendar.remind(t3)
        third = json.loads(feed_path.read_text())
        self.assertTrue(third["nextMeeting"]["inProgress"])
        self.assertEqual(third["updatedAt"], t3.isoformat())

    def test_courier_cal_next_cli_command(self) -> None:
        today = datetime.now().astimezone().date()
        start = datetime.now().astimezone().replace(second=0, microsecond=0) + timedelta(minutes=25)
        if start.date() != today:
            start = datetime.combine(today, datetime.min.time(), tzinfo=start.tzinfo) + timedelta(hours=23, minutes=30)
        calendar.add_event({
            "title": "CLI Smoke Meeting",
            "where": "https://meet.jit.si/JuncoSmokeRoom",
            "notes": "",
            "allDay": False,
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=20)).isoformat(),
            "reminders": [10],
        })
        calendar.add_actionable("Test CLI actionable", today.isoformat())

        courier_bin = HERE.parent.parent / "bin" / "courier"
        proc = subprocess.run(
            [str(courier_bin), "cal", "next", "--json"],
            capture_output=True,
            text=True,
            check=True,
            env=os.environ.copy(),
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["todayDate"], today.isoformat())
        self.assertEqual(payload["openActionablesCount"], 1)
        self.assertEqual(payload["actionables"][0]["title"], "Test CLI actionable")
        self.assertTrue(any(e["joinUrl"] == "https://meet.jit.si/JuncoSmokeRoom" for e in payload["todayEvents"]))
        # Adding the event and actionable also atomically wrote next-meeting.json.
        self.assertTrue(calendar.next_meeting_path().exists())
