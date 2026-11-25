import QtQuick
import QtQuick.Layouts
import qs.services

// A quick reply under an email, to whoever Reply would pick. + opens the full
// reply window; the face adds an emoji; the clip attaches files; Ctrl+Enter
// or the arrow sends.
ColumnLayout {
    id: root

    required property var mail
    property var attachments: []
    property string problem: ""
    readonly property string firstName: (mail?.fromName ?? "").split(" ")[0]

    readonly property var emojis: ["👍", "🙏", "🙌", "👏", "🎉", "✅", "❤️", "😊", "😂", "😅", "🤔", "👀", "🔥", "✨", "💯", "🚀", "📌", "📎", "⏰", "📅", "☕", "🙂", "😉", "😍", "😮", "😢", "👋", "💪", "🤝", "👌"]

    function send(): void {
        const text = input.text.trim();
        if (text === "" || Inbox.sending)
            return;
        problem = "";
        Inbox.quickReply(mail.id, text, attachments, reason => {
            if (reason === "") {
                input.text = "";
                attachments = [];
            } else {
                problem = reason;
            }
        });
    }

    spacing: 6

    Flow {
        Layout.fillWidth: true
        visible: root.attachments.length > 0
        spacing: 6

        Repeater {
            model: root.attachments

            delegate: Rectangle {
                id: file

                required property string modelData
                required property int index

                height: 30
                width: fileRow.implicitWidth + 16
                radius: 15
                color: Theme.m3secondaryContainer

                Row {
                    id: fileRow

                    x: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: file.modelData.split("/").pop()
                        color: Theme.m3onSecondaryContainer
                        font.pixelSize: 12
                    }

                    IconButton {
                        anchors.verticalCenter: parent.verticalCenter
                        icon: "close"
                        tip: "Remove"
                        size: 22
                        iconColor: Theme.m3onSecondaryContainer
                        onClicked: root.attachments = root.attachments.filter((_, at) => at !== file.index)
                    }
                }
            }
        }
    }

    Label {
        Layout.fillWidth: true
        visible: root.problem !== ""
        text: root.problem
        wrapMode: Text.Wrap
        color: Theme.m3error
        font.pixelSize: 12
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: Math.max(58, input.implicitHeight + 30)
        radius: 29
        color: Theme.m3surfaceContainerHigh
        border.width: input.activeFocus ? 1.5 : 1
        border.color: input.activeFocus ? Theme.alpha(Theme.m3primary, 0.7) : Theme.m3outlineVariant

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 6
            spacing: 4

            IconButton {
                icon: "add"
                tip: "Open the full reply window"
                size: 38
                filled: true
                fillColor: Theme.m3surfaceContainerHighest
                iconColor: Theme.m3onSurface
                onClicked: Inbox.compose("reply", root.mail.id)
            }

            Flickable {
                id: page

                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(140, input.implicitHeight)
                Layout.leftMargin: 6
                clip: true
                contentHeight: input.implicitHeight
                boundsBehavior: Flickable.StopAtBounds

                TextEdit {
                    id: input

                    width: page.width
                    renderType: Text.NativeRendering
                    wrapMode: TextEdit.Wrap
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 15
                    Keys.onPressed: event => {
                        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
                            root.send();
                            event.accepted = true;
                        }
                    }

                    Label {
                        visible: input.text === ""
                        text: root.firstName ? `Reply to ${root.firstName}…` : "Reply…"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 15
                    }
                }
            }

            IconButton {
                id: emojiButton

                icon: "mood"
                tip: "Emoji"
                size: 38
                filled: picker.visible
                fillColor: Theme.m3secondaryContainer
                onClicked: picker.visible = !picker.visible
            }

            IconButton {
                icon: "attach_file"
                tip: "Attach files"
                size: 38
                onClicked: Inbox.pickFiles(paths => root.attachments = root.attachments.concat(paths))
            }

            IconButton {
                icon: Inbox.sending ? "hourglass_top" : "send"
                tip: "Send (Ctrl+Enter)"
                size: 46
                filled: true
                fillColor: Theme.m3primary
                iconColor: Theme.m3onPrimary
                onClicked: root.send()
            }
        }

        // A few emoji over the bar; a click puts one at the cursor.
        Rectangle {
            id: picker

            visible: false
            anchors.right: parent.right
            anchors.rightMargin: 60
            anchors.bottom: parent.top
            anchors.bottomMargin: 8
            width: grid.implicitWidth + 20
            height: grid.implicitHeight + 20
            radius: 18
            color: Theme.m3popupHigh
            border.width: 1
            border.color: Theme.alpha(Theme.m3outlineVariant, 0.6)
            z: 20

            Grid {
                id: grid

                anchors.centerIn: parent
                columns: 10
                spacing: 2

                Repeater {
                    model: root.emojis

                    delegate: Rectangle {
                        required property string modelData

                        width: 36
                        height: 36
                        radius: 10
                        color: emojiArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent"

                        Text {
                            anchors.centerIn: parent
                            text: parent.modelData
                            font.pixelSize: 20
                            renderType: Text.NativeRendering
                        }

                        MouseArea {
                            id: emojiArea

                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                input.insert(input.cursorPosition, parent.modelData);
                                picker.visible = false;
                                input.forceActiveFocus();
                            }
                        }
                    }
                }
            }
        }
    }
}
