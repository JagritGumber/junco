import QtQuick
import QtQuick.Layouts
import qs.services

// One compact row of the mail list (54 px base height, down from 76 px).
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
            college: [Theme.glassActive, Theme.m3onSurface],
            trash: [Theme.glassControl, Theme.m3onSurfaceVariant],
            scheduled: [Theme.glassActive, Theme.m3onSurface]
        })[row.category] ?? [Theme.glassControl, Theme.m3onSurfaceVariant]

    signal clicked

    implicitHeight: Math.max(68, content.implicitHeight + 22)

    Rectangle {
        id: wash

        anchors.fill: parent
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: 14
        color: root.selected ? Theme.glassSelectedRow : (area.containsMouse ? Theme.glassHover : "transparent")
        border.width: !Theme.glass && root.selected ? 1 : 0
        border.color: Theme.glassActiveBorder
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    RowLayout {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        spacing: 12
        z: 1

        Item {
            Layout.alignment: Qt.AlignVCenter
            implicitWidth: 36
            implicitHeight: 36

            Avatar {
                anchors.fill: parent
                visible: (root.row.avatar ?? "") !== "" || (root.row.icon ?? "") === ""
                name: root.row.title
                image: root.row.avatar ?? ""
                size: 36
            }

            Rectangle {
                anchors.fill: parent
                visible: (root.row.avatar ?? "") === "" && (root.row.icon ?? "") !== ""
                radius: 18
                color: root.tile[0]

                Icon {
                    anchors.centerIn: parent
                    name: root.row.icon ?? ""
                    size: 18
                    color: root.tile[1]
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3

            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Item {
                    Layout.fillWidth: true
                    implicitHeight: titleRow.implicitHeight

                    Row {
                        id: titleRow

                        width: parent.width
                        spacing: 6

                        Label {
                            width: Math.min(implicitWidth, Math.max(0, parent.width - (root.unread ? 12 : 0)))
                            text: root.row.title
                            elide: Text.ElideRight
                            font.pixelSize: 13
                            weight: root.unread ? Font.Medium : Font.Normal
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

                Icon {
                    visible: root.row.starred ?? false
                    name: "star"
                    fill: 1
                    size: 14
                    color: Theme.m3tertiary
                }

                Label {
                    text: root.row.time
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 11
                    weight: Font.Normal
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 5

                Icon {
                    visible: root.row.attachment ?? false
                    name: "attach_file"
                    size: 13
                }

                Label {
                    Layout.fillWidth: true
                    text: root.row.subtitle
                    elide: Text.ElideRight
                    color: root.unread ? Theme.m3onSurface : Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }

                Rectangle {
                    visible: root.folded
                    implicitWidth: foldRow.implicitWidth + 10
                    implicitHeight: 18
                    radius: 9
                    color: Theme.glassControl

                    Row {
                        id: foldRow

                        anchors.centerIn: parent
                        spacing: 2

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.row.count
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 10
                            weight: Font.Medium
                        }

                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: root.open ? "expand_less" : "expand_more"
                            size: 14
                        }
                    }
                }
            }

            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 3
                visible: (!Theme.glass && (root.row.chips ?? []).length > 0) || (root.row.expiry ?? null) !== null
                spacing: 6

                ExpiryBadge {
                    visible: (root.row.expiry ?? null) !== null
                    expiry: root.row.expiry ?? null
                    compact: true
                }

                Repeater {
                    model: Theme.glass ? [] : (root.row.chips ?? [])

                    delegate: Rectangle {
                        required property string modelData

                        width: chipLabel.implicitWidth + 12
                        height: 18
                        radius: 9
                        color: Theme.glassControl
                        border.width: 1
                        border.color: Theme.glassBorderSubtle

                        Label {
                            id: chipLabel

                            anchors.centerIn: parent
                            text: parent.modelData
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 10
                            weight: Font.Normal
                        }
                    }
                }
            }
        }

        Pill {
            visible: root.row.kind === "trash"
            text: "Restore"
            icon: "restore_from_trash"
            size: 28
            fontSize: 11
            onClicked: Inbox.act("untrash", [root.row.open])
        }

        Pill {
            visible: root.row.kind === "scheduled"
            text: "Send now"
            icon: "send"
            size: 28
            fontSize: 11
            onClicked: Inbox.sendScheduledNow(root.row.file)
        }

        IconButton {
            visible: Inbox.folder === "expiring" && (root.row.expiry ?? null) !== null
            icon: "close"
            tip: "Cancel scheduled deletion"
            size: 28
            onClicked: Inbox.cancelExpiry(root.row.expiry.thread_id || root.row.threadId || root.row.open, null)
        }

        IconButton {
            visible: root.row.kind === "scheduled"
            icon: "close"
            tip: "Cancel this scheduled email"
            size: 28
            onClicked: Inbox.cancelScheduled(root.row.file)
        }
    }
}
