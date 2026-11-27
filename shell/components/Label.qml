import QtQuick
import qs.services

// Mail text is untrusted: plain text by default, so nothing in a subject or
// name is read as markup (and no remote image ever loads).
//
// Use `weight` (Font.Normal / Font.Medium / Font.DemiBold) instead of
// `font.weight`: Rubik[wght].ttf triggers Qt 6 synthetic/over-heavy bolding
// whenever font.weight > 400, so Label drives the variable `wght` axis at
// font.weight: Font.Normal for crisp, even stroke weights.
Text {
    property int weight: Font.Normal

    renderType: Text.NativeRendering
    textFormat: Text.PlainText
    color: Theme.m3onSurface
    font.family: Theme.sans
    font.pixelSize: 14
    font.weight: Font.Normal
    font.variableAxes: weight > Font.Normal
        ? ({ "wght": weight >= Font.DemiBold ? Theme.weightHeading : Theme.weightMedium })
        : ({})
}
