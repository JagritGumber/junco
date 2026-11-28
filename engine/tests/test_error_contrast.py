"""Automated WCAG AA (>= 4.5:1) contrast regression tests for Junco error,
re-auth, and sync status buttons across Calendar and Mail (Dark & Light glass
and Solid modes).

All tests run in isolated temp XDG directories with offscreen Quickshell so
real accounts, live desktop apps, and Caelestia state are never touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
REPO_ROOT = ENGINE.parent

DARK_SCHEME = {
    "name": "dynamic",
    "mode": "dark",
    "colours": {
        "primary": "becba7",
        "primaryPaletteKeyColor": "6f7b5b",
        "error": "ffb4ab",
        "onError": "690005",
        "errorContainer": "93000a",
        "onErrorContainer": "ffdad6",
    },
}

LIGHT_SCHEME = {
    "name": "dynamic",
    "mode": "light",
    "colours": {
        "primary": "4e5e8b",
        "primaryPaletteKeyColor": "6676a5",
        "error": "ba1a1a",
        "onError": "ffffff",
        "errorContainer": "ffdad6",
        "onErrorContainer": "410002",
    },
}


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _lin_channel(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = rgb
    return 0.2126 * _lin_channel(r) + 0.7152 * _lin_channel(g) + 0.0722 * _lin_channel(b)


def _over(fg: tuple[float, float, float, float], bg: tuple[float, float, float]) -> tuple[float, float, float]:
    """Composite straight-alpha RGBA foreground over opaque RGB background."""
    r, g, b, a = fg
    return (
        r * a + bg[0] * (1.0 - a),
        g * a + bg[1] * (1.0 - a),
        b * a + bg[2] * (1.0 - a),
    )


def _qt_tint(base: tuple[float, float, float, float], tint: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Match Qt.tint(base, tint): blends RGB by tint.a while preserving base.a."""
    ta = tint[3]
    return (
        base[0] * (1.0 - ta) + tint[0] * ta,
        base[1] * (1.0 - ta) + tint[1] * ta,
        base[2] * (1.0 - ta) + tint[2] * ta,
        base[3],
    )


def _rgba(entry: dict[str, float]) -> tuple[float, float, float, float]:
    return (float(entry["r"]), float(entry["g"]), float(entry["b"]), float(entry["a"]))


def _contrast_ratio(fg_rgba: tuple[float, float, float, float], bg_rgb: tuple[float, float, float]) -> float:
    """WCAG 2.1 contrast ratio of fg_rgba composited over opaque bg_rgb."""
    eff_fg = _over(fg_rgba, bg_rgb)
    l1 = _luminance(eff_fg)
    l2 = _luminance(bg_rgb)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


