import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Teach fields, beside the open email: its template's name, the text you
// just selected and a name for it (or a suggestion: Repo, PR, Title…), the
// fields so far with their value here, and the template's other emails read
// with them as you go. Nothing is kept until Save.
GlassPane {
    id: root

    readonly property var draft: Inbox.teachDraft
    readonly property var pick: Inbox.teachPick
    readonly property var preview: Inbox.teachPreview
    readonly property var names: (draft?.fields ?? []).map(f => f.name)
    // The field a selection goes to, and how.
    property string fieldName: ""
    property bool asList: false
    property bool asLink: false
    property bool optional: false

    // A new selection suggests how to keep it: a row's text as a list, a
    // link's address for "Link".
    onPickChanged: {
        if (!pick)
            return;
        asList = pick.repeats;
        asLink = pick.link !== "" && /link|url/i.test(fieldName);
    }

    function valueText(value): string {
        const items = Inbox.asList(value);
        if (items.length === 0)
            return "—";
        return typeof value === "string" || items.length === 1 ? items[0] : `${items.length}: ${items.join(", ")}`;
    }

    // One email's fields, in a line.
    function summary(row): string {
        if (row.status === "reteach")
            return `Needs re-teaching: can't find ${row.missing.join(", ")}`;
        if (row.status === "new")
            return "";
        return (draft?.fields ?? []).map(f => row.values[f.name] === undefined ? `${f.name} —` : `${f.name} ${valueText(row.values[f.name])}`).join("  ·  ");
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Icon {
                name: "dataset"
                size: 24
                color: Theme.m3primary
            }

            Label {
                Layout.fillWidth: true
                text: "Teach fields"
                font.pixelSize: 20
                weight: Font.Medium
            }

            IconButton {
                icon: "close"
                tip: Inbox.teachDirty ? "Close without saving" : "Close"
                onClicked: Inbox.stopTeaching()
            }
        }

        FormField {
            Layout.fillWidth: true
            text: root.draft?.name ?? ""
            hint: "This template's name"
            onAccepted: Inbox.teachRename(text)
            onTextChanged: if (root.draft && text !== root.draft.name) Inbox.teachRename(text)
        }

        Label {
            Layout.fillWidth: true
            text: root.draft ? `${Inbox.teachCount} emails from ${root.draft.sender} are made like this one. Teaching on its ${root.draft.surface === "html" ? "designed version" : "text"}.` : (Inbox.teachBusy ? "Reading emails like this one…" : "")
            wrapMode: Text.Wrap
            color: Theme.m3onSurfaceVariant
            font.pixelSize: 12
        }

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: body.implicitHeight
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: body

                width: parent.width
                spacing: 12

                // The selection, and where it goes.
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: picker.implicitHeight + 28
                    radius: 18
                    color: Theme.m3surfaceContainer

                    ColumnLayout {
                        id: picker

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 10

                        Label {
                            Layout.fillWidth: true
                            text: root.pick ? (root.pick.subject ? "Selected in the subject" : "Selected") : "Select text in the email or its subject"
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                            weight: Font.Medium
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            visible: root.pick !== null
                            implicitHeight: picked.implicitHeight + 16
                            radius: 10
                            color: Theme.alpha(Theme.m3primary, 0.14)

                            Label {
                                id: picked

                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.margins: 10
                                text: root.pick?.value ?? ""
                                wrapMode: Text.WrapAnywhere
                                maximumLineCount: 3
                                elide: Text.ElideRight
                                font.pixelSize: 14
                            }
                        }

                        FormField {
                            id: nameField

                            Layout.fillWidth: true
                            hint: "Field name (Repo, PR, Author…)"
                            onTextChanged: {
                                root.fieldName = text;
                                if (root.pick && root.pick.link !== "" && /link|url/i.test(text))
                                    root.asLink = true;
                            }
                            onAccepted: addButton.clicked()
                        }

                        // Suggestions, then fields already taught (another
                        // example of one, from this email).
                        Flow {
                            Layout.fillWidth: true
                            spacing: 6

                            Repeater {
                                model: [...root.names, ...Inbox.teachSuggestions.filter(s => !root.names.some(n => n.toLowerCase() === s.toLowerCase()))]

                                delegate: Chip {
                                    required property var modelData

                                    text: modelData
                                    selected: root.fieldName.toLowerCase() === modelData.toLowerCase()
                                    onClicked: nameField.text = modelData
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 16

                            RowLayout {
                                spacing: 8

                                CheckBox {
                                    checked: root.asList
                                    tip: "The selection is one row of a list (commits, jobs): read every row"
                                    onToggled: root.asList = !root.asList
                                }

                                Label {
                                    text: "Every row"
                                    font.pixelSize: 13
                                }
                            }

                            RowLayout {
                                spacing: 8
                                opacity: root.pick?.link ? 1 : 0.4

                                CheckBox {
                                    checked: root.asLink && (root.pick?.link ?? "") !== ""
                                    tip: "Keep the address the selection links to, not its words"
                                    onToggled: if (root.pick?.link) root.asLink = !root.asLink
                                }

                                Label {
                                    text: "Link address"
                                    font.pixelSize: 13
                                }
                            }

                            RowLayout {
                                spacing: 8

                                CheckBox {
                                    checked: root.optional
                                    tip: "Not every email has it: missing doesn't mean the template changed"
                                    onToggled: root.optional = !root.optional
                                }

                                Label {
                                    text: "Optional"
                                    font.pixelSize: 13
                                }
                            }
                        }

                        Pill {
                            id: addButton

                            Layout.alignment: Qt.AlignRight
                            style: "filled"
                            icon: root.names.some(n => n.toLowerCase() === root.fieldName.trim().toLowerCase()) ? "add_task" : "add"
                            text: root.names.some(n => n.toLowerCase() === root.fieldName.trim().toLowerCase()) ? "Add example" : "Add field"
                            opacity: root.pick && root.fieldName.trim() !== "" ? 1 : 0.4
                            onClicked: {
                                if (!root.pick || root.fieldName.trim() === "")
                                    return;
                                Inbox.teachAdd(root.fieldName, { list: root.asList, link: root.asLink && root.pick.link !== "", optional: root.optional });
                                nameField.text = "";
                                root.asList = false;
                                root.asLink = false;
                                root.optional = false;
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            visible: Inbox.teachError !== ""
                            text: Inbox.teachError
                            wrapMode: Text.Wrap
                            color: Theme.m3error
                            font.pixelSize: 13
                        }
                    }
                }

                // The fields so far, with their value in this email.
                Label {
                    Layout.topMargin: 4
                    visible: root.names.length > 0
                    text: "Fields"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                    weight: Font.Medium
                }

                Repeater {
                    model: root.draft?.fields ?? []

                    delegate: Rectangle {
                        id: fieldRow

                        required property var modelData
                        readonly property var learned: (root.preview?.fields ?? []).find(f => f.name === modelData.name) ?? null
                        property bool renaming: false

                        Layout.fillWidth: true
                        implicitHeight: fieldColumn.implicitHeight + 20
                        radius: 14
                        color: Theme.m3surfaceContainer

                        ColumnLayout {
                            id: fieldColumn

                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 14
                            anchors.rightMargin: 6
                            spacing: 2

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Label {
                                    visible: !fieldRow.renaming
                                    text: fieldRow.modelData.name
                                    font.pixelSize: 14
                                    weight: Font.Medium
                                }

                                FormField {
                                    id: renameField

                                    Layout.fillWidth: true
                                    visible: fieldRow.renaming
                                    implicitHeight: 34
                                    hint: "New name"
                                    onAccepted: {
                                        if (text.trim() !== "" && !root.names.includes(text.trim()))
                                            Inbox.teachEdit(fieldRow.modelData.name, { name: text.trim() });
                                        fieldRow.renaming = false;
                                    }
                                }

                                Label {
                                    visible: !fieldRow.renaming
                                    text: [fieldRow.modelData.list ? "every row" : "", fieldRow.modelData.link ? "link" : "", fieldRow.modelData.subject ? "subject" : "", fieldRow.modelData.examples.length > 1 ? `${fieldRow.modelData.examples.length} examples` : ""].filter(t => t).join(" · ")
                                    color: Theme.m3onSurfaceVariant
                                    font.pixelSize: 12
                                }

                                Item {
                                    Layout.fillWidth: true
                                    visible: !fieldRow.renaming
                                }

                                IconButton {
                                    icon: fieldRow.renaming ? "check" : "edit"
                                    size: 30
                                    tip: "Rename"
                                    onClicked: {
                                        if (fieldRow.renaming) {
                                            renameField.accepted();
                                            return;
                                        }
                                        renameField.text = fieldRow.modelData.name;
                                        fieldRow.renaming = true;
                                    }
                                }

                                IconButton {
                                    icon: "delete"
                                    size: 30
                                    tip: "Delete this field"
                                    onClicked: Inbox.teachEdit(fieldRow.modelData.name, null)
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Label {
                                    Layout.fillWidth: true
                                    readonly property bool problem: fieldRow.learned !== null && (!fieldRow.learned.learned || (fieldRow.learned.missing && !fieldRow.modelData.optional))
                                    text: fieldRow.learned === null ? "…" : !fieldRow.learned.learned ? "Couldn't learn this from that selection: select it again" : fieldRow.learned.missing ? "Not found in this email: select it here, or tick Optional" : `Here: ${root.valueText(fieldRow.learned.value)}`
                                    elide: Text.ElideRight
                                    color: problem ? Theme.m3error : Theme.m3onSurfaceVariant
                                    font.pixelSize: 13
                                }

                                // Optional: missing in an email isn't a change of template.
                                CheckBox {
                                    checked: fieldRow.modelData.optional
                                    tip: "Optional: not every email has it, so missing doesn't mean re-teaching"
                                    onToggled: Inbox.teachEdit(fieldRow.modelData.name, { optional: !fieldRow.modelData.optional })
                                }

                                Label {
                                    text: "Optional"
                                    color: Theme.m3onSurfaceVariant
                                    font.pixelSize: 12
                                }
                            }
                        }
                    }
                }

                // The template's other emails, read with the fields so far.
                RowLayout {
                    Layout.topMargin: 6
                    Layout.fillWidth: true
                    visible: (root.preview?.rows ?? []).length > 0

                    Label {
                        Layout.fillWidth: true
                        text: root.names.length > 0 ? `On ${(root.preview?.rows ?? []).length} emails like this one` : `${(root.preview?.rows ?? []).length} emails like this one`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                        weight: Font.Medium
                    }

                    Label {
                        visible: Inbox.teachBusy
                        text: "Reading…"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }
                }

                Repeater {
                    model: root.preview?.rows ?? []

                    delegate: Rectangle {
                        id: previewRow

                        required property var modelData
                        readonly property bool current: modelData.id === Inbox.openId
                        readonly property bool flagged: modelData.status === "reteach"

                        Layout.fillWidth: true
                        implicitHeight: previewColumn.implicitHeight + 16
                        radius: 12
                        color: current ? Theme.alpha(Theme.m3primary, 0.12) : previewArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.06) : "transparent"

                        ColumnLayout {
                            id: previewColumn

                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 2

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Icon {
                                    visible: previewRow.flagged || previewRow.modelData.status === "ok"
                                    name: previewRow.flagged ? "warning" : "check_circle"
                                    size: 16
                                    color: previewRow.flagged ? Theme.m3error : Theme.m3primary
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: previewRow.modelData.subject
                                    elide: Text.ElideRight
                                    font.pixelSize: 13
                                    weight: previewRow.current ? Font.Medium : Font.Normal
                                }

                                Label {
                                    text: Inbox.whenText(previewRow.modelData.epoch)
                                    color: Theme.m3onSurfaceVariant
                                    font.pixelSize: 11
                                }
                            }

                            Label {
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: root.summary(previewRow.modelData)
                                elide: Text.ElideRight
                                color: previewRow.flagged ? Theme.m3error : Theme.m3onSurfaceVariant
                                font.pixelSize: 12
                            }
                        }

                        MouseArea {
                            id: previewArea

                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Inbox.openMessage(previewRow.modelData.id, true)
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            // Asks once: a template's fields go with it.
            Pill {
                property bool sure: false

                visible: Inbox.teachSaved
                style: "text"
                icon: "delete_forever"
                text: sure ? "Delete it and its fields?" : "Delete template"
                onClicked: {
                    if (!sure) {
                        sure = true;
                        return;
                    }
                    sure = false;
                    Inbox.deleteTemplate(root.draft.id);
                }
            }

            Item {
                Layout.fillWidth: true
            }

            Pill {
                visible: Inbox.teachSaved
                style: "outlined"
                icon: "table_view"
                text: "Table"
                onClicked: Inbox.openTable(root.draft.id)
            }

            Pill {
                style: "filled"
                icon: "save"
                text: Inbox.teachDirty || !Inbox.teachSaved ? "Save" : "Saved"
                opacity: Inbox.teachDirty && root.names.length > 0 ? 1 : 0.4
                onClicked: if (Inbox.teachDirty && root.names.length > 0) Inbox.teachSave()
            }
        }
    }
}
