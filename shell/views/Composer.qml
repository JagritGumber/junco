import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Reply like a chat. Enter sends, Shift+Enter adds a line.
Rectangle {
    id: root

    property string recipient

    function send(): void {
        Inbox.send(input.text);
        input.text = "";
    }

    implicitHeight: Math.max(60, input.implicitHeight + 28)
    radius: 30
    color: Theme.m3surfaceContainerHigh

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 22
        anchors.rightMargin: 8
        spacing: 6

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
                font.pixelSize: 15
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
                    font.pixelSize: 15
                }
            }
        }

        AccountTag {
            account: Inbox.selected?.account ?? "personal"
        }

        IconButton {
            icon: "send"
            tip: "Send (Enter; Shift+Enter for a new line)"
            filled: true
            fillColor: Theme.m3primary
            iconColor: Theme.m3onPrimary
            size: 44
            onClicked: root.send()
        }
    }
}
