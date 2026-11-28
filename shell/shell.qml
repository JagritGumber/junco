//@ pragma DefaultEnv QS_NO_RELOAD_POPUP=1
// The window's class, so docks and bars find courier.desktop (and its icon)
// instead of Quickshell's own entry. Read at startup only.
//@ pragma AppId courier

import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.services
import qs.views
import qs.components
import "services/palette.js" as Palette

// Junco Mail: one sheet of clear frosted glass (the window) with the sidebar
// on it and two raised milky cards (list, reader), tuned for Hyprland's own
// blur and a 15" 1920x1080 screen (full 1830x1040 and half 910x1040 tiles).
// The calendar is its own app, ../calendar.
ShellRoot {
    IpcHandler {
        target: "courier"

        function show(): void {
            window.visible = true;
        }

        function open(id: string): void {
            window.visible = true;
            Inbox.openMessage(id, true);
        }
    }

    FloatingWindow {
        id: window

        // Fullscreen flush geometry: collapse outer sheet rounding, outer
        // perimeter inset, and pane corner radii to 0 whenever the window is
        // fullscreen (true Window.FullScreen / FloatingWindow.fullscreen or
        // sized to fill the entire monitor).
        readonly property int screenWidth: window.screen ? window.screen.width : Screen.width
        readonly property int screenHeight: window.screen ? window.screen.height : Screen.height
        readonly property bool isFullScreen: window.fullscreen
            || glassCanvas.Window.visibility === Window.FullScreen
            || (screenWidth > 0 && screenHeight > 0 && window.width >= screenWidth && window.height >= screenHeight)
        readonly property int outerRadius: isFullScreen ? 0 : (Theme.glass ? Theme.paneRadius : 0)
        readonly property int outerInset: isFullScreen ? 0 : Theme.cardInset
        readonly property int paneCornerRadius: isFullScreen ? 0 : Theme.cardPaneRadius

        // Manual toggle (Ctrl+\ or sidebar button) plus automatic compact icon
        // rail below 1200 px so half-screen tiles (~950x1040) keep a wide chat/reader.
        property bool userCollapsedSidebar: false
        property int savedSidebarWidth: 216
        property int savedListWidth: 0
        readonly property bool compactSidebar: userCollapsedSidebar || width < 1200
        readonly property int defaultListWidth: width >= 1500 ? 412 : width >= 1150 ? 344 : 308
        readonly property int maxSidebarWidth: Math.max(160, Math.min(300, Math.floor(width * 0.26)))
        readonly property int sidebarWidth: compactSidebar ? 56 : Math.max(160, Math.min(maxSidebarWidth, savedSidebarWidth))
        readonly property int maxListWidth: Math.max(260, Math.min(520, width - sidebarWidth - 2 * outerInset - 2 * Theme.paneGap - 360))
        readonly property int listWidth: Math.max(260, Math.min(maxListWidth, savedListWidth > 0 ? savedListWidth : defaultListWidth))

        Binding {
            target: Theme
            property: "fullScreen"
            value: window.isFullScreen
        }

        function saveLayout(): void {
            layoutFile.setText(JSON.stringify({
                sidebarWidth: savedSidebarWidth,
                listWidth: savedListWidth
            }) + "\n");
        }

        FileView {
            id: layoutFile

            path: `${Inbox.stateDir}/mail-layout.json`
            atomicWrites: true
            printErrors: false
            onLoaded: {
                try {
                    const saved = JSON.parse(text());
                    if (typeof saved.sidebarWidth === "number" && saved.sidebarWidth >= 150 && saved.sidebarWidth <= 300)
                        window.savedSidebarWidth = Math.round(saved.sidebarWidth);
                    if (typeof saved.listWidth === "number" && (saved.listWidth === 0 || (saved.listWidth >= 240 && saved.listWidth <= 520)))
                        window.savedListWidth = Math.round(saved.listWidth);
                } catch (e) {
                    console.warn("Courier: couldn't read mail-layout.json:", e);
                }
            }
        }

        // Preview builds of this branch say so in the title, so a preview run
        // with `qs -p <worktree>/shell` can't be mistaken for the installed
        // Junco (both share the class "courier"). Drop before merging.
        title: "Junco · glass preview"
        implicitWidth: 1760
        implicitHeight: 1000
        color: Theme.windowBg
        // Required on Wayland so Hyprland gets an alpha buffer at all.
        surfaceFormat.opaque: !Theme.glass

        // Hyprland blurs behind the whole rounded sheet (ext-background-effect-v1,
        // which Hyprland 0.57 supports), clipped to the sheet's corners; or,
        // with Theme.sheetBlur off, only behind the cards, leaving the sheet as
        // clear unblurred glass.
        BackgroundEffect.blurRegion: Theme.glass ? (Theme.sheetBlur ? sheetRegion : cardRegion) : null

        readonly property Region sheetRegion: Region {
            item: glassCanvas
            radius: window.outerRadius
        }

        readonly property Region cardRegion: Region {
            Region {
                item: sidebar.visible ? sidebar : null
                radius: window.paneCornerRadius
            }
            Region {
                item: conversationList.visible ? conversationList : null
                radius: window.paneCornerRadius
            }
            Region {
                item: mailListLoader.visible ? mailListLoader.item : null
                radius: window.paneCornerRadius
            }
            Region {
                item: conversationView.visible ? conversationView : null
                radius: window.paneCornerRadius
            }
            Region {
                item: templateTableLoader.visible ? templateTableLoader.item : null
                radius: window.paneCornerRadius
            }
            Region {
                item: mailReaderLoader.visible ? mailReaderLoader.item : null
                radius: window.paneCornerRadius
            }
            Region {
                item: teachPanelLoader.visible ? teachPanelLoader.item : null
                radius: window.paneCornerRadius
            }
            Region {
                item: autoExpirySettingsLoader.visible ? autoExpirySettingsLoader.item : null
                radius: window.paneCornerRadius
            }
        }

        onVisibleChanged: if (!visible)
            Qt.quit()

        Item {
            id: glassCanvas

            anchors.fill: parent

            // The sheet: the window's one outer edge.
            Rectangle {
                id: outerSheet

                anchors.fill: parent
                radius: window.outerRadius
                color: Theme.glassSheet

                GlassEdge {
                    visible: Theme.glass
                    z: 1
                    radius: outerSheet.radius
                }
            }

            // The frost: a static noise tile over the glass, under the cards'
            // content (a plain tiled Image; Hyprland's rounding clips the
            // window's corners).
            Image {
                anchors.fill: parent
                visible: Theme.glass
                source: `file://${Quickshell.shellDir}/../assets/glass/grain.png`
                fillMode: Image.Tile
                smooth: false
                opacity: Theme.grainOpacity
            }

            // All panes (smoked sidebar + raised glass cards) share the same
            // outer inset (6 px windowed, 0 px fullscreen) and clear-glass
            // gutter (6 px) so every rounded corner sits concentrically inside
            // the 22 px outer sheet when windowed, or flush edge-to-edge in fullscreen.
            RowLayout {
                id: panesRow

                anchors.fill: parent
                anchors.margins: window.outerInset
                spacing: Theme.paneGap

                MailSidebar {
                    id: sidebar

                    Layout.preferredWidth: window.sidebarWidth
                    Layout.fillHeight: true
                    card: true
                    dividerRight: true
                    compact: window.compactSidebar
                    autoCompact: window.width < 1200
                    onToggleCompact: window.userCollapsedSidebar = !window.userCollapsedSidebar
                }

                ConversationList {
                    id: conversationList

                    Layout.preferredWidth: window.listWidth
                    Layout.fillHeight: true
                    dividerRight: true
                    visible: !Inbox.settingsOpen && Inbox.folder === "smart" && !Inbox.tableTemplate
                }

                Loader {
                    id: mailListLoader

                    Layout.preferredWidth: window.listWidth
                    Layout.fillHeight: true
                    active: !Inbox.settingsOpen && Inbox.folder !== "smart" && !Inbox.tableTemplate
                    visible: active
                    sourceComponent: MailList {
                        dividerRight: true
                    }
                }

                ConversationView {
                    id: conversationView

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: !Inbox.settingsOpen && Inbox.folder === "smart" && !Inbox.readerOpen && !Inbox.tableTemplate
                }

                Loader {
                    id: templateTableLoader

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    active: !Inbox.settingsOpen && Inbox.tableTemplate !== ""
                    visible: active
                    source: "views/TemplateTable.qml"
                }

                Loader {
                    id: mailReaderLoader

                    Layout.fillWidth: !Inbox.tableTemplate
                    Layout.preferredWidth: Inbox.tableTemplate ? 600 : -1
                    Layout.fillHeight: true
                    active: !Inbox.settingsOpen && (Inbox.tableTemplate ? Inbox.readerOpen : (Inbox.folder !== "smart" || Inbox.readerOpen))
                    visible: active
                    sourceComponent: MailReader {
                        dividerLeft: Inbox.tableTemplate !== ""
                    }
                }

                // Teach fields (developer-only via COURIER_DEV=1).
                Loader {
                    id: teachPanelLoader

                    Layout.preferredWidth: 400
                    Layout.fillHeight: true
                    active: !Inbox.settingsOpen && Inbox.teaching
                    visible: active
                    sourceComponent: TeachPanel {
                        dividerLeft: true
                    }
                }

                // Settings -> Auto-Expiry.
                Loader {
                    id: autoExpirySettingsLoader

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    active: Inbox.settingsOpen
                    visible: active
                    source: "views/AutoExpirySettings.qml"
                }
            }

            // Invisible drag-to-resize handle centered in the clear-glass gutter
            // between the sidebar and the middle card.
            SplitHandle {
                visible: !window.compactSidebar
                x: panesRow.x + sidebar.x + sidebar.width - (Theme.paneGap > 0 ? 0 : 3)
                y: window.outerInset
                width: Math.max(6, Theme.paneGap)
                height: Math.max(0, glassCanvas.height - 2 * window.outerInset)
                dragScope: glassCanvas
                value: window.sidebarWidth
                direction: 1
                onResized: next => window.savedSidebarWidth = Math.max(160, Math.min(window.maxSidebarWidth, next))
                onResizeFinished: window.saveLayout()
                onResetRequested: {
                    window.savedSidebarWidth = 216;
                    window.saveLayout();
                }
            }

            // Invisible drag-to-resize handle centered in the clear-glass gutter
            // between the thread list and reader.
            SplitHandle {
                readonly property Item activeList: conversationList.visible ? conversationList : (mailListLoader.visible ? mailListLoader : null)

                visible: activeList !== null && (conversationView.visible || mailReaderLoader.visible)
                x: panesRow.x + (activeList ? activeList.x + activeList.width : 0) - (Theme.paneGap > 0 ? 0 : 3)
                y: window.outerInset
                width: Math.max(6, Theme.paneGap)
                height: Math.max(0, glassCanvas.height - 2 * window.outerInset)
                dragScope: glassCanvas
                value: window.listWidth
                direction: 1
                onResized: next => window.savedListWidth = Math.max(240, Math.min(window.maxListWidth, next))
                onResizeFinished: window.saveLayout()
                onResetRequested: {
                    window.savedListWidth = 0;
                    window.saveLayout();
                }
            }
        }

        Loader {
            id: composeDialogLoader

            anchors.fill: parent
            active: Inbox.composing && Inbox.draft !== null
            source: "views/ComposeDialog.qml"
            z: 95
        }

        Shortcut {
            sequence: "Ctrl+K"
            onActivated: commandPalette.toggle()
        }

        Shortcut {
            sequence: "Ctrl+N"
            enabled: !commandPalette.open
            onActivated: Inbox.compose("new", "")
        }

        Shortcut {
            sequence: "Ctrl+\\"
            onActivated: window.userCollapsedSidebar = !window.userCollapsedSidebar
        }

        Loader {
            id: addAccountDialogLoader

            anchors.fill: parent
            active: Inbox.addingAccount
            source: "views/AddAccountDialog.qml"
            z: 96
        }

        Loader {
            id: pictureDialogLoader

            anchors.fill: parent
            active: Inbox.pictureCrop !== null
            source: "views/PictureDialog.qml"
            z: 97
        }

        Snackbar {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: window.outerInset + window.sidebarWidth + Theme.paneGap + 14
            anchors.bottomMargin: 16
            z: 100
        }

        AccountCard {
            id: accountCard

            anchors.fill: parent
            Component.onCompleted: Inbox.accountCard = accountCard
        }

        PopupMenu {
            id: windowMenu

            anchors.fill: parent
            z: 150
            Component.onCompleted: Inbox.windowMenu = windowMenu
        }

        Loader {
            id: paletteSchedulePopoverLoader

            anchors.fill: parent
            active: false
            source: "components/ScheduleDeletePopover.qml"
            z: 165
        }

        function activeMailTarget(): var {
            Inbox.revision;
            if (Inbox.reading && Inbox.reading.id) {
                return {
                    hasThread: true,
                    title: Inbox.reading.subject || Inbox.reading.fromName || "",
                    messageId: Inbox.reading.id,
                    threadId: Inbox.reading.threadId || Inbox.reading.id,
                    ids: [Inbox.reading.id],
                    starred: Boolean(Inbox.reading.starred),
                    unread: Boolean(Inbox.reading.unread),
                    hasExpiry: (Inbox.reading.expiry ?? null) !== null,
                    inbox: Boolean(Inbox.reading.inbox),
                    mailObj: Inbox.reading,
                    conversationId: ""
                };
            }
            if (Inbox.folder === "smart" && Inbox.selected) {
                const msgs = (Inbox.messages ?? []).filter(m => m && m.id);
                const latest = msgs.length > 0 ? msgs[msgs.length - 1] : null;
                const inboxIds = msgs.filter(m => m.inbox !== false).map(m => m.id);
                const targetIds = inboxIds.length > 0 ? inboxIds : (latest ? [latest.id] : []);
                const expiryObj = Inbox.selected.expiry ?? latest?.expiry ?? null;
                return {
                    hasThread: true,
                    title: Inbox.selected.name || Inbox.selected.subject || "",
                    messageId: latest?.id ?? "",
                    threadId: latest?.threadId || latest?.id || "",
                    ids: targetIds,
                    starred: Boolean(latest?.starred),
                    unread: (Inbox.selected.unread ?? 0) > 0 || Boolean(latest?.unread),
                    hasExpiry: expiryObj !== null,
                    inbox: true,
                    mailObj: latest ? Object.assign({}, latest, { expiry: expiryObj }) : null,
                    conversationId: Inbox.selected.id
                };
            }
            if (Inbox.folder !== "smart" && Inbox.selectedRow !== "") {
                const row = (Inbox.flatRows ?? []).find(item => item.type === "row" && item.id === Inbox.selectedRow) ?? null;
                if (row) {
                    const ids = (row.ids && row.ids.length > 0) ? row.ids : (row.open ? [row.open] : []);
                    const msgId = row.open || ids[0] || "";
                    return {
                        hasThread: ids.length > 0,
                        title: row.subtitle || row.title || "",
                        messageId: msgId,
                        threadId: row.threadId || msgId,
                        ids: ids,
                        starred: Boolean(row.starred),
                        unread: (row.unread ?? 0) > 0,
                        hasExpiry: (row.expiry ?? null) !== null,
                        inbox: Inbox.inInbox,
                        mailObj: { id: msgId, threadId: row.threadId || msgId, expiry: row.expiry ?? null },
                        conversationId: ""
                    };
                }
            }
            return {
                hasThread: false,
                title: "",
                messageId: "",
                threadId: "",
                ids: [],
                starred: false,
                unread: false,
                hasExpiry: false,
                inbox: false,
                mailObj: null,
                conversationId: ""
            };
        }

        function runMailPaletteAction(item: var): void {
            const action = item?.action;
            if (!action || action.type === "noop")
                return;
            if (action.type === "prefill") {
                commandPalette.setQuery(action.text ?? "");
                return;
            }
            const target = activeMailTarget();
            commandPalette.close(false);

            switch (action.type) {
            case "expiry_set":
                if (target.threadId)
                    Inbox.scheduleDelete(target.threadId, action.spec, action.note ?? "", Boolean(action.isDate), null);
                else
                    Inbox.sayError("Open or select a thread to schedule deletion.");
                break;
            case "expiry_clear":
                if (target.threadId)
                    Inbox.cancelExpiry(target.threadId, null);
                else
                    Inbox.sayError("Open or select a thread to clear scheduled deletion.");
                break;
            case "snooze":
                Inbox.snooze(target.ids, action.untilIso, action.label);
                break;
            case "reply":
                if (target.messageId)
                    Inbox.compose("reply", target.messageId);
                else
                    Inbox.compose("new", "");
                break;
            case "toggle_star":
                if (target.ids.length > 0)
                    Inbox.mark(target.starred ? "unstar" : "star", [target.messageId || target.ids[0]]);
                break;
            case "toggle_read":
                if (target.ids.length > 0)
                    Inbox.mark(target.unread ? "read" : "unread", target.ids);
                break;
            case "archive":
                if (target.conversationId)
                    Inbox.archiveConversation(target.conversationId);
                else if (target.ids.length > 0)
                    Inbox.act("archive", target.ids);
                break;
            case "open_schedule_delete":
                if (target.mailObj) {
                    if (!paletteSchedulePopoverLoader.active)
                        paletteSchedulePopoverLoader.active = true;
                    if (paletteSchedulePopoverLoader.item)
                        paletteSchedulePopoverLoader.item.showCentered(target.mailObj);
                } else {
                    Inbox.sayError("Open or select a thread first.");
                }
                break;
            case "compose":
                Inbox.compose("new", "");
                break;
            case "sync":
                Inbox.syncNow();
                break;
            case "toggle_sidebar":
                window.userCollapsedSidebar = !window.userCollapsedSidebar;
                break;
            case "open_expiry_settings":
                Inbox.openSettings();
                break;
            case "open_calendar":
                Inbox.openCalendar("");
                break;
            case "toggle_glass":
                Theme.toggleGlassMode();
                Inbox.say(Theme.dark ? "Switched to Dark glass" : "Switched to Light glass", null, Theme.dark ? "dark_mode" : "light_mode");
                if (Inbox.openId)
                    Inbox.refreshReading();
                break;
            case "jump":
                Inbox.closeTable();
                Inbox.openFolder(action.folder);
                if (action.folder === "smart" && action.lane)
                    Inbox.lane = action.lane;
                break;
            case "open_conversation":
                Inbox.closeSettings();
                Inbox.closeTable();
                if (Inbox.folder !== "smart")
                    Inbox.openFolder("smart");
                Inbox.lane = "all";
                Inbox.open(action.id);
                break;
            case "open_message":
                Inbox.closeSettings();
                Inbox.openMessage(action.id, true);
                break;
            case "search_all":
                Inbox.closeSettings();
                Inbox.closeTable();
                Inbox.searchEverything(action.query);
                break;
            }
        }

        CommandPalette {
            id: commandPalette

            readonly property var ranked: {
                if (!open)
                    return { modeBadge: "", modeBadgeTone: "", items: [] };
                Inbox.revision;
                const target = window.activeMailTarget();
                return Palette.rankMailItems(query, {
                    hasActiveThread: target.hasThread,
                    activeTitle: target.title,
                    activeStarred: target.starred,
                    activeUnread: target.unread,
                    activeHasExpiry: target.hasExpiry,
                    activeInbox: target.inbox,
                    dark: Theme.dark,
                    compactSidebar: window.compactSidebar,
                    conversations: Inbox.conversations ?? [],
                    flatRows: Inbox.folder !== "smart" ? (Inbox.flatRows ?? []) : [],
                    folder: Inbox.folder
                }, new Date());
            }

            anchors.fill: parent
            placeholder: "Type a command or search mail…"
            modeLabel: "Junco Mail"
            emptyHint: "Try \"exp 2y college\", \"snooze tomorrow 9am\", or \"from:name\""
            items: ranked.items
            activeBadge: ranked.modeBadge
            activeBadgeTone: ranked.modeBadgeTone || "complement"
            onOpened: Inbox.paletteOpen = true
            onClosed: Inbox.paletteOpen = false
            onTriggered: item => window.runMailPaletteAction(item)
            onTabRequested: (currentQuery, selectedItem) => {
                const next = Palette.tabCompleteQuery(currentQuery, selectedItem, "mail");
                if (next !== currentQuery)
                    setQuery(next);
            }
        }
    }
}
