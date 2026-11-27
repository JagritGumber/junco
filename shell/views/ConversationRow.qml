import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// One spacious conversation row (~76 px tall, ~8-10 threads on screen):
// clean circular avatar, 3-line stack (Sender + tiny pink unread dot | Medium
// subject | single-line muted snippet), and a soft pastel-pink inset card fill
// when selected (no vertical left stripe, no per-row clutter).
Rectangle {
    id: root

    property var conversation
    readonly property bool selected: Inbox.selectedId === conversation.id
    readonly property bool unread: conversation.unread > 0
    readonly property bool hovered: rowHover.hovered
    readonly property string subjectText: (conversation.subject ?? "").trim() || (conversation.preview ?? "")
    readonly property string snippetText: {
        const s = (conversation.snippet ?? conversation.preview ?? "").trim();
        return s === subjectText ? "" : s;
    }
    readonly property bool hasExpiry: (conversation.expiry ?? null) !== null

    implicitHeight: (snippetText !== "" ? 76 : 64) + (hasExpiry ? 24 : 0)
    radius: 14
    color: selected ? Theme.glassSelectedRow : (hovered ? Theme.glassHover : "transparent")
    border.width: !Theme.glass && selected ? 1 : 0
    border.color: Theme.glassActiveBorder

    HoverHandler {
        id: rowHover
    }

    RowLayout {
        z: 1
        anchors.fill: parent
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        anchors.topMargin: 10
        anchors.bottomMargin: 10
        spacing: 12

        Avatar {
            Layout.alignment: Qt.AlignVCenter
            name: root.conversation.name
            icon: root.conversation.icon ?? ""
            logo: root.conversation.logo ?? ""
            accentLogo: root.conversation.logo === "linear"
            image: root.conversation.avatar ?? ""
            size: 36
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 2

            // Line 1: Sender + tiny pink unread dot | muted time
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Item {
                    Layout.fillWidth: true
                    implicitHeight: senderRow.implicitHeight

                    Row {
                        id: senderRow

                        width: parent.width
                        spacing: 6

                        Label {
                            width: Math.min(implicitWidth, Math.max(0, parent.width - (root.unread ? 12 : 0)))
                            text: root.conversation.name
                            elide: Text.ElideRight
                            color: Theme.m3onSurface
                            font.pixelSize: 13
                            weight: root.unread || root.selected ? Font.Medium : Font.Normal
                        }

                        Rectangle {
                            visible: root.unread
                            anchors.verticalCenter: parent.verticalCenter
                            width: 6
                            height: 6
                            radius: 3
                            color: Theme.complementDot
                        }
                    }
                }

                Label {
                    text: root.conversation.time
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 11
                    weight: Font.Normal
                }
            }

            // Line 2: Medium-weight subject
            Label {
                Layout.fillWidth: true
                text: root.subjectText
                elide: Text.ElideRight
                color: Theme.m3onSurface
                font.pixelSize: 12
                weight: Font.Medium
            }

            // Line 3: Single-line muted snippet + hover-only archive action
            RowLayout {
                Layout.fillWidth: true
                visible: root.snippetText !== "" || root.hovered
                spacing: 6

                Label {
                    Layout.fillWidth: true
                    text: root.snippetText
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }

                IconButton {
                    visible: root.hovered
                    icon: "archive"
                    tip: "Archive conversation"
                    size: 22
                    onClicked: Inbox.archiveConversation(root.conversation.id)
                }
            }

            // Subtle compact expiry pill shown ONLY when this thread has a scheduled deletion.
            ExpiryBadge {
                Layout.topMargin: 2
                visible: root.hasExpiry
                expiry: root.conversation.expiry ?? null
                compact: true
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
