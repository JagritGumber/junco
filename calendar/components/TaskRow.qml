import QtQuick
import QtQuick.Layouts
import qs.services

// One actionable item: check it off, see a compact Carry over or Meeting tag,
// or dismiss it with the hover × button.
Item {
    id: task

    required property var modelData

    readonly property bool isDone: Boolean(modelData.completed)
    readonly property bool isCarryOver: Boolean(modelData.carryOver) && !isDone
    readonly property bool hasMeetingLink: (modelData.eventUid ?? "") !== ""

    implicitHeight: Math.max(36, row.implicitHeight + 10)

    RowLayout {
        id: row

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 10
        anchors.rightMargin: 6
        spacing: 10

        CheckBox {
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 1
            checked: task.isDone
            onToggled: Tasks.toggle(task.modelData.id)
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3

            Label {
                Layout.fillWidth: true
                text: task.modelData.title ?? ""
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
                color: task.isDone ? Theme.m3onSurfaceVariant : Theme.m3onSurface
                font.pixelSize: 13
                font.strikeout: task.isDone
            }

            RowLayout {
                visible: task.isCarryOver || task.hasMeetingLink
                spacing: 6

                Rectangle {
                    visible: task.isCarryOver
                    implicitWidth: carryLabel.implicitWidth + 10
                    implicitHeight: 18
                    radius: 9
                    color: Theme.m3tertiaryContainer

                    Label {
                        id: carryLabel

                        anchors.centerIn: parent
                        text: "Carry over"
                        color: Theme.m3onTertiaryContainer
                        font.pixelSize: 10
                        weight: Font.Medium
                    }
                }

                Row {
                    visible: task.hasMeetingLink
                    spacing: 3

                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: "event"
                        size: 12
                        color: Theme.m3onSurfaceVariant
                    }

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Meeting prep"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 10
                    }
                }
            }
        }

        IconButton {
            Layout.alignment: Qt.AlignTop
            icon: "close"
            tip: "Dismiss"
            size: 24
            opacity: hover.hovered ? 1 : 0
            onClicked: Tasks.remove(task.modelData.id)
        }
    }

    HoverHandler {
        id: hover
    }
}
