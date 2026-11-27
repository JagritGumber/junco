import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Settings -> Auto-Expiry: per-provider notification auto-delete rules (all OFF
// by default, Trash action by default, starred threads protected by default)
// plus custom providers and live dry-run match previews, styled as a raised
// frosted-glass pane matching Round 10.
GlassPane {
    id: root

    property bool addingCustom: false
    property string customError: ""
    property bool customNotificationsOnly: true
    property bool customSkipStarred: true
    property string expandedRuleId: ""
    property string editingDaysRuleId: ""
    property string editingDaysText: ""

    readonly property var retentionPresets: [3, 7, 14, 30]
    readonly property int expiringCount: Inbox.folders.find(f => f.id === "expiring")?.count ?? 0
    readonly property int enabledRuleCount: Inbox.expiryRules.filter(r => r.enabled).length

    function saveCustomProvider(): void {
        const name = customNameField.text.trim();
        const senders = customSendersField.text.trim();
        const days = parseInt(customDaysField.text.trim(), 10);
        if (!name) {
            customError = "Give the provider a name.";
            return;
        }
        if (!senders) {
            customError = "Enter a sender address or domain (e.g. alerts@example.com or example.com).";
            return;
        }
        if (isNaN(days) || days < 1 || days > 3650) {
            customError = "Retention days must be between 1 and 3650.";
            return;
        }
        customError = "";
        Inbox.saveExpiryRule({
            display_name: name,
            match_senders: senders,
            retention_days: days,
            notifications_only: customNotificationsOnly,
            skip_starred: customSkipStarred,
            enabled: true,
            action: "trash"
        }, (ok, res) => {
            if (!ok) {
                customError = res?.error ?? "Couldn't save custom provider.";
                return;
            }
            addingCustom = false;
            customNameField.text = "";
            customSendersField.text = "";
            customDaysField.text = "7";
            customNotificationsOnly = true;
            customSkipStarred = true;
        });
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 14

        // Top header bar.
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            IconButton {
                icon: "arrow_back"
                tip: "Back to mail (Esc)"
                size: 34
                onClicked: Inbox.closeSettings()
            }

            ColumnLayout {
                spacing: 2

                RowLayout {
                    spacing: 6

                    Label {
                        text: "Settings"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 18
                        weight: Font.Medium
                    }

                    Icon {
                        name: "chevron_right"
                        size: 18
                        color: Theme.m3onSurfaceVariant
                    }

                    Label {
                        text: "Auto-Expiry"
                        font.pixelSize: 18
                        weight: Font.DemiBold
                    }
                }

                Label {
                    text: root.enabledRuleCount > 0
                        ? `${root.enabledRuleCount} provider rule${root.enabledRuleCount === 1 ? "" : "s"} active · ${root.expiringCount} scheduled thread${root.expiringCount === 1 ? "" : "s"}`
                        : "Automatically clean up notification mail after a set number of days"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }

            Item {
                Layout.fillWidth: true
            }

            Pill {
                visible: root.expiringCount > 0
                style: "tonal"
                icon: "hourglass_empty"
                text: `Scheduled (${root.expiringCount})`
                size: 34
                fontSize: 13
                onClicked: {
                    Inbox.closeSettings();
                    Inbox.openFolder("expiring");
                }
            }

            Pill {
                style: "filled"
                icon: root.addingCustom ? "close" : "add"
                text: root.addingCustom ? "Cancel" : "Add custom provider"
                size: 34
                fontSize: 13
                onClicked: {
                    root.addingCustom = !root.addingCustom;
                    root.customError = "";
                }
            }
        }

        // Safety note banner (no outline, soft glass card fill).
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: safetyRow.implicitHeight + 18
            radius: Theme.cardRadius
            color: Theme.glassCard
            border.width: Theme.glass ? 0 : 1
            border.color: Theme.glassBorderSubtle

            RowLayout {
                id: safetyRow

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: 10

                Icon {
                    name: "shield"
                    size: 18
                    color: Theme.m3primary
                }

                Label {
                    Layout.fillWidth: true
                    text: "Expired threads move to Trash by default (recoverable in Gmail for 30 days). Direct human emails are skipped when notifications-only is on, and starred threads stay protected."
                    wrapMode: Text.Wrap
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }
        }

        // Inline custom provider creator.
        Rectangle {
            Layout.fillWidth: true
            visible: root.addingCustom
            implicitHeight: customForm.implicitHeight + 24
            radius: 14
            color: Theme.glassControl
            border.width: Theme.glass ? 0 : 1
            border.color: Theme.glassBorderSubtle

            GlassEdge {
                visible: Theme.glass
                radius: parent.radius
                side: false
            }

            ColumnLayout {
                id: customForm

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 10

                Label {
                    text: "New custom provider rule"
                    font.pixelSize: 14
                    weight: Font.DemiBold
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    FormField {
                        id: customNameField

                        Layout.preferredWidth: 240
                        implicitHeight: 36
                        hint: "Provider name (e.g. College)"
                    }

                    FormField {
                        id: customSendersField

                        Layout.fillWidth: true
                        implicitHeight: 36
                        hint: "Sender or domain (e.g. notices@college.edu, *.alerts.dev)"
                    }

                    FormField {
                        id: customDaysField

                        Layout.preferredWidth: 104
                        implicitHeight: 36
                        text: "14"
                        hint: "Days"
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14

                    Row {
                        spacing: 6

                        CheckBox {
                            checked: root.customNotificationsOnly
                            tip: "Only match automated notifications (skip direct human emails)"
                            onToggled: root.customNotificationsOnly = !root.customNotificationsOnly
                        }

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Notifications only"
                            font.pixelSize: 12
                            color: Theme.m3onSurface
                        }
                    }

                    Row {
                        spacing: 6

                        CheckBox {
                            checked: root.customSkipStarred
                            tip: "Never auto-delete starred threads"
                            onToggled: root.customSkipStarred = !root.customSkipStarred
                        }

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Skip starred"
                            font.pixelSize: 12
                            color: Theme.m3onSurface
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        visible: root.customError !== ""
                        text: root.customError
                        color: Theme.m3error
                        elide: Text.ElideRight
                        font.pixelSize: 12
                    }

                    Item {
                        Layout.fillWidth: true
                        visible: root.customError === ""
                    }

                    Pill {
                        style: "filled"
                        icon: "check"
                        text: "Save rule"
                        size: 32
                        fontSize: 12
                        onClicked: root.saveCustomProvider()
                    }
                }
            }
        }

        // Scrollable provider list.
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            contentHeight: rulesColumn.implicitHeight + 12

            ColumnLayout {
                id: rulesColumn

                width: parent.width
                spacing: 8

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 24
                    visible: Inbox.expiryRulesLoading && Inbox.expiryRules.length === 0
                    text: "Loading provider rules…"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }

                Repeater {
                    model: Inbox.expiryRules

                    delegate: Rectangle {
                        id: ruleCard

                        required property var modelData
                        readonly property bool isExpanded: root.expandedRuleId === modelData.id
                        readonly property bool isEditingDays: root.editingDaysRuleId === modelData.id
                        readonly property int matchCount: modelData.match_count ?? 0
                        readonly property bool isCustomPreset: !root.retentionPresets.includes(modelData.retention_days)

                        Layout.fillWidth: true
                        implicitHeight: cardCol.implicitHeight + 22
                        radius: 14
                        color: modelData.enabled ? Theme.glassControl : Theme.glassCard
                        border.width: Theme.glass ? 0 : 1
                        border.color: Theme.glassBorderSubtle

                        GlassEdge {
                            visible: Theme.glass && ruleCard.modelData.enabled
                            radius: parent.radius
                            side: false
                        }

                        ColumnLayout {
                            id: cardCol

                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 11
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            spacing: 8

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                // Provider title & sender patterns.
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3

                                    RowLayout {
                                        spacing: 8

                                        Label {
                                            text: ruleCard.modelData.display_name
                                            font.pixelSize: 14
                                            weight: Font.Medium
                                        }

                                        Rectangle {
                                            visible: !ruleCard.modelData.is_builtin
                                            implicitWidth: customTag.implicitWidth + 12
                                            implicitHeight: 18
                                            radius: 9
                                            color: Theme.m3tertiaryContainer

                                            Label {
                                                id: customTag

                                                anchors.centerIn: parent
                                                text: "Custom"
                                                color: Theme.m3onTertiaryContainer
                                                font.pixelSize: 10
                                                weight: Font.Medium
                                            }
                                        }

                                        // Live match preview pill (complementary status signal).
                                        Rectangle {
                                            implicitWidth: matchLabel.implicitWidth + 14
                                            implicitHeight: 20
                                            radius: 10
                                            color: ruleCard.matchCount > 0 ? Theme.m3tertiaryContainer : Theme.glassControl

                                            Label {
                                                id: matchLabel

                                                anchors.centerIn: parent
                                                text: `${ruleCard.matchCount} matching`
                                                color: ruleCard.matchCount > 0 ? Theme.m3onTertiaryContainer : Theme.m3onSurfaceVariant
                                                font.pixelSize: 11
                                                weight: Font.Medium
                                            }

                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    if (ruleCard.isExpanded) {
                                                        root.expandedRuleId = "";
                                                    } else {
                                                        root.expandedRuleId = ruleCard.modelData.id;
                                                        Inbox.previewExpiryRule(ruleCard.modelData.id, null);
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: (ruleCard.modelData.match_senders ?? []).join(", ")
                                        elide: Text.ElideRight
                                        color: Theme.m3onSurfaceVariant
                                        font.pixelSize: 12
                                    }
                                }

                                // Retention day chips: 3d, 7d, 14d, 30d, Custom.
                                Row {
                                    spacing: 4

                                    Repeater {
                                        model: root.retentionPresets

                                        delegate: Rectangle {
                                            required property int modelData
                                            readonly property bool selected: ruleCard.modelData.retention_days === modelData

                                            width: dayLbl.implicitWidth + 14
                                            height: 26
                                            radius: 13
                                            color: selected
                                                ? Theme.pill
                                                : (dayArea.containsMouse ? Theme.glassControlHover : Theme.glassControl)

                                            Label {
                                                id: dayLbl

                                                anchors.centerIn: parent
                                                text: `${modelData}d`
                                                color: parent.selected ? Theme.pillInk : Theme.m3onSurfaceVariant
                                                font.pixelSize: 12
                                                weight: parent.selected ? Font.Medium : Font.Normal
                                            }

                                            MouseArea {
                                                id: dayArea

                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    root.editingDaysRuleId = "";
                                                    const updated = Object.assign({}, ruleCard.modelData, { retention_days: modelData });
                                                    Inbox.saveExpiryRule(updated, null);
                                                }
                                            }
                                        }
                                    }

                                    // Custom days chip / inline editor.
                                    Rectangle {
                                        visible: !ruleCard.isEditingDays
                                        width: customDayLbl.implicitWidth + 14
                                        height: 26
                                        radius: 13
                                        color: ruleCard.isCustomPreset
                                            ? Theme.pill
                                            : (customDayArea.containsMouse ? Theme.glassControlHover : Theme.glassControl)

                                        Label {
                                            id: customDayLbl

                                            anchors.centerIn: parent
                                            text: ruleCard.isCustomPreset ? `${ruleCard.modelData.retention_days}d` : "Custom"
                                            color: ruleCard.isCustomPreset ? Theme.pillInk : Theme.m3onSurfaceVariant
                                            font.pixelSize: 12
                                            weight: ruleCard.isCustomPreset ? Font.Medium : Font.Normal
                                        }

                                        MouseArea {
                                            id: customDayArea

                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                root.editingDaysRuleId = ruleCard.modelData.id;
                                                root.editingDaysText = String(ruleCard.modelData.retention_days);
                                            }
                                        }
                                    }

                                    Rectangle {
                                        visible: ruleCard.isEditingDays
                                        width: 68
                                        height: 26
                                        radius: 13
                                        color: Theme.glassActive

                                        TextInput {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: 10
                                            verticalAlignment: TextInput.AlignVCenter
                                            color: Theme.m3onSurface
                                            font.family: Theme.sans
                                            font.pixelSize: 12
                                            text: root.editingDaysText
                                            focus: ruleCard.isEditingDays
                                            onTextChanged: if (ruleCard.isEditingDays) root.editingDaysText = text
                                            onAccepted: {
                                                const days = parseInt(text.trim(), 10);
                                                if (!isNaN(days) && days >= 1 && days <= 3650) {
                                                    const updated = Object.assign({}, ruleCard.modelData, { retention_days: days });
                                                    Inbox.saveExpiryRule(updated, null);
                                                }
                                                root.editingDaysRuleId = "";
                                            }
                                        }
                                    }
                                }

                                // Skip starred compact toggle pill.
                                Rectangle {
                                    implicitWidth: starRow.implicitWidth + 14
                                    implicitHeight: 26
                                    radius: 13
                                    color: ruleCard.modelData.skip_starred
                                        ? Theme.m3tertiaryContainer
                                        : Theme.glassControl

                                    Row {
                                        id: starRow

                                        anchors.centerIn: parent
                                        spacing: 4

                                        Icon {
                                            anchors.verticalCenter: parent.verticalCenter
                                            name: "star"
                                            fill: ruleCard.modelData.skip_starred ? 1 : 0
                                            size: 14
                                            color: ruleCard.modelData.skip_starred ? Theme.m3onTertiaryContainer : Theme.m3onSurfaceVariant
                                        }

                                        Label {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: "Skip starred"
                                            color: ruleCard.modelData.skip_starred ? Theme.m3onTertiaryContainer : Theme.m3onSurfaceVariant
                                            font.pixelSize: 11
                                            weight: Font.Medium
                                        }
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            const updated = Object.assign({}, ruleCard.modelData, { skip_starred: !ruleCard.modelData.skip_starred });
                                            Inbox.saveExpiryRule(updated, null);
                                        }
                                    }
                                }

                                // Delete custom rule.
                                IconButton {
                                    visible: !ruleCard.modelData.is_builtin
                                    icon: "delete"
                                    size: 28
                                    tip: "Remove custom provider"
                                    onClicked: Inbox.deleteExpiryRule(ruleCard.modelData.id)
                                }

                                // Enable / disable switch.
                                Switch {
                                    checked: ruleCard.modelData.enabled
                                    onToggled: {
                                        const updated = Object.assign({}, ruleCard.modelData, { enabled: !ruleCard.modelData.enabled });
                                        Inbox.saveExpiryRule(updated, null);
                                    }
                                }
                            }

                            // Inline dry-run preview when the match count pill is clicked.
                            Rectangle {
                                Layout.fillWidth: true
                                visible: ruleCard.isExpanded && Inbox.expiryPreview !== null && Inbox.expiryPreview.rule?.id === ruleCard.modelData.id
                                implicitHeight: previewCol.implicitHeight + 16
                                radius: Theme.controlRadius
                                color: Theme.glass ? (Theme.dark ? Qt.rgba(0, 0, 0, 0.22) : Qt.rgba(1, 1, 1, 0.28)) : Theme.m3surfaceContainerLow

                                ColumnLayout {
                                    id: previewCol

                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 8
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 12
                                    spacing: 6

                                    Label {
                                        Layout.fillWidth: true
                                        text: {
                                            const p = Inbox.expiryPreview;
                                            if (!p)
                                                return "";
                                            const parts = [`${p.match_count} matching thread${p.match_count === 1 ? "" : "s"}`];
                                            if (p.due_now_count > 0)
                                                parts.push(`${p.due_now_count} ready to trash now`);
                                            if (p.skipped_starred > 0)
                                                parts.push(`${p.skipped_starred} starred protected`);
                                            if (p.skipped_manual > 0)
                                                parts.push(`${p.skipped_manual} with manual schedule`);
                                            return parts.join(" · ");
                                        }
                                        color: Theme.m3onSurfaceVariant
                                        font.pixelSize: 11
                                        weight: Font.Medium
                                    }

                                    Repeater {
                                        model: Inbox.expiryPreview?.sample ?? []

                                        delegate: RowLayout {
                                            required property var modelData

                                            Layout.fillWidth: true
                                            spacing: 8

                                            Label {
                                                Layout.fillWidth: true
                                                text: modelData.subject
                                                elide: Text.ElideRight
                                                font.pixelSize: 12
                                            }

                                            Label {
                                                text: modelData.sender
                                                color: Theme.m3onSurfaceVariant
                                                font.pixelSize: 11
                                            }

                                            Label {
                                                text: modelData.due_now ? "Due now" : `in ${modelData.remaining}`
                                                color: modelData.due_now ? Theme.m3error : Theme.m3primary
                                                font.pixelSize: 11
                                                weight: Font.Medium
                                            }
                                        }
                                    }

                                    Label {
                                        visible: (Inbox.expiryPreview?.sample ?? []).length === 0
                                        text: "No existing notification threads match this provider."
                                        color: Theme.m3onSurfaceVariant
                                        font.pixelSize: 12
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.visible && !Inbox.composing && !Inbox.addingAccount && !Inbox.pictureCrop
        onActivated: Inbox.closeSettings()
    }
}
