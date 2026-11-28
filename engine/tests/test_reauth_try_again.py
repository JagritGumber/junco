"""Unit and interactive offscreen QML regression tests for Item #137:
Junco Calendar 'Sign in again' / 'Try again' card and Junco Mail sync pill.

All tests run in fully isolated temp XDG directories with harmless stub
commands in a temp PATH — real accounts, keyring entries, browsers, and
systemd services are never touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ENGINE = Path(__file__).resolve().parent.parent
REPO_ROOT = ENGINE.parent

sys.path.insert(0, str(ENGINE))
import courier_calendar as cal  # noqa: E402
import courier_mail as mail  # noqa: E402
import courier_sync as sync  # noqa: E402


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class ReauthStatusParsingTest(unittest.TestCase):
    def test_valid_account_id_accepts_safe_ids_and_rejects_injection(self) -> None:
        for good in ("studio", "personal", "work-2", "a", "a" + "0" * 31):
            self.assertEqual(cal.valid_account_id(good), good, good)

        for bad in (
            "",
            "   ",
            None,
            123,
            "-flag",
            "--help",
            "Studio",
            "studio;rm",
            "studio$(id)",
            "studio`id`",
            "../etc",
            "<account>",
            "studio\nrm",
            "a" * 33,
            "studio.com",
        ):
            self.assertEqual(cal.valid_account_id(bad), "", repr(bad))

    def test_parse_reauth_account_extracts_clean_account_and_blocks_injection(self) -> None:
        self.assertEqual(cal.parse_reauth_account("Sign in again: courier-auth add studio"), "studio")
        self.assertEqual(cal.parse_reauth_account("Sign in again: courier-auth add work-2."), "work-2")
        self.assertEqual(cal.parse_reauth_account("Run: courier-auth add studio --calendar-write"), "studio")
        self.assertEqual(
            cal.parse_reauth_account("No account named 'studio'. Run: courier-auth add studio"),
            "studio",
        )

        # Transient sync errors and placeholder hints return "".
        for non_reauth in (
            "",
            "Can't reach Google Calendar: temporary failure",
            "Turn on the Google Calendar API for your Cloud project.",
            "No Google account yet. Add one with courier-auth add <name>.",
            "Junco may only read your calendar: run courier-auth add <account> --calendar-write",
        ):
            self.assertEqual(cal.parse_reauth_account(non_reauth), "", non_reauth)

        # Command/argument injection attempts are strictly rejected.
        for malicious in (
            "Sign in again: courier-auth add studio; rm -rf /",
            "Sign in again: courier-auth add studio && whoami",
            "Sign in again: courier-auth add studio | cat /etc/passwd",
            "Sign in again: courier-auth add $(whoami)",
            "Sign in again: courier-auth add --email=evil@example.com",
            "Sign in again: courier-auth add studio\nwhoami",
            "Sign in again: courier-auth add studio --extra-flag",
        ):
            self.assertEqual(cal.parse_reauth_account(malicious), "", malicious)

    def test_read_status_enriches_legacy_signed_out_calendar_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
            }
            with mock.patch.dict(os.environ, env):
                cal.status_path().parent.mkdir(parents=True, exist_ok=True)
                cal.status_path().write_text(
                    json.dumps({"state": "signed-out", "message": "Sign in again: courier-auth add studio"}),
                    encoding="utf-8",
                )
                loaded = cal.read_status()
                self.assertEqual(loaded["state"], "signed-out")
                self.assertEqual(loaded["account"], "studio")

    def test_run_sync_status_records_structured_account_on_signed_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
            }
            with mock.patch.dict(os.environ, env), mock.patch.object(
                cal, "sync_calendars", side_effect=sync.SignedOut("studio")
            ):
                status = cal.run_sync_status()
                self.assertEqual(status["state"], "signed-out")
                self.assertEqual(status["account"], "studio")
                self.assertIn("courier-auth add studio", status["message"])
                persisted = json.loads(cal.status_path().read_text(encoding="utf-8"))
                self.assertEqual(persisted["account"], "studio")


class ReauthProcessSafetyTest(unittest.TestCase):
    def test_calendar_reauth_invokes_stub_with_email_and_syncs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / "bin"
            fakebin.mkdir()
            log_file = root / "auth_args.txt"
            _make_executable(
                fakebin / "courier-auth",
                f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {str(log_file)!r}\necho 'Signed in studio@example.com as studio.'\n",
            )
            (root / "config" / "courier").mkdir(parents=True)
            (root / "config" / "courier" / "accounts.json").write_text(
                json.dumps({"accounts": [{"id": "studio", "email": "studio@example.com"}]}),
                encoding="utf-8",
            )
            env = {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "PATH": f"{fakebin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            }
            with mock.patch.dict(os.environ, env), mock.patch.object(
                cal, "sync_calendars", return_value={"state": "ok", "calendars": 1, "events": 2, "synced": 100}
            ):
                result = cal.reauth_account("studio")
            self.assertTrue(result["ok"])
            self.assertEqual(result["account"], "studio")
            self.assertEqual(result["email"], "studio@example.com")
            self.assertEqual(result["status"]["state"], "ok")
            self.assertEqual(log_file.read_text(encoding="utf-8").splitlines(), ["add", "studio", "--email", "studio@example.com"])

    def test_calendar_and_mail_reauth_reject_invalid_account_without_spawning(self) -> None:
        with mock.patch("subprocess.Popen", side_effect=AssertionError("must not spawn for invalid account")):
            for bad in ("--help", "studio;id", "../foo", "UpperCase", ""):
                with self.assertRaises(cal.EventError):
                    cal.reauth_account(bad)
                with self.assertRaises(mail.MailError):
                    mail.add_account(bad)

    def test_mail_add_account_uses_isolated_path_stubs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fakebin = root / "bin"
            fakebin.mkdir()
            auth_log = root / "mail_auth.txt"
            _make_executable(
                fakebin / "courier-auth",
                f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {str(auth_log)!r}\n",
            )
            _make_executable(fakebin / "courier-sync", "#!/bin/sh\nexit 0\n")
            _make_executable(fakebin / "systemctl", "#!/bin/sh\nexit 0\n")
            (root / "config" / "courier").mkdir(parents=True)
            (root / "config" / "courier" / "accounts.json").write_text(
                json.dumps({"accounts": [{"id": "studio", "email": "studio@example.com"}]}),
                encoding="utf-8",
            )
            env = {
                "HOME": str(root / "home"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "PATH": f"{fakebin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            }
            with mock.patch.dict(os.environ, env):
                result = mail.add_account("studio")
            self.assertEqual(result, {"id": "studio", "email": "studio@example.com"})
            self.assertEqual(auth_log.read_text(encoding="utf-8").splitlines(), ["add", "studio", "--email", "studio@example.com"])


class InteractiveQmlReauthSmokeTest(unittest.TestCase):
    """Offscreen interactive Quickshell tests verifying actual clicks on
    CalendarStatus ('Sign in again' & 'Try again') and MailSidebar sync pill."""

    def _qs_bin(self) -> str:
        qs_bin = shutil.which("qs") or str(Path.home() / ".local/bin/qs")
        if not os.path.exists(qs_bin):
            self.skipTest("qs binary not installed")
        return qs_bin

    def _isolated_env(self, tmp_path: Path, fakebin: Path, glass_mode: str) -> dict[str, str]:
        run_dir = tmp_path / "run"
        run_dir.mkdir(mode=0o700, exist_ok=True)
        for sub in ("home", "config", "data", "state", "cache"):
            (tmp_path / sub).mkdir(exist_ok=True)
        return {
            "HOME": str(tmp_path / "home"),
            "USER": os.environ.get("USER", "user"),
            "LANG": "C.UTF-8",
            "PATH": f"{fakebin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_RUNTIME_DIR": str(run_dir),
            "QT_QPA_PLATFORM": "offscreen",
            "QT_QUICK_BACKEND": "software",
            "QT_FORCE_STDERR_LOGGING": "1",
            "QS_NO_RELOAD_POPUP": "1",
            "COURIER_GLASS_MODE": glass_mode,
            "COURIER_NO_NOTIFY": "1",
            "COURIER_OFFLINE": "1",
        }

    def _run_qs(self, qs_bin: str, shell_dir: Path, env: dict[str, str], timeout: int = 18) -> tuple[int, str]:
        proc = subprocess.Popen(
            [qs_bin, "-p", str(shell_dir)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            self.fail(f"Quickshell interactive probe timed out:\n{stdout}\n{stderr}")
        return proc.returncode, stdout + "\n" + stderr

    def test_calendar_status_click_reauth_and_try_again_dark_and_light(self) -> None:
        qs_bin = self._qs_bin()

        harness_qml = """import QtQuick
