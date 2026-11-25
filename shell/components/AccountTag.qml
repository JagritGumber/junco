import QtQuick
import qs.services

// Which inbox a conversation or event belongs to: the account's picture (or
// its initial on its colour) and its name. "This PC" is a plain dot.
Rectangle {
    id: root

    property string account

    readonly property bool local: account === "local"
    readonly property color tint: local ? Theme.m3onSurfaceVariant : Inbox.accountColor(account)

    implicitHeight: 24
    implicitWidth: row.implicitWidth + row.anchors.leftMargin + 9
    radius: height / 2
    color: Theme.m3surfaceContainerHighest

    Row {
        id: row

        anchors.left: parent.left
        anchors.leftMargin: root.local ? 9 : 3
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.local
            width: 7
            height: 7
            radius: 4
            color: root.tint
        }

        AccountBadge {
            anchors.verticalCenter: parent.verticalCenter
            // Shown even with one account; the tag's name says which.
            visible: !root.local
            account: root.local ? "" : root.account
            size: 18
            tip: ""
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.local ? "This PC" : Inbox.accountLabel(root.account)
            color: Theme.m3onSurfaceVariant
            font.pixelSize: 12
            font.weight: Font.Medium
        }
    }
}
