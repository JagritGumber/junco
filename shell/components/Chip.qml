import QtQuick
import qs.services

Rectangle {
    id: root

    property string text
    property int count: 0
    property bool selected: false

    signal clicked

    implicitHeight: 26
    implicitWidth: row.implicitWidth + 20
    radius: height / 2
    color: selected ? Theme.pill : (area.containsMouse ? Theme.glassControlHover : Theme.glassControl)
    border.width: 1
    border.color: Theme.glass ? Theme.glassBorder : Theme.glassBorderSubtle

    Row {
        id: row

        anchors.centerIn: parent
        spacing: 5

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            color: root.selected ? Theme.pillInk : Theme.m3onSurfaceVariant
            font.pixelSize: 12
            weight: root.selected ? Font.Medium : Font.Normal
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.count > 0
            text: root.count > 99 ? "99+" : root.count
            color: root.selected ? Theme.pillInk : Theme.m3onSurface
            font.pixelSize: 11
            weight: Font.Medium
        }
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
