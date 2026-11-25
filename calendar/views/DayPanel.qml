import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Calendar's right column: the picked day's events with Edit and More, its
// to-dos, what's coming after it, and a way to add one more event.
Rectangle {
    id: root

    // The Calendar page, for creating and editing events and opening menus.
    required property var page

    readonly property var events: Calendar.dayEvents
    readonly property bool isToday: Calendar.selected === Calendar.todayDay
    readonly property bool isPast: Calendar.selected < Calendar.todayDay
    readonly property string dayName: isToday ? "today" : `on ${Calendar.format(Calendar.selected, "dddd")}`
    readonly property var todos: {
        Tasks.tasks;
        return Tasks.forDay(Calendar.selected);
    }

    // A link from an event, opened only if it is a web link. The engine
    // already passes nothing else (web_link); this is the second check.
    function openWeb(link: string): void {
        if (/^https?:\/\//i.test(link ?? ""))
            Qt.openUrlExternally(link);
    }

    function moreMenu(button: Item, event: var): void {
        const entries = [];
        if (event.local) {
            entries.push({ icon: "edit", label: "Edit", run: () => root.page.editEvent(event) });
            entries.push({ icon: "content_copy", label: "Duplicate", run: () => root.page.duplicateEvent(event) });
        } else if (event.link !== "") {
            entries.push({ icon: "open_in_new", label: "Open in Google Calendar", run: () => root.openWeb(event.link) });
        }
        if (event.video !== "")
            entries.push({ icon: "videocam", label: "Join the call", run: () => root.openWeb(event.video) });
        entries.push({ icon: "visibility_off", label: `Hide ${event.calendar}`, run: () => Calendar.setHidden(event.calendarId, true) });
        if (event.local)
            entries.push({ separator: true }, { icon: "delete", label: "Delete event", danger: true, run: () => root.page.deleteEvent(event) });
        page.openMenu(button, entries);
    }

    radius: 28
    color: Theme.m3surfaceContainerLow

    Flickable {
        anchors.fill: parent
        anchors.margins: 16
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: column.implicitHeight + 8

        ColumnLayout {
            id: column

            width: parent.width
            spacing: 14

            ColumnLayout {
                Layout.topMargin: 6
                Layout.leftMargin: 2
                spacing: 4

                Label {
                    Layout.fillWidth: true
                    text: Calendar.format(Calendar.selected, Calendar.selected.slice(0, 4) === Calendar.todayDay.slice(0, 4) ? "dddd, d MMMM" : "dddd, d MMMM yyyy")
                    elide: Text.ElideRight
                    font.pixelSize: 26
                    font.weight: Font.Medium
                }

                Label {
                    text: root.events.length === 0 ? "No events" : root.events.length === 1 ? "1 event" : `${root.events.length} events`
                    color: Theme.m3onSurfaceVariant
                }
            }

            Repeater {
                model: root.events

                delegate: EventCard {
                    required property var modelData

                    Layout.fillWidth: true
                    event: modelData
                    onEdit: modelData.local ? root.page.editEvent(modelData) : root.openWeb(modelData.link)
                    onMore: button => root.moreMenu(button, modelData)
                }
            }

            // To-dos for the picked day; type and press Enter to add one.
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 6
                Layout.leftMargin: 2

                Label {
                    Layout.fillWidth: true
                    text: "To-dos"
                    font.pixelSize: 20
                    font.weight: Font.Medium
                }

                Label {
                    visible: root.todos.length > 0
                    text: `${root.todos.filter(task => task.done).length} of ${root.todos.length} done`
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: todoList.implicitHeight + 8
                radius: 20
                color: Theme.m3surfaceContainer

                ColumnLayout {
                    id: todoList

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 4
                    spacing: 0

                    Repeater {
                        model: root.todos

                        delegate: TaskRow {
                            Layout.fillWidth: true
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        implicitHeight: 44

                        Icon {
                            x: 15
                            anchors.verticalCenter: parent.verticalCenter
                            name: "add"
                            size: 20
                        }

                        TextInput {
                            id: newTodo

                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 50
                            anchors.rightMargin: 14
                            renderType: Text.NativeRendering
                            color: Theme.m3onSurface
                            font.family: Theme.sans
                            font.pixelSize: 14
                            clip: true
                            onAccepted: {
                                Tasks.addOn(text, Calendar.selected);
                                text = "";
                            }

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: newTodo.text === ""
                                text: root.isToday ? "Add a to-do for today" : `Add a to-do for ${Calendar.format(Calendar.selected, "ddd d MMM")}`
                                color: Theme.m3onSurfaceVariant
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 6
                implicitHeight: 1
                color: Theme.m3outlineVariant
            }

            Label {
                Layout.leftMargin: 2
                text: "Coming up"
                font.pixelSize: 20
                font.weight: Font.Medium
            }

            Repeater {
                model: Calendar.comingUp

                delegate: EventLine {
                    required property var modelData

                    Layout.fillWidth: true
                    event: modelData
                    showDate: true
                    onClicked: Calendar.selected = modelData.startDay
                }
            }

            Label {
                Layout.leftMargin: 2
                visible: Calendar.comingUp.length === 0
                text: "Nothing in the six weeks after this day."
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 13
            }

            // The day has room: say so, and offer to fill it.
            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 8
                visible: root.events.length < 2
                implicitHeight: empty.implicitHeight + 48
                radius: 24
                color: Theme.m3surfaceContainer

                ColumnLayout {
                    id: empty

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 20
                    spacing: 8

                    // A calendar with a little burst beside it.
                    Item {
                        Layout.alignment: Qt.AlignHCenter
                        implicitWidth: 96
                        implicitHeight: 84

                        Icon {
                            anchors.centerIn: parent
                            anchors.horizontalCenterOffset: -6
                            anchors.verticalCenterOffset: 6
                            name: "calendar_month"
                            size: 64
                            weight: 300
                            color: Theme.m3primary
                        }

                        Repeater {
                            model: [-50, -15, 20]

                            delegate: Rectangle {
                                required property int modelData

                                x: 72 + Math.cos(modelData * Math.PI / 180) * 6
                                y: 26 + Math.sin(modelData * Math.PI / 180) * 18
                                width: 11
                                height: 2.5
                                radius: 1.25
                                rotation: modelData
                                color: Theme.m3primary
                            }
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: root.events.length === 0 ? `Nothing planned ${root.dayName}` : `No other events ${root.dayName}`
                        wrapMode: Text.Wrap
                        font.pixelSize: 17
                        font.weight: Font.Medium
                    }

                    Label {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignHCenter
                        text: root.isPast ? "This day has passed. You can still add\nan event to keep a record." : "Your day is clear. Enjoy the time\nor create a new event."
                        wrapMode: Text.Wrap
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                        lineHeight: 1.15
                    }

                    Pill {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: 10
                        style: "filled"
                        icon: "add"
                        text: "Create event"
                        size: 48
                        fontSize: 15
                        onClicked: root.page.createEvent(Calendar.selected, -1)
                    }
                }
            }
        }
    }
}
