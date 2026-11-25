import QtQuick
import qs.services

// A Material switch: the thumb grows and slides right when on.
Rectangle {
    id: root

    property bool checked: false

    signal toggled

    implicitWidth: 52
    implicitHeight: 32
    radius: 16
    color: checked ? Theme.m3primary : Theme.m3surfaceContainerHighest
    border.width: checked ? 0 : 2
    border.color: Theme.m3outline

    Rectangle {
        width: root.checked ? 24 : 16
        height: width
        radius: width / 2
        anchors.verticalCenter: parent.verticalCenter
        x: root.checked ? parent.width - width - 4 : 8
        color: root.checked ? Theme.m3onPrimary : Theme.m3outline

        Behavior on x {
            NumberAnimation {
                duration: 180
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