class ErrorButtonContrastTest(unittest.TestCase):
    def _qs_bin(self) -> str:
        qs_bin = shutil.which("qs") or str(Path.home() / ".local/bin/qs")
        if not os.path.exists(qs_bin):
            self.skipTest("qs binary not installed")
        return qs_bin

    def _isolated_env(
        self,
        tmp_path: Path,
        fakebin: Path,
        glass_mode: str,
        theme_mode: str = "glass",
        scheme: dict | None = None,
    ) -> dict[str, str]:
        run_dir = tmp_path / "run"
        run_dir.mkdir(mode=0o700, exist_ok=True)
        for sub in ("home", "config", "data", "state", "cache"):
            (tmp_path / sub).mkdir(exist_ok=True)
        if scheme is not None:
            cael_state = tmp_path / "state" / "caelestia"
            cael_state.mkdir(parents=True, exist_ok=True)
            (cael_state / "scheme.json").write_text(json.dumps(scheme), encoding="utf-8")
        env = {
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
        if theme_mode == "solid":
            env["COURIER_THEME"] = "solid"
        return env

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
            self.fail(f"Quickshell contrast probe timed out:\n{stdout}\n{stderr}")
        return proc.returncode, stdout + "\n" + stderr

    def _assert_clean_qml(self, code: int, combined: str, label: str) -> None:
        self.assertEqual(code, 0, f"qs exited {code} ({label}):\n{combined}")
        for bad in ("WARN scene:", "TypeError", "ReferenceError", "Unable to assign", "ERROR"):
            self.assertNotIn(bad, combined, f"QML warning/error ({bad}) in {label}:\n{combined}")

    def test_calendar_status_buttons_wcag_aa_dark_light_and_solid(self) -> None:
        """Verify CalendarStatus 'Sign in again', 'Turn it on', and 'Try again'
        (both secondary and primary filled states) achieve >= 4.5:1 WCAG AA
        contrast across Dark glass, Light glass (with both dark & light
        Caelestia schemes), and Solid modes."""
        qs_bin = self._qs_bin()

        harness_qml = """import QtQuick
import Quickshell
import qs.services
import qs.components

ShellRoot {
    FloatingWindow {
        id: win

        implicitWidth: 280
        implicitHeight: 420

        function rgba(c) {
            const q = Qt.color(c);
            return { r: q.r, g: q.g, b: q.b, a: q.a };
        }

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

        Timer {
            id: probeTimer
            interval: 450
            running: true
            onTriggered: {
                const signInBtn = win.findByName(statusCard, "calendarSignInButton");
                const signInLbl = win.findByName(statusCard, "calendarSignInLabel");
                const retryBtn = win.findByName(statusCard, "calendarRetryButton");
                const retryLbl = win.findByName(statusCard, "calendarRetryLabel");
                const statusLbl = win.findByName(statusCard, "calendarStatusLabel");
                const out = {
                    mode: Theme.mode,
                    dark: Theme.dark,
                    glass: Theme.glass,
                    tokens: {
                        glassSheet: win.rgba(Theme.glassSheet),
                        glassSidebar: win.rgba(Theme.glassSidebar),
                        m3errorContainer: win.rgba(Theme.m3errorContainer),
                        m3onErrorContainer: win.rgba(Theme.m3onErrorContainer),
                        errorPill: win.rgba(Theme.errorPill),
                        errorPillInk: win.rgba(Theme.errorPillInk),
                        m3errorPopup: win.rgba(Theme.m3errorPopup),
                        pill: win.rgba(Theme.pill),
                        pillInk: win.rgba(Theme.pillInk)
                    },
                    // State 1: loaded from state/courier/calendar.json (signed-out)
                    signedOut: {
                        cardBg: win.rgba(statusCard.color),
                        statusText: win.rgba(statusLbl.color),
                        signInVisible: signInBtn.visible,
                        signInBg: win.rgba(signInBtn.color),
                        signInFg: win.rgba(signInLbl.color),
                        retryVisible: retryBtn.visible,
                        retryFilled: retryBtn.filled,
                        retryBg: win.rgba(retryBtn.color),
                        retryFg: win.rgba(retryLbl.color)
                    }
                };

                // State 2: API disabled (Turn it on primary + Try again secondary)
                Calendar.status = {
                    state: "error",
                    message: "Turn on the Google Calendar API for your Cloud project.",
                    action: "https://console.developers.google.com/apis/api/calendar-json.googleapis.com"
                };
                const fixBtn = win.findByName(statusCard, "calendarActionUrlButton");
                const fixLbl = win.findByName(statusCard, "calendarActionUrlLabel");
                out.apiDisabled = {
                    fixVisible: fixBtn.visible,
                    fixBg: win.rgba(fixBtn.color),
                    fixFg: win.rgba(fixLbl.color),
                    retryFilled: retryBtn.filled,
                    retryBg: win.rgba(retryBtn.color),
                    retryFg: win.rgba(retryLbl.color)
                };

                // State 3: transient sync error (Try again primary filled)
                Calendar.status = {
                    state: "error",
                    message: "Can't reach Google Calendar: temporary failure"
                };
                out.transientError = {
                    signInVisible: signInBtn.visible,
                    retryVisible: retryBtn.visible,
                    retryFilled: retryBtn.filled,
                    retryBg: win.rgba(retryBtn.color),
                    retryFg: win.rgba(retryLbl.color)
                };

                console.log("CAL_CONTRAST_PROBE=" + JSON.stringify(out));
                Qt.quit();
            }
        }
    }
}
"""

        cases = [
            ("dark", "glass", DARK_SCHEME),
            ("light", "glass", LIGHT_SCHEME),
            ("light", "glass", DARK_SCHEME),  # polarity override (!schemeMatchesMode)
            ("dark", "solid", DARK_SCHEME),
            ("light", "solid", LIGHT_SCHEME),
        ]

        for glass_mode, theme_mode, scheme in cases:
            label = f"{glass_mode}/{theme_mode}/scheme={scheme['mode']}"
            with self.subTest(case=label), tempfile.TemporaryDirectory(prefix="junco-cal-contrast-") as tmp:
                tmp_path = Path(tmp)
                fakebin = tmp_path / "fakebin"
                fakebin.mkdir()
                _make_executable(fakebin / "systemctl", "#!/bin/sh\necho disabled\nexit 0\n")

                cal_dir = tmp_path / "calendar"
                cal_dir.mkdir()
                (cal_dir / "shell.qml").write_text(harness_qml, encoding="utf-8")
                os.symlink(REPO_ROOT / "calendar" / "services", cal_dir / "services")
                os.symlink(REPO_ROOT / "calendar" / "components", cal_dir / "components")
                os.symlink(REPO_ROOT / "engine", tmp_path / "engine")
                os.symlink(REPO_ROOT / "bin", tmp_path / "bin")
                os.symlink(REPO_ROOT / "assets", tmp_path / "assets")

                env = self._isolated_env(tmp_path, fakebin, glass_mode, theme_mode=theme_mode, scheme=scheme)
                (tmp_path / "config" / "courier").mkdir(parents=True, exist_ok=True)
                (tmp_path / "config" / "courier" / "accounts.json").write_text(
                    json.dumps({"accounts": []}), encoding="utf-8"
                )
                (tmp_path / "state" / "courier").mkdir(parents=True, exist_ok=True)
                (tmp_path / "state" / "courier" / "calendar.json").write_text(
                    json.dumps({"state": "signed-out", "message": "Sign in again: courier-auth add personal"}),
                    encoding="utf-8",
                )
                code, combined = self._run_qs(qs_bin, cal_dir, env)
                self._assert_clean_qml(code, combined, label)

                match = re.search(r"CAL_CONTRAST_PROBE=(\{.*\})", combined)
                self.assertIsNotNone(match, f"Missing contrast probe ({label}):\n{combined}")
                probe = json.loads(match.group(1))
                tok = probe["tokens"]

                # Representative wallpapers behind the frosted window: dark & mid-tone.
                wallpapers = [(0.05, 0.06, 0.09), (0.35, 0.37, 0.42)]
                if glass_mode == "light":
                    wallpapers.append((0.88, 0.90, 0.94))

                for wp in wallpapers:
                    sheet_bg = _over(_rgba(tok["glassSheet"]), wp)
                    sidebar_bg = _over(_rgba(tok["glassSidebar"]), sheet_bg)
                    card_bg = _over(_rgba(probe["signedOut"]["cardBg"]), sidebar_bg)

                    # 1. Card status message text on error card
                    status_cr = _contrast_ratio(_rgba(probe["signedOut"]["statusText"]), card_bg)
                    self.assertGreaterEqual(status_cr, 4.5, f"{label} wp={wp} status text contrast={status_cr:.2f}")

                    # 2. Primary "Sign in again" button (resting, hover, pressed)
                    self.assertTrue(probe["signedOut"]["signInVisible"])
                    sign_in_bg_rgba = _rgba(probe["signedOut"]["signInBg"])
                    sign_in_fg_rgba = _rgba(probe["signedOut"]["signInFg"])
                    self.assertEqual(sign_in_fg_rgba[3], 1.0, f"{label} Sign in again text must be opaque")
                    for state_name, tint_a in (("rest", 0.0), ("hover", 0.10), ("pressed", 0.18)):
                        tinted = _qt_tint(sign_in_bg_rgba, (*sign_in_fg_rgba[:3], tint_a)) if tint_a else sign_in_bg_rgba
                        eff_btn_bg = _over(tinted, card_bg)
                        cr = _contrast_ratio(sign_in_fg_rgba, eff_btn_bg)
                        self.assertGreaterEqual(
                            cr, 4.5, f"{label} Sign in again ({state_name}) contrast={cr:.2f} < 4.5"
                        )

                    # 3. Secondary "Try again" button alongside "Sign in again"
                    self.assertTrue(probe["signedOut"]["retryVisible"])
                    self.assertFalse(probe["signedOut"]["retryFilled"])
                    sec_retry_bg = _over(_rgba(probe["signedOut"]["retryBg"]), card_bg)
                    sec_retry_cr = _contrast_ratio(_rgba(probe["signedOut"]["retryFg"]), sec_retry_bg)
                    self.assertGreaterEqual(
                        sec_retry_cr, 4.5, f"{label} wp={wp} secondary Try again contrast={sec_retry_cr:.2f}"
                    )

                    # 4. Primary "Turn it on" API console action button
                    self.assertTrue(probe["apiDisabled"]["fixVisible"])
                    fix_bg = _over(_rgba(probe["apiDisabled"]["fixBg"]), card_bg)
                    fix_cr = _contrast_ratio(_rgba(probe["apiDisabled"]["fixFg"]), fix_bg)
                    self.assertGreaterEqual(fix_cr, 4.5, f"{label} Turn it on contrast={fix_cr:.2f}")

                    # 5. Primary filled "Try again" button (transient sync error)
                    self.assertFalse(probe["transientError"]["signInVisible"])
                    self.assertTrue(probe["transientError"]["retryVisible"])
                    self.assertTrue(probe["transientError"]["retryFilled"])
                    prim_retry_bg = _over(_rgba(probe["transientError"]["retryBg"]), card_bg)
                    prim_retry_cr = _contrast_ratio(_rgba(probe["transientError"]["retryFg"]), prim_retry_bg)
                    self.assertGreaterEqual(
                        prim_retry_cr, 4.5, f"{label} primary Try again contrast={prim_retry_cr:.2f}"
                    )

                # 6. Error popup & primary Pill tokens over extreme black and white backdrops
                for backdrop in ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)):
                    popup_bg = _over(_rgba(tok["m3errorPopup"]), backdrop)
                    popup_cr = _contrast_ratio(_rgba(tok["m3onErrorContainer"]), popup_bg)
                    self.assertGreaterEqual(
                        popup_cr, 4.5, f"{label} m3errorPopup over {backdrop} contrast={popup_cr:.2f}"
                    )
                    pill_bg = _over(_rgba(tok["pill"]), backdrop)
                    pill_cr = _contrast_ratio(_rgba(tok["pillInk"]), pill_bg)
                    self.assertGreaterEqual(
                        pill_cr, 4.5, f"{label} Theme.pill over {backdrop} contrast={pill_cr:.2f}"
                    )

    def test_mail_sync_pill_and_error_snackbar_wcag_aa_dark_and_light(self) -> None:
        """Verify MailSidebar's sync-error pill ('Sign in again' / 'Sync needs a look')
        and error Snackbar achieve >= 4.5:1 text contrast (and >= 3:1 dot contrast)
        in both Dark and Light glass modes."""
        qs_bin = self._qs_bin()

        harness_qml = """import QtQuick
import Quickshell
import qs.services
import qs.views
import qs.components

ShellRoot {
    FloatingWindow {
        id: win

        implicitWidth: 540
        implicitHeight: 780

        function rgba(c) {
            const q = Qt.color(c);
            return { r: q.r, g: q.g, b: q.b, a: q.a };
        }

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

        MailSidebar {
            id: sidebar
            width: 216
            height: 760
            compact: false
        }

        Snackbar {
            id: snackbar
            anchors.left: parent.left
            anchors.bottom: parent.bottom
        }

        Timer {
            interval: 400
            running: true
            onTriggered: {
                Inbox.sayError("Google sign-in expired for personal.");
                const pill = win.findByName(sidebar, "mailSyncPill");
                const dot = win.findByName(sidebar, "mailSyncPillDot");
                const lbl = win.findByName(sidebar, "mailSyncPillLabel");
                const bar = win.findByName(snackbar, "snackbarBar");
                const barLbl = win.findByName(snackbar, "snackbarLabel");
                const out = {
                    mode: Theme.mode,
                    dark: Theme.dark,
                    glass: Theme.glass,
                    syncLabel: Inbox.syncLabel,
                    syncTrouble: Inbox.syncTrouble,
                    glassSheet: win.rgba(Theme.glassSheet),
                    glassSidebar: win.rgba(Theme.glassSidebar),
                    pillVisible: Boolean(pill && pill.visible),
                    pillBg: win.rgba(pill.color),
                    pillFg: win.rgba(lbl.color),
                    dotColor: win.rgba(dot.color),
                    sheetError: win.rgba(Theme.sheetError),
                    snackbarBg: win.rgba(bar.color),
                    snackbarFg: win.rgba(barLbl.color)
                };
                console.log("MAIL_CONTRAST_PROBE=" + JSON.stringify(out));
                Qt.quit();
            }
        }
    }
}
"""

        for glass_mode, scheme in (("dark", DARK_SCHEME), ("light", LIGHT_SCHEME), ("light", DARK_SCHEME)):
            label = f"mail/{glass_mode}/scheme={scheme['mode']}"
            with self.subTest(case=label), tempfile.TemporaryDirectory(prefix="junco-mail-contrast-") as tmp:
                tmp_path = Path(tmp)
                fakebin = tmp_path / "fakebin"
                fakebin.mkdir()
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

                env = self._isolated_env(tmp_path, fakebin, glass_mode, scheme=scheme)
                (tmp_path / "config" / "courier").mkdir(parents=True)
                (tmp_path / "config" / "courier" / "accounts.json").write_text(
                    json.dumps({"accounts": [{"id": "personal", "email": "personal@example.com"}]}),
                    encoding="utf-8",
                )
                (tmp_path / "state" / "courier").mkdir(parents=True)
                (tmp_path / "state" / "courier" / "sync.json").write_text(
                    json.dumps(
                        {
                            "finished": "2026-11-27T18:00:00+00:00",
                            "accounts": {"personal": {"state": "signed-out"}},
                        }
                    ),
                    encoding="utf-8",
                )

                code, combined = self._run_qs(qs_bin, shell_dir, env)
                self._assert_clean_qml(code, combined, label)

                match = re.search(r"MAIL_CONTRAST_PROBE=(\{.*\})", combined)
                self.assertIsNotNone(match, f"Missing mail contrast probe ({label}):\n{combined}")
                probe = json.loads(match.group(1))

                self.assertTrue(probe["syncTrouble"])
                self.assertEqual(probe["syncLabel"], "Sign in again")
                self.assertTrue(probe["pillVisible"])

                # Status dot uses Theme.sheetError on the smoked sidebar in both modes.
                self.assertEqual(probe["dotColor"], probe["sheetError"])

                # Mail sync pill text & dot contrast over representative desktop wallpapers.
                for wp in ((0.06, 0.08, 0.12), (0.28, 0.30, 0.36)):
                    sheet_bg = _over(_rgba(probe["glassSheet"]), wp)
                    sidebar_bg = _over(_rgba(probe["glassSidebar"]), sheet_bg)
                    pill_bg = _over(_rgba(probe["pillBg"]), sidebar_bg)
                    pill_cr = _contrast_ratio(_rgba(probe["pillFg"]), pill_bg)
                    dot_cr = _contrast_ratio(_rgba(probe["dotColor"]), pill_bg)
                    self.assertGreaterEqual(pill_cr, 4.5, f"{label} wp={wp} mailSyncPill contrast={pill_cr:.2f}")
                    self.assertGreaterEqual(dot_cr, 3.0, f"{label} wp={wp} mailSyncPill dot contrast={dot_cr:.2f}")

                # Floating error Snackbar must remain WCAG AA over both black and white content.
                for backdrop in ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)):
                    snack_bg = _over(_rgba(probe["snackbarBg"]), backdrop)
                    snack_cr = _contrast_ratio(_rgba(probe["snackbarFg"]), snack_bg)
                    self.assertGreaterEqual(
                        snack_cr, 4.5, f"{label} error Snackbar over {backdrop} contrast={snack_cr:.2f}"
                    )


if __name__ == "__main__":
    unittest.main()
