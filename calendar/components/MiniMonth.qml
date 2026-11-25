import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// A month, Monday first. Given a selected day it follows it, fills it, rings
// today, and reports clicks; without one, today is the filled circle.
ColumnLayout {
    id: root

    property date date: new Date()
    // Months away from today's month; the arrows move it.
    property int shift: 0
    // "YYYY-MM-DD" to mark and follow, or "" to only show today.
    property string selected: ""
    property bool longNames: false

    signal picked(string day)

    readonly property date shown: new Date(date.getFullYear(), date.getMonth() + shift, 1)
    readonly property int year: shown.getFullYear()
    readonly property int month: shown.getMonth()
    readonly property int offset: (new Date(year, month, 1).getDay() + 6) % 7
    readonly property int days: new Date(year, month + 1, 0).getDate()

    function follow(): void {
        if (selected === "")
            return;
        const [y, m] = selected.split("-").map(Number);
        shift = (y - date.getFullYear()) * 12 + (m - 1 - date.getMonth());
    }

    onSelectedChanged: follow()
    Component.onCompleted: follow()

    spacing: 8

    RowLayout {
        Label {
            Layout.fillWidth: true
            text: Qt.formatDate(root.shown, "MMMM yyyy")
            font.pixelSize: 15
            font.weight: Font.Medium
        }

        IconButton {
            icon: "chevron_left"
            tip: "Previous month"
            size: 32
            onClicked: root.shift--
        }

        IconButton {
            icon: "chevron_right"
            tip: "Next month"
            size: 32
            onClicked: root.shift++
        }
    }

    GridLayout {
        Layout.fillWidth: true
        columns: 7
        rowSpacing: 2
        columnSpacing: 0

        Repeater {
            model: root.longNames ? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] : ["M", "T", "W", "T", "F", "S", "S"]

            delegate: Label {
                required property string modelData

                Layout.fillWidth: true
                Layout.preferredWidth: 1
                horizontalAlignment: Text.AlignHCenter
                text: modelData
                color: Theme.m3onSurfaceVariant
                font.pixelSize: root.longNames ? 12 : 11
                font.weight: Font.Medium
            }
        }

        // Six weeks of cells whatever the month, so the sidebar below never
        // moves when the month changes; cells outside the month stay empty.
        Repeater {
            model: 42

            delegate: Item {
                id: cell

                required property int index
                readonly property int day: index - root.offset + 1
                readonly property bool inMonth: day > 0 && day <= root.days
                readonly property string key: `${root.year}-${String(root.month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`
                readonly property bool today: key === Calendar.todayDay
                // Beside the inbox today is the filled circle; on the Calendar
                // page the picked day is, and today keeps a ring.
                readonly property bool picked: root.selected === "" ? today : key === root.selected

                Layout.fillWidth: true
                Layout.preferredWidth: 1
                implicitHeight: 34

                Rectangle {
                    anchors.centerIn: parent
                    width: 30
                    height: 30
                    radius: 15
                    visible: cell.inMonth && (cell.picked || cell.today || area.containsMouse)
                    color: cell.picked ? Theme.m3primary : "transparent"
                    border.width: cell.today && !cell.picked ? 1.5 : 0
                    border.color: Theme.m3primary

                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        visible: area.containsMouse && !cell.picked
                        color: Theme.alpha(Theme.m3onSurface, 0.08)
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: cell.inMonth
                    text: cell.day
                    color: cell.picked ? Theme.m3onPrimary : cell.today ? Theme.m3primary : Theme.m3onSurface
                    font.pixelSize: 13
                    font.weight: cell.picked || cell.today ? Font.DemiBold : Font.Normal
                }

                MouseArea {
                    id: area

                    anchors.fill: parent
                    enabled: cell.inMonth && root.selected !== ""
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.picked(cell.key)
                }
            }
        }
    }
}
