import QtQuick
import qs.services

// A Material Symbols Rounded glyph, drawn the way Caelestia draws its icons:
// the system's hinted renderer (crisp at small sizes, where Qt's default
// smears), the optical size matched to the pixel size, and a lighter grade on
// dark themes.
//
// The glyph fills a size × size box and is centred by the font's own
// alignment. Measured on the real display (2026-11-21, 24 icons at the sizes
// buttons use): this lands the ink within 1 px of centre, while centring the
// TextMetrics ink box left icons 2–5 px high, because the hinted glyph that's
// drawn doesn't match the metrics measured for it.
Item {
    id: root

    property string name
    property real fill: 0
    property int size: 22
    property int weight: 400
    property color color: Theme.m3onSurfaceVariant

    implicitWidth: size
    implicitHeight: size

    Text {
        anchors.fill: parent
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        text: root.name
        color: root.color
        renderType: Text.NativeRendering
        font.family: Theme.iconFont
        font.pixelSize: root.size
        font.variableAxes: ({
                "FILL": root.fill,
                "wght": root.weight,
                "GRAD": Theme.dark ? -25 : 0,
                "opsz": Math.min(48, Math.max(20, root.size))
            })
    }
}
