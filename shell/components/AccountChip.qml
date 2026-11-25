import QtQuick
import qs.services

// An account to pick, as a chip: its picture (or initial) and its address.
// The compose window's From. (Not the shared Chip: Calendar uses that, and
// has no accounts.)
Rectangle {
    id: root

    property string account
    property bool selected: false

    readonly property var info: Inbox.accounts.find(a => a.id === account) ?? null

    signal clicked

    implicitHeight: 34
    implicitWidth: row.implicitWidth + 6 + 14
    radius: height / 2
    color: selected ? Theme.m3primary : (area.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent")
    border.width: selected ? 0 : 1
    border.color: Theme.m3outlineVariant

    Row {
        id: row

        anchors.left: parent.left
        anchors.leftMargin: 6
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        AccountBadge {
            anchors.verticalCenter: parent.verticalCenter
            // Shown even with one account; the chip's address names it.
            visible: true
            account: root.account
            size: 24
            tip: ""
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.info?.email ?? root.account
            color: root.selected ? Theme.m3onPrimary : Theme.m3onSurfaceVariant
            font.pixelSize: 13
            font.weight: Font.Medium
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
