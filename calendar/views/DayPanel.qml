import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Junco Calendar's frosted-glass right column: "Today & Actionables".
// Strictly focused on the selected day (default: Today) — never dumps future
// months. Highlights Today's next/live meeting with countdown + one-click Join,
// collapses finished meetings into "Earlier today (N)", and keeps Today's
// SQLite-backed Actionables front and centre.
GlassPane {
    id: root

    fill: Theme.glassList

    required property var page

    property bool showEarlier: false

    readonly property var events: Calendar.dayEvents
    readonly property bool isToday: Calendar.selected === Calendar.todayDay
    readonly property bool isPast: Calendar.selected < Calendar.todayDay

    readonly property var allDayEvents: events.filter(e => e.allDay)
    readonly property var timedEvents: events.filter(e => !e.allDay)
    readonly property var upcomingTimed: {
        const ref = Calendar.nowMs;
        if (!isToday)
            return timedEvents;
        return timedEvents.filter(e => !Calendar.isEventPast(e, ref));
    }
    readonly property var earlierTimed: {
        const ref = Calendar.nowMs;
        if (!isToday)
            return [];
        return timedEvents.filter(e => Calendar.isEventPast(e, ref));
    }
    readonly property var spotlightEvent: isToday && upcomingTimed.length > 0 ? upcomingTimed[0] : null
    readonly property var laterTimed: spotlightEvent !== null ? upcomingTimed.slice(1) : upcomingTimed
    readonly property var actionables: Tasks.items

    onIsTodayChanged: showEarlier = false

    Connections {
        target: Calendar

        function onSelectedChanged(): void {
            root.showEarlier = false;
        }
    }

    // A link from an event, opened only if it is a web link.
    function openWeb(link: string): void {
        if (/^https?:\/\//i.test(link ?? ""))
            Qt.openUrlExternally(link);
    }

    function moreMenu(button: Item, event: var): void {
        const entries = [];
        entries.push({ icon: "checklist", label: "Add prep actionable", run: () => Tasks.addPrepFor(event, Calendar.selected) });
        if (event.video !== "")
            entries.push({ icon: "videocam", label: "Join meeting", run: () => root.openWeb(event.video) });
        if (event.local) {
            entries.push({ icon: "edit", label: "Edit", run: () => root.page.editEvent(event) });
            entries.push({ icon: "content_copy", label: "Duplicate", run: () => root.page.duplicateEvent(event) });
        } else if (event.link !== "") {
            entries.push({ icon: "open_in_new", label: "Open in Google Calendar", run: () => root.openWeb(event.link) });
        }
        entries.push({ icon: "visibility_off", label: `Hide ${event.calendar}`, run: () => Calendar.setHidden(event.calendarId, true) });
        if (event.local)
            entries.push({ separator: true }, { icon: "delete", label: "Delete event", danger: true, run: () => root.page.deleteEvent(event) });
        page.openMenu(button, entries);
    }

    function submitActionable(): void {
        const text = newActionable.text.trim();
        if (text === "")
            return;
        Tasks.add(text, Calendar.selected, "");
        newActionable.text = "";
    }

    Flickable {
        anchors.fill: parent
        anchors.margins: 14
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: column.implicitHeight + 10

        ColumnLayout {
            id: column

            width: parent.width
            spacing: 12

            // Header: Today focus, or selected day with one-click "Back to Today".
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 2
                Layout.leftMargin: 2
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Label {
                            Layout.fillWidth: true
                            text: root.isToday
                                ? "Today"
                                : Calendar.format(Calendar.selected, Calendar.selected.slice(0, 4) === Calendar.todayDay.slice(0, 4) ? "dddd, d MMMM" : "dddd, d MMMM yyyy")
                            elide: Text.ElideRight
                            font.pixelSize: root.isToday ? 20 : 17
                            weight: Font.DemiBold
                        }

                        Label {
                            Layout.fillWidth: true
                            text: root.isToday
                                ? Calendar.format(Calendar.todayDay, "dddd, d MMMM")
                                : (root.events.length === 0 ? "No events" : root.events.length === 1 ? "1 event" : `${root.events.length} events`)
                            elide: Text.ElideRight
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                        }
                    }

                    IconButton {
                        icon: "add"
                        tip: "Create event"
                        size: 32
                        filled: true
                        fillColor: Theme.glassControl
                        iconColor: Theme.m3onSurface
                        onClicked: root.page.createEvent(Calendar.selected, -1)
                    }
                }

                // One-click snap back to Today whenever viewing another day.
                RowLayout {
                    Layout.fillWidth: true
                    visible: !root.isToday

                    Pill {
                        style: "tonal"
                        icon: "today"
                        text: "Back to Today"
                        size: 30
                        fontSize: 12
                        onClicked: Calendar.selected = Calendar.todayDay
                    }

                    Item {
                        Layout.fillWidth: true
                    }
                }
            }

            // 1. Next-Up Meeting Spotlight (Today only)
            NextMeetingCard {
                Layout.fillWidth: true
                visible: root.spotlightEvent !== null
                event: root.spotlightEvent ?? ({})
                onJoin: url => root.openWeb(url)
                onAddPrep: Tasks.addPrepFor(root.spotlightEvent, Calendar.todayDay)
                onMore: button => root.moreMenu(button, root.spotlightEvent)
            }

            // 2. All-day events for the selected day (compact slim strips)
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.allDayEvents.length > 0
                spacing: 6

                Repeater {
                    model: root.allDayEvents

                    delegate: Rectangle {
                        id: allDayRow

                        required property var modelData

                        Layout.fillWidth: true
                        implicitHeight: 34
                        radius: Theme.cardRadius
                        color: Theme.glassCard
                        border.width: Theme.glass ? 0 : 1
                        border.color: Theme.glassBorderSubtle

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 6
                            spacing: 8

                            Rectangle {
                                width: 7
                                height: 7
                                radius: 3.5
                                color: allDayRow.modelData.color || Theme.m3primary
                            }

                            Label {
                                Layout.fillWidth: true
                                text: allDayRow.modelData.title ?? ""
                                elide: Text.ElideRight
                                font.pixelSize: 12
                                weight: Font.Medium
                            }

                            Label {
                                text: "All day"
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 11
                            }

                            IconButton {
                                id: allDayMore

                                icon: "more_horiz"
                                tip: "More options"
                                size: 24
                                onClicked: root.moreMenu(allDayMore, allDayRow.modelData)
                            }
                        }
                    }
                }
            }

            // 3. Remaining schedule (Today's later meetings, or selected day's meetings)
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.laterTimed.length > 0
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 2

                    Label {
                        Layout.fillWidth: true
                        text: root.isToday ? (root.spotlightEvent !== null ? "Later today" : "Today's schedule") : "Schedule"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                        weight: Font.Medium
                    }

                    Label {
                        text: `${root.laterTimed.length}`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 11
                    }
                }

                Repeater {
                    model: root.laterTimed

                    delegate: EventCard {
                        required property var modelData

                        Layout.fillWidth: true
                        event: modelData
                        onEdit: modelData.local ? root.page.editEvent(modelData) : root.openWeb(modelData.link)
                        onMore: button => root.moreMenu(button, modelData)
                        onAddPrep: Tasks.addPrepFor(modelData, Calendar.selected)
                    }
                }
            }

            // 4. Compact empty-schedule note (never steals space from Actionables)
            Rectangle {
                Layout.fillWidth: true
                visible: root.isToday
                    ? (root.spotlightEvent === null && root.allDayEvents.length === 0)
                    : (root.events.length === 0)
                implicitHeight: emptyRow.implicitHeight + 22
                radius: Theme.cardRadius
                color: Theme.glassCard
                border.width: Theme.glass ? 0 : 1
                border.color: Theme.glassBorderSubtle

                RowLayout {
                    id: emptyRow

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 12
                    anchors.rightMargin: 10
                    spacing: 10

                    Icon {
                        name: root.isToday && root.earlierTimed.length > 0 ? "event_available" : "calendar_today"
                        size: 20
                        color: Theme.m3primary
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.isToday
                            ? (root.earlierTimed.length > 0 ? "No more meetings today." : "No meetings today.")
                            : (root.isPast ? "No events recorded on this day." : "No meetings planned.")
                        wrapMode: Text.Wrap
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }

                    Pill {
                        style: "tonal"
                        icon: "add"
                        text: "New"
                        size: 28
                        fontSize: 12
                        onClicked: root.page.createEvent(Calendar.selected, -1)
                    }
                }
            }

            // 5. Collapsed / dimmed "Earlier today (N)" toggle (Today only)
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.isToday && root.earlierTimed.length > 0
                spacing: 6

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 32
                    radius: Theme.controlRadius
                    color: earlierArea.containsMouse ? Theme.glassHover : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 8
                        spacing: 6

                        Icon {
                            name: root.showEarlier ? "expand_more" : "chevron_right"
                            size: 18
                            color: Theme.m3onSurfaceVariant
                        }

                        Label {
                            Layout.fillWidth: true
                            text: `Earlier today (${root.earlierTimed.length})`
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                            weight: Font.Medium
                        }
                    }

                    MouseArea {
                        id: earlierArea

                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.showEarlier = !root.showEarlier
                    }
                }

                Repeater {
                    model: root.showEarlier ? root.earlierTimed : []

                    delegate: EventCard {
                        required property var modelData

                        Layout.fillWidth: true
                        event: modelData
                        dimmed: true
                        onEdit: modelData.local ? root.page.editEvent(modelData) : root.openWeb(modelData.link)
                        onMore: button => root.moreMenu(button, modelData)
                        onAddPrep: Tasks.addPrepFor(modelData, Calendar.selected)
                    }
                }
            }

            // 6. Today's Actionables (lightweight SQLite checklist)
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                Layout.leftMargin: 2

                Label {
                    Layout.fillWidth: true
                    text: root.isToday ? "Today's actionables" : "Actionables"
                    font.pixelSize: 14
                    weight: Font.Medium
                }

                Label {
                    visible: root.actionables.length > 0
                    text: Tasks.openCount === 0 ? "All done" : `${Tasks.openCount} open`
                    color: Tasks.openCount === 0 ? Theme.m3tertiary : Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: actionablesCol.implicitHeight + 8
                radius: Theme.cardRadius
                color: Theme.glassCard
                border.width: Theme.glass ? 0 : 1
                border.color: Theme.glassBorderSubtle

                GlassEdge {
                    visible: Theme.glass
                    radius: parent.radius
                    side: false
                }

                ColumnLayout {
                    id: actionablesCol

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 4
                    spacing: 2

                    // Inline "+ Add actionable" input
                    Item {
                        Layout.fillWidth: true
                        implicitHeight: 38

                        IconButton {
                            x: 6
                            anchors.verticalCenter: parent.verticalCenter
                            icon: "add"
                            tip: "Add actionable"
                            size: 28
                            iconColor: newActionable.text.trim() !== "" ? Theme.m3primary : Theme.m3onSurfaceVariant
                            onClicked: root.submitActionable()
                        }

                        TextInput {
                            id: newActionable

                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 38
                            anchors.rightMargin: 12
                            renderType: Text.NativeRendering
                            color: Theme.m3onSurface
                            font.family: Theme.sans
                            font.pixelSize: 13
                            clip: true
                            onAccepted: root.submitActionable()

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: newActionable.text === ""
                                text: root.isToday ? "Add actionable for today" : `Add actionable for ${Calendar.format(Calendar.selected, "ddd d MMM")}`
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 13
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                        visible: root.actionables.length > 0
                        implicitHeight: 1
                        color: Theme.glassDivider
                    }

                    Repeater {
                        model: root.actionables

                        delegate: TaskRow {
                            Layout.fillWidth: true
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        Layout.leftMargin: 12
                        Layout.rightMargin: 12
                        Layout.topMargin: 2
                        Layout.bottomMargin: 8
                        visible: root.actionables.length === 0
                        text: "No actionables yet — type above or click Prep on any meeting."
                        wrapMode: Text.Wrap
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }
                }
            }
        }
    }
}
