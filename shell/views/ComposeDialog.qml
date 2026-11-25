import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Writing an email: a new one, a reply, a reply to all or a forward. To, Cc
// and Bcc suggest people you write to; Attach opens the file picker; Ctrl+Enter
// sends. Closing keeps what you wrote until you send or discard it.
Item {
    id: root

    readonly property var draft: Inbox.draft
    readonly property string mode: draft?.mode ?? "new"
    // Which draft the fields were last filled from.
    property string loadedKey: ""
    property bool showCopies: false
    property var attachments: []

    // Fills the fields from the draft when a new one opens or its prefill arrives.
    function load(): void {
        const key = draft ? `${draft.mode}|${draft.id}|${draft.loading ? 1 : 0}` : "";
        if (!draft || key === loadedKey)
            return;
        loadedKey = key;
        toField.people = draft.to;
        ccField.people = draft.cc;
        bccField.people = draft.bcc;
        subject.text = draft.subject;
        body.text = draft.body;
        attachments = draft.attachments;
        showCopies = draft.cc.length > 0 || draft.bcc.length > 0;
        Qt.callLater(() => (mode === "new" || mode === "forward") && draft.to.length === 0 ? toField.focusInput() : body.forceActiveFocus());
    }

    // Edits go straight into the draft, so closing never loses them.
    function keep(field: string, value: var): void {
        if (draft)
            draft[field] = value;
    }

    function close(): void {
        toField.flush();
        ccField.flush();
        bccField.flush();
        Inbox.composing = false;
    }

    // The time a send was asked for, kept while the window asks whether to
    // send an email with no text.
    property var pendingAt: null

    // emptyOk: after "Send anyway" (the engine refuses an empty email otherwise).
    function send(at: var, emptyOk: bool): void {
        toField.flush();
        ccField.flush();
        bccField.flush();
        if (toField.people.length + ccField.people.length + bccField.people.length === 0) {
            Inbox.composeError = "Add someone to send it to.";
            toField.focusInput();
            return;
        }
        pendingAt = at ?? null;
        Inbox.sendDraft({
            mode: mode,
            id: draft.id,
            account: draft.account,
            to: toField.people,
            cc: ccField.people,
            bcc: bccField.people,
            subject: subject.text,
            body: body.text,
            attachments: attachments,
            emptyOk: emptyOk === true
        }, at ?? null);
    }

    visible: Inbox.composing && draft !== null
    z: 95

    onVisibleChanged: if (visible)
        load()

    Connections {
        target: Inbox

        function onDraftChanged(): void {
            if (root.visible)
                root.load();
            if (!Inbox.draft)
                root.loadedKey = "";
        }
    }

    Shortcut {
        sequences: ["Ctrl+Return", "Ctrl+Enter"]
        enabled: root.visible
        onActivated: root.send(null, false)
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.visible
        onActivated: root.close()
    }

    // The scrim: a click outside closes, keeping the draft.
    Rectangle {
        anchors.fill: parent
        radius: 28
        color: Theme.alpha("#000000", 0.45)

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: root.close()
            onWheel: wheel => wheel.accepted = true
        }
    }

    Rectangle {
        id: card

        anchors.centerIn: parent
        width: Math.min(780, parent.width - 48)
        height: Math.min(parent.height - 48, 760)
        radius: 28
        color: Theme.m3popup

        MouseArea {
            anchors.fill: parent
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 8

                Label {
                    Layout.fillWidth: true
                    text: ({ new: "New email", reply: "Reply", replyall: "Reply all", forward: "Forward" })[root.mode] ?? "New email"
                    font.pixelSize: 22
                    font.weight: Font.Medium
                }

                // Which account sends it, when there's more than one: each
                // with its picture.
                Repeater {
                    model: Inbox.accounts.length > 1 ? Inbox.accounts : []

                    delegate: AccountChip {
                        required property var modelData

                        account: modelData.id
                        selected: (root.draft?.account ?? "") === modelData.id
                        onClicked: {
                            root.keep("account", modelData.id);
                            Inbox.draft = Object.assign({}, Inbox.draft);
                        }
                    }
                }

                IconButton {
                    icon: "close"
                    tip: "Close (Esc); your draft stays until you send or discard it"
                    size: 38
                    onClicked: root.close()
                }
            }

            // Raised while suggesting, so the list draws over the fields below.
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                z: toField.suggesting ? 10 : 0

                RecipientField {
                    id: toField

                    Layout.fillWidth: true
                    label: "To"
                    onEdited: people => root.keep("to", people)
                }

                Label {
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 13
                    visible: !root.showCopies
                    text: "Cc  Bcc"
                    color: Theme.m3primary
                    font.weight: Font.Medium

                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -6
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.showCopies = true;
                            ccField.focusInput();
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: Theme.m3outlineVariant
            }

            RecipientField {
                id: ccField

                Layout.fillWidth: true
                visible: root.showCopies
                label: "Cc"
                onEdited: people => root.keep("cc", people)
            }

            Rectangle {
                Layout.fillWidth: true
                visible: root.showCopies
                implicitHeight: 1
                color: Theme.m3outlineVariant
            }

            RecipientField {
                id: bccField

                Layout.fillWidth: true
                visible: root.showCopies
                label: "Bcc"
                onEdited: people => root.keep("bcc", people)
            }

            Rectangle {
                Layout.fillWidth: true
                visible: root.showCopies
                implicitHeight: 1
                color: Theme.m3outlineVariant
            }

            TextInput {
                id: subject

                Layout.fillWidth: true
                Layout.preferredHeight: 46
                verticalAlignment: TextInput.AlignVCenter
                renderType: Text.NativeRendering
                color: Theme.m3onSurface
                selectionColor: Theme.m3primary
                selectedTextColor: Theme.m3onPrimary
                font.family: Theme.sans
                font.pixelSize: 15
                font.weight: Font.Medium
                clip: true
                onTextChanged: root.keep("subject", text)
                Keys.onReturnPressed: body.forceActiveFocus()

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: subject.text === ""
                    text: "Subject"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 15
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: Theme.m3outlineVariant
            }

            Flickable {
                id: page

                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.topMargin: 10
                clip: true
                contentHeight: body.implicitHeight
                boundsBehavior: Flickable.StopAtBounds

                MouseArea {
                    width: page.width
                    height: Math.max(page.height, body.implicitHeight)
                    cursorShape: Qt.IBeamCursor
                    onClicked: body.forceActiveFocus()
                }

                TextEdit {
                    id: body

                    width: page.width
                    renderType: Text.NativeRendering
                    wrapMode: TextEdit.Wrap
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 15
                    selectByMouse: true
                    onTextChanged: {
                        root.keep("body", text);
                        Inbox.composeEmpty = false;
                    }
                    // Keeps the caret in view while typing a long email.
                    onCursorRectangleChanged: {
                        if (cursorRectangle.y < page.contentY)
                            page.contentY = cursorRectangle.y;
                        else if (cursorRectangle.y + cursorRectangle.height > page.contentY + page.height)
                            page.contentY = cursorRectangle.y + cursorRectangle.height - page.height;
                    }

                    Label {
                        visible: body.text === ""
                        text: root.mode === "new" ? "Write your email" : root.mode === "forward" ? "Add a note (optional)" : "Write your reply"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 15
                    }
                }
            }

            // What goes along: the original under a reply or forward, and files.
            Label {
                Layout.fillWidth: true
                Layout.topMargin: 6
                visible: root.mode !== "new" && !(root.draft?.loading ?? false)
                text: root.mode === "forward"
                    ? `The original email goes below your note${(root.draft?.forwarded ?? []).length > 0 ? `, with its ${(root.draft?.forwarded ?? []).length === 1 ? "attachment" : (root.draft?.forwarded ?? []).length + " attachments"}` : ""}.`
                    : "The email you're answering is quoted below your reply."
                wrapMode: Text.Wrap
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 12
            }

            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 6
                visible: root.attachments.length > 0 || (root.draft?.forwarded ?? []).length > 0
                spacing: 8

                Repeater {
                    model: root.draft?.forwarded ?? []

                    delegate: Rectangle {
                        required property string modelData

                        height: 34
                        width: forwardedRow.implicitWidth + 24
                        radius: 17
                        color: Theme.m3surfaceContainerHighest

                        Row {
                            id: forwardedRow

                            anchors.centerIn: parent
                            spacing: 6

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: "attach_file"
                                size: 16
                            }

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                text: parent.parent.modelData
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 13
                            }
                        }
                    }
                }

                Repeater {
                    model: root.attachments

                    delegate: Rectangle {
                        id: file

                        required property string modelData
                        required property int index

                        height: 34
                        width: fileRow.implicitWidth + 18
                        radius: 17
                        color: Theme.m3secondaryContainer

                        Row {
                            id: fileRow

                            x: 12
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: "attach_file"
                                size: 16
                                color: Theme.m3onSecondaryContainer
                            }

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                text: file.modelData.split("/").pop()
                                color: Theme.m3onSecondaryContainer
                                font.pixelSize: 13
                                font.weight: Font.Medium
                            }

                            IconButton {
                                anchors.verticalCenter: parent.verticalCenter
                                icon: "close"
                                tip: "Remove"
                                size: 22
                                iconColor: Theme.m3onSecondaryContainer
                                onClicked: {
                                    root.attachments = root.attachments.filter((_, at) => at !== file.index);
                                    root.keep("attachments", root.attachments);
                                }
                            }
                        }
                    }
                }
            }

            // Sending an email with no text: asked, never by accident.
            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 6
                visible: Inbox.composeEmpty
                implicitHeight: emptyRow.implicitHeight + 16
                radius: 16
                color: Theme.m3secondaryContainer

                RowLayout {
                    id: emptyRow

                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 8
                    spacing: 8

                    Icon {
                        name: "edit_off"
                        size: 20
                        color: Theme.m3onSecondaryContainer
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "This email has no text."
                        color: Theme.m3onSecondaryContainer
                        font.weight: Font.Medium
                    }

                    Pill {
                        style: "text"
                        text: "Keep writing"
                        onClicked: {
                            Inbox.composeEmpty = false;
                            body.forceActiveFocus();
                        }
                    }

                    Pill {
                        style: "filled"
                        text: "Send anyway"
                        onClicked: root.send(root.pendingAt, true)
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                Layout.topMargin: 6
                visible: Inbox.composeError !== ""
                text: Inbox.composeError
                wrapMode: Text.Wrap
                color: Theme.m3error
                font.pixelSize: 13
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 10
                spacing: 8

                Pill {
                    style: "filled"
                    icon: Inbox.sending ? "hourglass_top" : "send"
                    text: Inbox.sending ? "Sending…" : "Send"
                    tip: "Send (Ctrl+Enter)"
                    onClicked: root.send(null, false)
                }

                IconButton {
                    icon: "attach_file"
                    tip: "Attach files"
                    onClicked: Inbox.pickFiles(paths => {
                        root.attachments = root.attachments.concat(paths);
                        root.keep("attachments", root.attachments);
                    })
                }

                Item {
                    Layout.fillWidth: true
                }

                Label {
                    visible: root.draft?.loading ?? false
                    text: "Filling in who it goes to…"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }

                IconButton {
                    icon: "delete"
                    tip: "Discard this draft"
                    onClicked: Inbox.discardDraft()
                }
            }
        }
    }
}
