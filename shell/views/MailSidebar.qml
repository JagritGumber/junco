import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.services
import qs.components

// Junco Mail's sidebar: a rounded inset smoked-glass pane (same outer inset,
// 16 px radius and clear-glass gutter as the Inbox and Reader cards) with light
// ink; expands to 204 px on wide screens and collapses to a 56 px icon rail on
// half-screen tiles (~910x1040) or via Ctrl+\. Pip and a small sync pill fill
// the otherwise empty space above the accounts when there is room.
GlassPane {
    id: root

    property bool compact: false
    property bool autoCompact: false

    signal toggleCompact

    fill: Theme.glassSidebar

    readonly property var order: ["smart", "all", "starred", "sent", "archive", "expiring", "trash"]

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.compact ? 8 : 14
        spacing: root.compact ? 8 : 8

        // Header: Pip icon + "Junco" + rail toggle (expanded), or centered Pip (compact).
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: root.compact ? 0 : 4
            Layout.topMargin: 2
            Layout.bottomMargin: root.compact ? 6 : 10
            spacing: 4

            Item {
                Layout.fillWidth: root.compact
                implicitWidth: root.compact ? 38 : titleRow.implicitWidth
                implicitHeight: 28

                AppTitle {
                    id: titleRow

                    visible: !root.compact
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Junco"
                    icon: `file://${Quickshell.shellDir}/../assets/icons/courier-pip.svg`
                    iconSize: 22
                    fontSize: 17
                    gap: 8
                    color: Theme.sheetInk
                }

                Image {
                    visible: root.compact
                    anchors.centerIn: parent
                    width: 24
                    height: 24
                    source: `file://${Quickshell.shellDir}/../assets/icons/courier-pip.svg`
                    sourceSize: Qt.size(24, 24)
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.compact && !root.autoCompact
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.toggleCompact()
                }
            }

            Item {
                Layout.fillWidth: true
                visible: !root.compact
            }

            IconButton {
                visible: !root.compact
                icon: "left_panel_close"
                tip: "Collapse sidebar (Ctrl+\\)"
                size: 26
                iconColor: Theme.sheetInkVariant
                onClicked: root.toggleCompact()
            }
        }

        // Compose button: calm accent pill (expanded) or rounded accent button (compact).
        Pill {
            Layout.fillWidth: true
            Layout.bottomMargin: 14
            visible: !root.compact
            style: "filled"
            icon: "edit"
            text: "Compose"
            size: 42
            fontSize: 13
            hint: "Ctrl N"
            tip: "Write an email (Ctrl+N)"
            onClicked: Inbox.compose("new", "")
        }

        IconButton {
            Layout.alignment: Qt.AlignHCenter
            Layout.bottomMargin: 8
            visible: root.compact
            icon: "edit"
            tip: "Compose (Ctrl+N)"
            size: 40
            cornerRadius: 13
            filled: true
            fillColor: Theme.pill
            iconColor: Theme.pillInk
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
                spacing: 4

                Repeater {
                    model: root.order.map(id => Inbox.folders.find(f => f.id === id)).filter(f => f)

                    delegate: SidebarItem {
                        required property var modelData

                        Layout.fillWidth: true
                        compact: root.compact
                        icon: modelData.icon
                        text: modelData.name
                        count: modelData.count
                        active: Inbox.folder === modelData.id && !Inbox.tableTemplate && !Inbox.settingsOpen
                        onClicked: {
                            Inbox.closeTable();
                            Inbox.openFolder(modelData.id);
                        }
                    }
                }

                // Developer-only taught template tables (COURIER_DEV=1).
                Label {
                    Layout.topMargin: 14
                    Layout.leftMargin: 12
                    Layout.bottomMargin: 4
                    visible: !root.compact && Inbox.developer && Inbox.templates.length > 0
                    text: "Tables"
                    color: Theme.sheetInkVariant
                    font.pixelSize: 11
                    weight: Font.Medium
                }

                Repeater {
                    model: Inbox.developer ? Inbox.templates : []

                    delegate: SidebarItem {
                        required property var modelData

                        Layout.fillWidth: true
                        compact: root.compact
                        icon: "table_view"
                        text: modelData.name
                        active: Inbox.tableTemplate === modelData.id
                        onClicked: Inbox.openTable(modelData.id)
                    }
                }
            }
        }

        // Pip and the sync pill, in the sidebar's otherwise empty lower part;
        // only when the window is tall enough that the folders keep their room.
        Item {
            Layout.fillWidth: true
            Layout.topMargin: 8
            Layout.bottomMargin: 6
            visible: !root.compact && Theme.glass && root.height > 680
            implicitHeight: pip.height + 10 + syncPill.height

            Image {
                id: pip

                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                width: 64
                height: 64
                source: `file://${Quickshell.shellDir}/../assets/icons/courier-pip.svg`
                sourceSize: Qt.size(64, 64)
                fillMode: Image.PreserveAspectFit
                smooth: true
                asynchronous: true
                opacity: 0.92
                Accessible.ignored: true
            }

            Rectangle {
                id: syncPill
                objectName: "mailSyncPill"

                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                visible: Inbox.syncLabel !== ""
                width: syncRow.implicitWidth + 18
                height: 24
                radius: 12
                color: syncPillArea.pressed
                    ? Theme.sheetControlHover
                    : syncPillArea.containsMouse
                    ? Theme.sheetControlHover
                    : Theme.sheetControl
                border.width: Theme.glass ? 0 : 1
                border.color: Theme.sheetRim

                Behavior on color {
                    ColorAnimation {
                        duration: Theme.animFast
                        easing.type: Easing.OutCubic
                    }
                }

                Row {
                    id: syncRow

                    anchors.centerIn: parent
                    spacing: 6

                    Rectangle {
                        objectName: "mailSyncPillDot"
                        anchors.verticalCenter: parent.verticalCenter
                        width: 7
                        height: 7
                        radius: 3.5
                        color: Inbox.reauthInFlight !== ""
                            ? Theme.accent
                            : Inbox.syncTrouble
                            ? Theme.sheetError
                            : Inbox.syncing
                            ? Theme.accent
                            : Theme.complementSheetDot
                    }

                    Label {
                        objectName: "mailSyncPillLabel"
                        anchors.verticalCenter: parent.verticalCenter
                        text: Inbox.syncLabel
                        color: Theme.sheetInk
                        font.pixelSize: 11
                        weight: Inbox.syncTrouble ? Font.Medium : Font.Normal
                    }
                }

                MouseArea {
                    id: syncPillArea
                    objectName: "mailSyncPillArea"

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Inbox.handleSyncPillClick()
                }

                Loader {
                    active: syncPillArea.containsMouse
                    sourceComponent: Tooltip {
                        parent: syncPill
                        text: Inbox.reauthInFlight !== ""
                            ? "Waiting for sign-in in browser · click to cancel"
                            : Inbox.syncTroubleMessage !== ""
                            ? `${Inbox.syncTroubleMessage} · click to fix`
                            : "Click to sync mail now"
                    }
                }
            }
        }

        SidebarItem {
            Layout.fillWidth: true
            compact: root.compact
            icon: "settings"
            text: "Settings"
            active: Inbox.settingsOpen
            onClicked: Inbox.settingsOpen ? Inbox.closeSettings() : Inbox.openSettings()
        }

        // Subtle glass divider above account bar.
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 8
            Layout.bottomMargin: 8
            implicitHeight: 1
            color: Theme.sheetDivider
        }
        AccountBar {
            Layout.fillWidth: true
            compact: root.compact
        }
    }
}
