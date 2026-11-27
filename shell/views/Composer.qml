import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Slim frosted-glass chat reply composer. Enter sends, Shift+Enter adds a line.
Rectangle {
    id: root

    property string recipient

    function send(): void {
        Inbox.send(input.text);
        input.text = "";
    }

    implicitHeight: Math.max(48, input.implicitHeight + 24)
    radius: Theme.rowRadius
    color: input.activeFocus ? Theme.glassControlHover : Theme.glassControl
    border.width: Theme.glass ? 0 : 1
    border.color: input.activeFocus ? Theme.alpha(Theme.m3primary, 0.72) : Theme.glassBorder

    Behavior on color {
        ColorAnimation {
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
    }

    GlassEdge {
        visible: Theme.glass
        radius: Theme.rowRadius
        fade: 9
        side: false
        light: Theme.alpha(Theme.pureWhite, Theme.dark ? 0.18 : 0.24)
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 8
        spacing: 8

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            TextEdit {
                id: input

                renderType: Text.NativeRendering
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.m3onSurface
                selectionColor: Theme.m3primary
                selectedTextColor: Theme.m3onPrimary
                font.family: Theme.sans
                font.pixelSize: 14
                wrapMode: TextEdit.Wrap
                Keys.onReturnPressed: event => {
                    if (event.modifiers & Qt.ShiftModifier) {
                        event.accepted = false;
                    } else {
                        root.send();
                    }
                }

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: input.text === ""
                    text: `Reply to ${root.recipient.split(" ")[0]}…`
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }
            }
        }

        AccountTag {
            visible: root.width >= 320
            account: Inbox.selected?.account ?? "personal"
        }

        IconButton {
            icon: "send"
            tip: "Send (Enter; Shift+Enter for a new line)"
            filled: true
            fillColor: Theme.pill
            iconColor: Theme.pillInk
            size: 32
            cornerRadius: 10
            onClicked: root.send()
        }
    }
}
