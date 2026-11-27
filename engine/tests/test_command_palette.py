"""Unit tests, integration hook tests, and static QML audits for Junco's
Frosted-Glass Command Palette (Ctrl+K, Item #127).

Runs palette.js directly via Node (matching test_reader_views.py's plaintext.js
pattern), verifies end-to-end compatibility with courier_expiry, courier_later,
and courier_calendar in isolated temp directories, and enforces Junco's Rubik
wght / zero-outline / zero-shader / zero-idle-animation rules.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ENGINE = Path(__file__).resolve().parent.parent
REPO_ROOT = ENGINE.parent
PALETTE_JS = REPO_ROOT / "shell" / "services" / "palette.js"

sys.path.insert(0, str(ENGINE))
import courier_calendar as cal  # noqa: E402
import courier_expiry as expiry  # noqa: E402
import courier_later as later  # noqa: E402


def run_palette_js(expr: str):
    """Evaluate a JS expression against shell/services/palette.js via node."""
    script = PALETTE_JS.read_text(encoding="utf-8").replace(".pragma library", "")
    program = f"{script}\nconst __res = ({expr});\nprocess.stdout.write(JSON.stringify(__res));\n"
    proc = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "needs node")
class PaletteParserAndFuzzyTest(unittest.TestCase):
    # Fixed local timestamp: Friday, 2026-11-27 10:15:00 local time.
    NOW_JS = "new Date(2026, 10, 27, 10, 15, 0, 0)"

    def test_expiry_duration_and_note_parsing(self) -> None:
        cases = [
            ("exp 7d", "7d", "", False, "2026-12-04"),
            ("exp 30d", "30d", "", False, "2026-12-27"),
            ("exp 6m", "6m", "", False, "2027-05-27"),
            ("exp 1y", "1y", "", False, "2027-11-27"),
            ("exp 2y", "2y", "", False, "2028-11-27"),
            ("exp 2y college", "2y", "college", False, "2028-11-27"),
            ("expire 14d tax receipts", "14d", "tax receipts", False, "2026-12-11"),
            ("exp 2 years grad school", "2y", "grad school", False, "2028-11-27"),
            ("exp 2028-11-27 diploma", "2028-11-27", "diploma", True, "2028-11-27"),
        ]
        for query, spec, note, is_date, preview_date in cases:
            with self.subTest(query=query):
                res = run_palette_js(f"parseExpiryCommand({json.dumps(query)}, {self.NOW_JS})")
                self.assertEqual(res["kind"], "expiry")
                self.assertEqual(res["mode"], "set")
                self.assertEqual(res["spec"], spec)
                self.assertEqual(res["note"], note)
                self.assertEqual(res["isDate"], is_date)
                self.assertEqual(res["previewDate"], preview_date)

    def test_expiry_clear_suggest_and_invalid(self) -> None:
        self.assertEqual(run_palette_js(f"parseExpiryCommand('exp', {self.NOW_JS})")["mode"], "suggest")
        self.assertEqual(run_palette_js(f"parseExpiryCommand('expire', {self.NOW_JS})")["mode"], "suggest")
        for clear_q in ("exp clear", "expire clear", "exp cancel", "exp off"):
            res = run_palette_js(f"parseExpiryCommand({json.dumps(clear_q)}, {self.NOW_JS})")
            self.assertEqual(res["mode"], "clear")
        for bad_q in ("exp 0d", "exp banana", "exp 2026-02-30", "exp 2020-01-01"):
            res = run_palette_js(f"parseExpiryCommand({json.dumps(bad_q)}, {self.NOW_JS})")
            self.assertEqual(res["mode"], "invalid")
            self.assertTrue(res["error"])

    def test_snooze_shorthand_parsing(self) -> None:
        # 2026-11-27 is a Friday at 10:15.
        cases = [
            ("snooze 2h", "2026-11-27T12:15"),
            ("snooze 30m", "2026-11-27T10:45"),
            ("later 3d", "2026-11-30T10:15"),
            ("snooze tomorrow 9am", "2026-11-28T09:00"),
            ("snooze tomorrow 2:30pm", "2026-11-28T14:30"),
            ("snooze tmr 14:00", "2026-11-28T14:00"),
            ("snooze tomorrow", "2026-11-28T09:00"),
            ("snooze next week", "2026-11-30T09:00"),  # Next Monday
            ("snooze weekend", "2026-11-28T09:00"),  # Saturday
            ("snooze tonight", "2026-11-27T19:00"),
            ("snooze later today", "2026-11-27T18:00"),
            ("snooze mon 10am", "2026-11-30T10:00"),
            ("snooze 5pm", "2026-11-27T17:00"),
            ("snooze 9am", "2026-11-28T09:00"),  # 9am already passed -> tomorrow
            ("snooze 2027-01-15 8:30am", "2027-01-15T08:30"),
        ]
        for query, expected_iso in cases:
            with self.subTest(query=query):
                res = run_palette_js(f"parseSnoozeCommand({json.dumps(query)}, {self.NOW_JS})")
                self.assertEqual(res["kind"], "snooze")
                self.assertEqual(res["mode"], "set")
                self.assertEqual(res["untilIso"], expected_iso)

    def test_snooze_suggest_and_invalid(self) -> None:
        self.assertEqual(run_palette_js(f"parseSnoozeCommand('snooze', {self.NOW_JS})")["mode"], "suggest")
        self.assertEqual(run_palette_js(f"parseSnoozeCommand('later', {self.NOW_JS})")["mode"], "suggest")
        for bad_q in ("snooze 0h", "snooze banana", "snooze 2020-01-01 9am", "snooze tomorrow 25:00"):
            res = run_palette_js(f"parseSnoozeCommand({json.dumps(bad_q)}, {self.NOW_JS})")
            self.assertEqual(res["mode"], "invalid")

    def test_from_query_parsing(self) -> None:
        res1 = run_palette_js("parseFromQuery('from:alex')")
        self.assertEqual(res1, {"kind": "from", "senderNeedle": "alex", "extraNeedle": ""})
        res2 = run_palette_js("parseFromQuery('from: alex invoice')")
        self.assertEqual(res2, {"kind": "from", "senderNeedle": "alex", "extraNeedle": "invoice"})
        res3 = run_palette_js("parseFromQuery('from:\"Alex Rivera\" Q4')")
        self.assertEqual(res3, {"kind": "from", "senderNeedle": "Alex Rivera", "extraNeedle": "Q4"})
        self.assertIsNone(run_palette_js("parseFromQuery('invoice from alex')"))

    def test_todo_command_parsing(self) -> None:
        self.assertEqual(
            run_palette_js("parseTodoCommand('todo Send Q4 deck')"),
            {"kind": "todo", "mode": "add", "keyword": "todo", "text": "Send Q4 deck"},
        )
        self.assertEqual(
            run_palette_js("parseTodoCommand('task Review PR #42')"),
            {"kind": "todo", "mode": "add", "keyword": "task", "text": "Review PR #42"},
        )
        self.assertEqual(
            run_palette_js("parseTodoCommand('add Buy coffee')"),
            {"kind": "todo", "mode": "add", "keyword": "add", "text": "Buy coffee"},
        )
        self.assertEqual(run_palette_js("parseTodoCommand('todo')")["mode"], "prompt")
        self.assertIsNone(run_palette_js("parseTodoCommand('today')"))

    def test_quick_event_parsing(self) -> None:
        res = run_palette_js(f"parseQuickEventCommand('new Design Review 4pm', {self.NOW_JS}, '2026-11-27')")
        self.assertEqual(res["mode"], "create")
        self.assertEqual(res["title"], "Design Review")
        self.assertEqual(res["day"], "2026-11-27")
        self.assertEqual(res["startMinutes"], 16 * 60)
        self.assertEqual(res["endMinutes"], 17 * 60)
        self.assertTrue(res["hasExplicitTime"])

        res_range = run_palette_js(f"parseQuickEventCommand('event Sprint Sync tomorrow 4-5:30pm', {self.NOW_JS}, '2026-11-27')")
        self.assertEqual(res_range["title"], "Sprint Sync")
        self.assertEqual(res_range["day"], "2026-11-28")
        self.assertEqual(res_range["startMinutes"], 16 * 60)
        self.assertEqual(res_range["endMinutes"], 17 * 60 + 30)

        res_dur = run_palette_js(f"parseQuickEventCommand('new Coffee at 9:30am for 30m', {self.NOW_JS}, '2026-11-27')")
        self.assertEqual(res_dur["title"], "Coffee")
        self.assertEqual(res_dur["startMinutes"], 9 * 60 + 30)
        self.assertEqual(res_dur["endMinutes"], 10 * 60)

        res_notime = run_palette_js(f"parseQuickEventCommand('new Brainstorm', {self.NOW_JS}, '2026-11-27')")
        self.assertEqual(res_notime["title"], "Brainstorm")
        self.assertFalse(res_notime["hasExplicitTime"])
        self.assertEqual(res_notime["startMinutes"], 11 * 60)  # Next hour after 10:15

        res_prompt = run_palette_js(f"parseQuickEventCommand('new', {self.NOW_JS}, '2026-11-27')")
        self.assertEqual(res_prompt["mode"], "prompt")

    def test_fuzzy_scoring_order(self) -> None:
        exact = run_palette_js("fuzzyScore('compose', 'Compose')")
        prefix = run_palette_js("fuzzyScore('comp', 'Compose email')")
        boundary = run_palette_js("fuzzyScore('exp', 'Open Auto-Expiry Settings')")
        subseq = run_palette_js("fuzzyScore('oas', 'Open Auto-Expiry Settings')")
        miss = run_palette_js("fuzzyScore('zzz', 'Open Auto-Expiry Settings')")

        self.assertTrue(exact["matched"])
        self.assertTrue(prefix["matched"])
        self.assertTrue(boundary["matched"])
        self.assertTrue(subseq["matched"])
        self.assertFalse(miss["matched"])
        self.assertGreater(exact["score"], prefix["score"])
        self.assertGreater(prefix["score"], subseq["score"])
        self.assertGreater(boundary["score"], subseq["score"])

    def test_tab_completion(self) -> None:
        self.assertEqual(run_palette_js("tabCompleteQuery('ex', null, 'mail')"), "exp ")
        self.assertEqual(run_palette_js("tabCompleteQuery('sn', null, 'mail')"), "snooze ")
        self.assertEqual(run_palette_js("tabCompleteQuery('fr', null, 'mail')"), "from:")
        self.assertEqual(run_palette_js("tabCompleteQuery('to', null, 'calendar')"), "todo ")
        self.assertEqual(run_palette_js("tabCompleteQuery('ne', null, 'calendar')"), "new ")
        self.assertEqual(
            run_palette_js("tabCompleteQuery('exp', {tabComplete: 'exp 2y '}, 'mail')"),
            "exp 2y ",
        )

    def test_mail_palette_ranking_contexts(self) -> None:
        sample_convs = [
            {
                "id": "p:alex@example.com",
                "kind": "person",
                "lane": "people",
                "name": "Alex Rivera",
                "address": "alex@example.com",
                "subject": "Q4 Launch Plan",
                "snippet": "Can you check the final deck?",
                "time": "10:02",
                "unread": 1,
                "expiry": None,
            },
            {
                "id": "u:billing@cloud.example",
                "kind": "lane",
                "lane": "updates",
                "name": "Cloud Billing",
                "address": "billing@cloud.example",
                "subject": "November Invoice #912",
                "snippet": "Your payment succeeded",
                "time": "Yesterday",
                "unread": 0,
                "expiry": {"remaining": "2y", "note": "receipts"},
            },
        ]
        ctx = {
            "hasActiveThread": True,
            "activeTitle": "Q4 Launch Plan",
            "activeStarred": False,
            "activeUnread": True,
            "activeHasExpiry": False,
            "activeInbox": True,
            "dark": True,
            "compactSidebar": False,
            "conversations": sample_convs,
            "flatRows": [],
            "folder": "smart",
        }

        # Empty query surfaces Current thread actions first.
        empty = run_palette_js(f"rankMailItems('', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertEqual(empty["items"][0]["group"], "Current thread")
        ids = [i["id"] for i in empty["items"]]
        for req_id in ("mail:reply", "mail:star", "mail:read", "mail:archive", "mail:schedule_delete", "mail:compose", "mail:toggle_glass"):
            self.assertIn(req_id, ids)

        # Without active thread, Current thread actions are hidden.
        ctx_no_thread = dict(ctx, hasActiveThread=False)
        empty_no = run_palette_js(f"rankMailItems('', {json.dumps(ctx_no_thread)}, {self.NOW_JS})")
        self.assertFalse(any(i["group"] == "Current thread" for i in empty_no["items"]))

        # Smart expiry command
        exp_res = run_palette_js(f"rankMailItems('exp 2y college', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertEqual(exp_res["modeBadge"], "Auto-Expiry")
        self.assertEqual(exp_res["items"][0]["action"], {"type": "expiry_set", "spec": "2y", "note": "college", "isDate": False})
        self.assertFalse(exp_res["items"][0].get("disabled", False))

        # Smart expiry disabled when no active thread
        exp_no = run_palette_js(f"rankMailItems('exp 2y college', {json.dumps(ctx_no_thread)}, {self.NOW_JS})")
        self.assertTrue(exp_no["items"][0]["disabled"])

        # From filter matches Alex Rivera only
        from_res = run_palette_js(f"rankMailItems('from:alex', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertEqual(from_res["modeBadge"], "From filter")
        self.assertEqual(from_res["items"][0]["id"], "conv:p:alex@example.com")
        self.assertFalse(any(i["id"] == "conv:u:billing@cloud.example" for i in from_res["items"]))

        # Fuzzy search finds Cloud Billing by subject keyword "invoice"
        fuzzy_res = run_palette_js(f"rankMailItems('invoice', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertTrue(any(i["id"] == "conv:u:billing@cloud.example" for i in fuzzy_res["items"]))

    def test_calendar_palette_ranking_contexts(self) -> None:
        next_meeting = {
            "id": "ev-1",
            "title": "Design Critique",
            "startDay": "2026-11-27",
            "start": "2026-11-27T10:00:00",
            "end": "2026-11-27T10:45:00",
            "time": "10:00 am – 10:45 am",
            "video": "https://meet.example.com/abc-defg-hij",
            "where": "Meet",
            "calendar": "Work",
            "allDay": False,
        }
        ctx = {
            "todayDay": "2026-11-27",
            "selectedDay": "2026-11-27",
            "view": "week",
            "sidebarShown": True,
            "dayShown": True,
            "dark": True,
            "nextMeeting": next_meeting,
            "nextMeetingLive": True,
            "nextMeetingCountdown": "Live now · 30m left",
            "events": [next_meeting],
            "actionables": [{"id": 7, "title": "Send Q4 slides", "completed": False, "carryOver": False}],
        }

        empty = run_palette_js(f"rankCalendarItems('', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertEqual(empty["items"][0]["id"], "cal:join_next")
        self.assertEqual(empty["items"][0]["badgeTone"], "complement")
        self.assertIn("Live now", empty["items"][0]["badge"])

        todo_res = run_palette_js(f"rankCalendarItems('todo Review roadmap', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertEqual(todo_res["modeBadge"], "Actionable")
        self.assertEqual(
            todo_res["items"][0]["action"],
            {"type": "add_actionable", "title": "Review roadmap", "dueDate": "2026-11-27"},
        )

        ev_res = run_palette_js(f"rankCalendarItems('new Design Review 4pm', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertEqual(ev_res["modeBadge"], "Quick Event")
        self.assertEqual(len(ev_res["items"]), 2)
        self.assertEqual(ev_res["items"][0]["action"]["type"], "create_event_prefilled")
        self.assertEqual(ev_res["items"][1]["action"]["type"], "create_event_direct")

        # Fuzzy search finds both events and actionables
        search_task = run_palette_js(f"rankCalendarItems('slides', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertEqual(search_task["items"][0]["action"]["type"], "toggle_actionable")
        self.assertEqual(search_task["items"][0]["action"]["id"], 7)

        search_event = run_palette_js(f"rankCalendarItems('critique', {json.dumps(ctx)}, {self.NOW_JS})")
        self.assertTrue(any(i["action"]["type"] == "focus_event" for i in search_event["items"]))


@unittest.skipUnless(shutil.which("node"), "needs node")
class PaletteBackendIntegrationTest(unittest.TestCase):
    """End-to-end checks verifying palette.js outputs cleanly invoke real
    courier_expiry, courier_later, and courier_calendar backends in isolation.
    """

    def test_expiry_parsed_command_roundtrips_with_sqlite_backend(self) -> None:
        parsed = run_palette_js("parseExpiryCommand('exp 2y college', new Date(2026, 10, 27, 10, 15, 0, 0))")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "expiry.db"
            conn = expiry.open_db(db_path)
            try:
                saved = expiry.set_thread_expiry(
                    conn,
                    "thread-demo-1",
                    after=parsed["spec"],
                    note=parsed["note"],
                    subject="Campus Housing Confirmation",
                    sender="housing@campus.example",
                )
                self.assertEqual(saved["thread_id"], "thread-demo-1")
                self.assertEqual(saved["note"], "college")
                self.assertEqual(saved["source"], "manual")

                cancelled = expiry.cancel_thread_expiry(conn, "thread-demo-1")
                self.assertTrue(cancelled["cancelled"])
            finally:
                conn.close()

    def test_snooze_parsed_command_accepted_by_courier_later(self) -> None:
        future_base = datetime.now() + timedelta(days=1)
        now_js = f"new Date({future_base.year}, {future_base.month - 1}, {future_base.day}, 10, 0, 0, 0)"
        parsed = run_palette_js(f"parseSnoozeCommand('snooze tomorrow 9am', {now_js})")
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_STATE_HOME": tmp}
            with mock.patch.dict(os.environ, env):
                archived: list[tuple[str, list[str]]] = []
                result = later.snooze(
                    lambda action, ids: archived.append((action, list(ids))),
                    ["msg-demo-42"],
                    parsed["untilIso"],
                    "Demo Subject",
                )
                self.assertEqual(result["snoozed"], ["msg-demo-42"])
                self.assertEqual(archived, [("archive", ["msg-demo-42"])])
                self.assertEqual(len(later.snoozed()), 1)

    def test_calendar_actionable_and_quick_event_roundtrip(self) -> None:
        todo_parsed = run_palette_js("parseTodoCommand('todo Prepare demo script')")
        ev_parsed = run_palette_js("parseQuickEventCommand('new Demo Rehearsal 4pm', new Date(2026, 10, 27, 10, 0, 0, 0), '2026-11-27')")
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_DATA_HOME": tmp, "XDG_STATE_HOME": tmp, "XDG_CONFIG_HOME": tmp}
            with mock.patch.dict(os.environ, env):
                added = cal.add_actionable(todo_parsed["text"], due_date="2026-11-27")
                self.assertEqual(added["title"], "Prepare demo script")
                listed = cal.list_actionables("2026-11-27")
                self.assertEqual(len(listed), 1)
                self.assertFalse(listed[0]["completed"])

                toggled = cal.toggle_actionable(added["id"])
                self.assertTrue(toggled["completed"])

                start_h, start_m = divmod(ev_parsed["startMinutes"], 60)
                end_h, end_m = divmod(ev_parsed["endMinutes"], 60)
                created = cal.add_event({
                    "title": ev_parsed["title"],
                    "allDay": False,
                    "start": f"{ev_parsed['day']}T{start_h:02d}:{start_m:02d}:00",
                    "end": f"{ev_parsed['day']}T{end_h:02d}:{end_m:02d}:00",
                    "where": "",
                    "notes": "",
                    "reminders": [10],
                })
                self.assertEqual(created["title"], "Demo Rehearsal")


class PaletteStaticAuditTest(unittest.TestCase):
    """Enforces Junco's Round 10 + Rubik wght + thermal hygiene constraints."""

    AUDITED_QML_FILES = [
        REPO_ROOT / "shell" / "components" / "CommandPalette.qml",
        REPO_ROOT / "shell" / "shell.qml",
        REPO_ROOT / "shell" / "services" / "Theme.qml",
        REPO_ROOT / "shell" / "services" / "Inbox.qml",
        REPO_ROOT / "shell" / "components" / "ScheduleDeletePopover.qml",
        REPO_ROOT / "shell" / "views" / "MailReader.qml",
        REPO_ROOT / "calendar" / "shell.qml",
        REPO_ROOT / "calendar" / "services" / "Calendar.qml",
        REPO_ROOT / "calendar" / "views" / "CalendarPage.qml",
        REPO_ROOT / "calendar" / "views" / "EventDialog.qml",
    ]

    def test_zero_faux_bold_or_heavy_font_weight(self) -> None:
        bold_re = re.compile(r"\bfont\.bold\s*:\s*true\b")
        weight_re = re.compile(r"\bfont\.weight\s*:\s*(?:Font\.(?:Medium|DemiBold|Bold|ExtraBold|Black)|[5-9]\d\d)\b")
        for path in self.AUDITED_QML_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(bold_re.search(text), f"font.bold: true found in {path}")
            self.assertIsNone(weight_re.search(text), f"font.weight > Normal found in {path}")

    def test_command_palette_zero_outlines_shaders_and_idle_animations(self) -> None:
        palette_qml = (REPO_ROOT / "shell" / "components" / "CommandPalette.qml").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bborder\.width\s*:\s*[1-9]", palette_qml), "Non-zero border.width in CommandPalette.qml")
        for forbidden in ("MultiEffect", "FastBlur", "GaussianBlur", "ShaderEffect", "Animation.Infinite"):
            self.assertNotIn(forbidden, palette_qml, f"Forbidden token {forbidden} in CommandPalette.qml")

    def test_calendar_symlinks_resolve_to_shell(self) -> None:
        cal_qml = REPO_ROOT / "calendar" / "components" / "CommandPalette.qml"
        cal_js = REPO_ROOT / "calendar" / "services" / "palette.js"
        self.assertTrue(cal_qml.is_symlink())
        self.assertTrue(cal_js.is_symlink())
        self.assertEqual(cal_qml.resolve(), (REPO_ROOT / "shell" / "components" / "CommandPalette.qml").resolve())
        self.assertEqual(cal_js.resolve(), PALETTE_JS.resolve())


if __name__ == "__main__":
    unittest.main()
