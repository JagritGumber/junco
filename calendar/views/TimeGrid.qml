import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The Day and Week views: a column per day, an hour per row, all-day events
// above the hours and a line at the current time. Overlapping events share
// their column side by side. Double-click an empty hour to start an event there.
Item {
    id: root

    // The Calendar page, for creating and editing events.
    required property var page

    readonly property var days: {
        const count = Calendar.view === "week" ? 7 : 1;
        const list = [];
        for (let i = 0; i < count; i++)
            list.push(Calendar.addDays(Calendar.spanFirst, i));
        return list;
    }
    readonly property int hourHeight: 56
    readonly property int gutter: 68
    readonly property real columnWidth: (width - gutter) / days.length
    readonly property var allDay: days.map(day => Calendar.shownEvents.filter(event => event.allDay && Calendar.touches(event, day)))
    readonly property int allDayRows: Math.min(3, allDay.reduce((most, list) => Math.max(most, list.length), 0))
    property int nowMinutes: new Date().getHours() * 60 + new Date().getMinutes()

    function scrollToMorning(): void {
        const showToday = days.includes(Calendar.todayDay);
        hours.contentY = Math.max(0, Math.min(hours.contentHeight - hours.height, ((showToday ? Math.floor(nowMinutes / 60) - 1 : 8) * hourHeight)));
    }

    Component.onCompleted: Qt.callLater(scrollToMorning)
    onVisibleChanged: if (visible)
        Qt.callLater(scrollToMorning)

    Timer {
        interval: 60 * 1000
        running: root.visible
        repeat: true
        onTriggered: root.nowMinutes = new Date().getHours() * 60 + new Date().getMinutes()
    }

    // Weekday and date over each column.
    Item {
        id: header

        width: parent.width
        height: 72

        Repeater {
            model: root.days

            delegate: Item {
                id: head

                required property string modelData
                required property int index
                readonly property bool today: modelData === Calendar.todayDay
                readonly property bool picked: modelData === Calendar.selected && root.days.length > 1

                x: root.gutter + index * root.columnWidth
                width: root.columnWidth
                height: header.height

                Column {
                    anchors.centerIn: parent
                    spacing: 2

                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Calendar.format(head.modelData, root.days.length > 1 ? "ddd" : "dddd")
                        color: head.today ? Theme.m3primary : Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                        font.weight: Font.Medium
                    }

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 38
                        height: 38
                        radius: 19
                        color: head.today ? Theme.m3primary : head.picked ? Theme.alpha(Theme.m3primary, 0.18) : (headArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent")

                        Label {
                            anchors.centerIn: parent
                            text: Number(head.modelData.slice(8))
                            color: head.today ? Theme.m3onPrimary : Theme.m3onSurface
                            font.pixelSize: 18
                            font.weight: head.today || head.picked ? Font.DemiBold : Font.Normal
                        }
                    }
                }

                MouseArea {
                    id: headArea

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Calendar.selected = head.modelData
                    onDoubleClicked: {
                        Calendar.selected = head.modelData;
                        Calendar.setView("day");
                    }
                }
            }
        }
    }

    // All-day events, up to three a day, then "+N more".
    Item {
        id: allDayRow

        anchors.top: header.bottom
        width: parent.width
        height: root.allDayRows > 0 ? root.allDayRows * 27 + 8 : 0
        visible: root.allDayRows > 0

        Label {
            width: root.gutter - 12
            y: 6
            horizontalAlignment: Text.AlignRight
            text: "All day"
            color: Theme.m3onSurfaceVariant
            font.pixelSize: 11
        }

        Repeater {
            model: root.days

            delegate: Column {
                id: dayChips

                required property string modelData
                required property int index
                readonly property var list: root.allDay[index] ?? []
                readonly property int fits: list.length <= 3 ? list.length : 2

                x: root.gutter + index * root.columnWidth + 4
                y: 2
                width: root.columnWidth - 8
                spacing: 3

                Repeater {
                    model: dayChips.list.slice(0, dayChips.fits)

                    delegate: EventChip {
                        required property var modelData

                        width: dayChips.width
                        event: modelData
                        onClicked: Calendar.selected = dayChips.modelData
                        onDoubleClicked: if (modelData.local)
                            root.page.editEvent(modelData)
                    }
                }

                Label {
                    visible: dayChips.list.length > dayChips.fits
                    leftPadding: 6
                    text: `+${dayChips.list.length - dayChips.fits} more`
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                    font.weight: Font.Medium

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Calendar.selected = dayChips.modelData
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.top: allDayRow.bottom
        width: parent.width
        height: 1
        color: Theme.alpha(Theme.m3outlineVariant, 0.55)
    }

    Flickable {
        id: hours

        anchors.top: allDayRow.bottom
        anchors.topMargin: 1
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: 24 * root.hourHeight + 12

        Item {
            width: hours.width
            height: hours.contentHeight

            // Hour lines and labels.
            Repeater {
                model: 24

                delegate: Item {
                    required property int index

                    y: index * root.hourHeight + 6
                    width: parent.width
                    height: root.hourHeight

                    Label {
                        visible: parent.index > 0
                        width: root.gutter - 14
                        y: -7
                        horizontalAlignment: Text.AlignRight
                        text: `${parent.index % 12 === 0 ? 12 : parent.index % 12} ${parent.index < 12 ? "am" : "pm"}`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 11
                    }

                    Rectangle {
                        x: root.gutter - 6
                        width: parent.width - x
                        height: 1
                        visible: parent.index > 0
                        color: Theme.alpha(Theme.m3outlineVariant, 0.45)
                    }
                }
            }

            Repeater {
                model: root.days

                delegate: Item {
                    id: column

                    required property string modelData
                    required property int index
                    readonly property var placed: Calendar.lanes(Calendar.shownEvents.filter(event => !event.allDay && Calendar.touches(event, modelData)).map(event => {
                        // An event crossing midnight shows its part of this day.
                        const start = event.startDay < column.modelData ? 0 : event.startMinutes;
                        const end = event.endDay > column.modelData ? 1440 : event.endMinutes;
                        return Object.assign({}, event, { startMinutes: start, endMinutes: end });
                    }))

                    x: root.gutter + index * root.columnWidth
                    y: 6
                    width: root.columnWidth
                    height: 24 * root.hourHeight

                    Rectangle {
                        width: 1
                        height: parent.height
                        color: Theme.alpha(Theme.m3outlineVariant, 0.45)
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: Calendar.selected = column.modelData
                        onDoubleClicked: mouse => root.page.createEvent(column.modelData, Math.floor(mouse.y / root.hourHeight * 2) * 30)
                    }

                    Repeater {
                        model: column.placed

                        delegate: Rectangle {
                            id: block

                            required property var modelData
                            readonly property var event: modelData.event
                            readonly property real slot: (column.width - 8) / modelData.lanes

                            x: 4 + modelData.lane * slot
                            y: event.startMinutes / 60 * root.hourHeight + 1
                            width: slot - 3
                            height: Math.max(30, event.endMinutes - event.startMinutes) / 60 * root.hourHeight - 2
                            radius: 10
                            color: Qt.tint(Theme.m3surfaceContainerLow, Theme.alpha(event.color || Theme.m3primary, blockArea.containsMouse ? 0.42 : 0.3))
                            clip: true

                            Rectangle {
                                x: 4
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                anchors.margins: 5
                                width: 3
                                radius: 1.5
                                color: block.event.color || Theme.m3primary
                            }

                            Column {
                                x: 13
                                y: 5
                                width: parent.width - 18
                                spacing: 1

                                Label {
                                    width: parent.width
                                    text: block.event.title
                                    wrapMode: block.height > 64 ? Text.Wrap : Text.NoWrap
                                    maximumLineCount: Math.max(1, Math.floor((block.height - 26) / 16))
                                    elide: Text.ElideRight
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                }

                                Label {
                                    width: parent.width
                                    visible: block.height >= 44
                                    text: block.event.time
                                    elide: Text.ElideRight
                                    color: Theme.m3onSurfaceVariant
                                    font.pixelSize: 11
                                }
                            }

                            MouseArea {
                                id: blockArea

                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: Calendar.selected = column.modelData
                                onDoubleClicked: if (block.event.local)
                                    root.page.editEvent(block.event)
                            }
                        }
                    }

                    // Now.
                    Item {
                        visible: column.modelData === Calendar.todayDay
                        y: root.nowMinutes / 60 * root.hourHeight
                        width: parent.width
                        z: 2

                        Rectangle {
                            x: -5
                            y: -5
                            width: 10
                            height: 10
                            radius: 5
                            color: Theme.m3error
                        }

                        Rectangle {
                            y: -1
                            width: parent.width
                            height: 2
                            color: Theme.m3error
                        }
                    }
                }
            }
        }
    }
}
