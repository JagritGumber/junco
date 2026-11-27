import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The inbox as conversations, Beeper-style: dense, scannable frosted-glass
// thread list maximizing vertical count on 15" 16:9 displays.
GlassPane {
    id: root

    fill: Theme.glassList

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        // Calm header: Inbox · N unread + filter button.
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 4
            Layout.rightMargin: 2
            spacing: 8

            Label {
                text: Inbox.lane === "newsletters" ? "Newsletters" : "Inbox"
                font.pixelSize: 17
                weight: Font.DemiBold
            }

            Label {
                readonly property int unreadTotal: Inbox.unreadIn(Inbox.lane)

                visible: unreadTotal > 0
                text: `·  ${unreadTotal} unread`
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 12
            }

            Item {
                Layout.fillWidth: true
            }

            IconButton {
                id: filterButton

                icon: "tune"
                tip: "Filter & refresh"
                size: 28
                filled: Inbox.lane === "newsletters"
                fillColor: Theme.glassActive
                iconColor: Inbox.lane === "newsletters" ? Theme.m3primary : Theme.m3onSurfaceVariant
                onClicked: menu.show(filterButton, [
                    { icon: "newspaper", label: "Newsletters", checked: Inbox.lane === "newsletters", run: () => Inbox.lane = Inbox.lane === "newsletters" ? "all" : "newsletters" },
                    { separator: true },
                    { icon: "refresh", label: "Refresh", run: () => Inbox.refresh() }
                ])
            }
        }

        // Calm frosted-glass search field.
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 36
            radius: 12
            color: Theme.glassControl
            border.width: 1
            border.color: search.activeFocus ? Theme.alpha(Theme.m3primary, 0.72) : Theme.glass ? Theme.glassBorder : Theme.glassBorderSubtle

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 6
                spacing: 8

                Icon {
                    name: "search"
                    size: 16
                    color: Theme.m3onSurfaceVariant
                }

                TextInput {
                    id: search

                    Layout.fillWidth: true
                    renderType: Text.NativeRendering
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 13
                    clip: true
                    onTextChanged: Inbox.query = text
                    onAccepted: {
                        const words = text;
                        text = "";
                        Inbox.searchEverything(words);
                    }
                    Keys.onEscapePressed: text = ""

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: search.text === ""
                        text: "Search mail (Enter for all)"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }
                }

                IconButton {
                    visible: search.text !== ""
                    icon: "close"
                    tip: "Clear"
                    size: 24
                    onClicked: search.text = ""
                }
            }
        }

        // Compact lane filter chips.
        RowLayout {
            Layout.fillWidth: true
            spacing: 5

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

            Item {
                Layout.fillWidth: true
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Label {
                anchors.centerIn: parent
                visible: Inbox.visibleConversations.length === 0
                width: parent.width - 32
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                lineHeight: 1.2
                text: Inbox.query.trim() !== "" ? "No conversation matches.\nPress Enter to search every email." : Inbox.conversations.length === 0 ? "Loading…" : "Nothing here."
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 13
            }

            ListView {
                anchors.fill: parent
                clip: true
                cacheBuffer: 320
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
