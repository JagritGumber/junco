import QtQuick
import qs.services

// A one-line text field on a rounded surface, with a hint while it's empty.
Rectangle {
    id: root

    property alias text: input.text
    property string hint: ""

    signal accepted

    implicitHeight: 44
    radius: 14
    color: Theme.m3surfaceContainerHighest
    border.width: input.activeFocus ? 1.5 : 0
    border.color: Theme.alpha(Theme.m3primary, 0.7)

    TextInput {
        id: input

        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        verticalAlignment: TextInput.AlignVCenter
        renderType: Text.NativeRendering
        color: Theme.m3onSurface
        selectionColor: Theme.m3primary
        selectedTextColor: Theme.m3onPrimary
        font.family: Theme.sans
        font.pixelSize: 14
        clip: true
        onAccepted: root.accepted()

        Label {
            anchors.verticalCenter: parent.verticalCenter
            visible: input.text === ""
            text: root.hint
            color: Theme.m3onSurfaceVariant
        }
    }
}
