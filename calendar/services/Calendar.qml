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
    readonly property string mailLauncher: `${Quickshell.shellDir}/../bin/courier`
    readonly property string stateDir: `${Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state"}/courier`

    property var status: ({ state: "never" })
    property bool syncing: false
    property bool signingIn: false
    property string signingInAccount: ""
    property var _syncJob: null
    property var _authJob: null
    property bool reminders: true

    signal feedback(string message)
    property string todayDay: dayOf(new Date())
    // Updated on the single 60s clock tick (zero busy-wait polling).
    property double nowMs: Date.now()
    // "month", "week", "day" or "agenda".
    property string view: "month"
    // The picked day. The month, week or day on screen is the one holding it.
    property string selected: todayDay
    property var calendars: []
    property var accounts: []
    // Calendar ids switched off in "My calendars", id -> true.
    property var hidden: ({})
    // User-resized side panel widths, persisted in calendar-view.json.
    property int sidebarWidth: 228
    property int dayPanelWidth: 296
    // Every event touching the days on screen.
    property var events: []
    // Events strictly for the picked day (never future months).
    property var around: []
    // Events strictly for Today (keeps Join next meeting accurate from any date).
    property var todayEvents: []
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
    readonly property var nextMeeting: {
        const ref = nowMs;
        const upcoming = visible(todayEvents)
            .filter(event => !event.allDay && touches(event, todayDay) && !isEventPast(event, ref))
            .sort((a, b) => eventStartMs(a) - eventStartMs(b));
        return upcoming.length > 0 ? upcoming[0] : null;
    }
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

    function eventStartMs(event): double {
        if (!event || event.allDay)
            return 0;
        const parsed = Date.parse(event.start ?? "");
        if (!Number.isNaN(parsed))
            return parsed;
        if (!event.startDay)
            return 0;
        const base = dateOf(event.startDay);
        return base.getTime() + (event.startMinutes ?? 0) * 60000;
    }

    function eventEndMs(event): double {
        if (!event || event.allDay)
            return 0;
        const parsed = Date.parse(event.end ?? "");
        if (!Number.isNaN(parsed))
            return parsed;
        if (!event.endDay && !event.startDay)
            return 0;
        const base = dateOf(event.endDay ?? event.startDay);
        return base.getTime() + (event.endMinutes ?? 0) * 60000;
    }

    function formatDurationShort(totalMinutes: int): string {
        const mins = Math.max(1, Math.round(totalMinutes));
        if (mins < 60)
            return `${mins}m`;
        const hours = Math.floor(mins / 60);
        const rem = mins % 60;
        return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`;
    }

    function isEventLive(event, refMs): bool {
        if (!event || event.allDay)
            return false;
        const start = eventStartMs(event);
        const end = eventEndMs(event);
        return start <= refMs && refMs < end;
    }

    function isEventPast(event, refMs): bool {
        if (!event || event.allDay)
            return false;
        return eventEndMs(event) <= refMs;
    }

    function countdownLabel(event, refMs): string {
        if (!event || event.allDay)
            return "";
        const start = eventStartMs(event);
        const end = eventEndMs(event);
        if (start <= refMs && refMs < end) {
            const leftMin = Math.max(1, Math.ceil((end - refMs) / 60000));
            return `Live now · ${formatDurationShort(leftMin)} left`;
        }
        if (start > refMs) {
            const waitMin = Math.ceil((start - refMs) / 60000);
            if (waitMin <= 0)
                return "Starting now";
            return `In ${formatDurationShort(waitMin)}`;
        }
        return "Ended";
    }

    function attendeeLabel(event): string {
        const count = Number(event?.attendeeCount ?? 0);
        if (count <= 1)
            return "";
        return `${count} people`;
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

    property bool ready: false
    property int bootstrapRequest: 0
    property int spanRequest: 0
    property int aroundRequest: 0
    property int todayRequest: 0
    property int everythingRequest: 0
    property string loadedSpanFirst: ""
    property string loadedSpanAfter: ""

    function loadSpan(): void {
        if (!ready)
            return;
        const first = spanFirst;
        const after = spanAfter;
        const request = ++spanRequest;
        run(["range", first, after], found => {
            if (request === root.spanRequest) {
                root.events = found;
                root.loadedSpanFirst = first;
                root.loadedSpanAfter = after;
                if (root.selected >= first && root.selected < after) {
                    const selEvents = found.filter(ev => root.touches(ev, root.selected));
                    root.around = selEvents;
                    if (root.selected === root.todayDay)
                        root.todayEvents = selEvents;
                }
            }
        });
    }

    function loadAround(): void {
        if (!ready)
            return;
        // Fast path: if the picked day sits inside the already-loaded span,
        // derive its events in-memory with zero Python subprocess spawn.
        if (loadedSpanFirst !== "" && selected >= loadedSpanFirst && selected < loadedSpanAfter) {
            const selEvents = events.filter(ev => touches(ev, selected));
            around = selEvents;
            if (selected === todayDay)
                todayEvents = selEvents;
            return;
        }
        const request = ++aroundRequest;
        run(["range", selected, addDays(selected, 1)], found => {
            if (request === root.aroundRequest) {
                root.around = found;
                if (root.selected === root.todayDay)
                    root.todayEvents = found;
            }
        });
    }

    function loadToday(): void {
        if (!ready)
            return;
        if (loadedSpanFirst !== "" && todayDay >= loadedSpanFirst && todayDay < loadedSpanAfter) {
            todayEvents = events.filter(ev => touches(ev, todayDay));
            return;
        }
        const request = ++todayRequest;
        run(["range", todayDay, addDays(todayDay, 1)], found => {
            if (request === root.todayRequest)
                root.todayEvents = found;
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

    // Single-process startup & refresh: loads calendars, accounts, status,
    // span events, selected day, today, and actionables in ONE Python call.
    function refresh(): void {
        nowMs = Date.now();
        const first = spanFirst;
        const after = spanAfter;
        const sel = selected;
        const today = todayDay;
        const request = ++bootstrapRequest;
        spanRequest++;
        aroundRequest++;
        todayRequest++;
        run(["bootstrap", first, after, sel, "--today", today], result => {
            if (request !== root.bootstrapRequest)
                return;
            root.calendars = result.calendars ?? [];
            root.accounts = result.accounts ?? [];
            root.status = result.status ?? ({ state: "never" });
            root.events = result.events ?? [];
            root.loadedSpanFirst = first;
            root.loadedSpanAfter = after;
            root.around = result.around ?? [];
            root.todayEvents = result.todayEvents ?? [];
            if (result.actionables !== undefined)
                Tasks.applyLoaded(result.actionables);
        });
        if (query !== "" || everything.length > 0)
            loadEverything();
    }

    function reauthAccountFor(st: var): string {
        if (!st)
            return "";
        const idPattern = /^[a-z0-9][a-z0-9-]{0,31}$/;
        const direct = typeof st.account === "string" ? st.account.trim() : "";
        if (idPattern.test(direct))
            return direct;
        const msg = typeof st.message === "string" ? st.message : "";
        const match = /(?:^|\s)courier-auth\s+add\s+([^\s]+)(?:\s+--calendar-write)?\s*$/.exec(msg);
        if (!match)
            return "";
        let token = match[1];
        if (token.endsWith("."))
            token = token.slice(0, -1);
        return idPattern.test(token) ? token : "";
    }

    function syncNow(): void {
        if (signingIn) {
            feedback(`Finish signing in to ${signingInAccount} in your browser…`);
            return;
        }
        if (syncing) {
            feedback("Sync already in progress…");
            return;
        }
        syncing = true;
        feedback("Syncing calendars…");
        const job = syncJobComponent.createObject(root, { command: [engine, "sync"] });
        _syncJob = job;
        job.finished = (ok, value, errText) => {
            if (root._syncJob === job)
                root._syncJob = null;
            root.syncing = false;
            if (value && typeof value.state === "string") {
                root.status = value;
                if (value.state === "ok") {
                    root.refresh();
                    root.feedback("Calendars synced");
                } else if (value.state === "signed-out") {
                    const acct = root.reauthAccountFor(value);
                    root.feedback(acct ? `Sign in again for ${acct}` : (value.message || "Sign in again to sync calendars"));
                } else {
                    root.feedback(value.message || "Calendar sync failed.");
                }
            } else {
                root.feedback(errText || "Calendar sync failed.");
            }
        };
        job.running = true;
    }

    function signInAgain(accountName: string): void {
        const clean = (accountName || "").trim();
        if (!/^[a-z0-9][a-z0-9-]{0,31}$/.test(clean)) {
            feedback("Couldn't determine which account to sign in.");
            return;
        }
        if (signingIn) {
            feedback(`Finish signing in to ${signingInAccount} in your browser…`);
            return;
        }
        signingIn = true;
        signingInAccount = clean;
        feedback(`Opening Google sign-in for ${clean}…`);
        const job = syncJobComponent.createObject(root, { command: [engine, "reauth", clean] });
        _authJob = job;
        job.finished = (ok, value, errText) => {
            if (root._authJob === job)
                root._authJob = null;
            root.signingIn = false;
            root.signingInAccount = "";
            if (ok && value && !value.error) {
                if (value.status && typeof value.status.state === "string")
                    root.status = value.status;
                root.refresh();
                if (value.status && value.status.state !== "ok")
                    root.feedback(value.status.message || "Signed in, calendar sync needs attention.");
                else
                    root.feedback(`Signed in ${value.email || clean} · calendars synced`);
            } else {
                root.feedback(value?.error || errText || "Sign-in didn't finish.");
            }
        };
        job.running = true;
    }

    function cancelSignIn(): void {
        if (_authJob) {
            _authJob.signal(15);
            feedback("Sign-in cancelled");
        }
    }

    function openMail(): void {
        Quickshell.execDetached([mailLauncher]);
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
        saveView(true);
    }

    function showOnly(id: string): void {
        const next = {};
        for (const calendar of calendars)
            if (calendar.id !== id)
                next[calendar.id] = true;
        hidden = next;
        saveView(true);
    }

    function showAll(): void {
        hidden = {};
        saveView(true);
    }

    function setView(name: string): void {
        view = name;
        saveView(false);
    }

    function saveView(updateFeed): void {
        viewFile.setText(JSON.stringify({
            view: root.view,
            hidden: Object.keys(root.hidden),
            sidebarWidth: root.sidebarWidth,
            dayPanelWidth: root.dayPanelWidth
        }) + "\n");
        if (updateFeed === true)
            run(["next", "--write"], () => {});
    }

    // One process per request, so a slow one never swallows the next.
    function run(args, done, failed) {
        const job = jobComponent.createObject(root, { command: [engine, ...args] });
        job.done = done;
        job.failed = failed ?? null;
        job.running = true;
    }

    onSpanFirstChanged: if (ready) Qt.callLater(loadSpan)
    onSpanAfterChanged: if (ready) Qt.callLater(loadSpan)
    onSelectedChanged: if (ready) Qt.callLater(loadAround)
    onTodayDayChanged: if (ready) Qt.callLater(loadToday)
    onQueryChanged: if (query !== "" && everything.length === 0)
        loadEverything()

    Component.onCompleted: {
        ready = true;
        refresh();
        remindersProc.exec(["systemctl", "--user", "is-enabled", "courier-remind.timer"]);
    }

    Component.onDestruction: {
        if (_authJob)
            _authJob.signal(15);
    }

    // Single minute tick: keeps countdowns and midnight rollover fresh (zero busy-wait).
    Timer {
        interval: 60 * 1000
        running: true
        repeat: true
        onTriggered: {
            const current = new Date();
            root.nowMs = current.getTime();
            const now = root.dayOf(current);
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

    Component {
        id: syncJobComponent

        Process {
            id: syncJob

            property var finished
            property bool exited: false
            property bool outDone: false
            property int exitCode: -1
            property bool settled: false

            function maybeFinish(): void {
                if (settled || !exited || !outDone)
                    return;
                settled = true;
                let value = null;
                const raw = syncOut.text.trim();
                if (raw !== "") {
                    try {
                        value = JSON.parse(raw);
                    } catch (e) {
                        console.warn("Courier: couldn't read calendar job output:", e);
                    }
                }
                const errText = syncErr.text.trim().split("\n").filter(l => l.trim() !== "").pop() || "";
                const ok = exitCode === 0 && value !== null && value.error === undefined;
                if (syncJob.finished)
                    syncJob.finished(ok, value, errText);
                syncJob.destroy();
            }

            stdout: StdioCollector {
                id: syncOut

                onStreamFinished: {
                    syncJob.outDone = true;
                    syncJob.maybeFinish();
                }
            }

            stderr: StdioCollector {
                id: syncErr
            }

            onExited: code => {
                syncJob.exitCode = code;
                syncJob.exited = true;
                syncJob.maybeFinish();
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
                if (typeof saved.sidebarWidth === "number" && saved.sidebarWidth >= 180 && saved.sidebarWidth <= 360)
                    root.sidebarWidth = Math.round(saved.sidebarWidth);
                if (typeof saved.dayPanelWidth === "number" && saved.dayPanelWidth >= 220 && saved.dayPanelWidth <= 440)
                    root.dayPanelWidth = Math.round(saved.dayPanelWidth);
            } catch (e) {
                console.warn("Courier: couldn't read calendar-view.json:", e);
            }
        }
    }
}
