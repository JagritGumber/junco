import QtQuick
import qs.services

Rectangle {
    id: root

    property string account
    property bool selected: false

    readonly property var info: Inbox.accounts.find(a => a.id === account) ?? null

    signal clicked

    implicitHeight: 28
    implicitWidth: row.implicitWidth + 5 + 11
    radius: height / 2
    color: selected ? Theme.pill : (area.containsMouse ? Theme.glassControlHover : Theme.glassControl)
    border.width: Theme.glass ? 0 : (selected ? 0 : 1)
    border.color: Theme.glassBorderSubtle

    Row {
        id: row

        anchors.left: parent.left
        anchors.leftMargin: 5
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6

        AccountBadge {
            anchors.verticalCenter: parent.verticalCenter
            visible: true
            account: root.account
            size: 20
            tip: ""
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.info?.email ?? root.account
            color: root.selected ? Theme.pillInk : Theme.m3onSurfaceVariant
            font.pixelSize: 12
            weight: root.selected ? Font.Medium : Font.Normal
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
