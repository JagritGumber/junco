import QtQuick
import QtQuick.Layouts
import qs.services

// One row of the mail list: who it's from (or what it's about), the subject
// or a summary of a folded group, when, and chips for issue numbers. Unread
// rows carry a dot; the open one is tinted and outlined.
Item {
    id: root

    required property var row
    readonly property bool selected: Inbox.selectedRow === row.id
    readonly property bool unread: row.unread > 0
    readonly property bool folded: row.kind === "group" && row.count > 1
    readonly property bool open: Inbox.expanded[row.id] === true
    readonly property var tile: ({
            meeting: [Theme.m3primaryContainer, Theme.m3onPrimaryContainer],
            dev: [Theme.m3tertiaryContainer, Theme.m3onTertiaryContainer],
            college: [Theme.m3secondaryContainer, Theme.m3onSecondaryContainer],
            trash: [Theme.m3surfaceContainerHighest, Theme.m3onSurfaceVariant],
            scheduled: [Theme.m3secondaryContainer, Theme.m3onSecondaryContainer]
        })[row.category] ?? [Theme.m3surfaceContainerHighest, Theme.m3onSurfaceVariant]

    signal clicked

    implicitHeight: Math.max(76, content.implicitHeight + 26)

    Rectangle {
        id: wash

        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: 18
        color: root.selected ? Theme.alpha(Theme.m3primary, 0.16) : (area.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.05) : "transparent")
        border.width: root.selected ? 1.5 : 0
        border.color: Theme.alpha(Theme.m3primary, 0.55)
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    Rectangle {
        x: 8
        anchors.verticalCenter: parent.verticalCenter
        width: 7
        height: 7
        radius: 4
        visible: root.unread
        color: Theme.m3primary
    }

    RowLayout {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 24
        anchors.rightMargin: 14
        spacing: 14
        z: 1

        // A logo when the sender has one; otherwise a tile for what it is,
        // or a person's initials.
        Item {
            Layout.alignment: Qt.AlignTop
            implicitWidth: 44
            implicitHeight: 44

            Avatar {
                anchors.fill: parent
                visible: (root.row.avatar ?? "") !== "" || (root.row.icon ?? "") === ""
                name: root.row.title
                image: root.row.avatar ?? ""
                size: 44
            }

            Rectangle {
                anchors.fill: parent
                visible: (root.row.avatar ?? "") === "" && (root.row.icon ?? "") !== ""
                radius: 14
                color: root.tile[0]

                Icon {
                    anchors.centerIn: parent
                    name: root.row.icon ?? ""
                    size: 22
                    color: root.tile[1]
                }
            }

            // Which of your accounts it came to.
            AccountBadge {
                x: parent.width - width + 4
                y: parent.height - height + 4
                account: root.row.account ?? ""
                ringWidth: 2
                ring: Qt.tint(Theme.m3surfaceContainerLow, wash.color)
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.fillWidth: true
                    text: root.row.title
                    elide: Text.ElideRight
                    font.pixelSize: 15
                    font.weight: root.unread ? Font.DemiBold : Font.Medium
                }

                Icon {
                    visible: root.row.starred ?? false
                    name: "star"
                    fill: 1
                    size: 16
                    color: Theme.m3tertiary
                }

                Label {
                    text: root.row.time
                    color: root.unread ? Theme.m3primary : Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                    font.weight: root.unread ? Font.DemiBold : Font.Normal
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Icon {
                    visible: root.row.attachment ?? false
                    name: "attach_file"
                    size: 15
                }

                Label {
                    Layout.fillWidth: true
                    text: root.row.subtitle
                    elide: Text.ElideRight
                    color: root.unread ? Theme.m3onSurface : Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }

                // A folded group opens in place.
                Rectangle {
                    visible: root.folded
                    implicitWidth: foldRow.implicitWidth + 12
                    implicitHeight: 22
                    radius: 11
                    color: Theme.m3surfaceContainerHighest

                    Row {
                        id: foldRow

                        anchors.centerIn: parent
                        spacing: 2

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.row.count
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }

                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: root.open ? "expand_less" : "expand_more"
                            size: 16
                        }
                    }
                }
            }

            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 4
                visible: (root.row.chips ?? []).length > 0
                spacing: 6

                Repeater {
                    model: root.row.chips ?? []

                    delegate: Rectangle {
                        required property string modelData

                        width: chipLabel.implicitWidth + 18
                        height: 24
                        radius: 12
                        color: Theme.m3surfaceContainerHighest

                        Label {
                            id: chipLabel

                            anchors.centerIn: parent
                            text: parent.modelData
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                            font.weight: Font.Medium
                        }
                    }
                }
            }
        }

        // Trash and scheduled rows carry their one action.
        Pill {
            visible: root.row.kind === "trash"
            text: "Restore"
            icon: "restore_from_trash"
            size: 32
            fontSize: 12
            onClicked: Inbox.act("untrash", [root.row.open])
        }

        Pill {
            visible: root.row.kind === "scheduled"
            text: "Send now"
            icon: "send"
            size: 32
            fontSize: 12
            onClicked: Inbox.sendScheduledNow(root.row.file)
        }

        IconButton {
            visible: root.row.kind === "scheduled"
            icon: "close"
            tip: "Cancel this scheduled email"
            size: 32
            onClicked: Inbox.cancelScheduled(root.row.file)
        }
    }
}
