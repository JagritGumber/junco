import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// A lane (updates, newsletters) as a compact frosted-glass email list.
Item {
    id: root

    property string query: ""
    property bool oldestFirst: false
    property var folded: ({})
    property var picked: ({})
    readonly property var pickedIds: Object.keys(picked)
    readonly property bool mixedSenders: new Set(Inbox.messages.map(m => m.avatar || m.sender)).size > 1

    readonly property var rows: {
        Inbox.revision;
        const needle = query.trim().toLowerCase();
        const list = Inbox.messages.filter(m => !Inbox.hidden[m.id] && (needle === "" || `${m.title} ${m.sender} ${m.snippet}`.toLowerCase().includes(needle)));
        return oldestFirst ? list : list.slice().reverse();
    }
    readonly property var sections: {
        const order = oldestFirst ? ["Earlier", "Yesterday", "Today"] : ["Today", "Yesterday", "Earlier"];
        return order.map(name => ({ name: name, items: rows.filter(m => m.bucket === name) })).filter(section => section.items.length > 0);
    }

    function toggle(id: string): void {
        const next = Object.assign({}, picked);
        if (next[id])
            delete next[id];
        else
            next[id] = true;
        picked = next;
    }

    function pickAll(): void {
        const next = {};
        for (const message of rows)
            next[message.id] = true;
        picked = next;
    }

    function act(action: string): void {
        if (["archive", "inbox", "trash", "spam"].includes(action))
            Inbox.act(action, pickedIds);
        else
            Inbox.mark(action, pickedIds);
        picked = {};
    }

    Connections {
        target: Inbox

        function onSelectedIdChanged(): void {
            root.picked = {};
            root.query = "";
        }
    }

    Label {
        anchors.centerIn: parent
        visible: root.sections.length === 0 && root.query !== ""
        text: "No emails match."
        color: Theme.m3onSurfaceVariant
        font.pixelSize: 13
    }

    Flickable {
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: column.implicitHeight + 8

        ColumnLayout {
            id: column

            width: parent.width
            spacing: 8

            Repeater {
                model: root.sections

                delegate: ColumnLayout {
                    id: section

                    required property var modelData
                    readonly property bool isFolded: root.folded[modelData.name] === true

                    Layout.fillWidth: true
                    spacing: 8

                    Item {
                        Layout.fillWidth: true
                        implicitHeight: 32

                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            x: 6
                            spacing: 8

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: section.isFolded ? "chevron_right" : "expand_more"
                                size: 18
                                color: Theme.m3onSurfaceVariant
                            }

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                text: `${section.modelData.name}  ·  ${section.modelData.items.length}`
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 12
                                weight: Font.Medium
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                const next = Object.assign({}, root.folded);
                                next[section.modelData.name] = !section.isFolded;
                                root.folded = next;
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.bottomMargin: 8
                        visible: !section.isFolded
                        implicitHeight: list.implicitHeight + 8
                        radius: Theme.cardRadius
                        color: Theme.glassCard
                        border.width: Theme.glass ? 0 : 1
                        border.color: Theme.glassBorderSubtle

                        Column {
                            id: list

                            x: 0
                            y: 4
                            width: parent.width

                            Repeater {
                                model: section.modelData.items

                                delegate: Item {
                                    id: row

                                    required property var modelData
                                    required property int index
                                    readonly property bool current: Inbox.lastOpenedId === modelData.id
                                    readonly property bool isPicked: root.picked[modelData.id] === true
                                    readonly property var tone: ({
                                        review: [Theme.m3tertiaryContainer, Theme.m3onTertiaryContainer, "Review"],
                                        merged: [Theme.m3primaryContainer, Theme.m3onPrimaryContainer, "Merged"],
                                        failed: [Theme.m3errorContainer, Theme.m3onErrorContainer, "Failed"]
                                    })[modelData.status] ?? [Theme.glassControl, Theme.m3onSurfaceVariant, "Update"]

                                    width: list.width
                                    height: 64

                                    Rectangle {
                                        id: wash

                                        anchors.fill: parent
                                        anchors.leftMargin: 6
                                        anchors.rightMargin: 6
                                        anchors.topMargin: 2
                                        anchors.bottomMargin: 2
                                        radius: 12
                                        color: row.current || row.isPicked ? Theme.glassSelectedRow : (open.containsMouse ? Theme.glassHover : "transparent")
                                        border.width: !Theme.glass && row.current ? 1 : 0
                                        border.color: Theme.glassActiveBorder
                                    }

                                    Rectangle {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.bottom: parent.bottom
                                        anchors.leftMargin: 66
                                        anchors.rightMargin: 16
                                        height: 1
                                        visible: !row.current && !open.containsMouse && row.index < section.modelData.items.length - 1
                                        color: Theme.glassDivider
                                        opacity: 0.75
                                    }

                                    MouseArea {
                                        id: open

                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: Inbox.openMessage(row.modelData.id, true)
                                    }

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 14
                                        anchors.rightMargin: 14
                                        spacing: 14

                                        Item {
                                            implicitWidth: 38
                                            implicitHeight: 38

                                            Avatar {
                                                anchors.fill: parent
                                                visible: root.mixedSenders && (row.modelData.avatar ?? "") !== ""
                                                name: row.modelData.sender
                                                image: row.modelData.avatar ?? ""
                                                size: 38
                                            }

                                            Rectangle {
                                                readonly property var tone: ({
                                                    receipt_long: [Theme.m3tertiaryContainer, Theme.m3onTertiaryContainer],
                                                    sell: [Theme.m3tertiaryContainer, Theme.m3onTertiaryContainer],
                                                    pin: [Theme.m3primaryContainer, Theme.m3onPrimaryContainer],
                                                    shield_lock: [Theme.m3primaryContainer, Theme.m3onPrimaryContainer],
                                                    local_shipping: [Theme.glassActive, Theme.m3onSurface],
                                                    autorenew: [Theme.glassActive, Theme.m3onSurface],
                                                    event: [Theme.glassActive, Theme.m3onSurface],
                                                    work: [Theme.glassActive, Theme.m3onSurface],
                                                    notification_important: [Theme.m3errorContainer, Theme.m3onErrorContainer],
                                                    error: [Theme.m3errorContainer, Theme.m3onErrorContainer]
                                                })[row.modelData.icon] ?? [Theme.glassControl, Theme.m3onSurfaceVariant]

                                                anchors.fill: parent
                                                visible: !root.mixedSenders || (row.modelData.avatar ?? "") === ""
                                                radius: width / 2
                                                color: tone[0]

                                                Icon {
                                                    anchors.centerIn: parent
                                                    name: row.modelData.icon
                                                    size: 18
                                                    color: parent.tone[1]
                                                }
                                            }

                                            AccountBadge {
                                                x: parent.width - width + 3
                                                y: parent.height - height + 3
                                                account: row.modelData.account ?? ""
                                                size: 14
                                                ringWidth: 2
                                                ring: Theme.solidSurfaceContainer
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 1

                                            Label {
                                                Layout.fillWidth: true
                                                text: row.modelData.title
                                                elide: Text.ElideRight
                                                font.pixelSize: 13
                                                weight: row.modelData.unread ? Font.Medium : Font.Normal
                                            }

                                            Label {
                                                Layout.fillWidth: true
                                                text: [row.modelData.sender, row.modelData.snippet].filter(part => part).join("  •  ")
                                                elide: Text.ElideRight
                                                color: Theme.m3onSurfaceVariant
                                                font.pixelSize: 12
                                            }
                                        }

                                        ExpiryBadge {
                                            visible: (row.modelData.expiry ?? null) !== null
                                            expiry: row.modelData.expiry ?? null
                                            compact: true
                                        }

                                        // What the email is: a review, a merge, a failure, an update.
                                        Rectangle {
                                            implicitHeight: 20
                                            implicitWidth: status.implicitWidth + 14
                                            radius: 10
                                            color: row.tone[0]

                                            Label {
                                                id: status

                                                anchors.centerIn: parent
                                                text: row.tone[2]
                                                color: row.tone[1]
                                                font.pixelSize: 10
                                                weight: Font.Medium
                                            }
                                        }

                                        Label {
                                            Layout.preferredWidth: 54
                                            horizontalAlignment: Text.AlignRight
                                            text: row.modelData.time
                                            color: row.modelData.unread ? Theme.m3primary : Theme.m3onSurfaceVariant
                                            font.pixelSize: 11
                                            weight: row.modelData.unread ? Font.Medium : Font.Normal
                                        }

                                        IconButton {
                                            icon: "star"
                                            filled: false
                                            iconColor: row.modelData.starred ? Theme.m3tertiary : Theme.m3onSurfaceVariant
                                            iconFill: row.modelData.starred ? 1 : 0
                                            tip: row.modelData.starred ? "Unstar (also in Gmail)" : "Star (also in Gmail)"
                                            size: 28
                                            onClicked: Inbox.mark(row.modelData.starred ? "unstar" : "star", [row.modelData.id])
                                        }

                                        CheckBox {
                                            tip: row.isPicked ? "Unselect" : "Select"
                                            checked: row.isPicked
                                            onToggled: root.toggle(row.modelData.id)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
