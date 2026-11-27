import QtQuick
import qs.services

// Filter tab chip (tabStyle: true) or compact selectable pill chip.
// In tabStyle mode:
//   - Active tab: cleanly padded full-radius capsule with delicate top glass sheen
//     and nested frosted count pill.
//   - Inactive tab: borderless crisp Adwaita Sans text with generous tap area and
//     soft count chip.
Rectangle {
    id: root

    property string text
    property int count: 0
    property bool selected: false
    property bool tabStyle: false

    signal clicked

    readonly property int padLeft: tabStyle ? (selected ? 12 : 6) : 12
    readonly property int padRight: tabStyle ? (selected ? (count > 0 ? 6 : 12) : 6) : (count > 0 ? 8 : 12)

    implicitHeight: tabStyle ? 32 : 30
    implicitWidth: row.implicitWidth + padLeft + padRight
    radius: height / 2
    color: selected
        ? Theme.pill
        : tabStyle
            ? (area.containsMouse ? Theme.glassHover : "transparent")
            : (area.containsMouse ? Theme.glassControlHover : Theme.glassControl)
    border.width: Theme.glass ? 0 : (tabStyle && !selected ? 0 : 1)
    border.color: Theme.glassBorderSubtle

    Behavior on color {
        ColorAnimation {
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
    }

    GlassEdge {
        visible: Theme.glass && root.selected
        radius: root.radius
        fade: 8
        side: false
        light: Theme.alpha(Theme.pureWhite, Theme.dark ? 0.16 : 0.30)
    }

    Row {
        id: row

        anchors.left: parent.left
        anchors.leftMargin: root.padLeft
        anchors.verticalCenter: parent.verticalCenter
        spacing: root.selected ? 7 : 6

        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            color: root.selected ? Theme.pillInk : (root.tabStyle ? Theme.m3onSurface : Theme.m3onSurfaceVariant)
            font.pixelSize: root.tabStyle ? 13 : 12
            weight: root.selected ? Font.DemiBold : (root.tabStyle ? Font.Medium : Font.Normal)
        }

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.count > 0
            implicitHeight: root.tabStyle ? 22 : 20
            implicitWidth: Math.max(root.tabStyle ? 24 : 20, countLabel.implicitWidth + 12)
            radius: height / 2
            border.width: 0
            color: root.selected
                ? (Theme.lightGlass ? Qt.rgba(1, 1, 1, 0.78) : Theme.alpha(Theme.pillInk, 0.18))
                : Theme.glassControl

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animFast
                    easing.type: Easing.OutCubic
                }
            }

            Label {
                id: countLabel

                anchors.centerIn: parent
                tabular: true
                text: root.count > 99 ? "99+" : root.count
                color: root.selected ? Theme.pillInk : Theme.m3onSurfaceVariant
                font.pixelSize: 11
                weight: Font.Medium
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
}
