import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Day and Week views: tighter 50 px header, 46 px hour rows (~18 hours visible
// at once on 1080p), 52 px time gutter, and crisp frosted event blocks.
Item {
    id: root

    required property var page

    readonly property var days: {
        const count = Calendar.view === "week" ? 7 : 1;
        const list = [];
        for (let i = 0; i < count; i++)
            list.push(Calendar.addDays(Calendar.spanFirst, i));
        return list;
    }
    readonly property int hourHeight: 54
    readonly property int gutter: 56
    readonly property real columnWidth: (width - gutter) / days.length
    readonly property var allDay: days.map(day => Calendar.shownEvents.filter(event => event.allDay && Calendar.touches(event, day)))
    readonly property int allDayRows: Math.min(3, allDay.reduce((most, list) => Math.max(most, list.length), 0))
    readonly property int nowMinutes: {
        const current = new Date(Calendar.nowMs);
        return current.getHours() * 60 + current.getMinutes();
    }

    function scrollToMorning(): void {
        const showToday = days.includes(Calendar.todayDay);
        hours.contentY = Math.max(0, Math.min(hours.contentHeight - hours.height, ((showToday ? Math.max(0, Math.floor(nowMinutes / 60) - 2) : 8) * hourHeight)));
    }

    Component.onCompleted: Qt.callLater(scrollToMorning)
    onVisibleChanged: if (visible)
        Qt.callLater(scrollToMorning)

    Item {
        id: header

        width: parent.width
        height: 60

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
                    spacing: 3

                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Calendar.format(head.modelData, root.days.length > 1 ? "ddd" : "dddd").toUpperCase()
                        color: head.today ? Theme.m3primary : Theme.m3onSurfaceVariant
                        font.pixelSize: 10
                        font.letterSpacing: 0.45
                        weight: Font.DemiBold
                    }

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 30
                        height: 30
                        radius: 15
                        color: head.today ? Theme.accentFill : head.picked ? Theme.glassActive : (headArea.containsMouse ? Theme.glassHover : "transparent")

                        Behavior on color {
                            ColorAnimation {
                                duration: Theme.animFast
                                easing.type: Easing.OutCubic
                            }
                        }

                        Label {
                            anchors.centerIn: parent
                            tabular: true
                            text: Number(head.modelData.slice(8))
                            color: head.today ? Theme.accentFillInk : Theme.m3onSurface
                            font.pixelSize: 14
                            weight: head.today || head.picked ? Font.DemiBold : Font.Medium
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

    Item {
        id: allDayRow

        anchors.top: header.bottom
        width: parent.width
        height: root.allDayRows > 0 ? root.allDayRows * 23 + 6 : 0
        visible: root.allDayRows > 0

        Label {
            width: root.gutter - 10
            y: 4
            horizontalAlignment: Text.AlignRight
            text: "All day"
            color: Theme.m3onSurfaceVariant
            font.pixelSize: 10
        }

        Repeater {
            model: root.days

            delegate: Column {
                id: dayChips

                required property string modelData
                required property int index
                readonly property var list: root.allDay[index] ?? []
                readonly property int fits: list.length <= 3 ? list.length : 2

                x: root.gutter + index * root.columnWidth + 3
                y: 2
                width: root.columnWidth - 6
                spacing: 2

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
                    leftPadding: 5
                    text: `+${dayChips.list.length - dayChips.fits} more`
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 11
                    weight: Font.Normal

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
        color: Theme.glassGrid
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
        contentHeight: 24 * root.hourHeight + 10

        Item {
            width: hours.width
            height: hours.contentHeight

            Repeater {
                model: 24

                delegate: Item {
                    required property int index

                    y: index * root.hourHeight + 5
                    width: parent.width
                    height: root.hourHeight

                    Label {
                        visible: parent.index > 0
                        width: root.gutter - 12
                        y: -6
                        horizontalAlignment: Text.AlignRight
                        tabular: true
                        text: `${parent.index % 12 === 0 ? 12 : parent.index % 12}${parent.index < 12 ? "am" : "pm"}`
                        color: Theme.m3onSurfaceVariant
                        opacity: 0.82
                        font.pixelSize: 11
                        weight: Font.Medium
                    }

                    Rectangle {
                        x: root.gutter - 4
                        width: parent.width - x
                        height: 1
                        visible: parent.index > 0
                        color: Theme.glassGrid
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
                        const start = event.startDay < column.modelData ? 0 : event.startMinutes;
                        const end = event.endDay > column.modelData ? 1440 : event.endMinutes;
                        return Object.assign({}, event, { startMinutes: start, endMinutes: end });
                    }))

                    x: root.gutter + index * root.columnWidth
                    y: 5
                    width: root.columnWidth
                    height: 24 * root.hourHeight

                    Rectangle {
                        width: 1
                        height: parent.height
                        color: Theme.glassGrid
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
                            readonly property real slot: (column.width - 6) / modelData.lanes

                            readonly property color baseTone: event.color || Theme.m3primary

                            x: 3 + modelData.lane * slot
                            y: event.startMinutes / 60 * root.hourHeight + 1
                            width: slot - 2
                            height: Math.max(26, event.endMinutes - event.startMinutes) / 60 * root.hourHeight - 2
                            radius: 10
                            color: Theme.eventFill(baseTone, blockArea.containsMouse)
                            border.width: Theme.glass ? 0 : 1
                            border.color: Theme.alpha(baseTone, 0.68)
                            clip: true

                            Behavior on color {
                                ColorAnimation {
                                    duration: Theme.animFast
                                    easing.type: Easing.OutCubic
                                }
                            }

                            Rectangle {
                                x: 4
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                anchors.margins: 4
                                width: 3
                                radius: 1.5
                                color: block.event.color || Theme.m3primary
                            }

                            Column {
                                x: 12
                                y: 5
                                width: parent.width - 16
                                spacing: 2

                                Label {
                                    width: parent.width
                                    text: block.event.title
                                    wrapMode: block.height > 54 ? Text.Wrap : Text.NoWrap
                                    maximumLineCount: Math.max(1, Math.floor((block.height - 22) / 15))
                                    elide: Text.ElideRight
                                    font.pixelSize: 12
                                    weight: Font.Medium
                                }

                                Label {
                                    width: parent.width
                                    visible: block.height >= 38
                                    tabular: true
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

                    Item {
                        visible: column.modelData === Calendar.todayDay
                        y: root.nowMinutes / 60 * root.hourHeight
                        width: parent.width
                        z: 2

                        Rectangle {
                            x: -4
                            y: -4
                            width: 8
                            height: 8
                            radius: 4
                            color: Theme.glass ? Theme.accentFill : Theme.m3error
                        }

                        Rectangle {
                            y: -1
                            width: parent.width
                            height: 1.5
                            color: Theme.glass ? Theme.accentFill : Theme.m3error
                        }
                    }
                }
            }
        }
    }
}
