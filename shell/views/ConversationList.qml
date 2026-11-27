import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The inbox as conversations: calm, airy frosted-glass thread list with a
// single-row flagship filter bar, generous horizontal tab spacing, concentric
// inset selected cards, and collapsible inline search (Ctrl+F or filter menu).
GlassPane {
    id: root

    fill: Theme.glassList

    property bool searching: false
    readonly property bool searchShown: searching || Inbox.query !== ""
    readonly property int headerPadX: width >= 340 ? 16 : 12
    readonly property int tabGap: width >= 380 ? 22 : width >= 330 ? 16 : 10
    readonly property int cardInsetX: width >= 340 ? 11 : 8

    Shortcut {
        sequence: "Ctrl+F"
        enabled: root.visible && !Inbox.paletteOpen && !Inbox.composing && !Inbox.settingsOpen
        onActivated: {
            root.searching = true;
            search.forceActiveFocus();
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: 12
        anchors.bottomMargin: 8
        spacing: 10

        // Calm single-row Filter Header Bar (50 px visual header zone with top margin).
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 38
            Layout.leftMargin: root.headerPadX
            Layout.rightMargin: root.headerPadX
            spacing: 8

            Row {
                Layout.alignment: Qt.AlignVCenter
                spacing: root.tabGap

                Repeater {
                    model: Inbox.lanes.filter(lane => lane.chip)

                    delegate: Chip {
                        required property var modelData

                        tabStyle: true
                        text: modelData.label
                        count: Inbox.unreadIn(modelData.id)
                        selected: Inbox.lane === modelData.id
                        onClicked: Inbox.lane = modelData.id
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }

            IconButton {
                id: filterButton

                icon: "tune"
                tip: "Filter, search & refresh"
                size: 32
                iconSize: 19
                filled: Inbox.lane === "newsletters" || root.searchShown
                fillColor: Theme.glassActive
                iconColor: Inbox.lane === "newsletters" || root.searchShown ? Theme.m3primary : Theme.m3onSurfaceVariant
                onClicked: menu.show(filterButton, [
                    {
                        icon: "search",
                        label: root.searchShown ? "Hide search" : "Search inbox…",
                        run: () => {
                            if (root.searchShown) {
                                root.searching = false;
                                search.text = "";
                            } else {
                                root.searching = true;
                                search.forceActiveFocus();
                            }
                        }
                    },
                    {
                        icon: "newspaper",
                        label: "Newsletters",
                        checked: Inbox.lane === "newsletters",
                        run: () => Inbox.lane = Inbox.lane === "newsletters" ? "all" : "newsletters"
                    },
                    { separator: true },
                    { icon: "refresh", label: "Refresh", run: () => Inbox.refresh() }
                ])
            }
        }

        // Collapsible frosted-glass search field (opened via Ctrl+F or filter menu).
        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: root.headerPadX
            Layout.rightMargin: root.headerPadX
            visible: root.searchShown
            implicitHeight: 38
            radius: Theme.controlRadius
            color: search.activeFocus ? Theme.glassControlHover : Theme.glassControl
            border.width: Theme.glass ? 0 : 1
            border.color: search.activeFocus ? Theme.alpha(Theme.m3primary, 0.72) : Theme.glassBorderSubtle

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 8
                spacing: 8

                Icon {
                    name: "search"
                    size: 17
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
                        root.searching = false;
                        Inbox.searchEverything(words);
                    }
                    Keys.onEscapePressed: {
                        text = "";
                        root.searching = false;
                    }

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: search.text === ""
                        text: "Search mail (Enter for all)"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }
                }

                IconButton {
                    icon: "close"
                    tip: "Close search"
                    size: 26
                    onClicked: {
                        search.text = "";
                        root.searching = false;
                    }
                }
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
                lineHeight: 1.25
                text: Inbox.query.trim() !== "" ? "No conversation matches.\nPress Enter to search every email." : Inbox.conversations.length === 0 ? "Loading…" : "Nothing here."
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 13
            }

            ListView {
                id: listView

                anchors.fill: parent
                anchors.leftMargin: root.cardInsetX
                anchors.rightMargin: root.cardInsetX
                clip: true
                cacheBuffer: 360
                spacing: 4
                topMargin: 2
                bottomMargin: 6
                model: Inbox.visibleConversations
                boundsBehavior: Flickable.StopAtBounds

                delegate: ConversationRow {
                    required property var modelData
                    required property int index

                    width: listView.width
                    conversation: modelData
                    isLast: index === listView.count - 1
                    nextSelected: index + 1 < Inbox.visibleConversations.length
                        && Inbox.visibleConversations[index + 1].id === Inbox.selectedId
                }
            }
        }
    }

    PopupMenu {
        id: menu

        anchors.fill: parent
    }
}
