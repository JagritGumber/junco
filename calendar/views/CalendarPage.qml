import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The Calendar: your calendars and the month on the left, the month, week,
// day or agenda in the middle, the picked day on the right. Every Google
// calendar is a read-only copy; events you create live on this PC.
Item {
    id: root

    property bool searching: false
    // The event just deleted, kept for Undo.
    property var deleted: null

    function openMenu(button: Item, entries: var): void {
        menu.show(button, entries);
    }

    function createEvent(day: string, minutes: int): void {
        dialog.create(day, minutes);
    }

    function editEvent(event: var): void {
        dialog.edit(event, false);
    }

    function duplicateEvent(event: var): void {
        dialog.edit(event, true);
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

    RowLayout {
        anchors.fill: parent
        spacing: 12

        CalendarSidebar {
            Layout.preferredWidth: 290
            Layout.fillHeight: true
            visible: root.width >= 900
            page: root
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 28
            color: Theme.m3surfaceContainerLow

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10

                // Arrows, Today, the month, search, the view switch and ⋮.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    IconButton {
                        icon: "chevron_left"
                        tip: "Previous"
                        size: 44
                        filled: true
                        fillColor: Theme.m3surfaceContainerHigh
                        iconColor: Theme.m3onSurface
                        onClicked: Calendar.step(-1)
                    }

                    IconButton {
                        icon: "chevron_right"
                        tip: "Next"
                        size: 44
                        filled: true
                        fillColor: Theme.m3surfaceContainerHigh
                        iconColor: Theme.m3onSurface
                        onClicked: Calendar.step(1)
                    }

                    Pill {
                        text: "Today"
                        size: 44
                        onClicked: Calendar.selected = Calendar.todayDay
                    }

                    Label {
                        Layout.fillWidth: true
                        Layout.leftMargin: 10
                        text: {
                            Calendar.selected;
                            Calendar.view;
                            return Calendar.spanTitle();
                        }
                        elide: Text.ElideRight
                        font.pixelSize: 26
                        font.weight: Font.Medium
                    }

                    // Search every copied event; Esc or × closes it.
                    Rectangle {
                        Layout.preferredWidth: root.searching ? 260 : 44
                        implicitHeight: 44
                        radius: 22
                        color: root.searching ? Theme.m3surfaceContainerHigh : (searchArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent")

                        Behavior on Layout.preferredWidth {
                            NumberAnimation {
                                duration: 160
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
                            x: 11
                            anchors.verticalCenter: parent.verticalCenter
                            name: "search"
                            size: 22
                            color: Theme.m3onSurface
                        }

                        TextInput {
                            id: search

                            anchors.left: parent.left
                            anchors.right: clear.left
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 42
                            visible: root.searching
                            renderType: Text.NativeRendering
                            color: Theme.m3onSurface
                            font.family: Theme.sans
                            font.pixelSize: 14
                            clip: true
                            onTextChanged: Calendar.query = text
                            Keys.onEscapePressed: root.closeSearch()

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: search.text === ""
                                text: "Search events"
                                color: Theme.m3onSurfaceVariant
                            }
                        }

                        IconButton {
                            id: clear

                            anchors.right: parent.right
                            anchors.rightMargin: 4
                            anchors.verticalCenter: parent.verticalCenter
                            visible: root.searching
                            icon: "close"
                            tip: "Close search"
                            size: 36
                            onClicked: root.closeSearch()
                        }
                    }

                    // Day, Week, Month, Agenda.
                    Rectangle {
                        implicitWidth: views.implicitWidth + 8
                        implicitHeight: 48
                        radius: 24
                        color: Theme.m3surfaceContainerHigh

                        Row {
                            id: views

                            anchors.centerIn: parent
                            spacing: 2

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

                                    width: segmentLabel.implicitWidth + 30
                                    height: 40
                                    radius: 20
                                    color: active ? Theme.m3primary : (segmentArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent")

                                    Label {
                                        id: segmentLabel

                                        anchors.centerIn: parent
                                        text: segment.modelData.label
                                        color: segment.active ? Theme.m3onPrimary : Theme.m3onSurfaceVariant
                                        font.pixelSize: 14
                                        font.weight: Font.Medium
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
                        id: moreButton

                        icon: "more_vert"
                        tip: "More"
                        size: 44
                        filled: true
                        fillColor: Theme.m3surfaceContainerHigh
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
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    MonthView {
                        anchors.fill: parent
                        visible: Calendar.view === "month" && !results.visible
                        page: root
                    }

                    TimeGrid {
                        anchors.fill: parent
                        visible: (Calendar.view === "week" || Calendar.view === "day") && !results.visible
                        page: root
                    }

                    AgendaList {
                        anchors.fill: parent
                        visible: Calendar.view === "agenda" && !results.visible
                        events: Calendar.shownEvents
                        from: Calendar.spanFirst
                        emptyText: `Nothing in ${Calendar.format(Calendar.selected, "MMMM")}.`
                        onPicked: event => Calendar.selected = event.startDay < Calendar.spanFirst ? Calendar.spanFirst : event.startDay
                    }

                    AgendaList {
                        id: results

                        anchors.fill: parent
                        visible: root.searching && Calendar.query.trim() !== ""
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

        DayPanel {
            Layout.preferredWidth: 330
            Layout.fillHeight: true
            visible: root.width >= 1150
            page: root
        }
    }

    // Deleted: a few seconds to take it back.
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 20
        visible: root.deleted !== null
        implicitWidth: undoRow.implicitWidth + 32
        implicitHeight: 52
        radius: 16
        color: Theme.m3popupHigh
        border.width: 1
        border.color: Theme.alpha(Theme.m3outlineVariant, 0.6)
        z: 80

        RowLayout {
            id: undoRow

            anchors.centerIn: parent
            spacing: 16

            Label {
                text: root.deleted ? `Deleted “${root.deleted.title}”` : ""
            }

            Label {
                text: "Undo"
                color: Theme.m3primary
                font.weight: Font.DemiBold

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

    EventDialog {
        id: dialog

        anchors.fill: parent
    }

    PopupMenu {
        id: menu

        anchors.fill: parent
    }
}
