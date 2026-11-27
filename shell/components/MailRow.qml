import QtQuick
import QtQuick.Layouts
import qs.services

// One calm, spacious row in a folder's mail list (harmonized with ConversationRow):
// concentric inset rounded card (15 px radius), 44 px circular avatar, generous
// 16 px avatar-to-text gap, clean typographic hierarchy, and 2-anchor right column.
Item {
    id: root

    required property var row
    property bool showDivider: false

    readonly property bool selected: Inbox.selectedRow === row.id
    readonly property bool unread: (row.unread ?? 0) > 0
    readonly property bool starred: Boolean(row.starred)
    readonly property bool folded: row.kind === "group" && row.count > 1
    readonly property bool open: Inbox.expanded[row.id] === true
    readonly property bool isSpecialAction: row.kind === "trash" || row.kind === "scheduled" || (Inbox.folder === "expiring" && (row.expiry ?? null) !== null)
    readonly property int innerPadX: width >= 310 ? 16 : 12
    readonly property int avatarSize: width >= 310 ? 44 : 40
    readonly property int avatarGap: width >= 310 ? 16 : 12
    readonly property int rightBuffer: width >= 310 ? 14 : 10
    readonly property var tile: ({
            meeting: [Theme.m3primaryContainer, Theme.m3onPrimaryContainer],
            dev: [Theme.m3tertiaryContainer, Theme.m3onTertiaryContainer],
            college: [Theme.glassActive, Theme.m3onSurface],
            trash: [Theme.glassControl, Theme.m3onSurfaceVariant],
            scheduled: [Theme.glassActive, Theme.m3onSurface]
        })[row.category] ?? [Theme.glassControl, Theme.m3onSurfaceVariant]

    signal clicked

    implicitHeight: Math.max(88, content.implicitHeight + 32)

    Rectangle {
        id: wash

        anchors.fill: parent
        radius: Theme.rowRadius
        color: root.selected ? Theme.glassSelectedRow : (area.containsMouse ? Theme.glassHover : "transparent")
        border.width: !Theme.glass && root.selected ? 1 : 0
        border.color: Theme.glassActiveBorder

        Behavior on color {
            ColorAnimation {
                duration: Theme.animFast
                easing.type: Easing.OutCubic
            }
        }

        GlassEdge {
            visible: Theme.glass && root.selected
            radius: wash.radius
            fade: 10
            side: false
            light: Theme.alpha(Theme.pureWhite, Theme.dark ? 0.22 : 0.34)
        }
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
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.innerPadX
        anchors.rightMargin: root.innerPadX
        anchors.topMargin: 15
        anchors.bottomMargin: 15
        spacing: 0
        z: 1

        Item {
            Layout.alignment: Qt.AlignVCenter
            implicitWidth: root.avatarSize
            implicitHeight: root.avatarSize

            Avatar {
                anchors.fill: parent
                visible: (root.row.avatar ?? "") !== "" || (root.row.icon ?? "") === ""
                name: root.row.title
                image: root.row.avatar ?? ""
                size: root.avatarSize
            }

            Rectangle {
                anchors.fill: parent
                visible: (root.row.avatar ?? "") === "" && (root.row.icon ?? "") !== ""
                radius: root.avatarSize / 2
                color: root.tile[0]

                Icon {
                    anchors.centerIn: parent
                    name: root.row.icon ?? ""
                    size: Math.round(root.avatarSize * 0.46)
                    color: root.tile[1]
                }
            }
        }

        Item {
            Layout.preferredWidth: root.avatarGap
            Layout.fillHeight: true
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 0

            Label {
                Layout.fillWidth: true
                text: root.row.title
                elide: Text.ElideRight
                color: Theme.m3onSurface
                font.pixelSize: 15
                weight: Font.DemiBold
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 6

                Icon {
                    visible: root.row.attachment ?? false
                    name: "attach_file"
                    size: 14
                    color: Theme.m3onSurfaceVariant
                }

                Label {
                    Layout.fillWidth: true
                    text: root.row.subtitle
                    elide: Text.ElideRight
                    color: root.unread ? Theme.m3onSurface : Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                    weight: root.unread ? Font.Medium : Font.Normal
                }

                Rectangle {
                    visible: root.folded
                    implicitWidth: foldRow.implicitWidth + 12
                    implicitHeight: 20
                    radius: 10
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
                Layout.topMargin: 5
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

        Item {
            Layout.preferredWidth: root.rightBuffer
            Layout.fillHeight: true
        }

        // Standard 2-anchor right column (timestamp + unread dot top-right, star bottom-right).
        ColumnLayout {
            visible: !root.isSpecialAction
            Layout.fillHeight: true
            spacing: 0

            Row {
                Layout.alignment: Qt.AlignRight | Qt.AlignTop
                Layout.topMargin: 1
                spacing: 8

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    tabular: true
                    text: root.row.time
                    color: Theme.m3onSurfaceVariant
                    opacity: root.unread ? 0.95 : 0.82
                    font.pixelSize: 12
                    weight: root.unread ? Font.Medium : Font.Normal
                }

                Rectangle {
                    visible: root.unread
                    anchors.verticalCenter: parent.verticalCenter
                    width: 8
                    height: 8
                    radius: 4
                    color: Theme.complementDot
                }
            }

            Item {
                Layout.fillHeight: true
            }

            IconButton {
                Layout.alignment: Qt.AlignRight | Qt.AlignBottom
                Layout.bottomMargin: -4
                Layout.rightMargin: -4
                icon: "star"
                filled: false
                iconFill: root.starred ? 1 : 0
                iconColor: root.starred ? Theme.m3tertiary : Theme.alpha(Theme.m3onSurfaceVariant, 0.72)
                tip: root.starred ? "Unstar" : "Star"
                size: 28
                iconSize: 18
                onClicked: {
                    const targetId = root.row.open || (root.row.ids && root.row.ids.length > 0 ? root.row.ids[0] : "");
                    if (targetId !== "")
                        Inbox.mark(root.starred ? "unstar" : "star", [targetId]);
                }
            }
        }

        Row {
            visible: root.isSpecialAction
            Layout.alignment: Qt.AlignVCenter
            spacing: 6

            Pill {
                visible: root.row.kind === "trash"
                text: "Restore"
                icon: "restore_from_trash"
                size: 30
                fontSize: 11
                onClicked: Inbox.act("untrash", [root.row.open])
            }

            Pill {
                visible: root.row.kind === "scheduled"
                text: "Send now"
                icon: "send"
                size: 30
                fontSize: 11
                onClicked: Inbox.sendScheduledNow(root.row.file)
            }

            IconButton {
                visible: Inbox.folder === "expiring" && (root.row.expiry ?? null) !== null
                icon: "close"
                tip: "Cancel scheduled deletion"
                size: 30
                onClicked: Inbox.cancelExpiry(root.row.expiry.thread_id || root.row.threadId || root.row.open, null)
            }

            IconButton {
                visible: root.row.kind === "scheduled"
                icon: "close"
                tip: "Cancel this scheduled email"
                size: 30
                onClicked: Inbox.cancelScheduled(root.row.file)
            }
        }
    }

    // Whisper-faint inset divider aligned with text column, hidden above/below selected row.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: root.innerPadX + root.avatarSize + root.avatarGap
        anchors.rightMargin: root.innerPadX
        y: parent.height + 1.5
        height: 1
        visible: root.showDivider && !root.selected && !area.containsMouse
        color: Theme.glassDivider
        opacity: 0.55
    }
}
