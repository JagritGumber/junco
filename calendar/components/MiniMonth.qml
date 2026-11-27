import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Compact mini-month picker (saves ~74 px vertical in CalendarSidebar).
ColumnLayout {
    id: root

    property date date: new Date()
    property int shift: 0
    property string selected: ""
    property bool longNames: false
    // Ink and the picked-day fill: navy on cards and popups (the defaults);
    // CalendarSidebar passes the sheet's light ink.
    property color ink: Theme.m3onSurface
    property color inkVariant: Theme.m3onSurfaceVariant
    property color pickedFill: Theme.glassActive

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

    spacing: 4

    RowLayout {
        Label {
            Layout.fillWidth: true
            Layout.leftMargin: 2
            text: Qt.formatDate(root.shown, "MMMM yyyy")
            color: root.ink
            font.pixelSize: 13
            font.letterSpacing: -0.2
            weight: Font.DemiBold
        }

        IconButton {
            icon: "chevron_left"
            tip: "Previous month"
            size: 24
            iconColor: root.inkVariant
            onClicked: root.shift--
        }

        IconButton {
            icon: "chevron_right"
            tip: "Next month"
            size: 24
            iconColor: root.inkVariant
            onClicked: root.shift++
        }
    }

    GridLayout {
        Layout.fillWidth: true
        columns: 7
        rowSpacing: 1
        columnSpacing: 0

        Repeater {
            model: root.longNames ? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] : ["M", "T", "W", "T", "F", "S", "S"]

            delegate: Label {
                required property string modelData

                Layout.fillWidth: true
                Layout.preferredWidth: 1
                horizontalAlignment: Text.AlignHCenter
                text: modelData
                color: root.inkVariant
                font.pixelSize: 11
                weight: Font.Normal
            }
        }

        Repeater {
            model: 42

            delegate: Item {
                id: cell

                required property int index
                readonly property int day: index - root.offset + 1
                readonly property bool inMonth: day > 0 && day <= root.days
                readonly property string key: `${root.year}-${String(root.month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`
                readonly property bool today: key === Calendar.todayDay
                readonly property bool picked: root.selected === "" ? today : key === root.selected

                Layout.fillWidth: true
                Layout.preferredWidth: 1
                implicitHeight: 24

                Rectangle {
                    anchors.centerIn: parent
                    width: 22
                    height: 22
                    radius: 11
                    visible: cell.inMonth && (cell.picked || cell.today || area.containsMouse)
                    // Glass: today is a filled pink accent dot, the picked day a
                    // clear-glass fill; no rings. Solid mode keeps the ring.
                    color: Theme.glass ? (cell.today ? Theme.accentFill : cell.picked ? root.pickedFill : "transparent") : (cell.picked ? Theme.m3primary : "transparent")
                    border.width: !Theme.glass && cell.today && !cell.picked ? 1.5 : 0
                    border.color: Theme.m3primary

                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        visible: area.containsMouse && !cell.picked
                        color: Theme.glassControlHover
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: cell.inMonth
                    tabular: true
                    text: cell.day
                    color: Theme.glass ? (cell.today ? Theme.accentFillInk : root.ink) : (cell.picked ? Theme.m3onPrimary : cell.today ? Theme.m3primary : Theme.m3onSurface)
                    font.pixelSize: 11
                    weight: cell.picked || cell.today ? Font.DemiBold : Font.Normal
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
