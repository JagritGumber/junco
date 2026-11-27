import QtQuick
import qs.services

// A compact rounded checkbox, filled with a tick when on.
Rectangle {
    id: root

    property string tip: ""
    property bool checked: false
    property color tint: Theme.m3primary
    property color checkColor: Theme.m3onPrimary

    signal toggled

    implicitWidth: 18
    implicitHeight: 18
    radius: 5
    color: checked ? tint : (area.containsMouse ? Theme.glassControlHover : "transparent")
    border.width: checked ? 0 : 1.5
    border.color: Theme.m3onSurfaceVariant

    Icon {
        anchors.centerIn: parent
        visible: root.checked
        name: "check"
        size: 14
        color: root.checkColor
    }

    MouseArea {
        id: area

        anchors.fill: parent
        anchors.margins: -6
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled()
    }

    Loader {
        active: area.containsMouse && root.tip !== ""
        sourceComponent: Tooltip {
            parent: root
            text: root.tip
        }
    }
}
