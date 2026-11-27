import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// A folder's list (Sent, Archive, Trash…): compact frosted-glass pane with
// scannable date groups and dense rows.
GlassPane {
    id: root

    fill: Theme.glassList

    property bool searching: false
    readonly property bool searchShown: searching || Inbox.search !== ""

    Connections {
        target: Inbox

        function onSearchChanged(): void {
            if (searchInput.text !== Inbox.search)
                searchInput.text = Inbox.search;
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: 12
        anchors.bottomMargin: 8
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 38
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            spacing: 8

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Label {
                    Layout.fillWidth: true
                    text: Inbox.listing?.title ?? Inbox.currentFolder?.name ?? ""
                    elide: Text.ElideRight
                    font.pixelSize: 17
                    weight: Font.DemiBold
                }

                Label {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: Inbox.search.trim() ? `Results for “${Inbox.search.trim()}”` : (Inbox.listing?.subtitle ?? "")
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }

            IconButton {
                id: filterButton

                icon: "tune"
                tip: "Filter"
                size: 32
                iconSize: 19
                filled: Inbox.unreadOnly || Inbox.withFiles
                fillColor: Theme.glassActive
                iconColor: Inbox.unreadOnly || Inbox.withFiles ? Theme.m3primary : Theme.m3onSurfaceVariant
                onClicked: menu.show(filterButton, [
                    { icon: "mark_email_unread", label: "Unread only", checked: Inbox.unreadOnly, run: () => Inbox.unreadOnly = !Inbox.unreadOnly },
                    { icon: "attach_file", label: "With attachments", checked: Inbox.withFiles, run: () => Inbox.withFiles = !Inbox.withFiles },
                    { separator: true },
                    { icon: "refresh", label: "Refresh", run: () => Inbox.refresh() }
                ])
            }

            IconButton {
                icon: "search"
                tip: "Search this folder"
                size: 32
                iconSize: 19
                filled: root.searchShown
                fillColor: Theme.glassActive
                iconColor: root.searchShown ? Theme.m3primary : Theme.m3onSurfaceVariant
                onClicked: {
                    if (root.searchShown) {
                        root.searching = false;
                        if (Inbox.search !== "")
                            Inbox.runSearch("");
                    } else {
                        root.searching = true;
                        searchInput.forceActiveFocus();
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            Layout.rightMargin: 16
            visible: root.searchShown
            implicitHeight: 38
            radius: Theme.controlRadius
            color: searchInput.activeFocus ? Theme.glassControlHover : Theme.glassControl
            border.width: Theme.glass ? 0 : 1
            border.color: searchInput.activeFocus ? Theme.alpha(Theme.m3primary, 0.72) : Theme.glassBorderSubtle

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 8
                spacing: 8

                Icon {
                    name: "search"
                    size: 16
                }

                TextInput {
                    id: searchInput

                    Layout.fillWidth: true
                    renderType: Text.NativeRendering
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 13
                    clip: true
                    onAccepted: Inbox.runSearch(text)
                    Keys.onEscapePressed: {
                        text = "";
                        root.searching = false;
                        Inbox.runSearch("");
                    }

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: searchInput.text === ""
                        text: `Search ${Inbox.currentFolder?.name ?? "mail"}, then Enter`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }
                }

                IconButton {
                    visible: searchInput.text !== ""
                    icon: "close"
                    tip: "Clear"
                    size: 24
                    onClicked: {
                        searchInput.text = "";
                        Inbox.runSearch("");
                    }
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Label {
                anchors.centerIn: parent
                visible: Inbox.flatRows.length === 0
                width: parent.width - 32
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: Inbox.listLoading ? "Loading…" : Inbox.listFailed ? "Couldn't load this folder." : Inbox.search.trim() ? "Nothing matches." : Inbox.unreadOnly || Inbox.withFiles ? "Nothing here with that filter." : "Nothing here."
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 13
            }

            ListView {
                id: list

                anchors.fill: parent
                anchors.leftMargin: root.width >= 340 ? 11 : 8
                anchors.rightMargin: root.width >= 340 ? 11 : 8
                spacing: 4
                topMargin: 2
                bottomMargin: 6

                footer: Label {
                    width: ListView.view.width
                    visible: Inbox.listing?.more ?? false
                    height: visible ? 40 : 0
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: "Showing the newest 150. Search to find older mail."
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
                clip: true
                cacheBuffer: 360
                boundsBehavior: Flickable.StopAtBounds
                model: Inbox.flatRows
                reuseItems: false

                delegate: Item {
                    id: slot

                    required property var modelData
                    required property int index

                    width: ListView.view.width
                    height: loader.item ? loader.item.implicitHeight : 0

                    Loader {
                        id: loader

                        width: parent.width
                        sourceComponent: slot.modelData.type === "header" ? header : slot.modelData.type === "member" ? member : mailRow
                    }

                    Component {
                        id: header

                        Item {
                            implicitHeight: 30

                            Label {
                                x: 14
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 5
                                text: slot.modelData.name
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 12
                                weight: Font.Medium
                            }
                        }
                    }

                    Component {
                        id: mailRow

                        MailRow {
                            row: slot.modelData
                            showDivider: slot.index + 1 < Inbox.flatRows.length
                                && Inbox.flatRows[slot.index + 1].type === "row"
                                && Inbox.flatRows[slot.index + 1].id !== Inbox.selectedRow
                            onClicked: Inbox.toggleRow(slot.modelData)
                        }
                    }

                    Component {
                        id: member

                        Item {
                            implicitHeight: 38

                            Rectangle {
                                readonly property bool current: Inbox.openId === slot.modelData.id

                                x: 54
                                width: parent.width - 58
                                height: 36
                                radius: 9
                                color: current ? Theme.glassActive : (memberArea.containsMouse ? Theme.glassHover : "transparent")
                                border.width: current ? 1 : 0
                                border.color: Theme.glassActiveBorder

                                Rectangle {
                                    x: -9
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 5
                                    height: 5
                                    radius: 2.5
                                    visible: slot.modelData.unread
                                    color: Theme.m3primary
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 8

                                    Label {
                                        Layout.maximumWidth: 110
                                        text: slot.modelData.title
                                        elide: Text.ElideRight
                                        font.pixelSize: 12
                                        weight: slot.modelData.unread ? Font.Medium : Font.Normal
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: slot.modelData.subtitle
                                        elide: Text.ElideRight
                                        color: Theme.m3onSurfaceVariant
                                        font.pixelSize: 12
                                    }

                                    Label {
                                        text: slot.modelData.time
                                        color: Theme.m3onSurfaceVariant
                                        font.pixelSize: 10
                                    }
                                }

                                MouseArea {
                                    id: memberArea

                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Inbox.openMessage(slot.modelData.id, true)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    PopupMenu {
        id: menu

        anchors.fill: parent
    }
}
