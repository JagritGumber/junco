import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// One conversation in the inbox list. Hovering shows the archive button in
// the unread count's place; nothing else moves.
Rectangle {
    id: root

    property var conversation
    readonly property bool selected: Inbox.selectedId === conversation.id
    readonly property bool unread: conversation.unread > 0
    // Over any part of the row, the archive button included. (The row's own
    // MouseArea loses hover to the button, which made the badge and button
    // swap places under the pointer.)
    readonly property bool hovered: rowHover.hovered

    implicitHeight: 76
    radius: 22
    color: selected ? Theme.m3secondaryContainer : (hovered ? Theme.alpha(Theme.m3onSurface, 0.06) : "transparent")

    HoverHandler {
        id: rowHover
    }

    // Above the row's click area, so the archive button gets its own clicks;
    // the text and pictures let clicks through to open the conversation.
    RowLayout {
        z: 1
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 14
        spacing: 12

        Avatar {
            name: root.conversation.name
            icon: root.conversation.icon ?? ""
            logo: root.conversation.logo ?? ""
            accentLogo: root.conversation.logo === "linear"
            image: root.conversation.avatar ?? ""
            size: 48

            // Which of your accounts the newest email came to.
            AccountBadge {
                x: parent.width - width + 4
                y: parent.height - height + 4
                account: root.conversation.account ?? ""
                size: 20
                ringWidth: 2
                ring: Qt.tint(Theme.m3surfaceContainerLow, root.color)
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.fillWidth: true
                    text: root.conversation.name
                    elide: Text.ElideRight
                    color: root.selected ? Theme.m3onSecondaryContainer : Theme.m3onSurface
                    font.pixelSize: 15
                    font.weight: root.unread ? Font.DemiBold : Font.Medium
                }

                Label {
                    text: root.conversation.time
                    color: root.unread ? Theme.m3primary : Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                    font.weight: root.unread ? Font.DemiBold : Font.Normal
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.fillWidth: true
                    text: root.conversation.preview
                    elide: Text.ElideRight
                    color: root.unread ? Theme.m3onSurface : Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }

                // One slot for the unread count and, on hover, the archive
                // button (archive is like clearing a chat: it leaves the list
                // until someone writes again). The slot keeps the line's
                // height and width either way; the 30 px button overhangs it.
                Item {
                    Layout.preferredWidth: Math.max(30, badge.implicitWidth)
                    Layout.preferredHeight: 20

                    Rectangle {
                        id: badge

                        anchors.centerIn: parent
                        visible: root.unread && !root.hovered
                        implicitHeight: 20
                        implicitWidth: Math.max(20, count.implicitWidth + 12)
                        radius: 10
                        color: Theme.m3primary

                        Label {
                            id: count

                            anchors.centerIn: parent
                            text: root.conversation.unread > 99 ? "99+" : root.conversation.unread
                            color: Theme.m3onPrimary
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }
                    }

                    IconButton {
                        anchors.centerIn: parent
                        visible: root.hovered
                        icon: "archive"
                        tip: "Archive conversation"
                        size: 30
                        onClicked: Inbox.archiveConversation(root.conversation.id)
                    }
                }
            }
        }
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: Inbox.open(root.conversation.id)
    }
}
