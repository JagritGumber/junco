import QtQuick
import qs.services

// Which inbox a conversation or event belongs to: compact frosted pill with
// the account's picture and name.
Rectangle {
    id: root

    property string account

    readonly property bool local: account === "local"
    readonly property color tint: local ? Theme.m3onSurfaceVariant : Inbox.accountColor(account)

    implicitHeight: 22
    implicitWidth: row.implicitWidth + row.anchors.leftMargin + 8
    radius: height / 2
    color: Theme.glassControl
    border.width: Theme.glass ? 0 : 1
    border.color: Theme.glassBorderSubtle

    Row {
        id: row

        anchors.left: parent.left
        anchors.leftMargin: root.local ? 8 : 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 5

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.local
            width: 6
            height: 6
            radius: 3
            color: root.tint
        }

        AccountBadge {
            anchors.verticalCenter: parent.verticalCenter
            visible: !root.local
            account: root.local ? "" : root.account
            size: 15
            tip: ""
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.local ? "This PC" : Inbox.accountLabel(root.account)
            color: Theme.darkGlass ? Theme.alpha(Theme.m3onSurface, 0.90) : Theme.m3onSurfaceVariant
            font.pixelSize: 11
            weight: Font.Medium
        }
    }
}
