import QtQuick
import qs.services

// A rounded text button with an optional leading icon. "filled" is the one
// main action (primary), "tonal" a quiet surface button, "outlined" a
// secondary action on a card, "text" the least weight (Cancel).
Rectangle {
    id: root

    property string text
    property string icon: ""
    property string style: "tonal"
    property int size: 40
    property int fontSize: 14
    property string tip: ""

    signal clicked

    readonly property color ink: style === "filled" ? Theme.m3onPrimary : style === "text" ? Theme.m3primary : Theme.m3onSurface

    implicitWidth: row.implicitWidth + (icon === "" ? 32 : 28)
    implicitHeight: size
    radius: size / 2
    color: {
        const hover = area.containsMouse ? (area.pressed ? 0.14 : 0.08) : 0;
        if (style === "filled")
            return hover ? Qt.tint(Theme.m3primary, Theme.alpha(Theme.m3onPrimary, hover)) : Theme.m3primary;
        if (style === "tonal")
            return hover ? Qt.tint(Theme.m3surfaceContainerHigh, Theme.alpha(Theme.m3onSurface, hover)) : Theme.m3surfaceContainerHigh;
        return hover ? Theme.alpha(style === "text" ? Theme.m3primary : Theme.m3onSurface, hover) : "transparent";
    }
    border.width: style === "outlined" ? 1 : 0
    border.color: Theme.m3outlineVariant

    Row {
        id: row

        anchors.centerIn: parent
        spacing: 8

        Icon {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.icon !== ""
            name: root.icon
            size: Math.round(root.size * 0.5)
            color: root.ink
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            color: root.ink
            font.pixelSize: root.fontSize
            font.weight: Font.Medium
        }
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
