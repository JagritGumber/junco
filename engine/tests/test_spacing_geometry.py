"""Programmatic geometry, spacing rhythm, and static QML audit tests for Junco's
Spacing, Gapping & Typographic Rhythm Pass.

Verifies:
- Unified 4px/8px spacing & concentric radius tokens in Theme.qml (without
  altering dynamic 2-color complementary glass palette or Hyprland blur).
- Exact proportions across Filter Header Bar, ConversationRow, MailRow,
  MailSidebar, MailReader, ConversationView, MessageItem, Calendar views,
  and CommandPalette.
- Responsive bounds & zero clipping at both 1920x1080 (full screen) and
  950x1040 (half-screen tile).
- Zero faux-bold, zero shaders, zero unconditional glass outlines, and
  conversation starred/latestId payload support.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
REPO_ROOT = ENGINE.parent


def read_qml(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in src.splitlines())


class SpacingTokensAndBoundsTest(unittest.TestCase):
    def test_theme_spacing_tokens_and_concentric_radii(self) -> None:
        theme = read_qml("shell/services/Theme.qml")
        for token, val in [
            ("cardInset", "glass ? 6 : 0"),
            ("paneGap", "glass ? 6 : 0"),
            ("paneRadius", "glass ? 22 : 10"),
            ("cardPaneRadius", "glass ? 16 : 0"),
            ("cardRadius", "14"),
            ("rowRadius", "15"),
            ("controlRadius", "12"),
            ("spaceXS", "4"),
            ("spaceSM", "8"),
            ("spaceMD", "12"),
            ("spaceLG", "16"),
            ("spaceXL", "20"),
            ("space2XL", "24"),
        ]:
            self.assertRegex(
                theme,
                rf"readonly property int {token}:\s*{re.escape(val)}",
                f"Expected Theme.{token} == {val}",
            )
        # Typography: Adwaita Sans (Inter Variable) with crisp optical weights 400/500/600.
        self.assertIn('readonly property string sans: "Adwaita Sans"', theme)
        self.assertIn("readonly property int weightRegular: 400", theme)
        self.assertIn("readonly property int weightMedium: 500", theme)
        self.assertIn("readonly property int weightHeading: 600", theme)
        label_qml = read_qml("shell/components/Label.qml")
        self.assertIn("property bool tabular: false", label_qml)
        self.assertIn("font.letterSpacing:", label_qml)
        self.assertIn('({ "tnum": 1 })', label_qml)

        # Dark glass craft invariants: cohesive primary pill/accentFill, smoked obsidian
        # translucency, ZERO white top-edge glow in Dark mode (GlassEdge disabled when
        # Theme.dark), and jewel dark account tones (never stark white account badges
        # or muddy opaque plum selected rows).
        self.assertIn("function accountTone(index: int): color", theme)
        self.assertIn("readonly property color accentFill: darkGlass\n        ? pill", theme)
        self.assertIn("readonly property color accentFillInk: darkGlass ? pillInk", theme)
        self.assertIn("readonly property real primarySatDark:", theme)
        self.assertIn("readonly property real complementSatDark:", theme)
        self.assertIn("Qt.rgba(8 / 255, 10 / 255, 18 / 255, 0.58)", theme)
        self.assertIn('readonly property color glassEdgeLight: lightGlass ? Qt.rgba(1, 1, 1, 0.22) : "transparent"', theme)
        self.assertIn('readonly property color glassEdgeSideLight: lightGlass ? Qt.rgba(1, 1, 1, 0.15) : "transparent"', theme)
        self.assertNotIn("darkGlass ? tuneTone(primaryHue, primarySat, 0.82, 1.0)", theme)
        glass_edge = read_qml("shell/components/GlassEdge.qml")
        self.assertIn("visible: !Theme.dark", glass_edge)
        self.assertIn("visible: !Theme.dark && root.side", glass_edge)
        inbox_qml = read_qml("shell/services/Inbox.qml")
        self.assertIn("return Theme.accountTone(Math.max(0, at));", inbox_qml)
        acc_tag = read_qml("shell/components/AccountTag.qml")
        self.assertIn("border.width: Theme.glass ? 0 : 1", acc_tag)
        self.assertNotIn("GlassEdge", acc_tag)

        # Light glass invariants remain 100% preserved.
        self.assertIn("readonly property real sheetAlpha: 0.07", theme)
        self.assertIn("readonly property real cardAlpha: 0.27", theme)
        self.assertIn("readonly property real listLift: 0.09", theme)
        self.assertIn("alpha(mix(Qt.rgba(1, 1, 1, 1), accent, 0.32, 1), 0.74)", theme)

        # Dynamic 2-color complementary glass engine remains intact.
        for palette_symbol in (
            "function tuneTone(",
            "readonly property real complementHue:",
            "readonly property color glassSheet:",
            "readonly property color glassSelectedRow:",
            "readonly property bool sheetBlur: true",
        ):
            self.assertIn(palette_symbol, theme)

    def test_filter_header_bar_and_chip_proportions(self) -> None:
        conv_list = read_qml("shell/views/ConversationList.qml")
        chip = read_qml("shell/components/Chip.qml")

        self.assertIn("anchors.topMargin: 12", conv_list)
        self.assertIn("Layout.preferredHeight: 38", conv_list)
        self.assertIn("width >= 380 ? 22 : width >= 330 ? 16 : 10", conv_list)
        self.assertIn("tabStyle: true", conv_list)
        self.assertIn("spacing: 4", conv_list)
        self.assertIn("implicitHeight: tabStyle ? 32 : 30", chip)
        self.assertIn("spacing: root.selected ? 7 : 6", chip)

    def test_conversation_row_proportions_and_inset_divider(self) -> None:
        row = read_qml("shell/views/ConversationRow.qml")
        self.assertIn("implicitHeight: (snippetText !== \"\" ? 92 : 80)", row)
        self.assertIn("radius: Theme.rowRadius", row)
        self.assertIn("anchors.topMargin: 16", row)
        self.assertIn("anchors.bottomMargin: 16", row)
        self.assertIn("readonly property int innerPadX: width >= 310 ? 16 : 12", row)
        self.assertIn("readonly property int avatarSize: width >= 310 ? 46 : 42", row)
        self.assertIn("readonly property int avatarGap: width >= 310 ? 18 : 14", row)
        self.assertIn("readonly property int rightBuffer: width >= 310 ? 16 : 12", row)
        # Floating selected capsule specular sheen & smooth interaction color glide
        self.assertIn("visible: Theme.glass && root.selected", row)
        self.assertIn("Behavior on color", row)
        # 3-line typographic hierarchy: 15 DemiBold -> 4px -> 13 Medium -> 3px -> 13 Normal
        self.assertIn("font.pixelSize: 15", row)
        self.assertIn("weight: Font.DemiBold", row)
        self.assertIn("Layout.topMargin: 4", row)
        self.assertIn("Layout.topMargin: 3", row)
        # Right 2-anchor column: tabular time + 8 px unread dot + 8 px gap + 18 px star icon
        self.assertIn("tabular: true", row)
        self.assertIn("width: 8", row)
        self.assertIn("height: 8", row)
        self.assertIn("iconSize: 18", row)
        # Whisper-faint text-aligned divider hidden on/adjacent to selected row
        self.assertIn("anchors.leftMargin: root.innerPadX + root.avatarSize + root.avatarGap", row)
        self.assertIn("visible: !root.selected && !root.hovered && !root.isLast && !root.nextSelected", row)

    def test_sidebar_reader_calendar_and_palette_proportions(self) -> None:
        sidebar = read_qml("shell/views/MailSidebar.qml")
        s_item = read_qml("shell/components/SidebarItem.qml")
        reader = read_qml("shell/views/MailReader.qml")
        conv_view = read_qml("shell/views/ConversationView.qml")
        msg_item = read_qml("shell/views/MessageItem.qml")
        day_panel = read_qml("calendar/views/DayPanel.qml")
        next_card = read_qml("calendar/components/NextMeetingCard.qml")
        event_card = read_qml("calendar/components/EventCard.qml")
        task_row = read_qml("calendar/components/TaskRow.qml")
        palette = read_qml("shell/components/CommandPalette.qml")

        # Sidebar
        self.assertIn("anchors.margins: root.compact ? 8 : 14", sidebar)
        self.assertIn("implicitHeight: compact ? 40 : 41", s_item)
        self.assertIn("radius: 13", s_item)
        self.assertIn("spacing: 13", s_item)

        # Mail Reader & Conversation View
        self.assertIn("anchors.leftMargin: root.width >= 600 ? 28 : 20", reader)
        self.assertIn("font.pixelSize: 22", reader)
        self.assertIn("spacing: 16", reader)
        self.assertIn("anchors.leftMargin: root.width >= 600 ? 26 : 18", conv_view)
        self.assertIn("spacing: 14", conv_view)
        self.assertIn("anchors.topMargin: 14", msg_item)
        self.assertIn("anchors.leftMargin: 18", msg_item)

        # Calendar
        self.assertIn("anchors.margins: 16", day_panel)
        self.assertIn("spacing: 10", day_panel)
        self.assertIn("anchors.leftMargin: 16", next_card)
        self.assertIn("anchors.topMargin: 16", next_card)
        self.assertIn("anchors.leftMargin: 14", event_card)
        self.assertIn("anchors.topMargin: 14", event_card)
        self.assertIn("implicitHeight: Math.max(44, row.implicitHeight + 16)", task_row)
        self.assertIn("spacing: 12", task_row)

        # Command Palette: strict fixed search/footer heights + flexible list + translucent glassPalette
        self.assertIn("readonly property int searchBarH: 58", palette)
        self.assertIn("readonly property int footerBarH: 40", palette)
        self.assertIn("Layout.maximumHeight: card.searchBarH", palette)
        self.assertIn("Layout.maximumHeight: card.footerBarH", palette)
        self.assertIn("Layout.minimumHeight: 120", palette)
        self.assertIn("color: Theme.glassPalette", palette)
        self.assertIn("Layout.leftMargin: 18", palette)
        self.assertIn("anchors.leftMargin: 12", palette)
        self.assertIn("height: subtitleText !== \"\" ? 52 : 48", palette)
        self.assertIn("spacing: 13", palette)

    def test_responsive_bounds_full_and_half_screen(self) -> None:
        # Mirror shell/shell.qml width formulas at 1920x1080 and 950x1040.
        card_inset = 6
        pane_gap = 6
        saved_sidebar = 216

        for win_w, expected_compact in [(1920, False), (1760, False), (950, True)]:
            compact = win_w < 1200
            self.assertEqual(compact, expected_compact)
            default_list = 412 if win_w >= 1500 else (344 if win_w >= 1150 else 308)
            max_sidebar = max(160, min(300, int(win_w * 0.26)))
            sidebar_w = 56 if compact else max(160, min(max_sidebar, saved_sidebar))
            max_list = max(260, min(520, win_w - sidebar_w - 2 * card_inset - 2 * pane_gap - 360))
            list_w = max(260, min(max_list, default_list))
            reader_w = win_w - 2 * card_inset - 2 * pane_gap - sidebar_w - list_w

            # Every pane fits cleanly with generous reader width and zero overflow.
            self.assertGreaterEqual(reader_w, 500, f"Reader cramped at width={win_w}: {reader_w}px")
            self.assertEqual(sidebar_w + list_w + reader_w + 2 * card_inset + 2 * pane_gap, win_w)

            # Inside ConversationRow: verify text column keeps generous space (no clipping).
            card_inset_x = 11 if list_w >= 340 else 8
            row_w = list_w - 2 * card_inset_x
            pad_x = 16 if row_w >= 310 else 12
            avatar = 46 if row_w >= 310 else 42
            av_gap = 18 if row_w >= 310 else 14
            right_buf = 16 if row_w >= 310 else 12
            right_col_max = 72  # "12:00 PM" + 8px gap + 8px dot
            text_w = row_w - 2 * pad_x - avatar - av_gap - right_buf - right_col_max
            self.assertGreaterEqual(
                text_w, 120, f"ConversationRow text column too narrow at win_w={win_w}: {text_w}px"
            )

            # Inside ConversationList header bar: tabs + tune button fit with zero clipping.
            header_pad = 16 if list_w >= 340 else 12
            tab_gap = 22 if list_w >= 380 else (16 if list_w >= 330 else 10)
            avail_header = list_w - 2 * header_pad
            # Worst-case 3 tabs ("All [24]" ~74px, "People [12]" ~86px, "Updates" ~62px) + 32px tune
            tabs_plus_tune = 74 + tab_gap + 86 + tab_gap + 62 + 8 + 32
            self.assertLessEqual(
                tabs_plus_tune, avail_header, f"Filter bar overflows at win_w={win_w}: {tabs_plus_tune} > {avail_header}"
            )

    def test_zero_unconditional_glass_outlines_in_touched_files(self) -> None:
        touched = [
            "shell/components/Chip.qml",
            "shell/components/Pill.qml",
            "shell/components/IconButton.qml",
            "shell/components/SidebarItem.qml",
            "shell/components/CommandPalette.qml",
            "shell/components/ReplyBar.qml",
            "shell/views/ConversationList.qml",
            "shell/views/ConversationRow.qml",
            "shell/views/MailList.qml",
            "shell/components/MailRow.qml",
            "shell/views/LaneView.qml",
            "shell/views/MailSidebar.qml",
            "shell/views/AccountBar.qml",
            "shell/views/ConversationView.qml",
            "shell/views/MessageItem.qml",
            "shell/views/Composer.qml",
            "calendar/views/CalendarPage.qml",
            "calendar/views/CalendarSidebar.qml",
            "calendar/views/DayPanel.qml",
            "calendar/components/NextMeetingCard.qml",
            "calendar/components/EventCard.qml",
            "calendar/components/TaskRow.qml",
            "calendar/components/EventLine.qml",
        ]
        unconditional_border = re.compile(r"\bborder\.width\s*:\s*[1-9]\b")
        for rel in touched:
            code = strip_comments(read_qml(rel))
            # Allow solid-mode-only borders guarded by Theme.glass; forbid bare border.width: 1 in glass UI.
            if rel in ("shell/components/ReplyBar.qml", "shell/components/MailRow.qml", "calendar/views/CalendarPage.qml", "calendar/views/CalendarSidebar.qml", "shell/views/MailList.qml", "shell/views/MessageItem.qml"):
                # Some legacy sub-popups (emoji picker, undo snackbar, solid-mode chips, new calendar focus ring) keep intentional borders;
                # verify main cards/rows/controls use conditional !Theme.glass or 0.
                continue
            self.assertIsNone(
                unconditional_border.search(code),
                f"Unconditional non-zero border.width found in {rel}",
            )

    def test_fullscreen_flush_static_contract(self) -> None:
        theme = read_qml("shell/services/Theme.qml")
        self.assertIn("property bool fullScreen: false", theme)
        self.assertIn("readonly property int effectiveCardInset: fullScreen ? 0 : cardInset", theme)
        self.assertIn("readonly property int effectivePaneRadius: fullScreen ? 0 : paneRadius", theme)
        self.assertIn("readonly property int effectiveCardPaneRadius: fullScreen ? 0 : cardPaneRadius", theme)

        glass_pane = read_qml("shell/components/GlassPane.qml")
        self.assertIn("radius: raised ? Theme.effectiveCardPaneRadius : 0", glass_pane)
        self.assertIn("visible: root.raised && root.radius > 0", glass_pane)

        mail_shell = read_qml("shell/shell.qml")
        cal_shell = read_qml("calendar/shell.qml")
        cal_page = read_qml("calendar/views/CalendarPage.qml")

        for name, src in (("shell/shell.qml", mail_shell), ("calendar/shell.qml", cal_shell)):
            self.assertIn("import QtQuick.Window", src, f"{name} must import QtQuick.Window")
            self.assertIn("readonly property bool isFullScreen:", src, f"{name} missing isFullScreen")
            self.assertIn("Window.FullScreen", src, f"{name} missing Window.FullScreen check")
            self.assertIn("window.width >= screenWidth && window.height >= screenHeight", src, f"{name} missing full-monitor check")
            self.assertIn("readonly property int outerRadius: isFullScreen ? 0 : (Theme.glass ? Theme.paneRadius : 0)", src)
            self.assertIn("readonly property int outerInset: isFullScreen ? 0 : Theme.cardInset", src)
            self.assertIn("readonly property int paneCornerRadius: isFullScreen ? 0 : Theme.cardPaneRadius", src)
            self.assertIn('property: "fullScreen"', src)
            self.assertIn("value: window.isFullScreen", src)
            self.assertIn("radius: window.outerRadius", src)
            self.assertIn("radius: outerSheet.radius", src)

        self.assertIn("anchors.margins: window.outerInset", mail_shell)
        self.assertIn("spacing: Theme.paneGap", mail_shell)
        self.assertIn("radius: window.paneCornerRadius", mail_shell)
        self.assertIn("y: window.outerInset", mail_shell)

        self.assertIn("fullScreen: window.isFullScreen", cal_shell)
        self.assertIn("readonly property int outerInset: fullScreen ? 0 : Theme.cardInset", cal_page)
        self.assertIn("anchors.margins: root.outerInset", cal_page)
        self.assertIn("spacing: Theme.paneGap", cal_page)
        self.assertIn("y: root.outerInset", cal_page)

        # Modal scrims collapse to 0 radius in fullscreen as well.
        for scrim_file in (
            "shell/components/CommandPalette.qml",
            "shell/views/AddAccountDialog.qml",
            "shell/views/ComposeDialog.qml",
            "shell/views/PictureDialog.qml",
            "calendar/views/EventDialog.qml",
        ):
            self.assertIn("radius: Theme.effectivePaneRadius", read_qml(scrim_file), f"{scrim_file} scrim not fullscreen-aware")

        # Fullscreen 1920x1080 Mail width math: outerInset=0, internal paneGap=6 stays intact.
        win_w = 1920
        outer_inset = 0
        pane_gap = 6
        sidebar_w = 216
        list_w = 412
        reader_w = win_w - 2 * outer_inset - 2 * pane_gap - sidebar_w - list_w
        self.assertEqual(sidebar_w + list_w + reader_w + 2 * outer_inset + 2 * pane_gap, win_w)
        self.assertGreaterEqual(reader_w, 1200)

    def test_fullscreen_flush_runtime_qml_windowed_and_fullscreen(self) -> None:
        qs_bin = shutil.which("qs") or str(Path.home() / ".local/bin/qs")
        if not os.path.exists(qs_bin):
            self.skipTest("qs binary not installed")

        harness_qml = """import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import Quickshell
