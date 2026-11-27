import QtQuick
import QtQuick.Layouts
import qs.services

// Slim frosted-glass quick reply under an email (42 px base height, down from 58 px).
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

    spacing: 5

    Flow {
        Layout.fillWidth: true
        visible: root.attachments.length > 0
        spacing: 5

        Repeater {
            model: root.attachments

            delegate: Rectangle {
                id: file

                required property string modelData
                required property int index

                height: 26
                width: fileRow.implicitWidth + 14
                radius: 13
                color: Theme.glassActive
                border.width: 1
                border.color: Theme.glassActiveBorder

                Row {
                    id: fileRow

                    x: 8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: file.modelData.split("/").pop()
                        color: Theme.m3onSurface
                        font.pixelSize: 11
                    }

                    IconButton {
                        anchors.verticalCenter: parent.verticalCenter
                        icon: "close"
                        tip: "Remove"
                        size: 18
                        iconColor: Theme.m3onSurface
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
        font.pixelSize: 11
    }

    Rectangle {
        Layout.fillWidth: true
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
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            spacing: 6

            IconButton {
                icon: "add"
                tip: "Open the full reply window"
                size: 30
                cornerRadius: 9
                filled: true
                fillColor: Theme.glassControl
                iconColor: Theme.m3onSurface
                onClicked: Inbox.compose("reply", root.mail.id)
            }

            Flickable {
                id: page

                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(120, input.implicitHeight)
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
                    font.pixelSize: 14
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
                        font.pixelSize: 13
                    }
                }
            }

            IconButton {
                id: emojiButton

                icon: "mood"
                tip: "Emoji"
                size: 30
                filled: picker.visible
                fillColor: Theme.glassActive
                onClicked: picker.visible = !picker.visible
            }

            IconButton {
                icon: "attach_file"
                tip: "Attach files"
                size: 30
                onClicked: Inbox.pickFiles(paths => root.attachments = root.attachments.concat(paths))
            }

            IconButton {
                icon: Inbox.sending ? "hourglass_top" : "send"
                tip: "Send (Ctrl+Enter)"
                size: 32
                cornerRadius: 10
                filled: true
                fillColor: Theme.pill
                iconColor: Theme.pillInk
                onClicked: root.send()
            }
        }

        Rectangle {
            id: picker

            visible: false
            anchors.right: parent.right
            anchors.rightMargin: 44
            anchors.bottom: parent.top
            anchors.bottomMargin: 6
            width: grid.implicitWidth + 16
            height: grid.implicitHeight + 16
            radius: 13
            color: Theme.m3popupHigh
            border.width: 1
            border.color: Theme.glassPopupBorder
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

                        width: 32
                        height: 32
                        radius: 8
                        color: emojiArea.containsMouse ? Theme.glassControlHover : "transparent"

                        Text {
                            anchors.centerIn: parent
                            text: parent.modelData
                            font.pixelSize: 18
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