import Quickshell
import qs.services
import qs.components

ShellRoot {
    FloatingWindow {
        id: win

        implicitWidth: 320
        implicitHeight: 420

        property var log: ({
            feedbacks: [],
            phase: 0,
            initial: null,
            duringSignIn: null,
            afterSignIn: null,
            duringRetry: null,
            afterRetry: null
        })

        function findByName(item, name) {
            if (!item)
                return null;
            if (item.objectName === name)
                return item;
            const list = item.children || [];
            for (let i = 0; i < list.length; i++) {
                const hit = findByName(list[i], name);
                if (hit)
                    return hit;
            }
            return null;
        }

        function clickButton(item) {
            if (!item)
                return false;
            const list = item.children || [];
            for (let i = 0; i < list.length; i++) {
                const c = list[i];
                if (c && typeof c.clicked === "function") {
                    c.clicked(null);
                    return true;
                }
            }
            return false;
        }

        Connections {
            target: Calendar

            function onFeedback(msg) {
                win.log.feedbacks.push(msg);
            }

            function onSigningInChanged() {
                if (win.log.phase === 1 && !Calendar.signingIn) {
                    finishSignInTimer.restart();
                }
            }

            function onSyncingChanged() {
                if (win.log.phase === 2 && !Calendar.syncing) {
                    finishRetryTimer.restart();
                }
            }
        }

        Item {
            width: 200
            height: 360
            x: 14
            y: 14

            CalendarStatus {
                id: statusCard

                width: parent.width
            }
        }

        // Wait for startup bootstrap to load calendar.json signed-out status.
        Timer {
            id: startTimer

            interval: 350
            running: true
            onTriggered: {
                const signInBtn = win.findByName(statusCard, "calendarSignInButton");
                const retryBtn = win.findByName(statusCard, "calendarRetryButton");
                win.log.initial = {
                    visible: statusCard.visible,
                    needsReauth: statusCard.needsReauth,
                    reauthAccount: statusCard.reauthAccount,
                    statusState: Calendar.status.state,
                    signInVisible: Boolean(signInBtn && signInBtn.visible),
                    signInFits: Boolean(signInBtn && (signInBtn.x + signInBtn.width <= statusCard.width)),
                    retryVisible: Boolean(retryBtn && retryBtn.visible),
                    retryFits: Boolean(retryBtn && (retryBtn.x + retryBtn.width <= statusCard.width))
                };
                win.log.phase = 1;
                const clicked = win.clickButton(signInBtn);
                win.log.duringSignIn = {
                    clicked: clicked,
                    signingIn: Calendar.signingIn,
                    signingInAccount: Calendar.signingInAccount,
                    busy: statusCard.busy
                };
            }
        }

        Timer {
            id: finishSignInTimer

            interval: 150
            onTriggered: {
                win.log.afterSignIn = {
                    statusState: Calendar.status.state,
                    visible: statusCard.visible,
                    signingIn: Calendar.signingIn
                };
                // Phase 2: simulate transient network error & click "Try again".
                Calendar.status = { state: "error", message: "Can't reach Google Calendar: temporary" };
                const signInBtn = win.findByName(statusCard, "calendarSignInButton");
                const retryBtn = win.findByName(statusCard, "calendarRetryButton");
                win.log.phase = 2;
                const clicked = win.clickButton(retryBtn);
                win.log.duringRetry = {
                    clicked: clicked,
                    signInHidden: Boolean(!signInBtn || !signInBtn.visible),
                    retryVisibleBefore: Boolean(retryBtn),
                    syncing: Calendar.syncing,
                    busy: statusCard.busy
                };
            }
        }

        Timer {
            id: finishRetryTimer

            interval: 150
            onTriggered: {
                win.log.afterRetry = {
                    statusState: Calendar.status.state,
                    visible: statusCard.visible,
                    syncing: Calendar.syncing
                };
                console.log("CAL_REAUTH_PROBE=" + JSON.stringify(win.log));
                Qt.quit();
            }
        }
    }
}
"""

        for glass_mode in ("dark", "light"):
            with self.subTest(glass_mode=glass_mode), tempfile.TemporaryDirectory(prefix="junco-cal-reauth-") as tmp:
                tmp_path = Path(tmp)
                fakebin = tmp_path / "fakebin"
                fakebin.mkdir()
                auth_log = tmp_path / "stub_auth_calls.txt"
                _make_executable(
                    fakebin / "courier-auth",
                    f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {str(auth_log)!r}\nsleep 0.05\necho 'Signed in studio'\n",
                )
                _make_executable(fakebin / "systemctl", "#!/bin/sh\necho disabled\nexit 0\n")

                cal_dir = tmp_path / "calendar"
                cal_dir.mkdir()
                (cal_dir / "shell.qml").write_text(harness_qml, encoding="utf-8")
                os.symlink(REPO_ROOT / "calendar" / "services", cal_dir / "services")
                os.symlink(REPO_ROOT / "calendar" / "components", cal_dir / "components")
                os.symlink(REPO_ROOT / "engine", tmp_path / "engine")
                os.symlink(REPO_ROOT / "bin", tmp_path / "bin")
                os.symlink(REPO_ROOT / "assets", tmp_path / "assets")

                env = self._isolated_env(tmp_path, fakebin, glass_mode)
                (tmp_path / "config" / "courier").mkdir(parents=True)
                (tmp_path / "config" / "courier" / "accounts.json").write_text(json.dumps({"accounts": []}), encoding="utf-8")
                (tmp_path / "state" / "courier").mkdir(parents=True)
                (tmp_path / "state" / "courier" / "calendar.json").write_text(
                    json.dumps({"state": "signed-out", "message": "Sign in again: courier-auth add studio"}),
                    encoding="utf-8",
                )

                code, combined = self._run_qs(qs_bin, cal_dir, env)
                self.assertEqual(code, 0, f"qs exited {code}:\n{combined}")
                for bad in ("WARN scene:", "TypeError", "ReferenceError", "Unable to assign", "ERROR"):
                    self.assertNotIn(bad, combined, f"QML warning/error ({bad}) in {glass_mode}:\n{combined}")

                match = re.search(r"CAL_REAUTH_PROBE=(\{.*\})", combined)
                self.assertIsNotNone(match, f"Missing probe output:\n{combined}")
                probe = json.loads(match.group(1))

                self.assertTrue(probe["initial"]["visible"])
                self.assertTrue(probe["initial"]["needsReauth"])
                self.assertEqual(probe["initial"]["reauthAccount"], "studio")
                self.assertTrue(probe["initial"]["signInVisible"])
                self.assertTrue(probe["initial"]["signInFits"])
                self.assertTrue(probe["initial"]["retryVisible"])
                self.assertTrue(probe["initial"]["retryFits"])

                self.assertTrue(probe["duringSignIn"]["clicked"])
                self.assertTrue(probe["duringSignIn"]["signingIn"])
                self.assertEqual(probe["duringSignIn"]["signingInAccount"], "studio")
                self.assertTrue(probe["duringSignIn"]["busy"])

                self.assertEqual(probe["afterSignIn"]["statusState"], "ok")
                self.assertFalse(probe["afterSignIn"]["visible"])
                self.assertFalse(probe["afterSignIn"]["signingIn"])

                self.assertTrue(probe["duringRetry"]["clicked"])
                self.assertTrue(probe["duringRetry"]["signInHidden"])
                self.assertTrue(probe["duringRetry"]["syncing"])
                self.assertTrue(probe["duringRetry"]["busy"])

                self.assertEqual(probe["afterRetry"]["statusState"], "ok")
                self.assertFalse(probe["afterRetry"]["visible"])
                self.assertFalse(probe["afterRetry"]["syncing"])

                self.assertTrue(auth_log.exists(), "Stub courier-auth was never invoked")
                self.assertIn("add studio", auth_log.read_text(encoding="utf-8"))
                self.assertTrue(any("Opening Google sign-in for studio" in msg for msg in probe["feedbacks"]))
                self.assertTrue(any("Syncing calendars" in msg for msg in probe["feedbacks"]))

    def test_mail_sidebar_sync_pill_click_triggers_reauth(self) -> None:
        qs_bin = self._qs_bin()

        harness_qml = """import QtQuick
