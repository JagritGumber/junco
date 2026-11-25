import QtQuick
import QtQuick.Layouts
import qs.services

// One to-do: tick it off, or remove it from the little × on hover.
Item {
    id: task

    required property var modelData

    implicitHeight: 40

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 6
        spacing: 12

        CheckBox {
            checked: task.modelData.done
            onToggled: Tasks.toggle(task.modelData.id)
        }

        Label {
            Layout.fillWidth: true
            text: task.modelData.title
            elide: Text.ElideRight
            color: task.modelData.done ? Theme.m3onSurfaceVariant : Theme.m3onSurface
            font.pixelSize: 14
        }

        IconButton {
            icon: "close"
            tip: "Remove"
            size: 28
            opacity: hover.hovered ? 1 : 0
            onClicked: Tasks.remove(task.modelData.id)
        }
    }

    HoverHandler {
        id: hover
    }
}
