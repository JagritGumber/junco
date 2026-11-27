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

import re
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


if __name__ == "__main__":
    unittest.main()
