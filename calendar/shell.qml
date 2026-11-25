//@ pragma DefaultEnv QS_NO_RELOAD_POPUP=1
// The window's class, so docks and bars find courier-calendar.desktop (and its
// icon) instead of Quickshell's own entry. Read at startup only.
//@ pragma AppId courier-calendar

import QtQuick
import Quickshell
import Quickshell.Io
import qs.services
import qs.views

// Calendar: a read-only copy of your Google calendars (courier-calendar.timer
// syncs it every 5 minutes), calendars kept on this PC, and your to-dos.
// Reminders fire from courier-remind.timer even while this window is closed.
// It shares the engine, theme and basic components with Courier (../shell).
ShellRoot {
    // `qs ipc -p <this folder> call calendar show` brings the window back.
    IpcHandler {
        target: "calendar"

        function show(): void {
            window.visible = true;
        }

        // Opens one day, e.g. "2026-12-11".
        function day(day: string): void {
            window.visible = true;
            if (/^\d{4}-\d{2}-\d{2}$/.test(day))
                Calendar.selected = day;
        }
    }

    FloatingWindow {
        id: window

        title: "Calendar"
        implicitWidth: 1560
        implicitHeight: 940
        color: Theme.m3surface

        // Closing the window quits, so the next launch starts fresh instead of
        // finding a windowless copy still running.
        onVisibleChanged: if (!visible)
            Qt.quit()

        CalendarPage {
            anchors.fill: parent
            anchors.margins: 12
        }
    }
}
