import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The month as a grid of weeks, Monday first, with the days either side of
// it dimmed. A click picks a day; a double click starts an event on it.
Item {
    id: root

    // The Calendar page, for creating and editing events.
    required property var page

    readonly property int rows: Calendar.monthRows
    readonly property string month: Calendar.selected.slice(0, 7)
    // Day -> its events, multi-day events on every day they cover.
    readonly property var byDay: {
        const days = {};
        for (const event of Calendar.shownEvents) {
            let day = event.startDay < Calendar.spanFirst ? Calendar.spanFirst : event.startDay;
            while (day <= event.endDay && day < Calendar.spanAfter) {
                (days[day] = days[day] ?? []).push(event);
                day = Calendar.addDays(day, 1);
            }
        }
        return days;
    }

    Row {
        id: weekdays

        width: parent.width
        height: 44

        Repeater {
            model: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

            delegate: Label {
                required property string modelData

                width: weekdays.width / 7
                height: weekdays.height
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                text: modelData
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 14
                font.weight: Font.Medium
            }
        }
    }

    Item {
        id: grid

        readonly property real cellWidth: width / 7
        readonly property real cellHeight: height / root.rows

        anchors.top: weekdays.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom

        // Lines between weeks and days.
        Repeater {
            model: root.rows

            delegate: Rectangle {
                required property int index

                y: Math.round(index * grid.cellHeight)
                width: grid.width
                height: 1
                color: Theme.alpha(Theme.m3outlineVariant, 0.55)
            }
        }

        Repeater {
            model: 6

            delegate: Rectangle {
                required property int index

                x: Math.round((index + 1) * grid.cellWidth)
                width: 1
                height: grid.height
                color: Theme.alpha(Theme.m3outlineVariant, 0.55)
            }
        }

        Repeater {
            model: root.rows * 7

            delegate: Item {
                id: cell

                required property int index
                readonly property string day: Calendar.addDays(Calendar.spanFirst, index)
                readonly property bool inMonth: day.slice(0, 7) === root.month
                readonly property bool today: day === Calendar.todayDay
                readonly property bool picked: day === Calendar.selected
                readonly property var events: root.byDay[day] ?? []

                // Two-line chips while they fit, then one-line chips, then
                // as many as fit and "+N more".
                readonly property real room: height - 46
                readonly property int fitsTall: Math.max(0, Math.floor((room + 4) / 50))
                readonly property int fitsShort: Math.max(0, Math.floor((room + 3) / 27))
                readonly property bool tall: events.length <= fitsTall
                readonly property int shownCount: tall || events.length <= fitsShort ? events.length : Math.max(0, fitsShort - 1)

                x: Math.round((index % 7) * grid.cellWidth)
                y: Math.round(Math.floor(index / 7) * grid.cellHeight)
                width: Math.round(grid.cellWidth)
                height: Math.round(grid.cellHeight)

                MouseArea {
                    id: area

                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: Calendar.selected = cell.day
                    onDoubleClicked: root.page.createEvent(cell.day, -1)
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 3
                    radius: 14
                    visible: cell.picked || area.containsMouse
                    color: cell.picked ? Theme.alpha(Theme.m3primary, 0.14) : Theme.alpha(Theme.m3onSurface, 0.04)
                    border.width: cell.picked ? 1.5 : 0
                    border.color: Theme.alpha(Theme.m3primary, 0.75)
                }

                Rectangle {
                    x: 8
                    y: 8
                    width: 30
                    height: 30
                    radius: 15
                    visible: cell.picked || cell.today
                    color: cell.picked ? Theme.m3primary : "transparent"
                    border.width: cell.today && !cell.picked ? 1.5 : 0
                    border.color: Theme.m3primary
                }

                Label {
                    x: cell.picked || cell.today ? 8 : 16
                    y: 8
                    width: 30
                    height: 30
                    horizontalAlignment: cell.picked || cell.today ? Text.AlignHCenter : Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                    text: Number(cell.day.slice(8))
                    color: cell.picked ? Theme.m3onPrimary : cell.today ? Theme.m3primary : cell.inMonth ? Theme.m3onSurface : Theme.alpha(Theme.m3onSurfaceVariant, 0.6)
                    font.pixelSize: 16
                    font.weight: cell.picked || cell.today ? Font.DemiBold : Font.Normal
                }

                Column {
                    x: 8
                    y: 44
                    width: parent.width - 16
                    spacing: cell.tall ? 4 : 3

                    Repeater {
                        model: cell.events.slice(0, cell.shownCount)

                        delegate: EventChip {
                            required property var modelData

                            width: parent.width
                            event: modelData
                            twoLines: cell.tall
                            opacity: cell.inMonth ? 1 : 0.6
                            onClicked: Calendar.selected = cell.day
                            onDoubleClicked: if (modelData.local)
                                root.page.editEvent(modelData)
                        }
                    }

                    Label {
                        visible: cell.shownCount < cell.events.length
                        leftPadding: 6
                        text: `+${cell.events.length - cell.shownCount} more`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                        font.weight: Font.Medium

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Calendar.selected = cell.day
                        }
                    }
                }
            }
        }
    }
}
