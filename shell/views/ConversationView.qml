import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The open conversation: compact frosted-glass header, denser chat bubbles or
// lane list, and slim reply composer.
GlassPane {
    id: root

    readonly property var conversation: Inbox.selected
    readonly property bool waiting: Inbox.messages.length === 0 && (Inbox.threadLoading || Inbox.threadFailed)
    readonly property bool lane: conversation !== null && conversation.kind !== "person"
    property bool searching: false

    onConversationChanged: searching = false

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: root.width >= 600 ? 26 : 18
        anchors.rightMargin: root.width >= 600 ? 26 : 18
        anchors.topMargin: 20
        anchors.bottomMargin: 20
        spacing: 14

        // Calm header (swaps smoothly to SelectionBar when picking rows).
        Item {
            id: header

            readonly property var activeLaneView: laneViewLoader.item
            readonly property bool selecting: root.lane && (activeLaneView?.pickedIds?.length ?? 0) > 0

            Layout.fillWidth: true
            implicitHeight: Math.max(50, normal.implicitHeight)

            RowLayout {
                id: normal

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 16
                enabled: !header.selecting
                opacity: header.selecting ? 0 : 1
                visible: opacity > 0

                Behavior on opacity {
                    NumberAnimation {
                        duration: Theme.animFast
                        easing.type: Easing.OutCubic
                    }
                }

                Avatar {
                    name: root.conversation?.name ?? ""
                    icon: root.conversation?.icon ?? ""
                    logo: root.conversation?.logo ?? ""
                    accentLogo: root.conversation?.logo === "linear"
                    image: root.conversation?.avatar ?? ""
                    size: 44
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3

                    Label {
                        Layout.fillWidth: true
                        text: root.conversation?.name ?? ""
                        elide: Text.ElideRight
                        font.pixelSize: 18
                        weight: Font.DemiBold
                    }

                    Item {
                        Layout.fillWidth: true
                        implicitHeight: Math.max(address.implicitHeight, tag.implicitHeight)

                        Label {
                            id: address

                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(implicitWidth, parent.width - (tag.visible ? tag.width + 6 : 0))
                            text: root.conversation?.address ?? ""
                            elide: Text.ElideRight
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                        }

                        AccountTag {
                            id: tag

                            anchors.left: address.right
                            anchors.leftMargin: 6
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
                    size: 30
                    filled: root.searching
                    onClicked: {
                        root.searching = !root.searching;
                        if (!root.searching && header.activeLaneView)
                            header.activeLaneView.query = "";
                    }
                }

                IconButton {
                    visible: root.lane
                    icon: (header.activeLaneView?.pickedIds?.length ?? 0) > 0 ? "check_box" : "select_check_box"
                    tip: (header.activeLaneView?.pickedIds?.length ?? 0) > 0 ? "Clear selection" : "Select all"
                    size: 30
                    filled: (header.activeLaneView?.pickedIds?.length ?? 0) > 0
                    onClicked: {
                        if (!header.activeLaneView)
                            return;
                        if (header.activeLaneView.pickedIds.length > 0)
                            header.activeLaneView.picked = {};
                        else
                            header.activeLaneView.pickAll();
                    }
                }

                IconButton {
                    visible: root.lane
                    icon: "sort"
                    tip: (header.activeLaneView?.oldestFirst ?? false) ? "Oldest first (click for newest)" : "Newest first (click for oldest)"
                    size: 30
                    filled: header.activeLaneView?.oldestFirst ?? false
                    onClicked: if (header.activeLaneView)
                        header.activeLaneView.oldestFirst = !header.activeLaneView.oldestFirst
                }

                IconButton {
                    visible: Inbox.isConversation(Inbox.selectedId)
                    icon: "archive"
                    tip: "Archive conversation"
                    size: 30
                    onClicked: Inbox.archiveConversation(Inbox.selectedId)
                }
            }

            SelectionBar {
                id: selectionBar

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                height: Math.max(38, parent.height)
                count: header.activeLaneView?.pickedIds?.length ?? 0
                total: header.activeLaneView?.rows?.length ?? 0
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
                    if (!header.activeLaneView)
                        return;
                    if (action === "clear")
                        header.activeLaneView.picked = {};
                    else if (action === "select-all")
                        header.activeLaneView.pickAll();
                    else
                        header.activeLaneView.act(action);
                }

                transform: Translate {
                    y: header.selecting ? 0 : -6

                    Behavior on y {
                        NumberAnimation {
                            duration: 130
                            easing.type: Easing.OutCubic
                        }
                    }
                }

                Behavior on opacity {
                    NumberAnimation {
                        duration: 130
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }

        // Crisp 1 px glass separator below header.
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: Theme.glassDivider
        }

        Rectangle {
            Layout.fillWidth: true
            visible: root.lane && root.searching
            implicitHeight: 38
            radius: Theme.controlRadius
            color: laneSearch.activeFocus ? Theme.glassControlHover : Theme.glassControl
            border.width: Theme.glass ? 0 : 1
            border.color: laneSearch.activeFocus ? Theme.alpha(Theme.m3primary, 0.72) : Theme.glassBorderSubtle

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 8

                Icon {
                    name: "search"
                    size: 16
                }

                TextInput {
                    id: laneSearch

                    renderType: Text.NativeRendering
                    Layout.fillWidth: true
                    color: Theme.m3onSurface
                    font.family: Theme.sans
                    font.pixelSize: 13
                    clip: true
                    focus: root.searching
                    text: header.activeLaneView?.query ?? ""
                    onTextChanged: if (header.activeLaneView)
                        header.activeLaneView.query = text

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: laneSearch.text === ""
                        text: `Search ${root.conversation?.name ?? ""}`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
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
            cacheBuffer: 400
            spacing: 14
            topMargin: 12
            bottomMargin: 14
            boundsBehavior: Flickable.StopAtBounds
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

        Loader {
            id: laneViewLoader

            Layout.fillWidth: true
            Layout.fillHeight: true
            active: root.lane
            visible: !root.waiting && root.lane
            source: "LaneView.qml"
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.waiting

            Column {
                anchors.centerIn: parent
                spacing: 10

                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Inbox.threadFailed ? "Couldn't load this conversation." : "Loading…"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }

                Pill {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: Inbox.threadFailed
                    style: "filled"
                    text: "Try again"
                    size: 32
                    onClicked: Inbox.open(Inbox.selectedId)
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
