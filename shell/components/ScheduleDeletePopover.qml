import QtQuick
import QtQuick.Layouts
import qs.services

// Reader popover for scheduling per-thread deletion ("Delete after 2 years",
// optional short note like "college", or an explicit YYYY-MM-DD date).
Item {
    id: root

    property var mail: null
    property string selectedPreset: "2y"
    property bool customMode: false
    property string errorText: ""

    readonly property var presets: [
        { key: "7d", label: "7 days" },
        { key: "30d", label: "30 days" },
        { key: "6m", label: "6 months" },
        { key: "1y", label: "1 year" },
        { key: "2y", label: "2 years" }
    ]

    function show(anchor: Item, mailItem: var): void {
        mail = mailItem;
        errorText = "";
        customMode = false;
        selectedPreset = "2y";
        noteField.text = mailItem?.expiry?.note ?? "";
        customDateField.text = "";
        const at = anchor.mapToItem(root, 0, 0);
        const cardW = card.width;
        const cardH = Math.max(300, card.implicitHeight);
        card.x = Math.max(12, Math.min(at.x + anchor.width - cardW, root.width - cardW - 12));
        const below = at.y + anchor.height + 8;
        card.y = below + cardH > root.height - 12 ? Math.max(12, at.y - cardH - 8) : below;
        visible = true;
    }

    function showCentered(mailItem: var): void {
        mail = mailItem;
        errorText = "";
        customMode = false;
        selectedPreset = "2y";
        noteField.text = mailItem?.expiry?.note ?? "";
        customDateField.text = "";
        const cardW = card.width;
        const cardH = Math.max(300, card.implicitHeight);
        card.x = Math.max(12, Math.round((root.width - cardW) / 2));
        card.y = Math.max(24, Math.min(Math.round((root.height - cardH) * 0.35), root.height - cardH - 24));
        visible = true;
    }

    function close(): void {
        visible = false;
        errorText = "";
    }

    function submit(): void {
        if (!mail)
            return;
        const targetId = mail.threadId || mail.id;
        const spec = customMode ? customDateField.text.trim() : selectedPreset;
        if (customMode && !/^\d{4}-\d{2}-\d{2}$/.test(spec)) {
            errorText = "Enter a date as YYYY-MM-DD (e.g. 2028-11-27).";
            return;
        }
        errorText = "";
        Inbox.scheduleDelete(targetId, spec, noteField.text.trim(), customMode, (ok, res) => {
            if (ok)
                close();
            else
                errorText = res?.error ?? "Couldn't schedule deletion.";
        });
    }

    visible: false
    z: 120

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onPressed: root.close()
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.visible
        onActivated: root.close()
    }

    Rectangle {
        id: card

        width: 348
        implicitHeight: layout.implicitHeight + 28
        height: implicitHeight
        radius: 16
        color: Theme.m3popupHigh
        border.width: 1
        border.color: Theme.glassPopupBorder

        MouseArea {
            anchors.fill: parent
        }

        ColumnLayout {
            id: layout

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 14
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Icon {
                    name: "auto_delete"
                    size: 19
                    color: Theme.m3primary
                }

                Label {
                    Layout.fillWidth: true
                    text: "Schedule delete"
                    font.pixelSize: 15
                    weight: Font.DemiBold
                }

                IconButton {
                    icon: "close"
                    size: 28
                    tip: "Close"
                    onClicked: root.close()
                }
            }

            // Existing schedule summary, if any.
            Rectangle {
                Layout.fillWidth: true
                visible: (root.mail?.expiry ?? null) !== null
                implicitHeight: currentRow.implicitHeight + 14
                radius: Theme.controlRadius
                color: Theme.m3tertiaryContainer

                RowLayout {
                    id: currentRow

                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 8
                    spacing: 8

                    Label {
                        Layout.fillWidth: true
                        text: {
                            const exp = root.mail?.expiry;
                            if (!exp)
                                return "";
                            const kind = exp.is_rule ? "Auto-delete" : "Scheduled";
                            const date = (exp.expires_at ?? "").slice(0, 10);
                            return `${kind}: ${date} (${exp.remaining})`;
                        }
                        elide: Text.ElideRight
                        color: Theme.m3onTertiaryContainer
                        font.pixelSize: 12
                        weight: Font.Medium
                    }

                    Pill {
                        style: "text"
                        text: "Cancel"
                        size: 26
                        fontSize: 12
                        onClicked: {
                            Inbox.cancelExpiry(root.mail.threadId || root.mail.id, ok => {
                                if (ok)
                                    root.close();
                            });
                        }
                    }
                }
            }

            Label {
                text: "Delete this thread after"
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 12
                weight: Font.Medium
            }

            Flow {
                Layout.fillWidth: true
                spacing: 6

                Repeater {
                    model: root.presets

                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool chosen: !root.customMode && root.selectedPreset === modelData.key

                        width: presetLabel.implicitWidth + 22
                        height: 30
                        radius: 15
                        color: chosen
                            ? Theme.pill
                            : (presetArea.containsMouse ? Theme.glassControlHover : Theme.glassControl)

                        Label {
                            id: presetLabel

                            anchors.centerIn: parent
                            text: modelData.label
                            color: parent.chosen ? Theme.pillInk : Theme.m3onSurface
                            font.pixelSize: 12
                            weight: parent.chosen ? Font.Medium : Font.Normal
                        }

                        MouseArea {
                            id: presetArea

                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                root.customMode = false;
                                root.selectedPreset = modelData.key;
                                root.errorText = "";
                            }
                        }
                    }
                }

                Rectangle {
                    readonly property bool chosen: root.customMode

                    width: customLabel.implicitWidth + 22
                    height: 30
                    radius: 15
                    color: chosen
                        ? Theme.pill
                        : (customArea.containsMouse ? Theme.glassControlHover : Theme.glassControl)

                    Label {
                        id: customLabel

                        anchors.centerIn: parent
                        text: "Custom date"
                        color: parent.chosen ? Theme.pillInk : Theme.m3onSurface
                        font.pixelSize: 12
                        weight: parent.chosen ? Font.Medium : Font.Normal
                    }

                    MouseArea {
                        id: customArea

                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.customMode = true;
                            root.errorText = "";
                        }
                    }
                }
            }

            FormField {
                id: customDateField

                Layout.fillWidth: true
                visible: root.customMode
                implicitHeight: 36
                hint: "YYYY-MM-DD (e.g. 2028-11-27)"
                onAccepted: root.submit()
            }

            FormField {
                id: noteField

                Layout.fillWidth: true
                implicitHeight: 36
                hint: "Optional note (e.g. college, receipt)"
                onAccepted: root.submit()
            }

            Label {
                Layout.fillWidth: true
                visible: root.errorText !== ""
                text: root.errorText
                wrapMode: Text.Wrap
                color: Theme.m3error
                font.pixelSize: 12
            }

            Label {
                Layout.fillWidth: true
                text: "Moves to Trash automatically — recoverable in Gmail for 30 days."
                wrapMode: Text.Wrap
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 11
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Item {
                    Layout.fillWidth: true
                }

                Pill {
                    style: "text"
                    text: "Close"
                    size: 32
                    fontSize: 13
                    onClicked: root.close()
                }

                Pill {
                    style: "filled"
                    icon: "schedule"
                    text: "Schedule"
                    size: 32
                    fontSize: 13
                    onClicked: root.submit()
                }
            }
        }
    }
}
