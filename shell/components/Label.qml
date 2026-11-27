import QtQuick
import qs.services

// Mail text is untrusted: plain text by default, so nothing in a subject or
// name is read as markup (and no remote image ever loads).
//
// Uses Adwaita Sans (Inter Variable) with optical `wght` variable axes at
// font.weight: Font.Normal (Regular 400, Medium 500, SemiBold 600), subtle
// negative tracking keyed off `weight` (avoiding grouped `font.*` binding
// loops), and optional `tabular: true` for aligned timestamps, counts, and dates.
Text {
    property int weight: Font.Normal
    property bool tabular: false

    renderType: Text.NativeRendering
    textFormat: Text.PlainText
    color: Theme.m3onSurface
    font.family: Theme.sans
    font.pixelSize: 14
    font.weight: Font.Normal
    font.variableAxes: weight > Font.Normal
        ? ({ "wght": weight >= Font.DemiBold ? Theme.weightHeading : Theme.weightMedium })
        : ({})
    font.features: tabular ? ({ "tnum": 1 }) : ({})
    font.letterSpacing: weight >= Font.DemiBold ? -0.28 : (weight >= Font.Medium ? -0.1 : 0)
}
