import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Junco Calendar: the calendars sidebar on the glass sheet, then the
// month/week view and the day panel as raised glass cards. Adapts from
// 1920x1080 full screen to ~910x1040 half tiles (sidebar and day panel
// auto-hide).
Item {
    id: root

    property bool searching: false
    property var deleted: null
    property string toastText: ""
    property bool fullScreen: Theme.fullScreen
    // 0 = auto (responsive), 1 = forced open, -1 = forced closed
    property int sidebarPref: 0
    property int dayPref: 0

    readonly property int outerInset: fullScreen ? 0 : Theme.cardInset
    readonly property bool sidebarShown: sidebarPref === 0 ? root.width >= 1120 : sidebarPref > 0
    readonly property bool dayShown: dayPref === 0 ? root.width >= 1260 : dayPref > 0
    readonly property int minCenterWidth: 420
    readonly property int maxSidebarWidth: Math.max(180, Math.min(360, Math.floor(root.width - (dayShown ? Calendar.dayPanelWidth + Theme.paneGap : 0) - 2 * outerInset - Theme.paneGap - minCenterWidth)))
    readonly property int effectiveSidebarWidth: Math.max(180, Math.min(maxSidebarWidth, Calendar.sidebarWidth))
    readonly property int maxDayPanelWidth: Math.max(220, Math.min(440, Math.floor(root.width - (sidebarShown ? effectiveSidebarWidth + Theme.paneGap : 0) - 2 * outerInset - Theme.paneGap - minCenterWidth)))
    readonly property int effectiveDayPanelWidth: Math.max(220, Math.min(maxDayPanelWidth, Calendar.dayPanelWidth))

    function toggleSidebar(): void {
        sidebarPref = sidebarShown ? -1 : 1;
    }

    function toggleDayPanel(): void {
        dayPref = dayShown ? -1 : 1;
    }

    function ensureDayPanelVisible(): void {
        if (!dayShown)
            dayPref = 1;
    }

    function showToast(text: string): void {
        toastText = text;
        toastTimer.restart();
    }

    function openMenu(button: Item, entries: var): void {
        menu.show(button, entries);
    }

    function openDialog(action: var): void {
        if (!dialogLoader.active)
            dialogLoader.active = true;
        if (dialogLoader.item)
            action(dialogLoader.item);
    }

    function createEvent(day: string, minutes: int): void {
        openDialog(d => d.create(day, minutes));
    }

    function createEventPrefilled(titleText: string, day: string, startMin: int, endMin: int): void {
        openDialog(d => d.createPrefilled(titleText, day, startMin, endMin));
    }

    function saveQuickEvent(titleText: string, onDay: string, startMin: int, endMin: int): void {
        const cleanTitle = (titleText ?? "").trim();
        if (cleanTitle === "")
            return;
        const targetDay = onDay || Calendar.selected || Calendar.todayDay;
        const stamp = mins => {
            const date = Calendar.addDays(targetDay, Math.floor(mins / 1440));
            const within = mins % 1440;
            return `${date}T${String(Math.floor(within / 60)).padStart(2, "0")}:${String(within % 60).padStart(2, "0")}:00`;
        };
        const event = {
            title: cleanTitle,
            where: "",
            notes: "",
            allDay: false,
            start: stamp(startMin),
            end: stamp(endMin > startMin ? endMin : startMin + 60),
            calendarId: Calendar.localCalendars[0]?.id ?? "",
            reminders: [10]
        };
        Calendar.save("", event, reason => {
            if (reason === "") {
                Calendar.selected = targetDay;
                root.showToast(`Created “${cleanTitle}”`);
            } else {
                root.showToast(reason);
            }
        });
    }

    function editEvent(event: var): void {
        openDialog(d => d.edit(event, false));
    }

    function duplicateEvent(event: var): void {
        openDialog(d => d.edit(event, true));
    }

    function deleteEvent(event: var): void {
        deleted = event;
        undoTimer.restart();
        Calendar.remove(event.id);
    }

    function undoDelete(): void {
        const event = deleted;
        deleted = null;
        Calendar.save("", {
            title: event.title,
            where: event.where,
            notes: event.notes,
            allDay: event.allDay,
            start: event.start,
            end: event.end,
            calendarId: event.calendarId,
            reminders: event.reminders
        }, () => {});
    }

    function closeSearch(): void {
        searching = false;
        search.text = "";
    }

    // All panes (smoked sidebar, main calendar grid, Today & Actionables) share
    // the same outer inset (6 px windowed, 0 px fullscreen) and clear-glass
    // gutter (6 px), with 16 px corners concentric with the 22 px outer sheet
    // when windowed, or flush edge-to-edge in fullscreen.
    RowLayout {
        id: panesRow

        anchors.fill: parent
        anchors.margins: root.outerInset
        spacing: Theme.paneGap

        CalendarSidebar {
            id: sidebar

            Layout.preferredWidth: root.effectiveSidebarWidth
            Layout.fillHeight: true
            card: true
            dividerRight: true
            visible: root.sidebarShown
            page: root
        }

        // Dense text (day numbers, hours, chips): the same small white
        // lift as Mail's list card, so it reads over dark wallpaper.
        GlassPane {
            Layout.fillWidth: true
            Layout.fillHeight: true
            fill: Theme.glassList

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 14

                    // Calm single-row frosted toolbar.
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        IconButton {
                            icon: root.sidebarShown ? "left_panel_close" : "left_panel_open"
                            tip: root.sidebarShown ? "Hide calendars sidebar" : "Show calendars sidebar"
                            size: 34
                            filled: !root.sidebarShown
                            fillColor: Theme.glassControl
                            iconColor: Theme.m3onSurface
                            onClicked: root.toggleSidebar()
                        }

                        IconButton {
                            visible: !root.sidebarShown
                            icon: "add"
                            tip: "Create event"
                            size: 34
                            cornerRadius: 11
                            filled: true
                            fillColor: Theme.pill
                            iconColor: Theme.pillInk
                            onClicked: root.createEvent(Calendar.selected, -1)
                        }

                        // Compact navigation cluster
                        Rectangle {
                            implicitWidth: navRow.implicitWidth + 8
                            implicitHeight: 34
                            radius: Theme.controlRadius
                            color: Theme.glassControl
                            border.width: Theme.glass ? 0 : 1
                            border.color: Theme.glassBorderSubtle

                            Row {
                                id: navRow

                                anchors.centerIn: parent
                                spacing: 0

                                IconButton {
                                    icon: "chevron_left"
                                    tip: "Previous"
                                    size: 28
                                    iconColor: Theme.m3onSurface
                                    onClicked: Calendar.step(-1)
                                }

                                IconButton {
                                    icon: "chevron_right"
                                    tip: "Next"
                                    size: 28
                                    iconColor: Theme.m3onSurface
                                    onClicked: Calendar.step(1)
                                }
                            }
                        }

                        Pill {
                            text: "Today"
                            size: 34
                            fontSize: 12
                            onClicked: Calendar.selected = Calendar.todayDay
                        }

                        Label {
                            Layout.fillWidth: true
                            Layout.leftMargin: 8
                            text: {
                                Calendar.selected;
                                Calendar.view;
                                return Calendar.spanTitle();
                            }
                            elide: Text.ElideRight
                            font.pixelSize: 18
                            weight: Font.DemiBold
                        }

                        // Search every copied event; Esc or × closes it.
                        Rectangle {
                            Layout.preferredWidth: root.searching ? 216 : 34
                            implicitHeight: 34
                            radius: Theme.controlRadius
                            color: root.searching ? Theme.glassControl : (searchArea.containsMouse ? Theme.glassControlHover : "transparent")
                            border.width: !Theme.glass && root.searching ? 1 : 0
                            border.color: search.activeFocus ? Theme.alpha(Theme.m3primary, 0.72) : Theme.glassBorderSubtle

                            Behavior on Layout.preferredWidth {
                                NumberAnimation {
                                    duration: 140
                                    easing.type: Easing.OutCubic
                                }
                            }

                            MouseArea {
                                id: searchArea

                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: root.searching ? Qt.IBeamCursor : Qt.PointingHandCursor
                                onClicked: {
                                    root.searching = true;
                                    search.forceActiveFocus();
                                }
                            }

                            Icon {
                                x: 7
                                anchors.verticalCenter: parent.verticalCenter
                                name: "search"
                                size: 17
                                color: Theme.m3onSurfaceVariant
                            }

                            TextInput {
                                id: search

                                anchors.left: parent.left
                                anchors.right: clear.left
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 28
                                visible: root.searching
                                renderType: Text.NativeRendering
                                color: Theme.m3onSurface
                                font.family: Theme.sans
                                font.pixelSize: 12
                                clip: true
                                onTextChanged: Calendar.query = text
                                Keys.onEscapePressed: root.closeSearch()

                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: search.text === ""
                                    text: "Search events"
                                    color: Theme.m3onSurfaceVariant
                                    font.pixelSize: 12
                                }
                            }

                            IconButton {
                                id: clear

                                anchors.right: parent.right
                                anchors.rightMargin: 2
                                anchors.verticalCenter: parent.verticalCenter
                                visible: root.searching
                                icon: "close"
                                tip: "Close search"
                                size: 24
                                onClicked: root.closeSearch()
                            }
                        }

                        // Calm frosted segmented switcher: Day | Week | Month | Agenda.
                        Rectangle {
                            implicitWidth: views.implicitWidth + 8
                            implicitHeight: 34
                            radius: Theme.controlRadius
                            color: Theme.glassControl
                            border.width: Theme.glass ? 0 : 1
                            border.color: Theme.glassBorderSubtle

                            Row {
                                id: views

                                anchors.centerIn: parent
                                spacing: 3

                                Repeater {
                                    model: [
                                        { id: "day", label: "Day" },
                                        { id: "week", label: "Week" },
                                        { id: "month", label: "Month" },
                                        { id: "agenda", label: "Agenda" }
                                    ]

                                    delegate: Rectangle {
                                        id: segment

                                        required property var modelData
                                        readonly property bool active: Calendar.view === modelData.id

                                        width: segmentLabel.implicitWidth + 22
                                        height: 28
                                        radius: 9
                                        color: active ? Theme.pill : (segmentArea.containsMouse ? Theme.glassHover : "transparent")

                                        Behavior on color {
                                            ColorAnimation {
                                                duration: Theme.animFast
                                                easing.type: Easing.OutCubic
                                            }
                                        }

                                        GlassEdge {
                                            visible: Theme.glass && segment.active
                                            radius: 9
                                            fade: 7
                                            side: false
                                            light: Theme.alpha(Theme.pureWhite, Theme.dark ? 0.14 : 0.26)
                                        }

                                        Label {
                                            id: segmentLabel

                                            anchors.centerIn: parent
                                            text: segment.modelData.label
                                            color: segment.active ? Theme.pillInk : Theme.m3onSurfaceVariant
                                            font.pixelSize: 12
                                            weight: segment.active ? Font.Medium : Font.Normal
                                        }

                                        MouseArea {
                                            id: segmentArea

                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                root.closeSearch();
                                                Calendar.setView(segment.modelData.id);
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        IconButton {
                            icon: root.dayShown ? "right_panel_close" : "right_panel_open"
                            tip: root.dayShown ? "Hide day panel" : "Show day panel"
                            size: 34
                            filled: !root.dayShown
                            fillColor: Theme.glassControl
                            iconColor: Theme.m3onSurface
                            onClicked: root.toggleDayPanel()
                        }

                        IconButton {
                            id: moreButton

                            icon: "more_vert"
                            tip: "More"
                            size: 34
                            filled: true
                            fillColor: Theme.glassControl
                            iconColor: Theme.m3onSurface
                            onClicked: root.openMenu(moreButton, [
                                { icon: "sync", label: "Sync calendars now", run: () => Calendar.syncNow() },
                                { icon: Calendar.reminders ? "notifications_active" : "notifications_off", label: "Desktop reminders", checked: Calendar.reminders, run: () => Calendar.setReminders(!Calendar.reminders) },
                                { icon: "select_all", label: "Show all calendars", run: () => Calendar.showAll() },
                                { separator: true },
                                { icon: "open_in_new", label: "Open Google Calendar", run: () => Qt.openUrlExternally("https://calendar.google.com/calendar/r") }
                            ])
                        }
                    }

                    Label {
                        Layout.leftMargin: 4
                        visible: root.searching && Calendar.query.trim() !== ""
                        text: Calendar.found.length === 1 ? `1 event matches “${Calendar.query.trim()}”` : `${Calendar.found.length} events match “${Calendar.query.trim()}”`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        readonly property bool showResults: root.searching && Calendar.query.trim() !== ""

                        Loader {
                            anchors.fill: parent
                            active: Calendar.view === "month" && !parent.showResults
                            visible: active
                            sourceComponent: MonthView {
                                page: root
                            }
                        }

                        Loader {
                            anchors.fill: parent
                            active: (Calendar.view === "week" || Calendar.view === "day") && !parent.showResults
                            visible: active
                            sourceComponent: TimeGrid {
                                page: root
                            }
                        }

                        Loader {
                            anchors.fill: parent
                            active: Calendar.view === "agenda" && !parent.showResults
                            visible: active
                            sourceComponent: AgendaList {
                                events: Calendar.shownEvents
                                from: Calendar.spanFirst
                                emptyText: `Nothing in ${Calendar.format(Calendar.selected, "MMMM")}.`
                                onPicked: event => Calendar.selected = event.startDay < Calendar.spanFirst ? Calendar.spanFirst : event.startDay
                            }
                        }

                        Loader {
                            id: resultsLoader

                            anchors.fill: parent
                            active: parent.showResults
                            visible: active
                            sourceComponent: AgendaList {
                                events: Calendar.found
                                emptyText: "No events match."
                                onPicked: event => {
                                    Calendar.selected = event.startDay;
                                    root.closeSearch();
                                }
                            }
                        }
                    }
                }
            }

            DayPanel {
                id: dayPanel

                Layout.preferredWidth: root.effectiveDayPanelWidth
                Layout.fillHeight: true
                dividerLeft: true
                visible: root.dayShown
                page: root
            }
    }

    // Invisible drag-to-resize handle centered in the clear-glass gutter
    // between the calendars sidebar and main view.
    SplitHandle {
        visible: root.sidebarShown
        x: panesRow.x + sidebar.x + sidebar.width - (Theme.paneGap > 0 ? 0 : 3)
        y: root.outerInset
        width: Math.max(6, Theme.paneGap)
        height: Math.max(0, root.height - 2 * root.outerInset)
        dragScope: root
        value: root.effectiveSidebarWidth
        direction: 1
        onResized: next => Calendar.sidebarWidth = Math.max(180, Math.min(root.maxSidebarWidth, next))
        onResizeFinished: Calendar.saveView()
        onResetRequested: {
            Calendar.sidebarWidth = 228;
            Calendar.saveView();
        }
    }

    // Invisible drag-to-resize handle centered in the clear-glass gutter
    // between the main view and the day panel.
    SplitHandle {
        visible: root.dayShown
        x: panesRow.x + dayPanel.x - (Theme.paneGap > 0 ? Theme.paneGap : 3)
        y: root.outerInset
        width: Math.max(6, Theme.paneGap)
        height: Math.max(0, root.height - 2 * root.outerInset)
        dragScope: root
        value: root.effectiveDayPanelWidth
        direction: -1
        onResized: next => Calendar.dayPanelWidth = Math.max(220, Math.min(root.maxDayPanelWidth, next))
        onResizeFinished: Calendar.saveView()
        onResetRequested: {
            Calendar.dayPanelWidth = 296;
            Calendar.saveView();
        }
    }

    // Deleted: a few seconds to take it back.
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 16
        visible: root.deleted !== null
        implicitWidth: undoRow.implicitWidth + 24
        implicitHeight: 42
        radius: 12
        color: Theme.m3popupHigh
        border.width: 1
        border.color: Theme.glassPopupBorder
        z: 80

        RowLayout {
            id: undoRow

            anchors.centerIn: parent
            spacing: 12

            Label {
                text: root.deleted ? `Deleted “${root.deleted.title}”` : ""
                font.pixelSize: 13
            }

            Label {
                text: "Undo"
                color: Theme.m3primary
                font.pixelSize: 13
                weight: Font.Medium

                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -8
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.undoDelete()
                }
            }
        }
    }

    Timer {
        id: undoTimer

        interval: 6000
        onTriggered: root.deleted = null
    }

    // Lightweight feedback pill for Command Palette actions (zero outline).
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.deleted !== null ? 66 : 16
        visible: root.toastText !== ""
        implicitWidth: toastLabel.implicitWidth + 28
        implicitHeight: 38
        radius: 12
        color: Theme.m3popupHigh
        border.width: 0
        z: 82

        GlassEdge {
            visible: Theme.glass
            radius: 12
            side: false
        }

        Label {
            id: toastLabel

            anchors.centerIn: parent
            text: root.toastText
            color: Theme.m3onSurface
            font.pixelSize: 13
            weight: Font.Medium
        }
    }

    Timer {
        id: toastTimer

        interval: 3400
        onTriggered: root.toastText = ""
    }

    Connections {
        target: Calendar

        function onFeedback(message: string): void {
            if (message !== "")
                root.showToast(message);
        }
    }

    Loader {
        id: dialogLoader

        anchors.fill: parent
        active: false
        source: "EventDialog.qml"
        z: 90
    }

    PopupMenu {
        id: menu

        anchors.fill: parent
    }
}
