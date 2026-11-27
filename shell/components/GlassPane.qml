import QtQuick
import Quickshell
import qs.services

// A pane of Junco's window. In glass mode the window is one clear sheet
// (shell.qml) and a pane is either:
//   - a raised glass card (`card: true`, the list and the reader): neutral
//     white at low alpha, so its colour comes from the wallpaper behind it,
//     with 16 px corners, no outline: light entering its top and left edge
//     (GlassEdge) and a soft low static shadow; or
//   - part of the sheet (`card: false`, the sidebar): no edge or shadow,
//     only its `fill` (the sidebar's smoked glass).
// The shadow is a pre-rendered 9-slice image (tools/make_glass_assets.py)
// with the card's own shape cut out, so it never greys the translucent card
// and costs no shader. In solid mode panes are flat and joined by 1 px
// dividers.
Rectangle {
    id: root

    property color fill: Theme.glassCardPane
    property bool card: true
    property bool dividerRight: false
    property bool dividerLeft: false

    readonly property bool raised: Theme.glass && card

    radius: raised ? Theme.cardPaneRadius : 0
    color: fill
    border.width: 0

    BorderImage {
        visible: root.raised
        z: -1
        anchors.fill: parent
        anchors.margins: -12
        source: `file://${Quickshell.shellDir}/../assets/glass/card-shadow.png`
        border.left: 28
        border.right: 28
        border.top: 28
        border.bottom: 28
        horizontalTileMode: BorderImage.Stretch
        verticalTileMode: BorderImage.Stretch
        smooth: true
    }

    // Above the fill, below the pane's content.
    GlassEdge {
        visible: root.raised
        radius: root.radius
    }

    // Solid mode: 1 px dividers between adjacent flat panes.
    Rectangle {
        visible: root.dividerRight && !Theme.glass
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: 1
        color: Theme.glassDivider
        z: 10
    }

    Rectangle {
        visible: root.dividerLeft && !Theme.glass
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        width: 1
        color: Theme.glassDivider
        z: 10
    }
}
