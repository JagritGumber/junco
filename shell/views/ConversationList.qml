import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The inbox as conversations, Beeper-style: each person is a chat, newest
// first; a sender's updates and the day's newsletters are lists of their own.
// Every account's mail is here together, each row with its account's dot.
Rectangle {
    id: root

    radius: 26
    color: Theme.m3surfaceContainerLow

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 6
            spacing: 6

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Label {
                    Layout.fillWidth: true
                    text: "Inbox"
                    font.pixelSize: 24
                    font.weight: Font.Medium
                }

                Label {
                    Layout.fillWidth: true
                    text: Inbox.lane === "newsletters" ? "Newsletters" : "People first, then updates"
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }
            }

            // Lanes too quiet for a chip live here.
            IconButton {
                id: filterButton

                icon: "tune"
                tip: "Filter"
                size: 44
                filled: Inbox.lane === "newsletters"
                fillColor: Theme.m3secondaryContainer
                iconColor: Inbox.lane === "newsletters" ? Theme.m3onSecondaryContainer : Theme.m3onSurfaceVariant
                onClicked: menu.show(filterButton, [
                    { icon: "newspaper", label: "Newsletters", checked: Inbox.lane === "newsletters", run: () => Inbox.lane = Inbox.lane === "newsletters" ? "all" : "newsletters" },
                    { separator: true },
                    { icon: "refresh", label: "Refresh", run: () => Inbox.refresh() }
                ])
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 44
            radius: 22
            color: Theme.m3surfaceContainerHigh

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 6
                spacing: 8

                Icon {
                    name: "search"
                    size: 20
                }

                TextInput {
                    id: search

                    Layout.fillWidth: true
                    renderType: Text.NativeRendering
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 14
                    clip: true
                    onTextChanged: Inbox.query = text
                    // Typing narrows the list; Enter searches every email.
                    onAccepted: {
                        const words = text;
                        text = "";
                        Inbox.searchEverything(words);
                    }
                    Keys.onEscapePressed: text = ""

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: search.text === ""
                        text: "Search (Enter for every email)"
                        color: Theme.m3onSurfaceVariant
                    }
                }

                IconButton {
                    visible: search.text !== ""
                    icon: "close"
                    tip: "Clear"
                    size: 32
                    onClicked: search.text = ""
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Repeater {
                model: Inbox.lanes.filter(lane => lane.chip)

                delegate: Chip {
                    required property var modelData

                    text: modelData.label
                    count: Inbox.unreadIn(modelData.id)
                    selected: Inbox.lane === modelData.id
                    onClicked: Inbox.lane = modelData.id
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Label {
                anchors.centerIn: parent
                visible: Inbox.visibleConversations.length === 0
                width: parent.width - 40
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                lineHeight: 1.2
                text: Inbox.query.trim() !== "" ? "No conversation matches.\nPress Enter to search every email." : Inbox.conversations.length === 0 ? "Loading…" : "Nothing here."
                color: Theme.m3onSurfaceVariant
            }

            ListView {
                anchors.fill: parent
                clip: true
                spacing: 4
                model: Inbox.visibleConversations
                boundsBehavior: Flickable.StopAtBounds

                delegate: ConversationRow {
                    required property var modelData

                    width: ListView.view.width
                    conversation: modelData
                }
            }
        }
    }

    PopupMenu {
        id: menu

        anchors.fill: parent
    }
}
