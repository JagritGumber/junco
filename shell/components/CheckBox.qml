import QtQuick
import qs.services

// A Material checkbox: an outlined rounded square, filled with a tick when on.
Rectangle {
    id: root

    // What ticking it does, shown on hover.
    property string tip: ""

    property bool checked: false
    // A calendar's checkbox takes the calendar's colour.
    property color tint: Theme.m3primary
    property color checkColor: Theme.m3onPrimary

    signal toggled

    implicitWidth: 22
    implicitHeight: 22
    radius: 6
    color: checked ? tint : (area.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent")
    border.width: checked ? 0 : 2
    border.color: Theme.m3onSurfaceVariant

    Icon {
        anchors.centerIn: parent
        visible: root.checked
        name: "check"
        size: 18
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

    // Its tip after a moment's hover, built only while hovered.
    Loader {
        active: area.containsMouse && root.tip !== ""
        sourceComponent: Tooltip {
            parent: root
            text: root.tip
        }
    }
}
