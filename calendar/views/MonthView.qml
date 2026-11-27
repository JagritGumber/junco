import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Month grid with crisp frosted lines and compact day headers (+78 px more
// vertical event space across 6 weeks).
Item {
    id: root

    required property var page

    readonly property int rows: Calendar.monthRows
    readonly property string month: Calendar.selected.slice(0, 7)
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
        height: 26

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
                font.pixelSize: 12
                weight: Font.Normal
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

        Repeater {
            model: root.rows

            delegate: Rectangle {
                required property int index

                y: Math.round(index * grid.cellHeight)
                width: grid.width
                height: 1
                color: Theme.glassGrid
            }
        }

        Repeater {
            model: 6

            delegate: Rectangle {
                required property int index

                x: Math.round((index + 1) * grid.cellWidth)
                width: 1
                height: grid.height
                color: Theme.glassGrid
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

                readonly property real room: height - 34
                readonly property int fitsTall: Math.max(0, Math.floor((room + 3) / 40))
                readonly property int fitsShort: Math.max(0, Math.floor((room + 2) / 23))
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
                    anchors.margins: 2
                    radius: 10
                    visible: cell.picked || area.containsMouse
                    color: cell.picked ? Theme.glassActive : Theme.glassHover
                    border.width: !Theme.glass && cell.picked ? 1 : 0
                    border.color: Theme.glassActiveBorder
                }

                Rectangle {
                    x: 6
                    y: 5
                    width: 24
                    height: 24
                    radius: 12
                    visible: cell.picked || cell.today
                    // Glass: today is a filled pink accent dot; the picked day's
                    // cell is already a clear-glass card, so its number only
                    // gets a lighter glass dot. No rings.
                    color: Theme.glass ? (cell.today ? Theme.accentFill : Theme.glassControlHover) : (cell.picked ? Theme.m3primary : "transparent")
                    border.width: !Theme.glass && cell.today && !cell.picked ? 1.5 : 0
                    border.color: Theme.m3primary
                }

                Label {
                    x: cell.picked || cell.today ? 6 : 10
                    y: 5
                    width: 24
                    height: 24
                    horizontalAlignment: cell.picked || cell.today ? Text.AlignHCenter : Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                    text: Number(cell.day.slice(8))
                    color: Theme.glass ? (cell.today ? Theme.accentFillInk : cell.inMonth ? Theme.m3onSurface : Theme.alpha(Theme.m3onSurfaceVariant, 0.6)) : (cell.picked ? Theme.m3onPrimary : cell.today ? Theme.m3primary : cell.inMonth ? Theme.m3onSurface : Theme.alpha(Theme.m3onSurfaceVariant, 0.55))
                    font.pixelSize: 13
                    weight: cell.picked || cell.today ? Font.Medium : Font.Normal
                }

                Column {
                    x: 5
                    y: 31
                    width: parent.width - 10
                    spacing: cell.tall ? 3 : 2

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
                        leftPadding: 5
                        text: `+${cell.events.length - cell.shownCount} more`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 11
                        weight: Font.Normal

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
