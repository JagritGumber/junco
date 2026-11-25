pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io
import "plaintext.js" as PlainText

// Courier's mail window, read from the local index by engine/courier_mail.py.
// courier-sync (a systemd timer, plus IMAP push) downloads mail; each finished
// sync rewrites sync.json and the window reloads.
//
// The inbox is conversations, Beeper-style: people as chats, a sender's
// updates and the newsletters as their own lists. Other folders (Sent,
// Archive, Trash…) are email lists by day. Changes to Gmail (archive, delete,
// spam) show at once, then "Deleted · Undo" once Gmail has them.
Singleton {
    id: root

    readonly property string engine: `${Quickshell.shellDir}/../engine/courier_mail.py`
    readonly property string stateDir: `${Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state"}/courier`
    readonly property string calendarLauncher: `${Quickshell.shellDir}/../bin/calendar`

    // Where you are --------------------------------------------------------------------

    // "smart" (the inbox's conversations) or another folder's email list.
    property string folder: "smart"
    // One account's mail ("" = every account together), from the account bar.
    property string account: ""
    property string search: ""
    property bool unreadOnly: false
    property bool withFiles: false
    // Folded rows opened in place, row id -> true.
    property var expanded: ({})
    property string selectedRow: ""
    // The open email's id; `reading` is its JSON once it arrives. While one
    // is open the reader takes the place of the conversation.
    property string openId: ""
    property var reading: null
    property bool readingFailed: false
    readonly property bool readerOpen: openId !== ""
    // Emails opened before, for the reader's back arrow.
    property var history: []
    // The email last opened from a sender's list, kept highlighted there.
    property string lastOpenedId: ""
    // The Add account window is open.
    property bool addingAccount: false
    // A menu over the whole window, for panes too narrow to hold their own.
    property var windowMenu: null

    // Conversations (the inbox) ------------------------------------------------------

    property string selectedId: ""
    property string lane: "all"
    // Typing in the list's search narrows the conversations.
    property string query: ""
    property var conversations: []
    // The open conversation's messages, oldest first.
    property var messages: []
    property bool threadLoading: false
    property bool threadFailed: false
    // Bumped on every local change, so views bound to nested arrays refresh.
    property int revision: 0

    // People are conversations; machine mail gets its own lanes so it never
    // buries a human.
    readonly property var lanes: [
        { id: "all", label: "All", chip: true },
        { id: "people", label: "People", chip: true },
        { id: "updates", label: "Updates", chip: true },
        { id: "newsletters", label: "Newsletters", chip: false }
    ]

    function unreadIn(laneId: string): int {
        revision;
        return conversations.filter(c => laneId === "all" || c.lane === laneId).reduce((total, c) => total + c.unread, 0);
    }

    readonly property var visibleConversations: {
        revision;
        const needle = query.trim().toLowerCase();
        return conversations.filter(c => !hidden[c.id] && (lane === "all" || c.lane === lane) && (needle === "" || `${c.name} ${c.preview} ${c.address}`.toLowerCase().includes(needle)));
    }

    readonly property var selected: {
        revision;
        return conversations.find(c => c.id === selectedId) ?? null;
    }

    function isConversation(id: string): bool {
        return id !== "";
    }

    // What the engine said --------------------------------------------------------------

    // { id, email, label, picture, pictureSource, defaultSource }: picture is
    // the one shown (yours, else the account's own Google photo or Gravatar,
    // else "" for its initial); pictureSource says which ("custom",
    // "google", "gravatar", ""); defaultSource what "back to default" shows.
    property var accounts: []
    // Bumped when an account's picture changes, so its image reloads.
    property int pictureVersion: 0
    // The picture being framed for an account: { account, source } or null.
    property var pictureCrop: null
    // The account card shown on hovering an account's circle (AccountCard).
    property var accountCard: null
    // sync.json's per-account state: { id: { state, have?, expected? } }.
    property var syncStatus: ({})
    property var folders: []
    property var listing: null
    property bool listLoading: false
    property bool listFailed: false
    property var storage: null
    property var contacts: []

    // Emails and conversations taken off the screen by an action, id ->
    // { done }, so a list that loads before Gmail (or the next sync) catches
    // up can't bring them back.
    property var hidden: ({})

    readonly property var currentFolder: folders.find(f => f.id === folder) ?? null
    readonly property bool inInbox: ["smart", "dev"].includes(folder)

    // A folder's list as one flat model: day headers, rows, and the emails of
    // a folded row opened in place.
    readonly property var flatRows: {
        const flat = [];
        for (const group of listing?.sections ?? []) {
            const rows = group.rows.filter(row => (!unreadOnly || row.unread > 0) && (!withFiles || row.attachment) && !(row.ids.length > 0 && row.ids.every(id => hidden[id])));
            if (rows.length === 0)
                continue;
            if (group.name)
                flat.push({ type: "header", name: group.name, key: `h:${group.name}` });
            for (const row of rows) {
                flat.push(Object.assign({ type: "row", key: row.id }, row));
                if (expanded[row.id])
                    for (const member of row.members.filter(m => !hidden[m.id]))
                        flat.push(Object.assign({ type: "member", key: `${row.id}/${member.id}`, row: row.id }, member));
            }
        }
        return flat;
    }

    // Loading ------------------------------------------------------------------------------

    // Every engine call runs in its own process; an answer nobody wants anymore
    // is ignored by its caller. done(ok, value): ok is false on {"error"}.
    // Returns the process, for the rare call that may need stopping.
    function run(args: var, done: var): var {
        const job = jobComponent.createObject(root, { command: [engine, ...args] });
        job.done = done ?? null;
        job.running = true;
        return job;
    }

    property int listRequest: 0
    property int readRequest: 0
    property int threadRequest: 0
    property int conversationsRequest: 0

    function loadFolders(): void {
        run(["folders", ...accountArgs()], (ok, result) => {
            if (ok)
                folders = result.folders;
        });
    }

    // The inbox's conversations, and the open one's messages again (quietly:
    // no "Loading…", and a reply still sending keeps its bubble). `after`
    // runs once both are in.
    function loadConversations(after: var): void {
        const request = ++conversationsRequest;
        run(["conversations", ...accountArgs()], (ok, list) => {
            if (request !== conversationsRequest)
                return;
            if (!ok) {
                sayError("Couldn't read the mail index.");
                return;
            }
            conversations = list;
            revision++;
            // Open the newest person on first load, or when the open one left
            // the inbox.
            if (selectedId === "" || !conversations.some(c => c.id === selectedId)) {
                const first = conversations.find(c => c.lane === "people") ?? conversations[0];
                if (first)
                    open(first.id);
                if (after)
                    after();
                return;
            }
            const id = selectedId;
            const thread = ++threadRequest;
            run(["thread", id, ...accountArgs()], (fresh, items) => {
                if (thread === threadRequest && id === selectedId && fresh) {
                    messages = items.concat(messages.filter(m => m.sending));
                    revision++;
                }
                if (after)
                    after();
            });
        });
    }

    // `after` runs once the list is in.
    function loadList(after: var): void {
        if (folder === "smart")
            return;
        const request = ++listRequest;
        listLoading = true;
        listFailed = false;
        const done = (ok, result) => {
            if (request !== listRequest)
                return;
            listLoading = false;
            listFailed = !ok;
            if (!ok) {
                if (result?.error)
                    sayError(result.error);
                return;
            }
            listing = result;
            if (after)
                after();
        };
        if (folder === "trash") {
            // Trash lives only in Gmail, and asking takes ~2.5 s (most of it
            // Gmail's sign-in). So Trash as last seen shows at once, and
            // Gmail's answer replaces it.
            const trash = (rows, subtitle) => ({ title: "Trash", subtitle: subtitle, sections: [{ name: "Recently deleted", rows: rows.filter(row => !account || row.account === account).map(row => Object.assign({ open: row.id, ids: [row.id], kind: "trash", category: "trash", icon: "delete", avatar: "", unread: 0, chips: [], members: [], count: 1 }, row)) }] });
            run(["trash", "--cached"], (ok, result) => {
                if (ok && result.cached && request === listRequest && listLoading)
                    listing = trash(result.rows, "Checking Gmail…");
            });
            run(["trash"], (ok, result) => done(ok, ok ? trash(result.rows, "Deleted in Gmail; restore within 30 days") : result));
        } else if (folder === "scheduled")
            run(["scheduled"], (ok, result) => done(ok, ok ? { title: "Scheduled", subtitle: "Waiting to be sent", sections: [{ name: "Waiting", rows: result.items.map(item => ({ id: `s:${item.file}`, file: item.file, open: "", ids: [], kind: "scheduled", category: "scheduled", icon: "schedule_send", avatar: "", title: item.to || "(no one yet)", subtitle: item.subject || "(no subject)", time: whenText(item.at), unread: 0, chips: [], members: [], count: 1 })) }] } : result));
        else
            run(["list", folder, ...(search.trim() ? ["--search", search.trim()] : []), ...accountArgs()], done);
    }

    function refresh(): void {
        loadFolders();
        if (folder === "smart")
            loadConversations(null);
        else
            loadList(null);
    }

    // A sync finished: reload, then let go of emails the actions hid, since the
    // fresh lists no longer have them (letting go first would flash them back).
    function synced(): void {
        loadFolders();
        // New mail of a taught template has its fields now (courier-sync).
        loadTemplates();
        if (tableTemplate)
            loadTable();
        if (folder === "smart")
            loadConversations(() => forgetSettled());
        else
            loadList(() => forgetSettled());
    }

    // Moving around ---------------------------------------------------------------------

    function openFolder(id: string): void {
        if (folder !== id) {
            folder = id;
            search = "";
            expanded = {};
            listing = null;
            selectedRow = "";
            closeMessage();
        }
        refresh();
    }

    // Every email, by words (subject, sender, text) or notmuch syntax.
    function runSearch(text: string): void {
        search = text;
        loadList(null);
    }

    // From the inbox's search box: the results are an email list in All Mail.
    function searchEverything(text: string): void {
        if (text.trim() === "")
            return;
        openFolder("all");
        runSearch(text.trim());
    }

    function toggleRow(row: var): void {
        selectedRow = row.id;
        if (row.kind === "group" && row.count > 1) {
            const next = Object.assign({}, expanded);
            if (next[row.id])
                delete next[row.id];
            else
                next[row.id] = true;
            expanded = next;
        }
        if (row.open)
            openMessage(row.open, true);
    }

    // One conversation: a person's chat, a sender's updates, the newsletters.
    function open(id: string): void {
        closeMessage();
        selectedId = id;
        messages = [];
        threadLoading = true;
        threadFailed = false;
        const request = ++threadRequest;
        run(["thread", id, ...accountArgs()], (ok, items) => {
            if (request !== threadRequest || id !== selectedId)
                return;
            threadLoading = false;
            threadFailed = !ok;
            messages = ok ? items : [];
            // A chat is read once its messages are on screen; a lane's emails
            // are marked read one by one as you open them.
            const conversation = conversations.find(c => c.id === id);
            if (ok && conversation && conversation.kind === "person" && conversation.unread > 0) {
                conversation.unread = 0;
                revision++;
                run(["read", id, ...accountArgs()], null);
                loadFolders();
            }
        });
    }

    function openMessage(id: string, fresh: bool): void {
        if (!id)
            return;
        if (fresh && openId && openId !== id)
            history = history.concat([openId]).slice(-30);
        openId = id;
        lastOpenedId = id;
        reading = null;
        readingFailed = false;
        const request = ++readRequest;
        // Deleted mail leaves this PC, so Trash is read from Gmail.
        const fromTrash = folder === "trash";
        run(fromTrash ? ["trash-open", id] : ["message", id, "--theme", readerTheme()], (ok, mail) => {
            if (request !== readRequest)
                return;
            if (!ok) {
                readingFailed = true;
                return;
            }
            reading = mail;
            // Opening an email reads it, here and (next sync) in Gmail.
            if (!fromTrash && markLocalRead(id))
                run(["mark", "read", id], () => loadFolders());
        });
    }

    // Back to the conversation (or the empty reader).
    function closeMessage(): void {
        openId = "";
        reading = null;
        readingFailed = false;
        history = [];
    }

    function back(): void {
        if (history.length === 0) {
            closeMessage();
            return;
        }
        const previous = history[history.length - 1];
        history = history.slice(0, -1);
        openMessage(previous, false);
    }

    // Flips unread marks on screen; true if the email was unread.
    function markLocalRead(id: string): bool {
        let changed = false;
        for (const group of listing?.sections ?? [])
            for (const row of group.rows) {
                const member = row.members.find(m => m.id === id && m.unread);
                if (member) {
                    member.unread = false;
                    changed = true;
                }
                if (row.open === id && row.unread > 0 && (row.count === 1 || !member)) {
                    row.unread = Math.max(0, row.unread - 1);
                    changed = true;
                } else if (member) {
                    row.unread = Math.max(0, row.unread - 1);
                }
            }
        for (const message of messages)
            if (message.id === id && message.unread) {
                message.unread = false;
                changed = true;
                if (selected)
                    selected.unread = Math.max(0, selected.unread - 1);
            }
        if (changed) {
            listing = listing ? Object.assign({}, listing) : listing;
            messages = messages.slice();
            revision++;
        }
        return changed || (reading?.unread ?? false);
    }

    // Changing mail ---------------------------------------------------------------------

    readonly property var undoing: ({ archive: "inbox", inbox: "archive", trash: "untrash", untrash: "trash", spam: "unspam", unspam: "spam" })
    // action -> [while Gmail does it, once it's done, icon]
    readonly property var verbs: ({
            archive: ["Archiving", "Archived", "archive"],
            inbox: ["Moving to Inbox", "Moved to Inbox", "move_to_inbox"],
            trash: ["Deleting", "Deleted", "delete"],
            untrash: ["Restoring", "Restored", "restore_from_trash"],
            spam: ["Reporting spam", "Marked as spam", "report"],
            unspam: ["Moving to Inbox", "Moved to Inbox", "move_to_inbox"]
        })

    // Takes these emails (or conversations) off the screen at once, and moves
    // on from the open email if it went.
    function hide(ids: var): void {
        const next = Object.assign({}, hidden);
        for (const id of ids)
            next[id] = { done: false };
        hidden = next;
        revision++;
        if (ids.includes(openId)) {
            const after = folder === "smart" ? null : flatRows.find(item => item.type === "row" && item.open && !ids.includes(item.open));
            if (after) {
                selectedRow = after.id;
                openMessage(after.open, false);
            } else {
                closeMessage();
            }
        }
    }

    // Gmail has it: they stay hidden until the next sync shows the same. If it
    // failed, they come back.
    function settle(ids: var, ok: bool): void {
        const next = Object.assign({}, hidden);
        for (const id of ids) {
            if (ok)
                next[id] = { done: true };
            else
                delete next[id];
        }
        hidden = next;
        revision++;
        if (ok)
            hiddenTimer.restart();
    }

    function forgetSettled(): void {
        const next = {};
        for (const id in hidden)
            if (!hidden[id].done)
                next[id] = hidden[id];
        hidden = next;
        revision++;
    }

    function leaves(action: string): bool {
        if (["trash", "spam"].includes(action))
            return true;
        if (action === "archive")
            return inInbox;
        if (["inbox", "untrash", "unspam"].includes(action))
            return folder === "archive" || folder === "trash";
        return false;
    }

    // Archive, delete, spam: on screen at once, "Deleting…" while Gmail does
    // it, then "Deleted · Undo".
    function act(action: string, ids: var): void {
        if (ids.length === 0)
            return;
        const verb = verbs[action];
        const what = ids.length === 1 ? "" : ` ${ids.length} emails`;
        const gone = leaves(action);
        if (gone)
            hide(ids);
        else if (reading && ids.includes(reading.id))
            reading = Object.assign({}, reading, { inbox: ["inbox", "untrash", "unspam"].includes(action) ? true : action === "archive" ? false : reading.inbox });
        sayPending(`${verb[0]}${what}…`, verb[2]);
        run(["act", action, ...ids], (ok, result) => {
            if (gone)
                settle(ids, ok);
            if (!ok) {
                sayError(result?.error ?? "Gmail didn't take that change.");
                refresh();
                return;
            }
            loadFolders();
            // Trash is Gmail's own list: show it as Gmail has it now.
            if (folder === "trash")
                loadList(null);
            if (folder === "smart")
                loadConversations(null);
            say(`${verb[1]}${what}`, undoing[action] ? { kind: "act", action: undoing[action], ids: ids } : null, verb[2]);
        });
    }

    // Archives every inbox email of a conversation; it leaves the list until
    // someone writes again.
    function archiveConversation(id: string): void {
        const conversation = conversations.find(c => c.id === id);
        const at = visibleConversations.findIndex(c => c.id === id);
        hide([id]);
        if (selectedId === id) {
            const next = visibleConversations[Math.min(at, visibleConversations.length - 1)];
            if (next)
                open(next.id);
        }
        sayPending(`Archiving ${conversation?.name ?? "conversation"}…`, "archive");
        run(["act", "archive", "--conversation", id, ...accountArgs()], (ok, result) => {
            settle([id], ok);
            if (!ok) {
                sayError(result?.error ?? "Gmail didn't archive that.");
                loadConversations(null);
                return;
            }
            loadFolders();
            loadConversations(null);
            say(`Archived ${conversation?.name ?? "conversation"}`, result.ids.length > 0 ? { kind: "act", action: "inbox", ids: result.ids, conversation: id } : null, "archive");
        });
    }

    // Read, unread, star: on screen at once, then in the index; the next sync
    // passes it on to Gmail.
    function mark(action: string, ids: var): void {
        if (ids.length === 0)
            return;
        if (reading && ids.includes(reading.id) && (action === "star" || action === "unstar"))
            reading = Object.assign({}, reading, { starred: action === "star" });
        for (const group of listing?.sections ?? [])
            for (const row of group.rows)
                if (row.ids.some(id => ids.includes(id))) {
                    if (action === "unread")
                        row.unread = Math.max(row.unread, 1);
                    else if (action === "read")
                        row.unread = 0;
                    else
                        row.starred = action === "star";
                }
        for (const message of messages)
            if (ids.includes(message.id)) {
                if (action === "read" || action === "unread")
                    message.unread = action === "unread";
                else
                    message.starred = action === "star";
            }
        if (listing)
            listing = Object.assign({}, listing);
        messages = messages.slice();
        revision++;
        run(["mark", action, ...ids], ok => {
            if (!ok)
                sayError("Couldn't update those emails.");
            loadFolders();
        });
    }

    function openCalendar(day: string): void {
        Quickshell.execDetached(day ? [calendarLauncher, day] : [calendarLauncher]);
    }

    // A meeting from an email, onto the calendar kept on this PC.
    function addMeeting(meeting: var): void {
        const event = { title: meeting.title, start: meeting.allDay ? meeting.day : meeting.start, end: meeting.allDay ? meeting.day : meeting.end, allDay: meeting.allDay, where: meeting.link || meeting.where || "", reminders: [10] };
        if (meeting.allDay)
            event.end = Qt.formatDate(new Date(new Date(meeting.day).getTime() + 86400000), "yyyy-MM-dd");
        const job = calendarJob.createObject(root, { command: [`${Quickshell.shellDir}/../engine/courier_calendar.py`, "add", JSON.stringify(event)] });
        job.done = ok => {
            if (!ok) {
                sayError("Couldn't add that to your calendar.");
                return;
            }
            if (reading?.details?.meeting)
                reading = Object.assign({}, reading, { details: Object.assign({}, reading.details, { meeting: Object.assign({}, reading.details.meeting, { added: true }) }) });
            say("Added to your calendar on this PC", null, "event_available");
        };
        job.running = true;
    }

    // An attachment opened in the system viewer, from a private copy: only
    // pictures, PDFs and text, with a safe name (the engine decides, and
    // says to save anything else).
    function previewAttachment(id: string, number: int): void {
        run(["preview", id, String(number)], (ok, result) => {
            if (ok && /^file:\/\//.test(result.url ?? ""))
                Qt.openUrlExternally(result.url);
            else
                sayError(result?.error ?? "Couldn't open that file.");
        });
    }

    function saveAttachment(id: string, number: int): void {
        run(["attachment", id, String(number)], (ok, saved) => {
            if (ok)
                say(`Saved ${saved.name} to Downloads`, null, "download");
            else
                sayError("Couldn't save that attachment.");
        });
    }

    // The email as designed, in the browser (scripts blocked by its policy).
    function viewOriginal(id: string): void {
        run(["original", id], (ok, result) => {
            if (ok)
                Qt.openUrlExternally(`file://${result.path}`);
            else
                sayError("Couldn't open the original.");
        });
    }

    function cancelScheduled(file: string): void {
        run(["unschedule", file], (ok, result) => {
            ok ? say("Scheduled email cancelled", null, "cancel_schedule_send") : sayError(result?.error ?? "Couldn't cancel that.");
            refresh();
        });
    }

    function sendScheduledNow(file: string): void {
        run(["send-now", file], (ok, result) => {
            ok ? say("Sent", null, "send") : sayError(result?.error ?? "Couldn't send that.");
            refresh();
        });
    }

    // Accounts --------------------------------------------------------------------------------

    // Signs a Google account in through the browser; its mail starts syncing
    // and shows in the same inbox as the others.
    // The sign-in under way, so Cancel can stop it.
    property var signingIn: null

    function addAccount(name: string, done: var): void {
        signingIn = run(["account-add", name], (ok, result) => {
            signingIn = null;
            if (ok) {
                // --fetch: the new account's own picture, right away.
                loadAccounts(true);
                refresh();
            }
            done(ok ? "" : result?.error ?? "Sign-in didn't finish.", result);
        });
    }

    // Google showed an error, or you changed your mind: the engine stops the
    // browser sign-in and answers "Sign-in cancelled."
    function cancelAddAccount(): void {
        if (signingIn)
            signingIn.signal(15);
    }

    function accountColor(id: string): color {
        const at = accounts.findIndex(a => a.id === id);
        return [Theme.m3primary, Theme.m3tertiary, Theme.m3error, Theme.m3success][Math.max(0, at) % 4];
    }

    function accountArgs(): var {
        return account ? ["--account", account] : [];
    }

    // Shows one account's mail, or every account's ("").
    function setAccount(id: string): void {
        if (account === id)
            return;
        account = id;
        selectedId = "";
        conversations = [];
        messages = [];
        listing = null;
        closeMessage();
        refresh();
    }

    // fetch: first look up any account's own picture not looked up yet (the
    // engine goes online only for those).
    function loadAccounts(fetch: bool): void {
        run(fetch ? ["accounts", "--fetch"] : ["accounts"], (ok, list) => {
            if (!ok)
                return;
            const added = list.some(a => !accounts.some(known => known.id === a.id));
            if (JSON.stringify(list) !== JSON.stringify(accounts))
                pictureVersion++;
            accounts = list;
            if (added && accounts.length > 0)
                loadStorage();
            // An account that's gone stops being the one shown.
            if (account && !list.some(a => a.id === account))
                setAccount("");
        });
    }

    // How far an account's first download is, 0 to 1, or -1 when it isn't
    // downloading.
    function progressOf(id: string): real {
        const entry = syncStatus[id];
        return entry?.state === "downloading" && entry.expected > 0 ? Math.min(1, entry.have / entry.expected) : -1;
    }

    function readSyncStatus(text: string): void {
        let next = {};
        try {
            next = JSON.parse(text).accounts ?? {};
        } catch (e) {
            return;
        }
        // Say so when an account's first download is done.
        for (const id in next)
            if (syncStatus[id]?.state === "downloading" && next[id].state === "ok")
                say(`${accounts.find(a => a.id === id)?.email ?? id} is fully downloaded`, null, "download_done");
        syncStatus = next;
    }

    // Another picture for an account: the file picker, then the picture
    // dialog to frame it (PictureDialog).
    function setAccountPicture(id: string): void {
        const picker = pickerComponent.createObject(root, {
            command: ["kdialog", "--title", `Choose a picture for ${accounts.find(a => a.id === id)?.email ?? id}`, "--getopenfilename", Quickshell.env("HOME"), "Pictures (*.png *.jpg *.jpeg *.webp *.gif *.bmp)"]
        });
        picker.done = paths => {
            if (paths.length > 0)
                pictureCrop = { account: id, source: paths[0] };
        };
        picker.running = true;
    }

    // crop: [x, y, size] in the image's own pixels. done(error): "" when saved.
    function saveAccountPicture(id: string, source: string, crop: var, done: var): void {
        run(["account-picture", id, source, "--crop", crop.join(",")], (ok, result) => {
            if (ok) {
                pictureVersion++;
                loadAccounts(false);
            }
            done(ok ? "" : result?.error ?? "Couldn't use that picture.");
        });
    }

    // Back to the account's own picture (Google photo, Gravatar, or initial).
    function useDefaultPicture(id: string): void {
        // The engine answers with the account as it now shows.
        run(["account-picture", id, "--clear"], (ok, result) => {
            if (!ok) {
                sayError(result?.error ?? "Couldn't change the picture.");
                return;
            }
            accounts = accounts.map(a => a.id === id ? result : a);
            pictureVersion++;
        });
    }

    // An account's picture actions, for its card and its right-click menu:
    // [{ icon, label, run }]. Change picture opens the file picker, then the
    // picture dialog to frame it.
    function pictureActions(id: string): var {
        const info = accounts.find(a => a.id === id);
        const actions = [{ icon: "add_a_photo", label: info?.picture ? "Change picture…" : "Set a picture…", run: () => setAccountPicture(id) }];
        // Your own picture: back to the account's (its Google photo,
        // Gravatar, or initial when it has neither).
        if (info?.pictureSource === "custom") {
            const back = { google: ["account_circle", "Use Google photo"], gravatar: ["account_circle", "Use Gravatar"] }[info.defaultSource] ?? ["hide_image", "Remove picture"];
            actions.push({ icon: back[0], label: back[1], run: () => useDefaultPicture(id) });
        }
        return actions;
    }

    // An account's Gmail storage, { used, limit } in bytes, or null until known.
    function storageOf(id: string): var {
        return (storage?.accounts ?? []).find(a => a.account === id) ?? null;
    }

    function accountLabel(id: string): string {
        return accounts.find(a => a.id === id)?.label ?? id;
    }

    // Times ---------------------------------------------------------------------------------

    function isoLocal(when: date): string {
        return Qt.formatDateTime(when, "yyyy-MM-ddTHH:mm:ss");
    }

    // "Today, 18:00", "Tomorrow, 08:00", "Sat 23 Nov, 09:00" for epoch seconds.
    function whenText(epoch: real): string {
        const moment = new Date(epoch * 1000);
        const today = new Date();
        const days = Math.round((new Date(moment.getFullYear(), moment.getMonth(), moment.getDate()) - new Date(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000);
        const day = days === 0 ? "Today" : days === 1 ? "Tomorrow" : days === -1 ? "Yesterday" : Qt.formatDate(moment, moment.getFullYear() === today.getFullYear() ? "ddd d MMM" : "ddd d MMM yyyy");
        return `${day}, ${Qt.formatTime(moment, "HH:mm")}`;
    }

    // The bar at the bottom ------------------------------------------------------------------

    // { text, icon, pending, undo, error }
    property var notice: null
    property string error: ""

    function say(text: string, undo: var, icon: var): void {
        notice = { text: text, undo: undo ?? null, icon: icon ?? "check_circle", pending: false, error: false };
        noticeTimer.interval = undo ? 10000 : 5000;
        noticeTimer.restart();
    }

    // While Gmail is still doing it; replaced by say() or sayError().
    function sayPending(text: string, icon: string): void {
        notice = { text: text, undo: null, icon: icon, pending: true, error: false };
        noticeTimer.stop();
    }

    function sayError(text: string): void {
        notice = { text: text, undo: null, icon: "error", pending: false, error: true };
        noticeTimer.interval = 8000;
        noticeTimer.restart();
    }

    onErrorChanged: if (error !== "") {
        sayError(error);
        error = "";
    }

    function undo(): void {
        const step = notice?.undo;
        if (!step)
            return;
        sayPending("Undoing…", "undo");
        run(["act", step.action, ...step.ids], (ok, result) => {
            if (!ok) {
                sayError(result?.error ?? "Couldn't undo that.");
            } else {
                // Whatever was hidden comes back the moment it's undone.
                settle(step.conversation ? [step.conversation, ...step.ids] : step.ids, false);
                say("Undone", null, "undo");
            }
            refresh();
        });
    }

    Timer {
        id: noticeTimer

        interval: 5000
        onTriggered: root.notice = null
    }

    // Hidden emails a sync hasn't caught up with in this long come back anyway.
    Timer {
        id: hiddenTimer

        interval: 3 * 60 * 1000
        onTriggered: root.forgetSettled()
    }

    // Writing --------------------------------------------------------------------------------

    // The email being written: { mode: "new" | "reply" | "replyall" | "forward",
    // id, account, to, cc, bcc, subject, body, attachments (paths), forwarded
    // (names of the original's attachments) }. Closing keeps it until sent.
    property var draft: null
    property bool composing: false
    property bool sending: false
    property string composeError: ""
    // The engine refused an email with no text: the compose window asks
    // whether to send it anyway.
    property bool composeEmpty: false

    function loadContacts(): void {
        if (contacts.length === 0)
            run(["contacts"], (ok, list) => {
                if (ok)
                    contacts = list;
            });
    }

    function compose(mode: string, id: string): void {
        composeError = "";
        composeEmpty = false;
        loadContacts();
        if (mode === "new") {
            // Picks up an unsent new email where it was left.
            if (!draft || draft.mode !== "new")
                draft = { mode: "new", id: "", account: accounts[0]?.id ?? "", to: [], cc: [], bcc: [], subject: "", body: "", attachments: [], forwarded: [] };
            composing = true;
            return;
        }
        draft = { mode: mode, id: id, account: "", to: [], cc: [], bcc: [], subject: "", body: "", attachments: [], forwarded: [], loading: true };
        composing = true;
        run(["draft", mode, id], (ok, prefill) => {
            if (!draft || draft.id !== id)
                return;
            if (!ok) {
                composeError = prefill?.error ?? "Couldn't open that email.";
                return;
            }
            draft = Object.assign({}, draft, { account: prefill.account, to: prefill.to, cc: prefill.cc, subject: prefill.subject, forwarded: prefill.attachments, loading: false });
        });
    }

    function discardDraft(): void {
        draft = null;
        composing = false;
        composeError = "";
        composeEmpty = false;
    }

    // Sends now, or at `at` (a date) when given.
    function sendDraft(fields: var, at: var): void {
        if (sending)
            return;
        const args = ["compose", "--account", fields.account || "", "--subject", fields.subject, "--body", fields.body];
        for (const person of fields.to)
            args.push("--to", person);
        for (const person of fields.cc)
            args.push("--cc", person);
        for (const person of fields.bcc)
            args.push("--bcc", person);
        for (const path of fields.attachments)
            args.push("--attach", path);
        if (fields.mode === "reply" || fields.mode === "replyall")
            args.push("--reply-to", fields.id);
        else if (fields.mode === "forward")
            args.push("--forward", fields.id);
        if (at)
            args.push("--at", isoLocal(at));
        // Only after "Send anyway": the engine refuses an email with no text
        // otherwise, so nothing goes out empty by accident.
        if (fields.emptyOk)
            args.push("--empty-ok");
        sending = true;
        composeError = "";
        composeEmpty = false;
        run(args, (ok, result) => {
            sending = false;
            if (!ok) {
                if (result?.empty)
                    composeEmpty = true;
                else
                    composeError = result?.error ?? "Sending failed.";
                return;
            }
            draft = null;
            composing = false;
            say(at ? `Scheduled for ${whenText(result.at)}` : "Sent", null, at ? "schedule_send" : "send");
            if (at)
                refresh();
        });
    }

    // A chat reply in a person's conversation: the bubble shows at once with a
    // clock, which turns into ticks (or an error mark) once msmtp sends it.
    function send(text: string): void {
        const body = text.trim();
        if (!selected || selected.kind !== "person" || body === "")
            return;
        const pending = {
            from: "me",
            day: "Today",
            time: Qt.formatTime(new Date(), "HH:mm"),
            body: body,
            attachments: [],
            sending: true
        };
        messages = messages.concat([pending]);
        selected.preview = `You: ${body.split("\n")[0]}`;
        selected.time = Qt.formatTime(new Date(), "HH:mm");
        revision++;
        sendComponent.createObject(root, {
            pending: pending,
            command: [engine, "send", selected.id, "--body", body],
            running: true
        });
    }

    // A reply from the bar under an open email: to whoever Reply would pick.
    function quickReply(id: string, body: string, attachments: var, done: var): void {
        const args = ["compose", "--reply-to", id, "--body", body];
        for (const path of attachments)
            args.push("--attach", path);
        sending = true;
        run(args, (ok, result) => {
            sending = false;
            done(ok ? "" : result?.error ?? "Sending failed.");
            if (ok)
                say("Reply sent", null, "send");
        });
    }

    // Files to attach, from the system's file picker.
    function pickFiles(done: var): void {
        const picker = pickerComponent.createObject(root);
        picker.done = done;
        picker.running = true;
    }

    // Plain-text mail as rich text: links clickable and short, *bold* and
    // _italic_ restored, Gmail's "address <address>" said once; everything
    // else escaped (plaintext.js).
    // Links in plain text; `wholeLinks` (teach mode) shows each whole
    // address instead of its site, so a selection maps back to the text.
    function linked(text: string, color: string, wholeLinks): string {
        return PlainText.linked(text, color, !!wholeLinks);
    }

    // The reader's plain view (PlainText.formatted) in the app's colours.
    // `footer` is the engine's footer offset (-1: shown in full).
    function formatted(text: string, footer: int, wholeLinks): string {
        return PlainText.formatted(text, {
            text: hexOf(Theme.m3onSurface),
            muted: hexOf(Theme.m3onSurfaceVariant),
            link: hexOf(Theme.m3primary),
            code: hexOf(Theme.m3surfaceContainerHighest)
        }, { footer: footer, wholeLinks: !!wholeLinks });
    }

    // #rrggbb, whatever the colour's transparency.
    function hexOf(colour: color): string {
        return "#" + [colour.r, colour.g, colour.b].map(v => Math.round(v * 255).toString(16).padStart(2, "0")).join("");
    }

    // The reader's colours, for simple HTML mail drawn in them (courier_theme.py).
    function readerTheme(): string {
        return JSON.stringify({
            surface: hexOf(Theme.m3surfaceContainerLow),
            text: hexOf(Theme.m3onSurface),
            muted: hexOf(Theme.m3onSurfaceVariant),
            link: hexOf(Theme.m3primary)
        });
    }

    // How one sender's mail shows ("colours": auto | dark | original,
    // "plain": auto | always | original), then the open email again.
    function setReaderPref(sender: string, key: string, value: string): void {
        run(["reader-pref", sender, `--${key}`, value], ok => {
            if (!ok)
                sayError("Couldn't save that.");
            else if (openId)
                openMessage(openId, false);
        });
    }

    // A field's value as a list: none, one, or every row's. (A list that came
    // through a Repeater's modelData is a QML sequence, which Array.isArray
    // calls no array.)
    function asList(value): var {
        if (value === null || value === undefined || value === "")
            return [];
        return typeof value === "string" || typeof value === "number" ? [String(value)] : Array.from(value);
    }

    function formatBytes(bytes: real): string {
        const gb = bytes / (1024 * 1024 * 1024);
        if (gb < 1)
            return `${Math.round(bytes / (1024 * 1024))} MB`;
        // 15 GB, not 15.0 GB.
        return Math.abs(gb - Math.round(gb)) < 0.05 ? `${Math.round(gb)} GB` : `${gb.toFixed(1)} GB`;
    }

    // (Storage loads with the accounts.)
    Component.onCompleted: {
        loadAccounts(false);
        refresh();
        loadTemplates();
        // Then each account's own picture, if one was never looked up.
        loadAccounts(true);
    }

    function loadStorage(): void {
        run(["storage"], (ok, result) => {
            if (ok)
                storage = result;
        });
    }

    Component {
        id: sendComponent

        Process {
            id: sender

            property var pending

            stderr: StdioCollector {
                id: sendErrors
            }
            onExited: code => {
                sender.pending.sending = false;
                sender.pending.failed = code !== 0;
                if (code !== 0)
                    root.sayError(sendErrors.text.trim() || "Sending failed.");
                root.messages = root.messages.slice();
                sender.destroy();
            }
        }
    }

    // Teach fields --------------------------------------------------------------------

    // You open an automated email, press Teach fields, select text and name it
    // ("Repo", "PR"…); Courier learns the email's template and reads those
    // fields out of every other email made from it (engine/courier_templates.py,
    // courier_fields.py). The panel's draft is only kept on Save.

    // Teach fields' screens (the reader's grid button and panel, the field
    // card, the sidebar's Tables) are for developers for now: run Courier
    // with COURIER_DEV=1 to see them. Templates and the fields read with them
    // (and the notifications built from those) work either way.
    readonly property bool developer: Quickshell.env("COURIER_DEV") === "1"
    // The reader, for its selection (MailReader registers itself).
    property var reader: null
    property bool teaching: false
    // { id, account, sender, fingerprint, name, surface, fields: [{ name, list,
    // link, subject, optional, examples: [{ id, value, start, end }] }] }
    property var teachDraft: null
    property bool teachSaved: false
    property bool teachDirty: false
    property int teachCount: 0
    property var teachSuggestions: []
    // { fields, current, rows, unlearned }: the draft read from this email and
    // the template's others.
    property var teachPreview: null
    property bool teachBusy: false
    property string teachError: ""
    // The reader's selection as the engine placed it: { id, value, start,
    // end, subject, link, repeats }.
    property var teachPick: null
    property int teachRequest: 0
    // Teaching starts once this email has opened (Teach again on another).
    property string teachAfterOpen: ""
    // Templates you taught, for the sidebar; the Updates table open, if any.
    property var templates: []
    property string tableTemplate: ""
    property var table: null
    property bool tableLoading: false
    property bool tableFailed: false

    // An engine call with a JSON payload on stdin (selections and drafts never
    // go in the arguments).
    function runInput(args: var, input: var, done: var): var {
        const job = inputJobComponent.createObject(root, { command: [engine, ...args], input: JSON.stringify(input) });
        job.done = done ?? null;
        job.running = true;
        return job;
    }

    function startTeaching(): void {
        if (!developer || !reading || !openId)
            return;
        closeTable();
        teaching = true;
        teachBusy = true;
        teachError = "";
        teachPick = null;
        teachPreview = null;
        // The plain text first (what notification mail opens in); the designed
        // version when there's no text to teach on.
        const text = reading.plain || (reading.html ? "" : (reading.full || reading.body || ""));
        const surface = text.trim() !== "" ? "text" : "html";
        const id = openId;
        const request = ++teachRequest;
        run(["teach-start", id, "--surface", surface], (ok, result) => {
            if (request !== teachRequest)
                return;
            teachBusy = false;
            if (!ok) {
                teachError = result?.error ?? "Couldn't start teaching.";
                return;
            }
            teachDraft = result.template;
            teachSaved = result.saved;
            teachDirty = false;
            teachCount = result.count;
            teachSuggestions = result.suggestions;
            teachPreview = result.preview;
        });
    }

    function stopTeaching(): void {
        teaching = false;
        teachDraft = null;
        teachPreview = null;
        teachPick = null;
        teachError = "";
        teachDirty = false;
        teachRequest++;
    }

    // Opens an email and teaches its template (a card's or a row's Teach again).
    function teachOn(id: string): void {
        closeTable();
        if (id === openId && reading) {
            startTeaching();
            return;
        }
        teachAfterOpen = id;
        openMessage(id, true);
    }

    // Places the reader's selection in the email (called as it changes).
    function teachPlace(): void {
        const picked = reader ? reader.selection() : null;
        if (!teaching || !teachDraft || !picked || picked.text.trim() === "") {
            teachPick = null;
            return;
        }
        const id = openId;
        const request = ++teachRequest;
        runInput(["teach-select", id], Object.assign({ surface: teachDraft.surface }, picked), (ok, result) => {
            if (request !== teachRequest || id !== openId)
                return;
            teachPick = ok ? result : null;
            teachError = ok ? "" : (result?.error ?? "");
        });
    }

    // Adds the placed selection as an example of a field: a new one, or one
    // already there (another example of it).
    function teachAdd(name: string, options: var): void {
        const field = name.trim();
        if (!teachDraft || !teachPick || field === "")
            return;
        const example = { id: teachPick.id, value: teachPick.value };
        if (!teachPick.subject) {
            example.start = teachPick.start;
            example.end = teachPick.end;
        }
        const fields = teachDraft.fields.map(f => Object.assign({}, f));
        const existing = fields.find(f => f.name.toLowerCase() === field.toLowerCase());
        if (existing) {
            existing.examples = existing.examples.filter(e => e.id !== example.id).concat([example]);
            existing.list = options.list;
            existing.link = options.link;
        } else {
            fields.push({ name: field, list: options.list, link: options.link, subject: teachPick.subject, optional: options.optional, examples: [example] });
        }
        teachDraft = Object.assign({}, teachDraft, { fields: fields });
        teachDirty = true;
        teachPick = null;
        if (reader)
            reader.clearSelection();
        teachRefresh();
    }

    function teachEdit(name: string, change: var): void {
        if (!teachDraft)
            return;
        let fields = teachDraft.fields.map(f => Object.assign({}, f));
        if (change === null)
            fields = fields.filter(f => f.name !== name);
        else
            fields = fields.map(f => f.name === name ? Object.assign(f, change) : f);
        teachDraft = Object.assign({}, teachDraft, { fields: fields });
        teachDirty = true;
        teachRefresh();
    }

    // Kept as typed (spaces and all); the engine trims it on Save.
    function teachRename(template: string): void {
        if (!teachDraft || template.trim() === "" || template === teachDraft.name)
            return;
        teachDraft = Object.assign({}, teachDraft, { name: template });
        teachDirty = true;
    }

    // The draft read from this email and the template's others.
    function teachRefresh(): void {
        if (!teachDraft)
            return;
        const request = ++teachRequest;
        teachBusy = true;
        runInput(["teach-preview", openId], teachDraft, (ok, result) => {
            if (request !== teachRequest)
                return;
            teachBusy = false;
            if (ok)
                teachPreview = result;
            teachError = ok ? "" : (result?.error ?? "Couldn't read the other emails.");
        });
    }

    function teachSave(): void {
        if (!teachDraft || teachDraft.fields.length === 0)
            return;
        const request = ++teachRequest;
        teachBusy = true;
        runInput(["teach-save", openId], teachDraft, (ok, result) => {
            if (request !== teachRequest)
                return;
            teachBusy = false;
            if (!ok) {
                teachError = result?.error ?? "Couldn't save.";
                return;
            }
            teachSaved = true;
            teachDirty = false;
            teachDraft = Object.assign({}, teachDraft, { id: result.id, name: result.name });
            say(result.flagged > 0 ? `Saved · ${result.count} emails read, ${result.flagged} need re-teaching` : `Saved · ${result.count} emails read`, null, "dataset");
            loadTemplates();
            refreshReading();
        });
    }

    function deleteTemplate(id: string): void {
        run(["template-delete", id], (ok, result) => {
            if (!ok) {
                sayError(result?.error ?? "Couldn't delete that template.");
                return;
            }
            if (teachDraft?.id === id)
                stopTeaching();
            if (tableTemplate === id)
                closeTable();
            say("Template deleted", null, "delete");
            loadTemplates();
            refreshReading();
        });
    }

    // The open email again, quietly: its field card after a change.
    function refreshReading(): void {
        if (!openId || folder === "trash")
            return;
        const id = openId;
        const request = ++readRequest;
        run(["message", id, "--theme", readerTheme()], (ok, mail) => {
            if (ok && request === readRequest && id === openId)
                reading = mail;
        });
    }

    function loadTemplates(): void {
        run(["templates", ...accountArgs()], (ok, result) => {
            if (ok)
                templates = result.templates;
        });
    }

    function openTable(id: string): void {
        stopTeaching();
        tableTemplate = id;
        table = null;
        loadTable();
    }

    function closeTable(): void {
        tableTemplate = "";
        table = null;
    }

    function loadTable(): void {
        if (!tableTemplate)
            return;
        const id = tableTemplate;
        tableLoading = true;
        tableFailed = false;
        run(["template-table", id], (ok, result) => {
            if (id !== tableTemplate)
                return;
            tableLoading = false;
            tableFailed = !ok;
            if (ok)
                table = result;
            else
                sayError(result?.error ?? "Couldn't read that template's emails.");
        });
    }

    onOpenIdChanged: {
        // Teaching follows you between the template's emails; leaving them
        // (or closing the email) ends it.
        if (teaching && (openId === "" || !(teachPreview?.rows ?? []).some(row => row.id === openId)))
            stopTeaching();
        teachPick = null;
    }

    onReadingChanged: {
        if (reading && teachAfterOpen && reading.id === teachAfterOpen) {
            teachAfterOpen = "";
            startTeaching();
        } else if (reading && teaching) {
            teachRefresh();
        }
    }

    Component {
        id: pickerComponent

        Process {
            id: picker

            property var done

            command: ["kdialog", "--title", "Attach files", "--getopenfilename", Quickshell.env("HOME"), "--multiple", "--separate-output"]
            stdout: StdioCollector {
                onStreamFinished: {
                    picker.done(text.split("\n").filter(line => line.trim() !== ""));
                    picker.destroy();
                }
            }
        }
    }

    Component {
        id: calendarJob

        Process {
            id: calendarProcess

            property var done

            stdout: StdioCollector {
                onStreamFinished: {
                    let ok = true;
                    try {
                        ok = !JSON.parse(text).error;
                    } catch (e) {
                        ok = false;
                    }
                    calendarProcess.done(ok);
                    calendarProcess.destroy();
                }
            }
        }
    }

    Component {
        id: inputJobComponent

        Process {
            id: inputJob

            property var done
            property string input

            stdinEnabled: true
            onStarted: {
                write(input);
                // Closes stdin: the engine reads to the end.
                stdinEnabled = false;
            }
            stdout: StdioCollector {
                onStreamFinished: {
                    let value = null;
                    let ok = true;
                    try {
                        value = JSON.parse(text);
                        ok = !(value && value.error);
                    } catch (e) {
                        ok = false;
                    }
                    if (inputJob.done)
                        inputJob.done(ok, value);
                    inputJob.destroy();
                }
            }
            stderr: StdioCollector {
                onStreamFinished: if (text.trim() !== "") console.warn("Courier engine:", text.trim())
            }
        }
    }

    Component {
        id: jobComponent

        Process {
            id: job

            property var done

            stdout: StdioCollector {
                onStreamFinished: {
                    let value = null;
                    let ok = true;
                    try {
                        value = JSON.parse(text);
                        ok = !(value && value.error);
                    } catch (e) {
                        ok = false;
                    }
                    if (job.done)
                        job.done(ok, value);
                    job.destroy();
                }
            }
            stderr: StdioCollector {
                onStreamFinished: if (text.trim() !== "") console.warn("Courier engine:", text.trim())
            }
        }
    }

    // A finished sync changes what's in the inbox. During an account's first
    // download it's rewritten every minute, with how far along it is.
    FileView {
        id: syncFile

        path: `${root.stateDir}/sync.json`
        watchChanges: true
        printErrors: false
        onFileChanged: {
            reload();
            root.synced();
        }
        onLoaded: root.readSyncStatus(text())
    }

    // Sender pictures arrive after a sync, from courier-avatars.
    FileView {
        path: `${root.stateDir}/avatars.json`
        watchChanges: true
        printErrors: false
        onFileChanged: if (root.folder === "smart")
            root.loadConversations(null)
    }

    // So do your accounts' own pictures (Google photo, Gravatar).
    FileView {
        path: `${root.stateDir}/account-pictures.json`
        watchChanges: true
        printErrors: false
        onFileChanged: root.loadAccounts(false)
    }
}
