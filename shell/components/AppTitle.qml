import QtQuick

// An app's title with its icon before it: Pip for Mail, Tab for Calendar.
// The icon is centred on the title's capitals (not its line box, which has
// room for descenders), and the row is exactly the title's height, so
// nothing below it moves. Decorative only: no click, no tooltip, and
// screen readers skip it.
Item {
    id: root

    required property string text
    // A file:// URL to the icon (an SVG).
    required property string icon
    // The icon's drawn size and its gap to the title, in logical pixels. The
    // tile's own margin and the letter's side bearing add 2-3 px, so the
    // gap the eye sees is 11-12 px.
    property int iconSize: 30
    property int gap: 9

    implicitWidth: title.x + title.implicitWidth
    implicitHeight: title.implicitHeight

    // The height of the title's capitals, from an "M" in its font.
    TextMetrics {
        id: capitals

        font: title.font
        text: "M"
    }

    Image {
        width: root.iconSize
        height: root.iconSize
        y: Math.round(title.baselineOffset - capitals.tightBoundingRect.height / 2 - root.iconSize / 2)
        source: root.icon
        // Qt rasterises an SVG at sourceSize times the window's device pixel
        // ratio (checked at 2x: it matches a 60 px render, not a 30 px one
        // scaled up), so this is the drawn size and stays sharp at any scale.
        sourceSize: Qt.size(root.iconSize, root.iconSize)
        fillMode: Image.PreserveAspectFit
        smooth: true
        Accessible.ignored: true
    }

    Label {
        id: title

        x: root.iconSize + root.gap
        text: root.text
        font.pixelSize: 26
        font.weight: Font.Medium
    }
}
