//@ pragma DefaultEnv QS_NO_RELOAD_POPUP=1
// The window's class, so docks and bars find courier-calendar.desktop (and its
// icon) instead of Quickshell's own entry. Read at startup only.
//@ pragma AppId courier-calendar

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.services
import qs.views
import qs.components
import "services/palette.js" as Palette

// Junco Calendar: the same glass as Junco Mail (../shell), sharing its Theme
// and components through links in services/ and components/: one clear sheet
// (the window) with the calendars sidebar on it and the month/week view and
// the day panel as raised cards, no outlines, Hyprland's own blur behind the
// whole sheet. Tuned for a 15" 1920x1080 screen (full and half tiles).
ShellRoot {
    IpcHandler {
        target: "calendar"

        function show(): void {
            window.visible = true;
        }

        function day(day: string): void {
            window.visible = true;
            if (/^\d{4}-\d{2}-\d{2}$/.test(day))
                Calendar.selected = day;
        }
    }

    FloatingWindow {
        id: window

        // Preview builds of this branch say so in the title (Mail does too).
        // Drop before merging.
        title: "Junco Calendar · glass preview"
        implicitWidth: 1560
        implicitHeight: 940
        color: Theme.windowBg
        // Required on Wayland so Hyprland gets an alpha buffer at all.
        surfaceFormat.opaque: !Theme.glass

        // Hyprland blurs behind the whole rounded sheet (ext-background-effect-v1).
        BackgroundEffect.blurRegion: Theme.glass ? sheetRegion : null

        readonly property Region sheetRegion: Region {
            item: glassCanvas
            radius: Theme.paneRadius
        }

        onVisibleChanged: if (!visible)
            Qt.quit()

        Item {
            id: glassCanvas

            anchors.fill: parent

            // The sheet: the window's one outer edge, no rim line.
            Rectangle {
                anchors.fill: parent
                radius: Theme.glass ? Theme.paneRadius : 0
                color: Theme.glassSheet

                GlassEdge {
                    visible: Theme.glass
                    radius: Theme.paneRadius
                }
            }

            // The frost: a static noise tile over the glass, under the cards.
            Image {
                anchors.fill: parent
                visible: Theme.glass
                source: `file://${Quickshell.shellDir}/../assets/glass/grain.png`
                fillMode: Image.Tile
                smooth: false
                opacity: Theme.grainOpacity
            }

            CalendarPage {
                id: calendarPage

                anchors.fill: parent
            }
        }

        Shortcut {
            sequence: "Ctrl+K"
            onActivated: commandPalette.toggle()
        }

        function runCalendarPaletteAction(item: var): void {
            const action = item?.action;
            if (!action || action.type === "noop")
                return;
            if (action.type === "prefill") {
                commandPalette.setQuery(action.text ?? "");
                return;
            }
            commandPalette.close(false);

            switch (action.type) {
            case "join_next_meeting": {
                const ev = action.event;
                if (ev && /^https?:\/\//i.test(ev.video ?? "")) {
                    Qt.openUrlExternally(ev.video);
                    calendarPage.showToast(`Joining “${ev.title || "meeting"}”`);
                } else {
                    Calendar.selected = Calendar.todayDay;
                    calendarPage.ensureDayPanelVisible();
                    calendarPage.showToast(`Focused “${ev?.title || "next meeting"}”`);
                }
                break;
            }
            case "add_actionable":
                Tasks.add(action.title, action.dueDate || Calendar.todayDay, "");
                Calendar.selected = action.dueDate || Calendar.todayDay;
                calendarPage.ensureDayPanelVisible();
                calendarPage.showToast(`Added actionable: “${action.title}”`);
                break;
            case "new_event_dialog":
                calendarPage.createEvent(Calendar.selected, -1);
                break;
            case "create_event_prefilled":
                calendarPage.createEventPrefilled(action.title, action.day, action.startMinutes, action.endMinutes);
                break;
            case "create_event_direct":
                calendarPage.saveQuickEvent(action.title, action.day, action.startMinutes, action.endMinutes);
                break;
            case "jump_today":
                Calendar.selected = Calendar.todayDay;
                break;
            case "set_view":
                calendarPage.closeSearch();
                Calendar.setView(action.view);
                break;
            case "toggle_sidebar":
                calendarPage.toggleSidebar();
                break;
            case "toggle_day_panel":
                calendarPage.toggleDayPanel();
                break;
            case "sync":
                Calendar.syncNow();
                calendarPage.showToast("Syncing calendars…");
                break;
            case "open_mail":
                Calendar.openMail();
                break;
            case "toggle_glass":
                Theme.toggleGlassMode();
                calendarPage.showToast(Theme.dark ? "Switched to Dark glass" : "Switched to Light glass");
                break;
            case "focus_event":
                if (action.event && action.event.startDay) {
                    calendarPage.closeSearch();
                    Calendar.selected = action.event.startDay;
                    calendarPage.ensureDayPanelVisible();
                }
                break;
            case "toggle_actionable":
                Tasks.toggle(action.id);
                calendarPage.ensureDayPanelVisible();
                break;
            }
        }

        CommandPalette {
            id: commandPalette

            readonly property var ranked: {
                if (!open)
                    return { modeBadge: "", modeBadgeTone: "", items: [] };
                const refMs = Calendar.nowMs;
                const next = Calendar.nextMeeting;
                const pool = Calendar.everything.length > 0
                    ? Calendar.visible(Calendar.everything)
                    : Calendar.visible((Calendar.todayEvents ?? []).concat(Calendar.shownEvents ?? []).concat(Calendar.dayEvents ?? []));
                return Palette.rankCalendarItems(query, {
                    todayDay: Calendar.todayDay,
                    selectedDay: Calendar.selected,
                    view: Calendar.view,
                    sidebarShown: calendarPage.sidebarShown,
                    dayShown: calendarPage.dayShown,
                    dark: Theme.dark,
                    nextMeeting: next,
                    nextMeetingLive: next ? Calendar.isEventLive(next, refMs) : false,
                    nextMeetingCountdown: next ? Calendar.countdownLabel(next, refMs) : "",
                    events: pool,
                    actionables: Tasks.items ?? []
                }, new Date(refMs));
            }

            anchors.fill: parent
            placeholder: "Type a command, event, or todo…"
            modeLabel: "Junco Calendar"
            emptyHint: "Try \"todo Send slides\", \"new Design Review 4pm\", or \"week\""
            items: ranked.items
            activeBadge: ranked.modeBadge
            activeBadgeTone: ranked.modeBadgeTone || "complement"
            onOpened: {
                Calendar.nowMs = Date.now();
                if (Calendar.everything.length === 0)
                    Calendar.loadEverything();
            }
            onTriggered: item => window.runCalendarPaletteAction(item)
            onTabRequested: (currentQuery, selectedItem) => {
                const next = Palette.tabCompleteQuery(currentQuery, selectedItem, "calendar");
                if (next !== currentQuery)
                    setQuery(next);
            }
        }
    }
}
