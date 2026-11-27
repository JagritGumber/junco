import QtQuick
import qs.services

// Which inbox a conversation or event belongs to: compact frosted pill with
// the account's picture and name.
Rectangle {
    id: root

    property string account

    readonly property bool local: account === "local"
    readonly property color tint: local ? Theme.m3onSurfaceVariant : Inbox.accountColor(account)

    implicitHeight: 20
    implicitWidth: row.implicitWidth + row.anchors.leftMargin + 7
    radius: height / 2
    color: Theme.glassControl
    border.width: 1
    border.color: Theme.glassBorderSubtle

    Row {
        id: row

        anchors.left: parent.left
        anchors.leftMargin: root.local ? 7 : 3
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
            size: 14
            tip: ""
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.local ? "This PC" : Inbox.accountLabel(root.account)
            color: Theme.m3onSurfaceVariant
            font.pixelSize: 11
            weight: Font.Medium
        }
    }
}
