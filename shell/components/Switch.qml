import QtQuick
import qs.services

// A calm toggle switch: flat accent fill when on, neutral glass capsule when off.
Rectangle {
    id: root

    property bool checked: false

    signal toggled

    implicitWidth: 46
    implicitHeight: 26
    radius: 13
    color: checked ? Theme.accentFill : Theme.glassControl
    border.width: checked || Theme.glass ? 0 : 1
    border.color: Theme.m3outline

    Rectangle {
        width: root.checked ? 20 : 16
        height: width
        radius: width / 2
        anchors.verticalCenter: parent.verticalCenter
        x: root.checked ? parent.width - width - 3 : 5
        color: root.checked ? Theme.accentFillInk : Theme.m3onSurfaceVariant

        Behavior on x {
            NumberAnimation {
                duration: 160
                easing.type: Easing.OutCubic
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled()
    }
}
