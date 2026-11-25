import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// An account's card, shown after a moment's hover on its circle in the account
// bar, or at once on a click of the big one: its picture, name and address,
// its storage as a bar, and what you can do with it (change its picture,
// show only its mail). The "All" circle's card lists the accounts and adds
// one. It sits over the window above the circle; moving onto it keeps it
// open, leaving both closes it. Right-click on a circle still opens the menu.
//
// Hover inside uses HoverHandlers, never hover-enabled MouseAreas: those
// would take the hover from the card's own HoverHandler, and the card would
// close under the pointer.
Item {
    id: root

    property string account: ""
    // The circle it belongs to, in this item's coordinates.
    property real anchorX: 0
    property real anchorTop: 0
    property real anchorBottom: 0
    // The circle under the pointer, if any.
    property Item hovered: null
    property Item pending: null
    property string pendingAccount: ""

    readonly property var info: Inbox.accounts.find(a => a.id === account) ?? null
    readonly property var quota: account ? Inbox.storageOf(account) : null
    readonly property real used: quota && quota.limit > 0 ? Math.min(1, quota.used / quota.limit) : 0
    // The account the window shows (as the account bar works it out).
    readonly property string current: Inbox.account !== "" ? Inbox.account : Inbox.accounts.length === 1 ? Inbox.accounts[0].id : ""
    readonly property var actions: {
        if (account === "") {
            const all = Inbox.account !== "" ? [{ icon: "all_inbox", label: "Show every account's mail", run: () => Inbox.setAccount("") }] : [];
            return [...all, { icon: "person_add", label: "Add account…", run: () => Inbox.addingAccount = true }];
        }
        const show = account !== current ? [{ icon: "inbox", label: "Show only its mail", run: () => Inbox.setAccount(root.account) }] : [];
        return [...Inbox.pictureActions(account), ...show];
    }

    // A circle says the pointer came or went. Moving straight from one
    // circle to the next can bring the new one's enter before the old one's
    // leave; that late leave is ignored.
    function hover(item: Item, id: string, inside: bool): void {
        if (inside) {
            hovered = item;
            closing.stop();
            // Already open: follow along the bar at once.
            if (visible) {
                place(item, id);
                return;
            }
            pending = item;
            pendingAccount = id;
            opening.restart();
            return;
        }
        if (hovered !== item)
            return;
        hovered = null;
        if (pending === item)
            opening.stop();
        if (visible)
            closing.restart();
    }

    // At once, for a click.
    function showNow(item: Item, id: string): void {
        opening.stop();
        closing.stop();
        place(item, id);
    }

    function place(item: Item, id: string): void {
        const at = item.mapToItem(root, 0, 0);
        account = id;
        anchorX = at.x;
        anchorTop = at.y;
        anchorBottom = at.y + item.height;
        visible = true;
    }

    function close(): void {
        opening.stop();
        closing.stop();
        pending = null;
        visible = false;
    }

    function run(action: var): void {
        close();
        action.run();
    }

    visible: false
    z: 140

    // A short wait each way, so passing over the bar doesn't flicker.
    Timer {
        id: opening

        interval: 450
        onTriggered: if (root.pending)
            root.place(root.pending, root.pendingAccount)
    }

    Timer {
        id: closing

        interval: 250
        onTriggered: if (!root.hovered && !cardHover.hovered)
            root.close()
    }

    Rectangle {
        id: card

        width: 312
        height: content.implicitHeight + 24
        // Above the circle, its left edge near the circle's; below it only
        // when there's no room above.
        x: Math.max(8, Math.min(root.anchorX - 6, root.width - width - 8))
        y: root.anchorTop - height - 10 >= 8 ? root.anchorTop - height - 10 : Math.min(root.anchorBottom + 10, root.height - height - 8)
        radius: 20
        color: Theme.m3popupHigh
        border.width: 1
        border.color: Theme.alpha(Theme.m3outlineVariant, 0.6)

        HoverHandler {
            id: cardHover

            onHoveredChanged: hovered ? closing.stop() : closing.restart()
        }

        // Clicks on the card's padding stay on the card.
        MouseArea {
            anchors.fill: parent
        }

        ColumnLayout {
            id: content

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 12
            spacing: 0

            // One account: picture (click it to change), name, address.
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 6
                visible: root.account !== ""
                spacing: 14

                Item {
                    implicitWidth: 56
                    implicitHeight: 56

                    AccountBadge {
                        anchors.centerIn: parent
                        visible: true
                        account: root.account
                        size: 56
                        tip: ""
                    }

                    // Says the picture can be changed; a click on it does.
                    Rectangle {
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.rightMargin: -3
                        anchors.bottomMargin: -3
                        width: 26
                        height: 26
                        radius: 13
                        color: faceHover.hovered ? Qt.tint(Theme.m3primaryContainer, Theme.alpha(Theme.m3onPrimaryContainer, 0.12)) : Theme.m3primaryContainer
                        border.width: 2
                        border.color: Theme.m3popupHigh

                        Icon {
                            anchors.centerIn: parent
                            name: "photo_camera"
                            size: 15
                            color: Theme.m3onPrimaryContainer
                        }
                    }

                    HoverHandler {
                        id: faceHover

                        cursorShape: Qt.PointingHandCursor
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.run(root.actions[0])
                    }

                    Loader {
                        active: faceHover.hovered
                        sourceComponent: Tooltip {
                            parent: faceHover.parent
                            text: "Change picture"
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Label {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 0
                        text: root.info?.label ?? root.account
                        elide: Text.ElideRight
                        font.pixelSize: 16
                        font.weight: Font.Medium
                    }

                    Label {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 0
                        text: root.info?.email ?? ""
                        elide: Text.ElideRight
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                    }
                }
            }

            // Its storage, as a bar. The exact numbers are in its tooltip too.
            ColumnLayout {
                id: storage

                Layout.fillWidth: true
                Layout.leftMargin: 6
                Layout.rightMargin: 6
                Layout.topMargin: 10
                Layout.bottomMargin: 4
                visible: root.account !== "" && root.quota !== null
                spacing: 7

                RowLayout {
                    Layout.fillWidth: true

                    Icon {
                        name: "cloud"
                        size: 16
                        color: Theme.m3onSurfaceVariant
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "Storage"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                        font.weight: Font.Medium
                    }

                    Label {
                        text: root.quota ? `${Inbox.formatBytes(root.quota.used)} of ${Inbox.formatBytes(root.quota.limit)}` : ""
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }
                }

                // Material's linear progress: a track, the used part, a stop.
                Item {
                    Layout.fillWidth: true
                    implicitHeight: 6

                    Rectangle {
                        anchors.fill: parent
                        radius: 3
                        color: Theme.alpha(Theme.m3onSurface, 0.12)
                    }

                    Rectangle {
                        width: Math.max(height, parent.width * root.used)
                        height: parent.height
                        radius: 3
                        color: root.used >= 0.9 ? Theme.m3error : Theme.m3primary
                    }
                }

                HoverHandler {
                    id: storageHover
                }

                Loader {
                    active: storageHover.hovered && root.quota !== null
                    sourceComponent: Tooltip {
                        parent: storage
                        text: `${Inbox.formatBytes(root.quota.used)} of ${Inbox.formatBytes(root.quota.limit)} used (${Math.round(root.used * 100)}%)`
                    }
                }
            }

            // All: the accounts (a click shows only that one's mail).
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.account === ""
                spacing: 0

                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 6
                    Layout.topMargin: 4
                    text: "All accounts"
                    font.pixelSize: 16
                    font.weight: Font.Medium
                }

                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 6
                    Layout.bottomMargin: 8
                    text: "Every account's mail together"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }

                Repeater {
                    model: root.account === "" ? Inbox.accounts : []

                    delegate: Rectangle {
                        id: row

                        required property var modelData

                        Layout.fillWidth: true
                        implicitHeight: 52
                        radius: 12
                        color: rowHover.hovered ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            anchors.rightMargin: 10
                            spacing: 12

                            AccountBadge {
                                visible: true
                                account: row.modelData.id
                                size: 34
                                tip: ""
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                Label {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 0
                                    text: row.modelData.label
                                    elide: Text.ElideRight
                                    font.weight: Font.Medium
                                }

                                Label {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 0
                                    text: row.modelData.email
                                    elide: Text.ElideRight
                                    color: Theme.m3onSurfaceVariant
                                    font.pixelSize: 12
                                }
                            }
                        }

                        HoverHandler {
                            id: rowHover

                            cursorShape: Qt.PointingHandCursor
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: root.run({ run: () => Inbox.setAccount(row.modelData.id) })
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 10
                Layout.bottomMargin: 6
                implicitHeight: 1
                color: Theme.m3outlineVariant
            }

            // What you can do, as menu rows.
            Repeater {
                model: root.actions

                delegate: Rectangle {
                    id: action

                    required property var modelData

                    Layout.fillWidth: true
                    implicitHeight: 42
                    radius: 12
                    color: actionHover.hovered ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 12

                        Icon {
                            name: action.modelData.icon
                            size: 20
                            color: Theme.m3onSurfaceVariant
                        }

                        Label {
                            Layout.fillWidth: true
                            text: action.modelData.label
                            elide: Text.ElideRight
                        }
                    }

                    HoverHandler {
                        id: actionHover

                        cursorShape: Qt.PointingHandCursor
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.run(action.modelData)
                    }
                }
            }
        }
    }
}
