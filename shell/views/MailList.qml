import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// A folder's list (Sent, Archive, Trash…; the inbox is ConversationList):
// its name and what it holds, filter and search, then the rows under Today,
// Yesterday and Earlier. Folded rows (a sender's morning of GitHub) open in
// place to show their emails.
Rectangle {
    id: root

    property bool searching: false
    readonly property bool searchShown: searching || Inbox.search !== ""

    // A search can start in the inbox's box and land here.
    Connections {
        target: Inbox

        function onSearchChanged(): void {
            if (searchInput.text !== Inbox.search)
                searchInput.text = Inbox.search;
        }
    }

    radius: 26
    color: Theme.m3surfaceContainerLow

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 6
            spacing: 6

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Label {
                    Layout.fillWidth: true
                    text: Inbox.listing?.title ?? Inbox.currentFolder?.name ?? ""
                    elide: Text.ElideRight
                    font.pixelSize: 24
                    font.weight: Font.Medium
                }

                Label {
                    Layout.fillWidth: true
                    text: Inbox.search.trim() ? `Results for “${Inbox.search.trim()}”` : (Inbox.listing?.subtitle ?? "")
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }
            }

            IconButton {
                id: filterButton

                icon: "tune"
                tip: "Filter"
                size: 44
                filled: Inbox.unreadOnly || Inbox.withFiles
                fillColor: Theme.m3secondaryContainer
                iconColor: Inbox.unreadOnly || Inbox.withFiles ? Theme.m3onSecondaryContainer : Theme.m3onSurfaceVariant
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
                size: 44
                filled: root.searchShown
                fillColor: Theme.m3secondaryContainer
                iconColor: root.searchShown ? Theme.m3onSecondaryContainer : Theme.m3onSurfaceVariant
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

        // Words in the subject, sender or text, or notmuch syntax (from:aarav).
        Rectangle {
            Layout.fillWidth: true
            visible: root.searchShown
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
                    id: searchInput

                    Layout.fillWidth: true
                    renderType: Text.NativeRendering
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 14
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
                    }
                }

                IconButton {
                    visible: searchInput.text !== ""
                    icon: "close"
                    tip: "Clear"
                    size: 32
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
                width: parent.width - 40
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: Inbox.listLoading ? "Loading…" : Inbox.listFailed ? "Couldn't load this folder." : Inbox.search.trim() ? "Nothing matches." : Inbox.unreadOnly || Inbox.withFiles ? "Nothing here with that filter." : "Nothing here."
                color: Theme.m3onSurfaceVariant
            }

            ListView {
                id: list

                anchors.fill: parent

                footer: Label {
                    width: ListView.view.width
                    visible: Inbox.listing?.more ?? false
                    height: visible ? 48 : 0
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: "Showing the newest 150. Search to find older mail."
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: Inbox.flatRows
                reuseItems: false

                // Only the kind of item each entry needs is built.
                delegate: Item {
                    id: slot

                    required property var modelData

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
                            implicitHeight: 42

                            Label {
                                x: 8
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 8
                                text: slot.modelData.name
                                font.pixelSize: 15
                                font.weight: Font.Medium
                            }
                        }
                    }

                    Component {
                        id: mailRow

                        MailRow {
                            row: slot.modelData
                            onClicked: Inbox.toggleRow(slot.modelData)
                        }
                    }

                    // One email of a folded row, opened in place.
                    Component {
                        id: member

                        Item {
                            implicitHeight: 48

                            Rectangle {
                                readonly property bool current: Inbox.openId === slot.modelData.id

                                x: 70
                                width: parent.width - 76
                                height: 46
                                radius: 14
                                color: current ? Theme.alpha(Theme.m3primary, 0.14) : (memberArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.05) : "transparent")

                                Rectangle {
                                    x: -10
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 6
                                    height: 6
                                    radius: 3
                                    visible: slot.modelData.unread
                                    color: Theme.m3primary
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 12
                                    spacing: 8

                                    Label {
                                        Layout.maximumWidth: 120
                                        text: slot.modelData.title
                                        elide: Text.ElideRight
                                        font.pixelSize: 13
                                        font.weight: slot.modelData.unread ? Font.DemiBold : Font.Medium
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: slot.modelData.subtitle
                                        elide: Text.ElideRight
                                        color: Theme.m3onSurfaceVariant
                                        font.pixelSize: 13
                                    }

                                    Label {
                                        text: slot.modelData.time
                                        color: Theme.m3onSurfaceVariant
                                        font.pixelSize: 11
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
