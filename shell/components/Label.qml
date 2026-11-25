import QtQuick
import qs.services

// Mail text is untrusted: plain text by default, so nothing in a subject or
// name is read as markup (and no remote image ever loads).
Text {
    renderType: Text.NativeRendering
    textFormat: Text.PlainText
    color: Theme.m3onSurface
    font.family: Theme.sans
    font.pixelSize: 14
}
