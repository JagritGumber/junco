import QtQuick
import qs.services

// A compact one-line text field on a frosted surface, with a hint while empty.
Rectangle {
    id: root

    property alias text: input.text
    property string hint: ""

    signal accepted

    implicitHeight: 34
    radius: Theme.controlRadius
    color: Theme.glassControl
    border.width: 1
    border.color: input.activeFocus ? Theme.alpha(Theme.m3primary, 0.72) : Theme.glassBorderSubtle

    TextInput {
        id: input

        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        verticalAlignment: TextInput.AlignVCenter
        renderType: Text.NativeRendering
        color: Theme.m3onSurface
        selectionColor: Theme.m3primary
        selectedTextColor: Theme.m3onPrimary
        font.family: Theme.sans
        font.pixelSize: 13
        clip: true
        onAccepted: root.accepted()

        Label {
            anchors.verticalCenter: parent.verticalCenter
            visible: input.text === ""
            text: root.hint
            color: Theme.m3onSurfaceVariant
            font.pixelSize: 13
        }
    }
}
