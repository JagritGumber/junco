import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.services
import qs.components

// Mail's sidebar: Compose, the folders with what's unread or waiting in each,
// and the account bar at the foot (every account together, or one).
Rectangle {
    id: root

    radius: 26
    color: Theme.m3surfaceContainerLow

    readonly property var order: ["smart", "all", "starred", "sent", "archive", "trash"]

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 4

        AppTitle {
            Layout.leftMargin: 8
            Layout.topMargin: 6
            Layout.bottomMargin: 10
            text: "Mail"
            icon: `file://${Quickshell.shellDir}/../assets/icons/courier-pip.svg`
        }

        Pill {
            Layout.fillWidth: true
            Layout.bottomMargin: 12
            style: "filled"
            icon: "add"
            text: "Compose"
            size: 52
            fontSize: 15
            tip: "Write an email (Ctrl+N)"
            onClicked: Inbox.compose("new", "")
        }

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            contentHeight: list.implicitHeight

            ColumnLayout {
                id: list

                width: parent.width
                spacing: 2

                Repeater {
                    model: root.order.map(id => Inbox.folders.find(f => f.id === id)).filter(f => f)

                    delegate: SidebarItem {
                        required property var modelData

                        Layout.fillWidth: true
                        icon: modelData.icon
                        text: modelData.name
                        count: modelData.count
                        active: Inbox.folder === modelData.id && !Inbox.tableTemplate
                        onClicked: {
                            Inbox.closeTable();
                            Inbox.openFolder(modelData.id);
                        }
                    }
                }

                // Templates you taught fields for, each as a table of updates.
                Label {
                    Layout.topMargin: 14
                    Layout.leftMargin: 12
                    Layout.bottomMargin: 4
                    visible: Inbox.developer && Inbox.templates.length > 0
                    text: "Tables"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                    font.weight: Font.Medium
                }

                Repeater {
                    model: Inbox.developer ? Inbox.templates : []

                    delegate: SidebarItem {
                        required property var modelData

                        Layout.fillWidth: true
                        icon: "table_view"
                        text: modelData.name
                        active: Inbox.tableTemplate === modelData.id
                        onClicked: Inbox.openTable(modelData.id)
                    }
                }
            }
        }

        // Your accounts as circles; switching, pictures, storage, adding.
        AccountBar {
            Layout.fillWidth: true
            Layout.bottomMargin: 2
        }
    }
}
