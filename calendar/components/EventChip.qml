import QtQuick
import QtQuick.Layouts
import qs.services

// An event inside a month cell or the all-day row: tinted in its calendar's
// colour with a bar on the left, a cake for birthdays, the start time for
// timed events. Two lines when the cell has room, one when it's busy.
Rectangle {
    id: root

    required property var event
    property bool twoLines: false

    signal clicked
    signal doubleClicked

    // A tall chip grows to two lines only when the title needs them.
    implicitHeight: twoLines ? Math.min(46, Math.max(30, label.implicitHeight + 12)) : 24
    radius: 8
    color: Theme.alpha(event.color || Theme.m3primary, area.containsMouse ? 0.32 : 0.22)

    Rectangle {
        x: 4
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 4
        width: 3
        radius: 1.5
        color: root.event.color || Theme.m3primary
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 6
        spacing: 6

        Icon {
            visible: root.event.kind === "birthday"
            name: "cake"
            size: 16
            color: Theme.m3onSurface
        }

        Label {
            id: label

            Layout.fillWidth: true
            text: root.event.allDay ? root.event.title : `${Calendar.shortClock(root.event.startMinutes)}  ${root.event.title}`
            wrapMode: root.twoLines ? Text.Wrap : Text.NoWrap
            maximumLineCount: root.twoLines ? 2 : 1
            elide: Text.ElideRight
            font.pixelSize: 12
            font.weight: Font.Medium
            lineHeight: 1.05
        }
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
        onDoubleClicked: root.doubleClicked()
    }
}
