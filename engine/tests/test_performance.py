"""Performance & regression tests for Junco Mail & Calendar (#115).

Verifies:
- Lazy module loading in courier_sync, courier_avatars, courier_calendar,
  courier_expiry, and courier_mail (zero eager ssl/imaplib/urllib/templates).
- Single-shot bootstrap endpoints for Mail and Calendar.
- Disk-backed conversation preview cache correctness & mtime/size invalidation.
- SQLite WAL + PRAGMA user_version fast-path on actionables.db and expiry.db.
- Static QML thermal/shader/typography/lazy-loader hygiene across shell & calendar.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

ENGINE = Path(__file__).resolve().parent.parent
REPO_ROOT = ENGINE.parent

sys.path.insert(0, str(ENGINE))
import courier_calendar as cal  # noqa: E402
import courier_expiry as expiry  # noqa: E402
import courier_mail as mail  # noqa: E402


class LazyImportTest(unittest.TestCase):
    def _imported_modules_after(self, module_name: str) -> set[str]:
        code = (
            f"import json, sys; sys.path.insert(0, {str(ENGINE)!r}); "
            f"import {module_name}; print(json.dumps(sorted(sys.modules.keys())))"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        return set(json.loads(proc.stdout))

    def test_courier_sync_skips_heavy_imports(self) -> None:
        mods = self._imported_modules_after("courier_sync")
        for heavy in ("imaplib", "ssl", "urllib.request", "email.parser", "subprocess", "argparse"):
            self.assertNotIn(heavy, mods, f"courier_sync eagerly imported {heavy}")

    def test_courier_avatars_skips_heavy_imports(self) -> None:
        mods = self._imported_modules_after("courier_avatars")
        for heavy in ("imaplib", "ssl", "urllib.request", "concurrent.futures", "courier_html", "html.parser"):
            self.assertNotIn(heavy, mods, f"courier_avatars eagerly imported {heavy}")

    def test_courier_calendar_skips_heavy_imports(self) -> None:
        mods = self._imported_modules_after("courier_calendar")
        for heavy in ("imaplib", "ssl", "urllib.request", "sqlite3", "argparse"):
            self.assertNotIn(heavy, mods, f"courier_calendar eagerly imported {heavy}")

    def test_courier_expiry_skips_heavy_imports(self) -> None:
        mods = self._imported_modules_after("courier_expiry")
        for heavy in ("imaplib", "ssl", "urllib.request", "argparse", "calendar"):
            self.assertNotIn(heavy, mods, f"courier_expiry eagerly imported {heavy}")

    def test_courier_mail_skips_heavy_imports(self) -> None:
        mods = self._imported_modules_after("courier_mail")
        for heavy in (
            "imaplib",
            "ssl",
            "urllib.request",
            "courier_gmail",
            "courier_html",
            "courier_templates",
            "courier_fields",
            "courier_views",
            "courier_expiry",
            "courier_later",
            "zoneinfo",
            "argparse",
        ):
            self.assertNotIn(heavy, mods, f"courier_mail eagerly imported {heavy}")


class SqliteAndBootstrapTest(unittest.TestCase):
    def test_calendar_bootstrap_and_wal_user_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_DATA_HOME": tmp, "XDG_STATE_HOME": tmp, "XDG_CONFIG_HOME": tmp}
            with mock.patch.dict(os.environ, env):
                today = date(2026, 11, 27)
                cal.add_event(
                    {
                        "title": "Perf Sync",
                        "where": "Google Meet",
                        "notes": "",
                        "allDay": False,
                        "start": "2026-11-27T11:00:00",
                        "end": "2026-11-27T11:45:00",
                        "reminders": [10],
                    }
                )
                cal.add_actionable("Ship perf pass", due_date="2026-11-27")

                snap = cal.bootstrap(date(2026, 11, 23), date(2026, 11, 30), today, today)
                self.assertIn("calendars", snap)
                self.assertIn("accounts", snap)
                self.assertIn("status", snap)
                self.assertEqual(len(snap["events"]), 1)
                self.assertEqual(len(snap["around"]), 1)
                self.assertEqual(len(snap["todayEvents"]), 1)
                self.assertEqual(len(snap["actionables"]), 1)
                self.assertEqual(snap["actionables"][0]["title"], "Ship perf pass")

                conn = sqlite3.connect(str(cal.actionables_db_path()))
                try:
                    self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                    self.assertGreaterEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
                finally:
                    conn.close()

    def test_expiry_db_wal_and_user_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "expiry.db"
            conn = expiry.open_db(db_path)
            try:
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], expiry.SCHEMA_VERSION)
                self.assertGreaterEqual(len(expiry.list_rules(conn)), 9)
            finally:
                conn.close()
            # Re-open takes the fast path without errors.
            conn2 = expiry.open_db(db_path)
            try:
                self.assertGreaterEqual(len(expiry.list_rules(conn2)), 9)
            finally:
                conn2.close()

    def test_preview_cache_hits_and_invalidates_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eml = Path(tmp) / "sample.eml"
            msg = EmailMessage()
            msg["From"] = "Alice <alice@example.com>"
            msg["Subject"] = "Hello"
            msg.set_content("First version of the preview line.\n")
            eml.write_bytes(msg.as_bytes())

            cache: dict[str, list] = {}
            dirty = [False]
            first = mail.preview_of(str(eml), "fallback", cache, dirty)
            self.assertEqual(first, "First version of the preview line.")
            self.assertTrue(dirty[0])

            # Second call with unchanged file hits cache (does not call read_message).
            dirty[0] = False
            with mock.patch.object(mail, "read_message", side_effect=AssertionError("should use cache")):
                second = mail.preview_of(str(eml), "fallback", cache, dirty)
            self.assertEqual(second, "First version of the preview line.")
            self.assertFalse(dirty[0])

            # Modifying file invalidates cache entry immediately.
            msg2 = EmailMessage()
            msg2["From"] = "Alice <alice@example.com>"
            msg2["Subject"] = "Hello"
            msg2.set_content("Updated content with different length and timestamp.\n")
            eml.write_bytes(msg2.as_bytes())
            third = mail.preview_of(str(eml), "fallback", cache, dirty)
            self.assertEqual(third, "Updated content with different length and timestamp.")
            self.assertTrue(dirty[0])


class QmlPerformanceHygieneTest(unittest.TestCase):
    def _all_qml_files(self) -> list[Path]:
        files = list((REPO_ROOT / "shell").rglob("*.qml"))
        files += [p for p in (REPO_ROOT / "calendar").rglob("*.qml") if not p.is_symlink()]
        return sorted(files)

    def test_zero_shaders_or_qtquick_effects_anywhere(self) -> None:
        forbidden = ("QtQuick.Effects", "RectangularShadow", "MultiEffect", "FastBlur", "GaussianBlur", "ShaderEffect")
        for path in self._all_qml_files():
            # Strip single-line comments so explanatory comments never false-positive.
            code = "\n".join(line.split("//", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())
            for token in forbidden:
                self.assertNotIn(token, code, f"Shader/Effect token {token!r} found in {path}")

    def test_zero_faux_bold_or_heavy_font_weight_anywhere(self) -> None:
        bold_re = re.compile(r"\bfont\.bold\s*:\s*true\b")
        weight_re = re.compile(r"\bfont\.weight\s*:\s*(?:Font\.(?:Medium|DemiBold|Bold|ExtraBold|Black)|[5-9]\d\d)\b")
        for path in self._all_qml_files():
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(bold_re.search(text), f"font.bold: true in {path}")
            self.assertIsNone(weight_re.search(text), f"font.weight > Normal in {path}")

    def test_calendar_sidebar_spinner_never_spins_on_state_never(self) -> None:
        text = (REPO_ROOT / "calendar" / "views" / "CalendarSidebar.qml").read_text(encoding="utf-8")
        self.assertNotIn('running: stateIcon.name === "sync"', text)
        self.assertIn('account.syncState === "syncing"', text)

    def test_timegrid_uses_shared_clock_with_zero_timers(self) -> None:
        text = (REPO_ROOT / "calendar" / "views" / "TimeGrid.qml").read_text(encoding="utf-8")
        self.assertNotIn("Timer {", text)
        self.assertIn("Calendar.nowMs", text)

    def test_hidden_modals_and_views_are_lazy_loaded(self) -> None:
        mail_shell = (REPO_ROOT / "shell" / "shell.qml").read_text(encoding="utf-8")
        for loader_id in (
            "mailListLoader",
            "mailReaderLoader",
            "autoExpirySettingsLoader",
            "composeDialogLoader",
            "addAccountDialogLoader",
            "pictureDialogLoader",
            "paletteSchedulePopoverLoader",
        ):
            self.assertIn(f"id: {loader_id}", mail_shell)

        cal_page = (REPO_ROOT / "calendar" / "views" / "CalendarPage.qml").read_text(encoding="utf-8")
        self.assertIn("id: dialogLoader", cal_page)
        self.assertIn("id: resultsLoader", cal_page)

        palette_qml = (REPO_ROOT / "shell" / "components" / "CommandPalette.qml").read_text(encoding="utf-8")
        self.assertIn("id: overlayLoader", palette_qml)


if __name__ == "__main__":
    unittest.main()
