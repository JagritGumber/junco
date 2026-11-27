import QtQuick
import QtQuick.Layouts
import qs.services

// One row of the sidebar, which sits on the clear glass sheet: light ink, and
// the open folder as a soft frosted-glass pill with an accent count badge (no
// vertical left stripe). Collapses into a 38x38 rail icon with a badge and a
// tooltip.
Rectangle {
    id: root

    property string icon
    property string text
    property int count: 0
    property bool active: false
    property bool compact: false

    signal clicked

    implicitHeight: compact ? 40 : 41
    radius: 13
    color: active ? Theme.sheetActive : (area.containsMouse ? Theme.sheetHover : "transparent")
    border.width: 0

    Behavior on color {
        ColorAnimation {
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
    }

    GlassEdge {
        visible: Theme.glass && root.active
        radius: root.radius
        fade: 9
        side: false
        light: Theme.alpha(Theme.pureWhite, Theme.dark ? 0.22 : 0.16)
    }

    // Expanded layout
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 13
        anchors.rightMargin: 11
        spacing: 13
        visible: !root.compact

        Icon {
            name: root.icon
            size: 19
            fill: root.active ? 1 : 0
            color: root.active ? Theme.sheetInk : Theme.sheetInkVariant
        }

        Label {
            Layout.fillWidth: true
            text: root.text
            elide: Text.ElideRight
            color: Theme.sheetInk
            font.pixelSize: 13
            weight: root.active ? Font.DemiBold : Font.Normal
        }

        Rectangle {
            visible: root.count > 0
            implicitWidth: Math.max(22, number.implicitWidth + 12)
            implicitHeight: 20
            radius: 10
            color: root.active ? Theme.accentFill : Theme.sheetControl

            Label {
                id: number

                anchors.centerIn: parent
                tabular: true
                text: root.count > 999 ? "999+" : root.count
                color: root.active ? Theme.accentFillInk : Theme.sheetInk
                font.pixelSize: 11
                weight: Font.Medium
            }
        }
    }

    // Compact icon-rail layout (for Hyprland half-screen tile or collapsed sidebar)
    Item {
        anchors.fill: parent
        visible: root.compact

        Icon {
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: root.count > 0 ? -2 : 0
            anchors.verticalCenterOffset: root.count > 0 ? 1 : 0
            name: root.icon
            size: 19
            fill: root.active ? 1 : 0
            color: root.active ? Theme.sheetInk : Theme.sheetInkVariant
        }

        Rectangle {
            visible: root.count > 0
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 1
            anchors.topMargin: 1
            implicitWidth: Math.max(15, compactCount.implicitWidth + 6)
            implicitHeight: 14
            radius: 7
            color: Theme.accentFill
            border.width: Theme.glass ? 0 : 1
            border.color: Theme.solidSurface

            Label {
                id: compactCount

                anchors.centerIn: parent
                text: root.count > 99 ? "99" : root.count
                color: Theme.accentFillInk
                font.pixelSize: 9
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

    Loader {
        active: root.compact && area.containsMouse
        sourceComponent: Tooltip {
            parent: root
            text: root.count > 0 ? `${root.text} (${root.count})` : root.text
        }
    }
}
