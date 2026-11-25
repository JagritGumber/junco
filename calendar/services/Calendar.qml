pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// The agenda from engine/courier_calendar.py: every Google calendar copied to
// this PC (courier-calendar.timer, every 5 minutes) plus events kept only
// here. Reminders fire from courier-remind.timer even while Courier is closed.
//
// The Calendar page reads days as "YYYY-MM-DD" strings, never Date objects:
// strings compare in order and never shift across a timezone or DST change.
Singleton {
    id: root

    readonly property string engine: `${Quickshell.shellDir}/../engine/courier_calendar.py`
    readonly property string stateDir: `${Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state"}/courier`

    property var status: ({ state: "never" })
    property bool reminders: true
    property string todayDay: dayOf(new Date())
    // "month", "week", "day" or "agenda".
    property string view: "month"
    // The picked day. The month, week or day on screen is the one holding it.
    property string selected: todayDay
    property var calendars: []
    property var accounts: []
    // Calendar ids switched off in "My calendars", id -> true.
    property var hidden: ({})
    // Every event touching the days on screen.
    property var events: []
    // The picked day and the six weeks after it, for the day panel.
    property var around: []
    // Search covers every copied event: 60 days back, a year ahead.
    property string query: ""
    property var everything: []

    readonly property string spanFirst: view === "month" ? monday(firstOfMonth(selected)) : view === "week" ? monday(selected) : view === "agenda" ? firstOfMonth(selected) : selected
    readonly property string spanAfter: view === "month" ? addDays(spanFirst, 7 * monthRows) : view === "week" ? addDays(spanFirst, 7) : view === "agenda" ? addMonths(firstOfMonth(selected), 1) : addDays(selected, 1)
    // Always six weeks, filled out with the next month's days, so the rows
    // keep their height from month to month (a month spans four to six weeks).
    readonly property int monthRows: 6

    readonly property var shownEvents: visible(events)
    readonly property var dayEvents: visible(around).filter(event => touches(event, selected))
    readonly property var comingUp: visible(around).filter(event => event.startDay > selected).slice(0, 3)
    readonly property var found: {
        const needle = query.trim().toLowerCase();
        if (needle === "")
            return [];
        return visible(everything).filter(event => `${event.title} ${event.where} ${event.notes} ${event.calendar}`.toLowerCase().includes(needle));
    }

    // The events of the calendars switched on, each once. The same event can
    // sit in two calendars: a meeting both your accounts are invited to, or
    // two subscriptions to the same holidays (Google's "Holidays in India" in
    // English and in English (India)). It shows from the first. Hidden
    // calendars drop out first, so switching one copy off never hides the
    // other.
    function visible(list: var): var {
        const seen = new Set();
        const shown = [];
        for (const event of list) {
            if (hidden[event.calendarId])
                continue;
            const key = `${(event.title ?? "").trim().toLowerCase()}|${event.start}|${event.end}`;
            if (seen.has(key))
                continue;
            seen.add(key);
            shown.push(event);
        }
        return shown;
    }
    readonly property var localCalendars: calendars.filter(calendar => calendar.source === "local")

    // Days ----------------------------------------------------------------------

    function dayOf(when) {
        return `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, "0")}-${String(when.getDate()).padStart(2, "0")}`;
    }

    function dateOf(day) {
        const [year, month, number] = day.split("-").map(Number);
        return new Date(year, month - 1, number);
    }

    function addDays(day, count) {
        const date = dateOf(day);
        date.setDate(date.getDate() + count);
        return dayOf(date);
    }

    // The same day of another month, or that month's last day when it's shorter.
    function addMonths(day, count) {
        const date = dateOf(day);
        const target = new Date(date.getFullYear(), date.getMonth() + count, 1);
        const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
        target.setDate(Math.min(date.getDate(), last));
        return dayOf(target);
    }

    function firstOfMonth(day) {
        return `${day.slice(0, 7)}-01`;
    }

    function daysInMonth(day) {
        const date = dateOf(day);
        return new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
    }

    function monday(day) {
        return addDays(day, -((dateOf(day).getDay() + 6) % 7));
    }

    // Rounded, so a 23- or 25-hour DST day still counts as one.
    function daysBetween(from, to) {
        return Math.round((dateOf(to) - dateOf(from)) / 86400000);
    }

    function touches(event, day) {
        return event.startDay <= day && day <= event.endDay;
    }

    function format(day, pattern) {
        return Qt.formatDate(dateOf(day), pattern);
    }

    // "10:30 am" for minutes after midnight; past 24 h it wraps to the next day.
    function clock(minutes) {
        const hour = Math.floor(minutes / 60) % 24;
        const minute = minutes % 60;
        return `${hour % 12 === 0 ? 12 : hour % 12}:${String(minute).padStart(2, "0")} ${hour < 12 ? "am" : "pm"}`;
    }

    // "10am", "10:30pm": the short form inside a month cell.
    function shortClock(minutes) {
        const hour = Math.floor(minutes / 60) % 24;
        const minute = minutes % 60;
        return `${hour % 12 === 0 ? 12 : hour % 12}${minute ? ":" + String(minute).padStart(2, "0") : ""}${hour < 12 ? "am" : "pm"}`;
    }

    function iconFor(event) {
        if (event.kind === "birthday")
            return "cake";
        if ((event.video ?? "") !== "")
            return "videocam";
        return "event";
    }

    // The title above the month grid, week or day.
    function spanTitle(): string {
        if (view === "month" || view === "agenda")
            return format(selected, "MMMM yyyy");
        // The year only when it isn't this one, so the title never gets cut.
        const year = day => day.slice(0, 4) === todayDay.slice(0, 4) ? "" : ` ${day.slice(0, 4)}`;
        if (view === "day")
            return format(selected, "ddd, d MMM") + year(selected);
        const last = addDays(spanFirst, 6);
        if (spanFirst.slice(0, 7) === last.slice(0, 7))
            return `${format(spanFirst, "d")} – ${format(last, "d MMM")}${year(last)}`;
        if (spanFirst.slice(0, 4) === last.slice(0, 4))
            return `${format(spanFirst, "d MMM")} – ${format(last, "d MMM")}${year(last)}`;
        return `${format(spanFirst, "d MMM yyyy")} – ${format(last, "d MMM yyyy")}`;
    }

    // The arrows move one month, week or day.
    function step(direction: int): void {
        if (view === "month" || view === "agenda")
            selected = addMonths(selected, direction);
        else
            selected = addDays(selected, direction * (view === "week" ? 7 : 1));
    }

    // Timed events side by side where they overlap: each gets a lane and the
    // number of lanes in its cluster, so a day column splits only where needed.
    function lanes(list) {
        const timed = list.filter(event => !event.allDay).slice().sort((a, b) => a.startMinutes - b.startMinutes || b.endMinutes - a.endMinutes);
        const placed = [];
        let cluster = [];
        let laneEnds = [];
        let clusterEnd = -1;
        const close = () => {
            for (const item of cluster)
                item.lanes = laneEnds.length;
            cluster = [];
            laneEnds = [];
        };
        for (const event of timed) {
            // Short events still take 30 minutes of height, so they overlap as drawn.
            const end = Math.max(event.endMinutes, event.startMinutes + 30);
            if (event.startMinutes >= clusterEnd)
                close();
            let lane = laneEnds.findIndex(laneEnd => laneEnd <= event.startMinutes);
            if (lane === -1) {
                lane = laneEnds.length;
                laneEnds.push(end);
            } else {
                laneEnds[lane] = end;
            }
            clusterEnd = Math.max(clusterEnd, end);
            const item = { event: event, lane: lane, lanes: 1 };
            cluster.push(item);
            placed.push(item);
        }
        close();
        return placed;
    }

    // Loading -------------------------------------------------------------------

    property int spanRequest: 0
    property int aroundRequest: 0
    property int everythingRequest: 0

    function loadSpan(): void {
        const request = ++spanRequest;
        run(["range", spanFirst, spanAfter], found => {
            if (request === root.spanRequest)
                root.events = found;
        });
    }

    function loadAround(): void {
        const request = ++aroundRequest;
        run(["range", selected, addDays(selected, 43)], found => {
            if (request === root.aroundRequest)
                root.around = found;
        });
    }

    function loadEverything(): void {
        const request = ++everythingRequest;
        run(["range", addDays(todayDay, -60), addDays(todayDay, 366)], found => {
            if (request === root.everythingRequest)
                root.everything = found;
        });
    }

    function loadCalendars(): void {
        run(["calendars"], result => {
            root.calendars = result.calendars;
            root.accounts = result.accounts;
            root.status = result.status;
        });
    }

    // After a sync or an edit: everything on screen again.
    function refresh(): void {
        loadCalendars();
        loadSpan();
        loadAround();
        if (query !== "")
            loadEverything();
    }

    function syncNow(): void {
        status = Object.assign({}, status, { state: status.state === "ok" ? "syncing" : status.state });
        Quickshell.execDetached(["systemctl", "--user", "start", "--no-block", "courier-calendar.service"]);
    }

    function setReminders(on: bool): void {
        reminders = on;
        Quickshell.execDetached(["systemctl", "--user", on ? "enable" : "disable", "--now", "courier-remind.timer"]);
    }

    // Events on this PC ----------------------------------------------------------

    // done(error): "" when saved, else the engine's reason.
    function save(id, event, done) {
        const args = id === "" ? ["add", JSON.stringify(event)] : ["update", id, JSON.stringify(event)];
        run(args, () => {
            root.refresh();
            done("");
        }, error => done(error));
    }

    function remove(id: string): void {
        run(["delete", id], () => root.refresh());
    }

    function addCalendar(name, done) {
        run(["add-calendar", name], () => {
            root.loadCalendars();
            done("");
        }, error => done(error));
    }

    // My calendars ---------------------------------------------------------------

    function setHidden(id: string, off: bool): void {
        const next = Object.assign({}, hidden);
        if (off)
            next[id] = true;
        else
            delete next[id];
        hidden = next;
        saveView();
    }

    function showOnly(id: string): void {
        const next = {};
        for (const calendar of calendars)
            if (calendar.id !== id)
                next[calendar.id] = true;
        hidden = next;
        saveView();
    }

    function showAll(): void {
        hidden = {};
        saveView();
    }

    function setView(name: string): void {
        view = name;
        saveView();
    }

    function saveView(): void {
        viewFile.setText(JSON.stringify({ view: root.view, hidden: Object.keys(root.hidden) }) + "\n");
    }

    // One process per request, so a slow one never swallows the next.
    function run(args, done, failed) {
        const job = jobComponent.createObject(root, { command: [engine, ...args] });
        job.done = done;
        job.failed = failed ?? null;
        job.running = true;
    }

    onSpanFirstChanged: Qt.callLater(loadSpan)
    onSpanAfterChanged: Qt.callLater(loadSpan)
    onSelectedChanged: Qt.callLater(loadAround)
    onQueryChanged: if (query !== "" && everything.length === 0)
        loadEverything()

    Component.onCompleted: {
        refresh();
        remindersProc.exec(["systemctl", "--user", "is-enabled", "courier-remind.timer"]);
    }

    // Past midnight, today moves on.
    Timer {
        interval: 60 * 1000
        running: true
        repeat: true
        onTriggered: {
            const now = root.dayOf(new Date());
            if (now !== root.todayDay) {
                if (root.selected === root.todayDay)
                    root.selected = now;
                root.todayDay = now;
            }
        }
    }

    Component {
        id: jobComponent

        Process {
            id: job

            property var done
            property var failed

            stdout: StdioCollector {
                onStreamFinished: {
                    let value = null;
                    try {
                        value = JSON.parse(text);
                    } catch (e) {
                        console.warn("Courier: couldn't read the calendar:", e);
                    }
                    if (value !== null && value.error === undefined)
                        job.done(value);
                    else if (job.failed)
                        job.failed(value?.error ?? "Something went wrong.");
                    job.destroy();
                }
            }
        }
    }

    Process {
        id: remindersProc

        stdout: StdioCollector {
            onStreamFinished: root.reminders = text.trim() === "enabled"
        }
    }

    // Each calendar sync rewrites its status, so this also catches new events.
    FileView {
        path: `${root.stateDir}/calendar.json`
        watchChanges: true
        onFileChanged: root.refresh()
    }

    // Which view and calendars you left on, kept between launches.
    FileView {
        id: viewFile

        path: `${root.stateDir}/calendar-view.json`
        atomicWrites: true
        printErrors: false
        onLoaded: {
            try {
                const saved = JSON.parse(text());
                if (["month", "week", "day", "agenda"].includes(saved.view))
                    root.view = saved.view;
                const hidden = {};
                for (const id of saved.hidden ?? [])
                    hidden[id] = true;
                root.hidden = hidden;
            } catch (e) {
                console.warn("Courier: couldn't read calendar-view.json:", e);
            }
        }
    }
}
