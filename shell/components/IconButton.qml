import QtQuick
import qs.services

Rectangle {
    id: root

    property string icon
    property bool filled: false
    property color fillColor: Theme.m3primaryContainer
    property color iconColor: filled ? Theme.m3onPrimaryContainer : Theme.m3onSurfaceVariant
    property int size: 40
    property real cornerRadius: size / 2
    property bool outlined: false
    property string tip: ""
    // 1 draws the icon filled (a starred star), 0 outlined.
    property int iconFill: filled ? 1 : 0

    signal clicked

    implicitWidth: size
    implicitHeight: size
    radius: cornerRadius
    border.width: outlined ? 1 : 0
    border.color: Theme.m3outlineVariant
    color: filled ? (area.pressed ? Qt.darker(fillColor, 1.1) : fillColor) : (area.containsMouse ? Theme.alpha(Theme.m3onSurface, area.pressed ? 0.12 : 0.08) : "transparent")

    Icon {
        anchors.centerIn: parent
        name: root.icon
        color: root.iconColor
        size: Math.round(root.size * 0.52)
        fill: root.iconFill
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
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
