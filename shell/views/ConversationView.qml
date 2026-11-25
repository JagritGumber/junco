import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The open conversation: a person as a chat with a reply box, or a sender's
// updates and the newsletters as an email list. An email opened from it shows
// in MailReader, in this pane's place.
Rectangle {
    id: root

    readonly property var conversation: Inbox.selected
    // Nothing to show yet: still loading, or the load failed.
    readonly property bool waiting: Inbox.messages.length === 0 && (Inbox.threadLoading || Inbox.threadFailed)
    // Updates and newsletters read as an email list; people as a chat.
    readonly property bool lane: conversation !== null && conversation.kind !== "person"
    property bool searching: false

    onConversationChanged: searching = false

    radius: 26
    color: Theme.m3surfaceContainerLow

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        // The header. While emails are picked, the selection's own bar takes
        // its place (Material's contextual top bar), so nothing covers the
        // list; with nothing picked it is exactly the header it always was.
        Item {
            id: header

            readonly property bool selecting: root.lane && laneView.pickedIds.length > 0

            Layout.fillWidth: true
            implicitHeight: normal.implicitHeight

            RowLayout {
                id: normal

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 14
                enabled: !header.selecting
                opacity: header.selecting ? 0 : 1
                visible: opacity > 0

                Behavior on opacity {
                    NumberAnimation {
                        duration: 150
                        easing.type: Easing.OutCubic
                    }
                }

                Avatar {
                    name: root.conversation?.name ?? ""
                    icon: root.conversation?.icon ?? ""
                    logo: root.conversation?.logo ?? ""
                    accentLogo: root.conversation?.logo === "linear"
                    image: root.conversation?.avatar ?? ""
                    size: 50
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: root.conversation?.name ?? ""
                        elide: Text.ElideRight
                        font.pixelSize: 20
                        font.weight: Font.Medium
                    }

                    // Plain positioning, not a layout: the address takes its own
                    // width, shortened only when the tag needs the room.
                    Item {
                        Layout.fillWidth: true
                        implicitHeight: Math.max(address.implicitHeight, tag.implicitHeight)

                        Label {
                            id: address

                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(implicitWidth, parent.width - (tag.visible ? tag.width + 8 : 0))
                            text: root.conversation?.address ?? ""
                            elide: Text.ElideRight
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 13
                        }

                        AccountTag {
                            id: tag

                            anchors.left: address.right
                            anchors.leftMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            visible: account !== ""
                            account: root.conversation?.account ?? ""
                        }
                    }
                }

                IconButton {
                    visible: root.lane
                    icon: "search"
                    tip: "Search this list"
                    filled: root.searching
                    onClicked: {
                        root.searching = !root.searching;
                        if (!root.searching)
                            laneView.query = "";
                    }
                }

                IconButton {
                    visible: root.lane
                    icon: laneView.pickedIds.length > 0 ? "check_box" : "select_check_box"
                    tip: laneView.pickedIds.length > 0 ? "Clear selection" : "Select all"
                    filled: laneView.pickedIds.length > 0
                    onClicked: laneView.pickedIds.length > 0 ? laneView.picked = {} : laneView.pickAll()
                }

                IconButton {
                    visible: root.lane
                    icon: "sort"
                    tip: laneView.oldestFirst ? "Oldest first (click for newest)" : "Newest first (click for oldest)"
                    filled: laneView.oldestFirst
                    onClicked: laneView.oldestFirst = !laneView.oldestFirst
                }

                // Archiving a conversation archives its inbox emails in Gmail; it
                // comes back when someone writes again.
                IconButton {
                    visible: Inbox.isConversation(Inbox.selectedId)
                    icon: "archive"
                    tip: "Archive conversation"
                    onClicked: Inbox.archiveConversation(Inbox.selectedId)
                }
            }

            SelectionBar {
                id: selectionBar

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                height: Math.max(48, parent.height)
                count: laneView.pickedIds.length
                total: laneView.rows.length
                context: root.conversation?.name ?? ""
                actions: [
                    { action: "archive", icon: "archive", label: "Archive", primary: true },
                    { action: "trash", icon: "delete", label: "Delete", primary: true },
                    { action: "read", icon: "drafts", label: "Read", primary: false },
                    { action: "unread", icon: "mark_email_unread", label: "Unread", primary: false },
                    { action: "star", icon: "star", label: "Star", primary: false }
                ]
                opacity: header.selecting ? 1 : 0
                visible: opacity > 0
                onTriggered: action => {
                    if (action === "clear")
                        laneView.picked = {};
                    else if (action === "select-all")
                        laneView.pickAll();
                    else
                        laneView.act(action);
                }

                // In with a short drop from above, out the same way.
                transform: Translate {
                    y: header.selecting ? 0 : -8

                    Behavior on y {
                        NumberAnimation {
                            duration: 150
                            easing.type: Easing.OutCubic
                        }
                    }
                }

                Behavior on opacity {
                    NumberAnimation {
                        duration: 150
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            visible: root.lane && root.searching
            implicitHeight: 44
            radius: 22
            color: Theme.m3surfaceContainerHigh

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                spacing: 10

                Icon {
                    name: "search"
                }

                TextInput {
                    id: laneSearch

                    renderType: Text.NativeRendering

                    Layout.fillWidth: true
                    color: Theme.m3onSurface
                    font.family: Theme.sans
                    font.pixelSize: 14
                    clip: true
                    focus: root.searching
                    text: laneView.query
                    onTextChanged: laneView.query = text

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: laneSearch.text === ""
                        text: `Search ${root.conversation?.name ?? ""}`
                        color: Theme.m3onSurfaceVariant
                    }
                }
            }
        }

        ListView {
            id: messages

            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !root.waiting && !root.lane
            clip: true
            spacing: 12
            boundsBehavior: Flickable.StopAtBounds
            // Only chats build bubbles; a lane's emails belong to LaneView.
            model: root.lane ? [] : Inbox.messages
            onCountChanged: Qt.callLater(positionViewAtEnd)
            onModelChanged: Qt.callLater(positionViewAtEnd)

            delegate: MessageItem {
                required property var modelData
                required property int index

                width: messages.width
                message: modelData
                previous: index > 0 ? messages.model[index - 1] : null
            }
        }

        LaneView {
            id: laneView

            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !root.waiting && root.lane
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.waiting

            Column {
                anchors.centerIn: parent
                spacing: 14

                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Inbox.threadFailed ? "Couldn't load this conversation." : "Loading…"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 14
                }

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: Inbox.threadFailed
                    implicitWidth: retry.implicitWidth + 32
                    implicitHeight: 36
                    radius: 18
                    color: Theme.m3primary

                    Label {
                        id: retry

                        anchors.centerIn: parent
                        text: "Try again"
                        color: Theme.m3onPrimary
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Inbox.open(Inbox.selectedId)
                    }
                }
            }
        }

        Composer {
            Layout.fillWidth: true
            visible: root.conversation?.kind === "person"
            recipient: root.conversation?.name ?? ""
        }
    }
}