import Quickshell
import qs.services
import qs.views

ShellRoot {
    FloatingWindow {
        id: win

        implicitWidth: 260
        implicitHeight: 780

        property var log: ({
            phase: 0,
            notices: [],
            initial: null,
            during: null,
            after: null
        })

        function findByName(item, name) {
            if (!item)
                return null;
            if (item.objectName === name)
                return item;
            const list = item.children || [];
            for (let i = 0; i < list.length; i++) {
                const hit = findByName(list[i], name);
                if (hit)
                    return hit;
            }
            return null;
        }

        Connections {
            target: Inbox

            function onNoticeChanged() {
                if (Inbox.notice && Inbox.notice.text)
                    win.log.notices.push(Inbox.notice.text);
            }

            function onReauthInFlightChanged() {
                if (win.log.phase === 1 && Inbox.reauthInFlight === "") {
                    doneTimer.restart();
                }
            }
        }

        MailSidebar {
            id: sidebar

            width: 216
            height: 760
            compact: false
        }

        Timer {
            interval: 400
            running: true
            onTriggered: {
                const pill = win.findByName(sidebar, "mailSyncPill");
                const area = win.findByName(sidebar, "mailSyncPillArea");
                win.log.initial = {
                    syncTrouble: Inbox.syncTrouble,
                    signedOutAccount: Inbox.syncSignedOutAccount,
                    syncLabel: Inbox.syncLabel,
                    pillVisible: Boolean(pill && pill.visible),
                    hasArea: Boolean(area)
                };
                win.log.phase = 1;
                if (area)
                    area.clicked(null);
                win.log.during = {
                    reauthInFlight: Inbox.reauthInFlight,
                    syncLabel: Inbox.syncLabel,
                    noticeText: Inbox.notice ? Inbox.notice.text : ""
                };
            }
        }

        Timer {
            id: doneTimer

            interval: 150
            onTriggered: {
                win.log.after = {
                    reauthInFlight: Inbox.reauthInFlight,
                    studioState: Inbox.syncStatus.studio ? Inbox.syncStatus.studio.state : "",
                    noticeText: Inbox.notice ? Inbox.notice.text : ""
                };
                console.log("MAIL_SYNC_PILL_PROBE=" + JSON.stringify(win.log));
                Qt.quit();
            }
        }
    }
}
"""

        for glass_mode in ("dark", "light"):
            with self.subTest(glass_mode=glass_mode), tempfile.TemporaryDirectory(prefix="junco-mail-reauth-") as tmp:
                tmp_path = Path(tmp)
                fakebin = tmp_path / "fakebin"
                fakebin.mkdir()
                auth_log = tmp_path / "stub_mail_auth.txt"
                _make_executable(
                    fakebin / "courier-auth",
                    f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {str(auth_log)!r}\nsleep 0.05\n",
                )
                _make_executable(fakebin / "courier-sync", "#!/bin/sh\nexit 0\n")
                _make_executable(fakebin / "systemctl", "#!/bin/sh\nexit 0\n")

                shell_dir = tmp_path / "shell"
                shell_dir.mkdir()
                (shell_dir / "shell.qml").write_text(harness_qml, encoding="utf-8")
                os.symlink(REPO_ROOT / "shell" / "services", shell_dir / "services")
                os.symlink(REPO_ROOT / "shell" / "components", shell_dir / "components")
                os.symlink(REPO_ROOT / "shell" / "views", shell_dir / "views")
                os.symlink(REPO_ROOT / "engine", tmp_path / "engine")
                os.symlink(REPO_ROOT / "bin", tmp_path / "bin")
                os.symlink(REPO_ROOT / "assets", tmp_path / "assets")

                env = self._isolated_env(tmp_path, fakebin, glass_mode)
                (tmp_path / "config" / "courier").mkdir(parents=True)
                (tmp_path / "config" / "courier" / "accounts.json").write_text(
                    json.dumps({"accounts": [{"id": "studio", "email": "studio@example.com"}]}),
                    encoding="utf-8",
                )
                (tmp_path / "state" / "courier").mkdir(parents=True)
                (tmp_path / "state" / "courier" / "sync.json").write_text(
                    json.dumps(
                        {
                            "finished": "2026-11-27T18:00:00+00:00",
                            "accounts": {"studio": {"state": "signed-out"}},
                        }
                    ),
                    encoding="utf-8",
                )

                code, combined = self._run_qs(qs_bin, shell_dir, env)
                self.assertEqual(code, 0, f"qs exited {code}:\n{combined}")
                for bad in ("WARN scene:", "TypeError", "ReferenceError", "Unable to assign", "ERROR"):
                    self.assertNotIn(bad, combined, f"QML warning/error ({bad}) in {glass_mode}:\n{combined}")

                match = re.search(r"MAIL_SYNC_PILL_PROBE=(\{.*\})", combined)
                self.assertIsNotNone(match, f"Missing mail probe output:\n{combined}")
                probe = json.loads(match.group(1))

                self.assertTrue(probe["initial"]["syncTrouble"])
                self.assertEqual(probe["initial"]["signedOutAccount"], "studio")
                self.assertEqual(probe["initial"]["syncLabel"], "Sign in again")
                self.assertTrue(probe["initial"]["pillVisible"])
                self.assertTrue(probe["initial"]["hasArea"])

                self.assertEqual(probe["during"]["reauthInFlight"], "studio")
                self.assertEqual(probe["during"]["syncLabel"], "Signing in…")
                self.assertIn("Opening Google sign-in", probe["during"]["noticeText"])

                self.assertEqual(probe["after"]["reauthInFlight"], "")
                self.assertEqual(probe["after"]["studioState"], "ok")
                self.assertTrue(
                    any("Signed in" in msg for msg in probe["notices"]),
                    f"Expected 'Signed in' notice in {probe['notices']!r}",
                )

                self.assertTrue(auth_log.exists(), "Stub courier-auth was never invoked from Mail")
                self.assertIn("add studio --email studio@example.com", auth_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
