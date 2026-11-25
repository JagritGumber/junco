import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// A lane (updates, newsletters) as an email list: newest first, folded into
// Today, Yesterday and Earlier. Each row has the sender and the mail's first
// line, a star that is your Gmail star, and a checkbox for acting on several.
// What to do with the picked emails is in the header above (SelectionBar in
// ConversationView), never over the list.
Item {
    id: root

    property string query: ""
    property bool oldestFirst: false
    property var folded: ({})
    // Picked emails, id -> true.
    property var picked: ({})
    readonly property var pickedIds: Object.keys(picked)
    // Logos tell senders apart in a mixed list (Newsletters); in one sender's
    // list the header already shows its logo, so rows show what each email is about.
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
    }

    Flickable {
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: column.implicitHeight + 12

        ColumnLayout {
            id: column

            width: parent.width
            spacing: 6

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
                        implicitHeight: 38

                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            x: 6
                            spacing: 8

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: section.isFolded ? "chevron_right" : "expand_more"
                                size: 22
                                color: Theme.m3onSurfaceVariant
                            }

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                text: `${section.modelData.name}  ·  ${section.modelData.items.length}`
                                font.pixelSize: 15
                                font.weight: Font.Medium
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
                        Layout.bottomMargin: 10
                        visible: !section.isFolded
                        implicitHeight: list.implicitHeight
                        radius: 18
                        color: Theme.m3surfaceContainer

                        Column {
                            id: list

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
                                    })[modelData.status] ?? [Theme.m3secondaryContainer, Theme.m3onSecondaryContainer, "Update"]

                                    width: list.width
                                    height: 66

                                    // The open email and picked rows get the mock's outlined tint.
                                    Rectangle {
                                        id: wash

                                        anchors.fill: parent
                                        anchors.margins: 2
                                        radius: 16
                                        color: row.current || row.isPicked ? Theme.alpha(Theme.m3primary, 0.12) : (open.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.05) : "transparent")
                                        border.width: row.current ? 1.5 : 0
                                        border.color: Theme.alpha(Theme.m3primary, 0.7)
                                    }

                                    Rectangle {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.bottom: parent.bottom
                                        anchors.leftMargin: 70
                                        height: 1
                                        visible: row.index < section.modelData.items.length - 1
                                        color: Theme.alpha(Theme.m3outlineVariant, 0.6)
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
                                        anchors.leftMargin: 16
                                        anchors.rightMargin: 16
                                        spacing: 14

                                        // The sender's logo when one is known; otherwise an
                                        // icon for what the email is about.
                                        Item {
                                            implicitWidth: 40
                                            implicitHeight: 40

                                            Avatar {
                                                anchors.fill: parent
                                                visible: root.mixedSenders && (row.modelData.avatar ?? "") !== ""
                                                name: row.modelData.sender
                                                image: row.modelData.avatar ?? ""
                                                size: 40
                                            }

                                            // A round tonal tile per kind of email, in the
                                            // wallpaper's palette: money, security, things
                                            // on the way or on a date, and alerts.
                                            Rectangle {
                                                readonly property var tone: ({
                                                    receipt_long: [Theme.m3tertiaryContainer, Theme.m3onTertiaryContainer],
                                                    sell: [Theme.m3tertiaryContainer, Theme.m3onTertiaryContainer],
                                                    pin: [Theme.m3primaryContainer, Theme.m3onPrimaryContainer],
                                                    shield_lock: [Theme.m3primaryContainer, Theme.m3onPrimaryContainer],
                                                    local_shipping: [Theme.m3secondaryContainer, Theme.m3onSecondaryContainer],
                                                    autorenew: [Theme.m3secondaryContainer, Theme.m3onSecondaryContainer],
                                                    event: [Theme.m3secondaryContainer, Theme.m3onSecondaryContainer],
                                                    work: [Theme.m3secondaryContainer, Theme.m3onSecondaryContainer],
                                                    notification_important: [Theme.m3errorContainer, Theme.m3onErrorContainer],
                                                    error: [Theme.m3errorContainer, Theme.m3onErrorContainer]
                                                })[row.modelData.icon] ?? [Theme.m3surfaceContainerHighest, Theme.m3onSurfaceVariant]

                                                anchors.fill: parent
                                                visible: !root.mixedSenders || (row.modelData.avatar ?? "") === ""
                                                radius: width / 2
                                                color: tone[0]

                                                Icon {
                                                    anchors.centerIn: parent
                                                    name: row.modelData.icon
                                                    size: 24
                                                    color: parent.tone[1]
                                                }
                                            }

                                            // Which of your accounts it came to.
                                            AccountBadge {
                                                x: parent.width - width + 4
                                                y: parent.height - height + 4
                                                account: row.modelData.account ?? ""
                                                ringWidth: 2
                                                ring: Qt.tint(Theme.m3surfaceContainer, wash.color)
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3

                                            Label {
                                                Layout.fillWidth: true
                                                text: row.modelData.title
                                                elide: Text.ElideRight
                                                font.pixelSize: 15
                                                font.weight: row.modelData.unread ? Font.DemiBold : Font.Medium
                                            }

                                            Label {
                                                Layout.fillWidth: true
                                                text: [row.modelData.sender, row.modelData.snippet].filter(part => part).join("  •  ")
                                                elide: Text.ElideRight
                                                color: Theme.m3onSurfaceVariant
                                                font.pixelSize: 13
                                            }
                                        }

                                        // What the email is: a review, a merge, a failure, an update.
                                        Rectangle {
                                            implicitHeight: 26
                                            implicitWidth: status.implicitWidth + 20
                                            radius: 13
                                            color: row.tone[0]

                                            Label {
                                                id: status

                                                anchors.centerIn: parent
                                                text: row.tone[2]
                                                color: row.tone[1]
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                            }
                                        }

                                        Label {
                                            Layout.preferredWidth: 64
                                            horizontalAlignment: Text.AlignRight
                                            text: row.modelData.time
                                            color: row.modelData.unread ? Theme.m3primary : Theme.m3onSurfaceVariant
                                            font.pixelSize: 13
                                            font.weight: row.modelData.unread ? Font.DemiBold : Font.Normal
                                        }

                                        IconButton {
                                            icon: "star"
                                            filled: false
                                            iconColor: row.modelData.starred ? Theme.m3tertiary : Theme.m3onSurfaceVariant
                                            iconFill: row.modelData.starred ? 1 : 0
                                            tip: row.modelData.starred ? "Unstar (also in Gmail)" : "Star (also in Gmail)"
                                            size: 34
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
