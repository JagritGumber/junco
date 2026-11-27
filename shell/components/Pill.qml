import QtQuick
import qs.services

// A frosted-glass pill button with an optional leading icon. "filled" is the
// primary accent action (a flat accent fill; on light glass with a crisp
// glass border), "tonal" a soft translucent glass button, "outlined" a
// rimmed glass pill, "text" minimal weight. An optional `hint` (a shortcut such as
// "Ctrl N") sits at the right end; the label then starts at the left.
Rectangle {
    id: root

    property string text
    property string icon: ""
    property string style: "tonal"
    property int size: 36
    property int fontSize: 13
    property string tip: ""
    property string hint: ""

    signal clicked

    readonly property color ink: style === "filled" ? Theme.pillInk : style === "text" ? Theme.m3primary : Theme.m3onSurface

    implicitWidth: row.implicitWidth + (icon === "" ? 28 : 24)
    implicitHeight: size
    radius: size / 2
    color: {
        const hover = area.containsMouse ? (area.pressed ? 0.16 : 0.10) : 0;
        if (style === "filled")
            return hover ? Qt.tint(Theme.pill, Theme.alpha(Theme.pillInk, hover * 0.5)) : Theme.pill;
        if (style === "tonal")
            return area.containsMouse ? Theme.glassControlHover : Theme.glassControl;
        if (style === "outlined")
            return Theme.glass ? (area.containsMouse ? Theme.glassControlHover : Theme.glassControl) : (area.containsMouse ? Theme.glassHover : Theme.alpha(Theme.m3onSurface, 0.03));
        return hover ? Theme.alpha(Theme.m3primary, hover) : "transparent";
    }
    border.width: !Theme.glass && style === "outlined" ? 1 : 0
    border.color: style === "outlined" ? Theme.glassBorder : Theme.glassBorderSubtle

    Behavior on color {
        ColorAnimation {
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
    }

    GlassEdge {
        visible: Theme.glass && root.style === "filled"
        radius: root.radius
        fade: 9
        side: false
        light: Theme.alpha(Theme.pureWhite, Theme.dark ? 0.16 : 0.28)
    }

    Row {
        id: row

        anchors.centerIn: hintRow.visible ? undefined : parent
        anchors.left: hintRow.visible ? parent.left : undefined
        anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        spacing: 7

        Icon {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.icon !== ""
            name: root.icon
            size: Math.round(root.size * 0.50)
            color: root.ink
        }

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            color: root.ink
            font.pixelSize: root.fontSize
            weight: style === "filled" ? Font.DemiBold : Font.Medium
        }
    }

    // The shortcut hint, as small key caps with comfortable right pill padding.
    Row {
        id: hintRow

        visible: root.hint !== "" && root.width >= row.implicitWidth + implicitWidth + 34
        anchors.right: parent.right
        anchors.rightMargin: 13
        anchors.verticalCenter: parent.verticalCenter
        spacing: 3

        Repeater {
            model: root.hint === "" ? [] : root.hint.split(" ")

            delegate: Rectangle {
                required property string modelData

                implicitWidth: key.implicitWidth + 8
                implicitHeight: 17
                radius: 5
                color: Theme.alpha(root.ink, 0.10)
                border.width: Theme.glass ? 0 : 1
                border.color: Theme.alpha(root.ink, 0.12)

                Label {
                    id: key

                    anchors.centerIn: parent
                    text: parent.modelData
                    color: Theme.alpha(root.ink, 0.72)
                    font.pixelSize: 10
                    weight: Font.Normal
                }
            }
        }
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
