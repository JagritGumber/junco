import QtQuick
import qs.services

Rectangle {
    id: root

    property string text
    property int count: 0
    property bool selected: false

    signal clicked

    implicitHeight: 34
    implicitWidth: row.implicitWidth + 28
    radius: height / 2
    color: selected ? Theme.m3primary : (area.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent")
    border.width: selected ? 0 : 1
    border.color: Theme.m3outlineVariant

    Row {
        id: row

        anchors.centerIn: parent
        spacing: 6

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            color: root.selected ? Theme.m3onPrimary : Theme.m3onSurfaceVariant
            font.pixelSize: 13
            font.weight: Font.Medium
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.count > 0
            text: root.count > 99 ? "99+" : root.count
            color: root.selected ? Theme.m3onPrimary : Theme.m3onSurface
            font.pixelSize: 12
            font.weight: Font.DemiBold
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
