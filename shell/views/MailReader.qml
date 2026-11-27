import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// One email: compact frosted-glass toolbar, tighter header & subject chrome,
// maximum room for the email body, and slim reply bar.
GlassPane {
    id: root

    readonly property var mail: Inbox.reading
    readonly property bool inbox: mail?.inbox ?? false
    readonly property bool inTrash: mail?.inTrash ?? false
    readonly property string accountEmail: Inbox.accounts.length > 1 ? (Inbox.accounts.find(a => a.id === mail?.account)?.email ?? "") : ""
    property bool showRecipients: false
    property bool showFull: false
    property string override: ""
    readonly property string teachSurface: Inbox.teaching ? (Inbox.teachDraft?.surface ?? "") : ""
    readonly property string mode: !mail ? "" : teachSurface === "text" ? "plain"
        : teachSurface === "html" && (mail.html ?? "") !== "" ? (mail.themed ? "themed" : "designed")
        : override === "text" ? "text"
        : override === "html" && (mail.html ?? "") !== "" ? (mail.themed ? "themed" : "designed") : (mail.view ?? "text")
    readonly property bool designed: mode === "designed" || mode === "themed"
    readonly property bool themedView: mode === "themed"
    // The body's own card: in glass mode a lighter, third level of glass
    // nested in the reader card; an email that brings its own colours keeps them.
    readonly property color paper: themedView ? (Theme.glass ? Theme.glassCard : "transparent") : mail?.htmlBackground ? mail.htmlBackground : "#ffffff"
    readonly property Item plainView: plainText
    readonly property string sender: mail?.prefs?.sender ?? ""
    readonly property Item designedView: designedText
    property string lastSelected: "body"

    // Rubik[wght].ttf (OS/2 usWeightClass=300) triggers Qt 6's synthetic
    // double-bolding at weight >= 700 (<b>, <strong>, <h1>..<h6>, <th>,
    // font-weight: bold). Driving RichText bold tags at font-weight: 600
    // selects Rubik's crisp SemiBold instance cleanly in both light and dark.
    function crispRichText(markup: string): string {
        if (!markup)
            return "";
        const rule = "<style>b,strong,h1,h2,h3,h4,h5,h6,th{font-weight:600;}</style>";
        if (/<head\b[^>]*>/i.test(markup))
            return markup.replace(/<head\b[^>]*>/i, match => match + rule);
        return rule + markup;
    }

    function selection(): var {
        if (lastSelected === "subject" && subjectText.selectedText !== "")
            return { subject: true, value: subjectText.selectedText, text: subjectText.selectedText };
        const edit = designed ? designedText : plainText;
        if (edit.selectedText === "")
            return null;
        return { subject: false, start: edit.selectionStart, end: edit.selectionEnd, shown: edit.getText(0, edit.length), text: edit.selectedText };
    }

    function clearSelection(): void {
        subjectText.deselect();
        designedText.deselect();
        plainText.deselect();
    }

    function selectionChanged(where: string): void {
        if (!Inbox.teaching)
            return;
        lastSelected = where;
        placing.restart();
    }

    function openSchedulePopover(anchor: Item, mailObj: var): void {
        if (!schedulePopoverLoader.active)
            schedulePopoverLoader.active = true;
        if (schedulePopoverLoader.item)
            schedulePopoverLoader.item.show(anchor, mailObj);
    }

    Component.onCompleted: Inbox.reader = root
    Component.onDestruction: if (Inbox.reader === root)
        Inbox.reader = null

    Timer {
        id: placing

        interval: 250
        onTriggered: Inbox.teachPlace()
    }

    onMailChanged: {
        showRecipients = false;
        showFull = false;
        override = "";
        page.contentY = 0;
    }

    // Nothing open yet.
    ColumnLayout {
        anchors.centerIn: parent
        visible: root.mail === null
        spacing: 10

        Icon {
            Layout.alignment: Qt.AlignHCenter
            name: Inbox.readingFailed ? "error" : "mail"
            size: 40
            color: Theme.m3onSurfaceVariant
        }

        Label {
            Layout.alignment: Qt.AlignHCenter
            text: Inbox.readingFailed ? "Couldn't open that email." : Inbox.openId !== "" ? "Opening…" : "Pick an email to read it here."
            color: Theme.m3onSurfaceVariant
            font.pixelSize: 13
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        visible: root.mail !== null
        spacing: 14

        // Calm mockup-style subject row (back button only when navigating from a conversation/history).
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            IconButton {
                visible: Inbox.folder === "smart" || Inbox.history.length > 0
                icon: "arrow_back"
                tip: Inbox.history.length > 0 ? "Back to the email before" : "Back to the conversation (Esc)"
                size: 30
                onClicked: Inbox.back()
            }

            TextEdit {
                id: subjectText

                Layout.fillWidth: true
                renderType: Text.NativeRendering
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                persistentSelection: Inbox.teaching
                text: root.mail?.subject ?? ""
                wrapMode: TextEdit.Wrap
                color: Theme.m3onSurface
                selectionColor: Theme.m3primary
                selectedTextColor: Theme.m3onPrimary
                font.family: Theme.sans
                font.pixelSize: 20
                font.weight: Font.Normal
                font.variableAxes: ({ "wght": Theme.weightHeading })
                onSelectedTextChanged: if (selectedText !== "") root.selectionChanged("subject")
            }

            Rectangle {
                visible: !root.inTrash
                Layout.alignment: Qt.AlignVCenter
                width: 8
                height: 8
                radius: 4
                color: Theme.complementDot
            }

            Pill {
                visible: root.inTrash
                style: "filled"
                icon: "restore_from_trash"
                text: "Restore"
                size: 32
                fontSize: 12
                onClicked: Inbox.act("untrash", [root.mail.id])
            }
        }

        // Calm sender header: Avatar + Name <address> / to me ▾ | time + star + reply + overflow menu.
        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            Avatar {
                Layout.alignment: Qt.AlignVCenter
                name: root.mail?.fromName ?? ""
                image: root.mail?.avatar ?? ""
                size: 38
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Label {
                        text: root.mail?.fromName ?? ""
                        color: Theme.m3onSurface
                        font.pixelSize: 14
                        weight: Font.Medium
                        elide: Text.ElideRight
                    }

                    Label {
                        Layout.fillWidth: true
                        visible: (root.mail?.fromAddress ?? "") !== ""
                        text: `<${root.mail?.fromAddress ?? ""}>`
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                }

                Item {
                    implicitWidth: recipientsRow.implicitWidth
                    implicitHeight: recipientsRow.implicitHeight

                    Row {
                        id: recipientsRow

                        spacing: 3

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: (root.mail?.mine ? `to ${(root.mail?.to ?? "").split(",")[0]}` : (root.mail?.details?.toMe ?? true) ? "to me" : `to ${(root.mail?.to ?? "").split(",")[0]}`) + (root.accountEmail ? "  · " : "")
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                        }

                        AccountBadge {
                            anchors.verticalCenter: parent.verticalCenter
                            account: root.accountEmail ? (root.mail?.account ?? "") : ""
                            size: 14
                            tip: ""
                        }

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: root.accountEmail !== ""
                            text: root.accountEmail
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                        }

                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: root.showRecipients ? "expand_less" : "expand_more"
                            size: 16
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.showRecipients = !root.showRecipients
                    }
                }
            }

            Label {
                Layout.alignment: Qt.AlignVCenter
                text: root.mail ? Inbox.whenText(root.mail.epoch) : ""
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 12
            }

            IconButton {
                visible: !root.inTrash
                icon: "star"
                iconFill: (root.mail?.starred ?? false) ? 1 : 0
                iconColor: (root.mail?.starred ?? false) ? Theme.m3tertiary : Theme.m3onSurfaceVariant
                tip: (root.mail?.starred ?? false) ? "Unstar" : "Star"
                size: 30
                onClicked: Inbox.mark(root.mail.starred ? "unstar" : "star", [root.mail.id])
            }

            IconButton {
                visible: !root.inTrash
                icon: "reply"
                tip: "Reply"
                size: 30
                onClicked: Inbox.compose("reply", root.mail.id)
            }

            IconButton {
                id: moreButton

                visible: !root.inTrash
                icon: "more_vert"
                tip: "More"
                size: 30
                onClicked: menu.show(moreButton, [
                    { icon: root.inbox ? "archive" : "move_to_inbox", label: root.inbox ? "Archive" : "Move to Inbox", run: () => Inbox.act(root.inbox ? "archive" : "inbox", [root.mail.id]) },
                    { icon: "mark_email_unread", label: "Mark unread", run: () => Inbox.mark("unread", [root.mail.id]) },
                    { icon: "auto_delete", label: (root.mail?.expiry ?? null) !== null ? "Change scheduled delete…" : "Schedule delete…", run: () => root.openSchedulePopover(moreButton, root.mail) },
                    { icon: "delete", label: "Delete", run: () => Inbox.act("trash", [root.mail.id]) },
                    { separator: true },
                    ...(root.mail.plain && root.mail.html && root.sender ? [root.mode === "plain"
                        ? { icon: "web", label: "Show original", run: () => Inbox.setReaderPref(root.sender, "plain", "original") }
                        : { icon: "notes", label: "Show plain text", run: () => Inbox.setReaderPref(root.sender, "plain", root.mail.plainAuto ? "auto" : "always") }] : []),
                    ...(root.mail.plain && root.sender ? [
                        { icon: root.mail.prefs.plain === "always" ? "check_box" : "check_box_outline_blank", label: "Always plain text",
                          run: () => Inbox.setReaderPref(root.sender, "plain", root.mail.prefs.plain === "always" ? "auto" : "always") }] : []),
                    ...(root.designed && root.sender ? [{ icon: root.themedView ? "light_mode" : "dark_mode", label: root.themedView ? "Original colours" : "Dark",
                        run: () => Inbox.setReaderPref(root.sender, "colours", root.themedView ? "original" : "dark") }] : []),
                    ...(root.mail.html && !root.mail.plain && root.mode !== "plain" ? [{ icon: root.designed ? "notes" : "web", label: root.designed ? "Show as plain text" : "Show designed version",
                        run: () => root.override = root.designed ? "text" : "html" }] : []),
                    { icon: "open_in_new", label: "Open in browser", run: () => Inbox.viewOriginal(root.mail.id) },
                    ...(Inbox.developer ? [{ icon: "dataset", label: Inbox.teaching ? "Stop teaching fields" : "Teach fields", run: () => Inbox.teaching ? Inbox.stopTeaching() : Inbox.startTeaching() }] : []),
                    { separator: true },
                    { icon: "report", label: "Report spam", danger: true, run: () => Inbox.act("spam", [root.mail.id]) }
                ])
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: Theme.glassDivider
        }

        Flickable {
            id: page

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: column.implicitHeight + 16
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: column

                x: 2
                width: Math.min(page.width - 4, 920)
                spacing: 14

                Rectangle {
                    Layout.fillWidth: true
                    visible: root.inTrash
                    implicitHeight: 38
                    radius: Theme.controlRadius
                    color: Theme.glassCard
                    border.width: 1
                    border.color: Theme.glassBorderSubtle

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 8

                        Icon {
                            name: "delete"
                            size: 18
                        }

                        Label {
                            Layout.fillWidth: true
                            text: "In Trash. Restore it to reply, archive, label or open its files. Gmail empties Trash after 30 days."
                            elide: Text.ElideRight
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                        }
                    }
                }

                // Subtle interactive expiry pill when this thread is scheduled for deletion.
                ExpiryBadge {
                    id: expiryBadge

                    visible: !root.inTrash && (root.mail?.expiry ?? null) !== null
                    expiry: root.mail?.expiry ?? null
                    interactive: true
                    onChangeClicked: root.openSchedulePopover(expiryBadge, root.mail)
                    onCancelClicked: Inbox.cancelExpiry(root.mail.threadId || root.mail.id, null)
                }

                Rectangle {
                    Layout.fillWidth: true
                    visible: root.showRecipients
                    implicitHeight: recipients.implicitHeight + 18
                    radius: Theme.cardRadius
                    color: Theme.glassCard
                    border.width: 1
                    border.color: Theme.glassBorderSubtle

                    ColumnLayout {
                        id: recipients

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 9
                        spacing: 3

                        Repeater {
                            model: [["From", root.mail ? `${root.mail.fromName} <${root.mail.fromAddress}>` : ""], ["To", root.mail?.to ?? ""], ["Cc", root.mail?.cc ?? ""], ["Date", root.mail?.date ?? ""]].filter(line => line[1])

                            delegate: RowLayout {
                                required property var modelData

                                Layout.fillWidth: true
                                spacing: 8

                                Label {
                                    Layout.preferredWidth: 40
                                    Layout.alignment: Qt.AlignTop
                                    text: parent.modelData[0]
                                    color: Theme.m3onSurfaceVariant
                                    font.pixelSize: 12
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: parent.modelData[1]
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }
                            }
                        }
                    }
                }

                MeetingCard {
                    Layout.fillWidth: true
                    visible: root.mail?.details?.meeting !== null && root.mail?.details?.meeting !== undefined
                    meeting: root.mail?.details?.meeting ?? ({})
                }

                FieldsCard {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 720
                    visible: Inbox.developer && (root.mail?.fields ?? null) !== null && !Inbox.teaching
                    card: root.mail?.fields ?? null
                    messageId: root.mail?.id ?? ""
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 720
                    visible: Inbox.teaching
                    implicitHeight: teachHint.implicitHeight + 18
                    radius: Theme.cardRadius
                    color: Theme.glassActive
                    border.width: 1
                    border.color: Theme.glassActiveBorder

                    RowLayout {
                        id: teachHint

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 8

                        Icon {
                            name: "text_select_start"
                            size: 18
                            color: Theme.m3primary
                        }

                        Label {
                            Layout.fillWidth: true
                            text: root.teachSurface === "html" ? "Select text in the email (or the subject), then name it in the panel. Teaching on the designed version." : "Select text in the email (or the subject), then name it in the panel. Teaching on the email's text."
                            wrapMode: Text.Wrap
                            color: Theme.m3onSurface
                            font.pixelSize: 12
                        }
                    }
                }

                Rectangle {
                    readonly property int inset: root.themedView ? 0 : 14

                    Layout.fillWidth: true
                    Layout.maximumWidth: 720
                    visible: root.designed
                    implicitHeight: designedText.implicitHeight + 2 * inset
                    radius: 13
                    color: root.paper
                    border.width: root.themedView && Theme.glass ? 1 : 0
                    border.color: Theme.glassBubbleOtherBorder
                    clip: true

                    TextEdit {
                        id: designedText

                        x: parent.inset
                        y: parent.inset
                        width: parent.width - 2 * parent.inset
                        renderType: Text.NativeRendering
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.Wrap
                        textFormat: TextEdit.RichText
                        persistentSelection: Inbox.teaching
                        text: root.designed ? root.crispRichText(root.mail.html) : ""
                        onSelectedTextChanged: if (selectedText !== "") root.selectionChanged("body")
                        color: root.themedView ? Theme.m3onSurface : root.paper.hslLightness < 0.5 ? "#e8eaed" : "#202124"
                        selectionColor: Theme.m3primary
                        selectedTextColor: Theme.m3onPrimary
                        font.family: Theme.sans
                        font.pixelSize: 14
                        onLinkActivated: link => Qt.openUrlExternally(link)

                        HoverHandler {
                            cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor
                        }
                    }
                }

                // Plain and text bodies: on a lighter glass card of their own
                // (level 3), nested in the reader card.
                Rectangle {
                    readonly property int inset: Theme.glass ? 14 : 0

                    Layout.fillWidth: true
                    Layout.maximumWidth: 820 + 2 * inset
                    visible: root.mode === "plain" || root.mode === "text"
                    implicitHeight: bodyColumn.implicitHeight + 2 * inset
                    radius: 13
                    color: Theme.glass ? Theme.glassCard : "transparent"
                    border.width: Theme.glass ? 1 : 0
                    border.color: Theme.glassBubbleOtherBorder

                    GlassEdge {
                        visible: Theme.glass
                        radius: 13
                        side: false
                    }

                    ColumnLayout {
                        id: bodyColumn

                        x: parent.inset
                        y: parent.inset
                        width: parent.width - 2 * parent.inset
                        spacing: 0

                        TextEdit {
                            id: plainText

                            Layout.fillWidth: true
                            visible: root.mode === "plain"
                            renderType: Text.NativeRendering
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            textFormat: TextEdit.RichText
                            persistentSelection: Inbox.teaching
                            text: !visible ? "" : root.crispRichText(root.teachSurface === "text" ? Inbox.formatted(root.mail.plain || root.mail.full || root.mail.body, -1, true)
                                : Inbox.formatted(root.mail.plain, root.mail.plainFooter ?? -1, false))
                            onSelectedTextChanged: if (selectedText !== "") root.selectionChanged("body")
                            color: Theme.m3onSurface
                            selectionColor: Theme.m3primary
                            selectedTextColor: Theme.m3onPrimary
                            font.family: Theme.sans
                            font.pixelSize: 14
                            onLinkActivated: link => Qt.openUrlExternally(link.replace(/&amp;/g, "&"))

                            HoverHandler {
                                cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor
                            }
                        }

                        TextEdit {
                            Layout.fillWidth: true
                            visible: root.mode === "text"
                            renderType: Text.NativeRendering
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            textFormat: TextEdit.RichText
                            text: root.mail && root.mode === "text" ? root.crispRichText(Inbox.linked(root.showFull && root.mail.full ? root.mail.full : root.mail.body, Theme.m3primary)) : ""
                            color: Theme.m3onSurface
                            selectionColor: Theme.m3primary
                            selectedTextColor: Theme.m3onPrimary
                            font.family: Theme.sans
                            font.pixelSize: 14
                            onLinkActivated: link => Qt.openUrlExternally(link.replace(/&amp;/g, "&"))

                            HoverHandler {
                                cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor
                            }
                        }
                    }
                }

                Label {
                    visible: root.mode === "text" && (root.mail?.full ?? "") !== ""
                    text: root.showFull ? "Hide quoted text" : "Show quoted text"
                    color: Theme.m3primary
                    font.pixelSize: 13
                    weight: Font.Medium

                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -6
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.showFull = !root.showFull
                    }
                }

                Label {
                    visible: (root.mail?.hasOriginal ?? false) && !Inbox.teaching
                    text: root.mode === "plain" ? "The email's text version, in Junco's colours. Show original"
                        : root.designed ? "Looks off? Open it in the browser ↗" : root.mail?.html ? "This email has a designed version. Show it" : "This email has a designed version. Open it in the browser ↗"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.mode === "plain" ? Inbox.setReaderPref(root.sender, "plain", "original")
                            : root.designed || !root.mail.html ? Inbox.viewOriginal(root.mail.id) : root.override = "html"
                    }
                }

                Repeater {
                    model: root.mail?.attachments ?? []

                    delegate: AttachmentCard {
                        required property var modelData

                        Layout.fillWidth: true
                        Layout.maximumWidth: 520
                        messageId: root.mail.id
                        file: modelData
                        inTrash: root.inTrash
                    }
                }

                RowLayout {
                    Layout.topMargin: 6
                    visible: !root.inTrash
                    spacing: 10

                    Pill {
                        style: "tonal"
                        icon: "reply"
                        text: "Reply"
                        size: 34
                        fontSize: 13
                        onClicked: Inbox.compose("reply", root.mail.id)
                    }

                    Pill {
                        style: "tonal"
                        icon: "reply_all"
                        text: "Reply all"
                        size: 34
                        fontSize: 13
                        onClicked: Inbox.compose("replyall", root.mail.id)
                    }

                    Pill {
                        style: "tonal"
                        icon: "forward"
                        text: "Forward"
                        size: 34
                        fontSize: 13
                        onClicked: Inbox.compose("forward", root.mail.id)
                    }

                    IconButton {
                        id: bottomMore

                        icon: "more_horiz"
                        tip: "More actions"
                        size: 34
                        filled: true
                        fillColor: Theme.glassControl
                        iconColor: Theme.m3onSurface
                        onClicked: menu.show(bottomMore, [
                            { icon: root.inbox ? "archive" : "move_to_inbox", label: root.inbox ? "Archive" : "Move to Inbox", run: () => Inbox.act(root.inbox ? "archive" : "inbox", [root.mail.id]) },
                            { icon: "mark_email_unread", label: "Mark unread", run: () => Inbox.mark("unread", [root.mail.id]) },
                            { icon: "auto_delete", label: (root.mail?.expiry ?? null) !== null ? "Change scheduled delete…" : "Schedule delete…", run: () => root.openSchedulePopover(bottomMore, root.mail) },
                            { icon: "delete", label: "Delete", run: () => Inbox.act("trash", [root.mail.id]) }
                        ])
                    }
                }
            }
        }

        ReplyBar {
            Layout.fillWidth: true
            visible: root.mail !== null && !root.inTrash && !/no-?reply|do-?not-?reply|notifications?@|mailer-daemon/i.test(root.mail?.fromAddress ?? "")
            mail: root.mail
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.visible && Inbox.readerOpen && !menu.visible && !(schedulePopoverLoader.item?.visible ?? false) && !Inbox.composing && !Inbox.addingAccount && !Inbox.pictureCrop && !Inbox.paletteOpen && !(Inbox.windowMenu?.visible ?? false)
        onActivated: Inbox.closeMessage()
    }

    PopupMenu {
        id: menu

        anchors.fill: parent
    }

    Loader {
        id: schedulePopoverLoader

        anchors.fill: parent
        active: false
        source: "../components/ScheduleDeletePopover.qml"
        z: 120
    }
}