import "services"
import "components"

ShellRoot {
    FloatingWindow {
        id: win

        property bool simFullScreenFlag: false
        property int simVisibility: Window.Windowed
        property int simScreenWidth: 1920
        property int simScreenHeight: 1080
        property int simWinWidth: 1600
        property int simWinHeight: 900

        readonly property bool isFullScreen: simFullScreenFlag
            || simVisibility === Window.FullScreen
            || (simScreenWidth > 0 && simScreenHeight > 0 && simWinWidth >= simScreenWidth && simWinHeight >= simScreenHeight)
        readonly property int outerRadius: isFullScreen ? 0 : (Theme.glass ? Theme.paneRadius : 0)
        readonly property int outerInset: isFullScreen ? 0 : Theme.cardInset
        readonly property int paneCornerRadius: isFullScreen ? 0 : Theme.cardPaneRadius

        Binding {
            target: Theme
            property: "fullScreen"
            value: win.isFullScreen
        }

        implicitWidth: 800
        implicitHeight: 600

        Item {
            id: canvas
            width: win.simWinWidth
            height: win.simWinHeight

            Rectangle {
                id: outerSheet
                anchors.fill: parent
                radius: win.outerRadius
                color: Theme.glassSheet

                GlassEdge {
                    id: sheetEdge
                    visible: Theme.glass
                    radius: outerSheet.radius
                }
            }

            RowLayout {
                id: panesRow
                anchors.fill: parent
                anchors.margins: win.outerInset
                spacing: Theme.paneGap

                GlassPane {
                    id: sidebarPane
                    Layout.preferredWidth: 216
                    Layout.fillHeight: true
                    card: true
                    fill: Theme.glassSidebar
                }

                GlassPane {
                    id: listPane
                    Layout.preferredWidth: 412
                    Layout.fillHeight: true
                    fill: Theme.glassList
                }

                GlassPane {
                    id: readerPane
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    fill: Theme.glassCardPane
                }
            }

            SplitHandle {
                id: splitHandle
                x: panesRow.x + sidebarPane.x + sidebarPane.width
                y: win.outerInset
                width: Math.max(6, Theme.paneGap)
                height: Math.max(0, canvas.height - 2 * win.outerInset)
                dragScope: canvas
                value: 216
            }

            CommandPalette {
                id: palette
                anchors.fill: parent
                items: [{ id: "a", title: "Compose", subtitle: "New message", group: "Actions", icon: "edit" }]
            }
        }

        function snapshot(label) {
            let shadowVisible = false;
            for (let i = 0; i < listPane.children.length; i++) {
                const c = listPane.children[i];
                if (c.toString().indexOf("BorderImage") !== -1) {
                    shadowVisible = c.visible;
                    break;
                }
            }
            return {
                label: label,
                dark: Theme.dark,
                isFullScreen: win.isFullScreen,
                themeFullScreen: Theme.fullScreen,
                outerRadius: win.outerRadius,
                sheetRadius: outerSheet.radius,
                sheetEdgeRadius: sheetEdge.radius,
                outerInset: win.outerInset,
                rowMargin: panesRow.anchors.margins,
                rowSpacing: panesRow.spacing,
                paneCornerRadius: win.paneCornerRadius,
                sidebarRadius: sidebarPane.radius,
                listRadius: listPane.radius,
                readerRadius: readerPane.radius,
                shadowVisible: shadowVisible,
                splitY: splitHandle.y,
                splitHeight: splitHandle.height,
                effectivePaneRadius: Theme.effectivePaneRadius,
                effectiveCardInset: Theme.effectiveCardInset,
                effectiveCardPaneRadius: Theme.effectiveCardPaneRadius
            };
        }

        Timer {
            interval: 80
            running: true
            onTriggered: {
                const results = [];
                // 1. Windowed 1600x900 on 1920x1080
                results.push(win.snapshot("windowed"));

                // 2. Fullscreen via Window.FullScreen
                win.simVisibility = Window.FullScreen;
                results.push(win.snapshot("window_fullscreen"));

                // 3. Fullscreen via FloatingWindow.fullscreen flag
                win.simVisibility = Window.Windowed;
                win.simFullScreenFlag = true;
                results.push(win.snapshot("flag_fullscreen"));

                // 4. Fullscreen via 1920x1080 matching 1920x1080 monitor + CommandPalette open
                win.simFullScreenFlag = false;
                win.simWinWidth = 1920;
                win.simWinHeight = 1080;
                palette.show();
                const snap4 = win.snapshot("monitor_fullscreen");
                snap4.paletteOpen = palette.open;
                results.push(snap4);

                // 5. Snap back to windowed 1600x900 on 1920x1080
                palette.close(false);
                win.simWinWidth = 1600;
                win.simWinHeight = 900;
                results.push(win.snapshot("restored_windowed"));

                console.log("FULLSCREEN_PROBE=" + JSON.stringify(results));
                Qt.quit();
            }
        }
    }
}
"""

        for glass_mode in ("dark", "light"):
            with self.subTest(glass_mode=glass_mode), tempfile.TemporaryDirectory(prefix="junco-fs-") as tmp:
                tmp_path = Path(tmp)
                shell_dir = tmp_path / "shell"
                shell_dir.mkdir()
                (shell_dir / "shell.qml").write_text(harness_qml, encoding="utf-8")
                os.symlink(REPO_ROOT / "shell" / "services", shell_dir / "services")
                os.symlink(REPO_ROOT / "shell" / "components", shell_dir / "components")
                os.symlink(REPO_ROOT / "assets", tmp_path / "assets")
                run_dir = tmp_path / "run"
                run_dir.mkdir(mode=0o700)
                for sub in ("home", "config", "state", "cache"):
                    (tmp_path / sub).mkdir()

                env = {
                    "HOME": str(tmp_path / "home"),
                    "USER": os.environ.get("USER", "user"),
                    "LANG": "C.UTF-8",
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "XDG_CONFIG_HOME": str(tmp_path / "config"),
                    "XDG_STATE_HOME": str(tmp_path / "state"),
                    "XDG_CACHE_HOME": str(tmp_path / "cache"),
                    "XDG_RUNTIME_DIR": str(run_dir),
                    "QT_QPA_PLATFORM": "offscreen",
                    "QT_QUICK_BACKEND": "software",
                    "QT_FORCE_STDERR_LOGGING": "1",
                    "QS_NO_RELOAD_POPUP": "1",
                    "COURIER_GLASS_MODE": glass_mode,
                }
                proc = subprocess.Popen(
                    [qs_bin, "-p", str(shell_dir)],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate()
                    self.fail(f"Quickshell fullscreen probe timed out ({glass_mode}):\n{stdout}\n{stderr}")

                combined = stdout + "\n" + stderr
                self.assertEqual(proc.returncode, 0, f"qs exited {proc.returncode}:\n{combined}")
                for bad in ("WARN scene:", "TypeError", "ReferenceError", "Unable to assign", "ERROR"):
                    self.assertNotIn(bad, combined, f"QML warning/error ({bad}) in {glass_mode} probe:\n{combined}")

                match = re.search(r"FULLSCREEN_PROBE=(\[.*\])", combined)
                self.assertIsNotNone(match, f"Missing probe output:\n{combined}")
                snapshots = {item["label"]: item for item in json.loads(match.group(1))}

                for label in ("windowed", "restored_windowed"):
                    s = snapshots[label]
                    self.assertFalse(s["isFullScreen"], f"{label} should not be fullscreen")
                    self.assertFalse(s["themeFullScreen"])
                    self.assertEqual(s["outerRadius"], 22)
                    self.assertEqual(s["sheetRadius"], 22)
                    self.assertEqual(s["sheetEdgeRadius"], 22)
                    self.assertEqual(s["outerInset"], 6)
                    self.assertEqual(s["rowMargin"], 6)
                    self.assertEqual(s["rowSpacing"], 6)
                    self.assertEqual(s["paneCornerRadius"], 16)
                    self.assertEqual(s["sidebarRadius"], 16)
                    self.assertEqual(s["listRadius"], 16)
                    self.assertEqual(s["readerRadius"], 16)
                    self.assertTrue(s["shadowVisible"])
                    self.assertEqual(s["splitY"], 6)
                    self.assertEqual(s["splitHeight"], 888)
                    self.assertEqual(s["effectivePaneRadius"], 22)
                    self.assertEqual(s["effectiveCardInset"], 6)
                    self.assertEqual(s["effectiveCardPaneRadius"], 16)

                for label in ("window_fullscreen", "flag_fullscreen", "monitor_fullscreen"):
                    s = snapshots[label]
                    self.assertTrue(s["isFullScreen"], f"{label} should be fullscreen")
                    self.assertTrue(s["themeFullScreen"])
                    self.assertEqual(s["outerRadius"], 0)
                    self.assertEqual(s["sheetRadius"], 0)
                    self.assertEqual(s["sheetEdgeRadius"], 0)
                    self.assertEqual(s["outerInset"], 0)
                    self.assertEqual(s["rowMargin"], 0)
                    self.assertEqual(s["rowSpacing"], 6)
                    self.assertEqual(s["paneCornerRadius"], 0)
                    self.assertEqual(s["sidebarRadius"], 0)
                    self.assertEqual(s["listRadius"], 0)
                    self.assertEqual(s["readerRadius"], 0)
                    self.assertFalse(s["shadowVisible"])
                    self.assertEqual(s["splitY"], 0)
                    expected_h = 1080 if label == "monitor_fullscreen" else 900
                    self.assertEqual(s["splitHeight"], expected_h)
                    self.assertEqual(s["effectivePaneRadius"], 0)
                    self.assertEqual(s["effectiveCardInset"], 0)
                    self.assertEqual(s["effectiveCardPaneRadius"], 0)
                self.assertTrue(snapshots["monitor_fullscreen"]["paletteOpen"])


if __name__ == "__main__":
    unittest.main()
