import QtQuick
import QtQuick.Layouts
import qs.services

// An event chip inside a month cell or the all-day strip: filled, never
// outlined (Theme.eventFill), with the calendar's colour as a small marker.
Rectangle {
    id: root

    required property var event
    property bool twoLines: false

    signal clicked
    signal doubleClicked

    readonly property color baseTone: event.color || Theme.m3primary

    implicitHeight: twoLines ? Math.min(36, Math.max(24, label.implicitHeight + 8)) : 20
    radius: 6
    color: Theme.eventFill(baseTone, area.containsMouse)
    border.width: Theme.glass ? 0 : 1
    border.color: Theme.alpha(baseTone, 0.68)

    Rectangle {
        x: 3
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 3
        width: 2.5
        radius: 1.25
        color: root.event.color || Theme.m3primary
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 9
        anchors.rightMargin: 5
        spacing: 4

        Icon {
            visible: root.event.kind === "birthday"
            name: "cake"
            size: 13
            color: Theme.eventInk
        }

        Label {
            id: label

            Layout.fillWidth: true
            text: root.event.allDay ? root.event.title : `${Calendar.shortClock(root.event.startMinutes)} ${root.event.title}`
            wrapMode: root.twoLines ? Text.Wrap : Text.NoWrap
            maximumLineCount: root.twoLines ? 2 : 1
            elide: Text.ElideRight
            color: Theme.eventInk
            font.pixelSize: 11
            weight: Font.Normal
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
