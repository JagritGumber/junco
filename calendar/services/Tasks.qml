pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// Today's actionables, backed by SQLite (calendar_actionables) through
// engine/courier_calendar.py. Uncompleted items from earlier days carry over
// into Today with carryOver=true until checked off or dismissed.
// Zero polling: reloads only on day change, user action, or state file change.
Singleton {
    id: root

    property var items: []
    property int requestId: 0
    readonly property int openCount: items.filter(item => !item.completed).length

    function applyLoaded(list: var): void {
        if (Array.isArray(list))
            root.items = list;
    }

    function loadFor(day: string): void {
        const target = day || Calendar.selected || Calendar.todayDay;
        const seq = ++requestId;
        Calendar.run(["actionables", "list", "--day", target], result => {
            if (seq === root.requestId && Array.isArray(result))
                root.items = result;
        });
    }

    function reload(): void {
        loadFor(Calendar.selected);
    }

    function add(title: string, dueDate: string, eventUid: string): void {
        const clean = (title ?? "").trim();
        if (clean === "")
            return;
        const target = dueDate || Calendar.selected || Calendar.todayDay;
        const args = ["actionables", "add", clean, "--due", target];
        const uid = (eventUid ?? "").trim();
        if (uid !== "")
            args.push("--event-uid", uid);
        Calendar.run(args, () => root.reload());
    }

    // One-click prep actionable linked to a meeting card.
    function addPrepFor(event: var, dueDate: string): void {
        if (!event)
            return;
        const uid = String(event.uid || event.id || "").trim();
        const title = `Prep: ${event.title || "Meeting"}`;
        // Avoid adding duplicate open prep items for the exact same meeting.
        const exists = items.some(item => !item.completed && (
            (uid !== "" && item.eventUid === uid && item.title === title) ||
            (uid === "" && item.title === title)
        ));
        if (exists)
            return;
        add(title, dueDate || Calendar.selected || Calendar.todayDay, uid);
    }

    function toggle(id: var): void {
        Calendar.run(["actionables", "toggle", String(id)], () => root.reload());
    }

    function remove(id: var): void {
        Calendar.run(["actionables", "delete", String(id)], () => root.reload());
    }

    Connections {
        target: Calendar

        function onSelectedChanged(): void {
            if (Calendar.ready)
                root.reload();
        }

        function onTodayDayChanged(): void {
            if (Calendar.ready)
                root.reload();
        }
    }

    // Initial load is piggybacked onto Calendar.bootstrap() (single Python call).
    // Picks up CLI/external actionable changes with zero polling.
    FileView {
        path: `${Calendar.stateDir}/next-meeting.json`
        watchChanges: true
        printErrors: false
        onFileChanged: root.reload()
    }
}
