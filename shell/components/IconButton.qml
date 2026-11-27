import QtQuick
import qs.services

Rectangle {
    id: root

    property string icon
    property bool filled: false
    property color fillColor: Theme.glassActive
    property color iconColor: filled ? Theme.m3onSurface : Theme.m3onSurfaceVariant
    property int size: 32
    property real cornerRadius: size / 2
    property bool outlined: false
    property string tip: ""
    // 1 draws the icon filled (a starred star), 0 outlined.
    property int iconFill: filled ? 1 : 0

    signal clicked

    implicitWidth: size
    implicitHeight: size
    radius: cornerRadius
    border.width: outlined || (filled && Theme.glass && fillColor !== Theme.pill) ? 1 : 0
    border.color: outlined ? Theme.glassBorder : Theme.glassBorderSubtle
    color: filled ? (area.pressed ? Qt.darker(fillColor, 1.1) : fillColor) : (area.containsMouse ? (area.pressed ? Theme.alpha(Theme.m3onSurface, 0.16) : Theme.glassControlHover) : "transparent")

    Icon {
        anchors.centerIn: parent
        name: root.icon
        color: root.iconColor
        size: Math.round(root.size * 0.56)
        fill: root.iconFill
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    Loader {
        active: area.containsMouse && root.tip !== ""
        sourceComponent: Tooltip {
            parent: root
            text: root.tip
        }
    }
}
