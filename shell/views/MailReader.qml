import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// One email: a toolbar (back, archive, delete, unread, more), the subject,
// who it's from and to, its meeting, the email itself (designed mail as
// designed, drawn by Qt's rich text; mail from people as text with working
// links), its files, Reply / Reply all / Forward, and a reply bar. In the inbox it takes the
// conversation's place; back or Escape returns to it.
Rectangle {
    id: root

    readonly property var mail: Inbox.reading
    readonly property bool inbox: mail?.inbox ?? false
    readonly property bool inTrash: mail?.inTrash ?? false
    readonly property string accountEmail: Inbox.accounts.length > 1 ? (Inbox.accounts.find(a => a.id === mail?.account)?.email ?? "") : ""
    property bool showRecipients: false
    property bool showFull: false
    // For this email only: "text" (its text, quotes folded) or "html" (its
    // HTML) instead of the view the engine chose; "" keeps that.
    property string override: ""
    // Teaching fields shows the surface the template is taught on: the plain
    // view (what notification mail opens in) or the designed version.
    readonly property string teachSurface: Inbox.teaching ? (Inbox.teachDraft?.surface ?? "") : ""
    // How the email shows (courier_mail.reading): "plain" its text part drawn
    // natively, "themed" simple HTML in the app's colours, "designed" HTML on
    // its own paper, "text" mail from people; while teaching, its surface.
    readonly property string mode: !mail ? "" : teachSurface === "text" ? "plain"
        : teachSurface === "html" && (mail.html ?? "") !== "" ? (mail.themed ? "themed" : "designed")
        : override === "text" ? "text"
        : override === "html" && (mail.html ?? "") !== "" ? (mail.themed ? "themed" : "designed") : (mail.view ?? "text")
    readonly property bool designed: mode === "designed" || mode === "themed"
    readonly property bool themedView: mode === "themed"
    // The email's own background, white unless it says otherwise; none when
    // it's drawn in the app's colours.
    readonly property color paper: themedView ? "transparent" : mail?.htmlBackground ? mail.htmlBackground : "#ffffff"
    // The plain view, for teach mode: selectionStart/selectionEnd and
    // getText() of what it shows (courier_mail.message_text, formatted).
    readonly property Item plainView: plainText
    readonly property string sender: mail?.prefs?.sender ?? ""
    // The designed view, for teach mode when a template is taught on HTML.
    readonly property Item designedView: designedText
    // Where the last selection was made: "subject" or "body".
    property string lastSelected: "body"

    // The selection, for Teach fields: in the subject, or in the email as the
    // reader shows it (offsets in its text, and that text, which the engine
    // lines up with its own).
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

    Component.onCompleted: Inbox.reader = root

    // A selection settles before the engine places it.
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

    radius: 26
    color: Theme.m3surfaceContainerLow

    // Nothing open yet.
    ColumnLayout {
        anchors.centerIn: parent
        visible: root.mail === null
        spacing: 12

        Icon {
            Layout.alignment: Qt.AlignHCenter
            name: Inbox.readingFailed ? "error" : "mail"
            size: 48
            color: Theme.m3onSurfaceVariant
        }

        Label {
            Layout.alignment: Qt.AlignHCenter
            text: Inbox.readingFailed ? "Couldn't open that email." : Inbox.openId !== "" ? "Opening…" : "Pick an email to read it here."
            color: Theme.m3onSurfaceVariant
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        visible: root.mail !== null
        spacing: 12

        // The toolbar.
        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            IconButton {
                icon: "arrow_back"
                tip: Inbox.history.length > 0 ? "Back to the email before" : Inbox.folder === "smart" ? "Back to the conversation (Esc)" : "Close (Esc)"
                onClicked: Inbox.back()
            }

            Item {
                Layout.fillWidth: true
            }

            Pill {
                visible: root.inTrash
                style: "filled"
                icon: "restore_from_trash"
                text: "Restore"
                size: 40
                onClicked: Inbox.act("untrash", [root.mail.id])
            }

            IconButton {
                visible: !root.inTrash
                icon: root.inbox ? "archive" : "move_to_inbox"
                tip: root.inbox ? "Archive" : "Move to Inbox"
                onClicked: Inbox.act(root.inbox ? "archive" : "inbox", [root.mail.id])
            }

            IconButton {
                visible: !root.inTrash
                icon: "delete"
                tip: "Delete"
                onClicked: Inbox.act("trash", [root.mail.id])
            }

            IconButton {
                visible: !root.inTrash
                icon: "mark_email_unread"
                tip: "Mark unread"
                onClicked: Inbox.mark("unread", [root.mail.id])
            }

            Item {
                Layout.fillWidth: true
            }

            // Teach fields: name what's in emails like this one.
            IconButton {
                visible: !root.inTrash && Inbox.developer
                icon: "dataset"
                filled: Inbox.teaching
                tip: Inbox.teaching ? "Stop teaching fields" : "Teach fields: pick out what emails like this one say"
                onClicked: Inbox.teaching ? Inbox.stopTeaching() : Inbox.startTeaching()
            }

            IconButton {
                id: moreButton

                visible: !root.inTrash
                icon: "more_vert"
                tip: "More"
                onClicked: menu.show(moreButton, [
                    { icon: "star", label: root.mail.starred ? "Unstar" : "Star", run: () => Inbox.mark(root.mail.starred ? "unstar" : "star", [root.mail.id]) },
                    // The text part, natively; remembered for the sender.
                    ...(root.mail.plain && root.mail.html && root.sender ? [root.mode === "plain"
                        ? { icon: "web", label: "Show original", run: () => Inbox.setReaderPref(root.sender, "plain", "original") }
                        : { icon: "notes", label: "Show plain text", run: () => Inbox.setReaderPref(root.sender, "plain", root.mail.plainAuto ? "auto" : "always") }] : []),
                    ...(root.mail.plain && root.sender ? [
                        { icon: root.mail.prefs.plain === "always" ? "check_box" : "check_box_outline_blank", label: "Always plain text",
                          run: () => Inbox.setReaderPref(root.sender, "plain", root.mail.prefs.plain === "always" ? "auto" : "always") }] : []),
                    // Its colours or the app's; remembered for the sender.
                    ...(root.designed && root.sender ? [{ icon: root.themedView ? "light_mode" : "dark_mode", label: root.themedView ? "Original colours" : "Dark",
                        run: () => Inbox.setReaderPref(root.sender, "colours", root.themedView ? "original" : "dark") }] : []),
                    ...(root.mail.html && !root.mail.plain && root.mode !== "plain" ? [{ icon: root.designed ? "notes" : "web", label: root.designed ? "Show as plain text" : "Show designed version",
                        run: () => root.override = root.designed ? "text" : "html" }] : []),
                    { icon: "open_in_new", label: "Open in browser", run: () => Inbox.viewOriginal(root.mail.id) },
                    ...(Inbox.developer ? [{ icon: "dataset", label: "Teach fields", run: () => Inbox.startTeaching() }] : []),
                    { separator: true },
                    { icon: "report", label: "Report spam", danger: true, run: () => Inbox.act("spam", [root.mail.id]) }
                ])
            }
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

                x: 4
                width: Math.min(page.width - 8, 820)
                spacing: 18

                // Selectable, so a field can come from the subject (a PR's number).
                TextEdit {
                    id: subjectText

                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    renderType: Text.NativeRendering
                    textFormat: TextEdit.PlainText
                    readOnly: true
                    selectByMouse: true
                    // While teaching, a selection stays as you name it.
                    persistentSelection: Inbox.teaching
                    text: root.mail?.subject ?? ""
                    wrapMode: TextEdit.Wrap
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 28
                    font.weight: Font.Medium
                    onSelectedTextChanged: if (selectedText !== "") root.selectionChanged("subject")
                }

                // Deleted: what's possible from here.
                Rectangle {
                    Layout.fillWidth: true
                    visible: root.inTrash
                    implicitHeight: 48
                    radius: 14
                    color: Theme.m3surfaceContainer

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 10

                        Icon {
                            name: "delete"
                            size: 20
                        }

                        Label {
                            Layout.fillWidth: true
                            text: "In Trash. Restore it to reply, archive, label or open its files. Gmail empties Trash after 30 days."
                            elide: Text.ElideRight
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 13
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14

                    Avatar {
                        Layout.alignment: Qt.AlignTop
                        name: root.mail?.fromName ?? ""
                        image: root.mail?.avatar ?? ""
                        size: 46
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3

                        Text {
                            Layout.fillWidth: true
                            renderType: Text.NativeRendering
                            textFormat: Text.StyledText
                            elide: Text.ElideRight
                            color: Theme.m3onSurface
                            font.family: Theme.sans
                            font.pixelSize: 15
                            text: root.mail ? `<b>${Inbox.linked(root.mail.fromName, "")}</b> <font color="${Theme.m3onSurfaceVariant}">&lt;${Inbox.linked(root.mail.fromAddress, "")}&gt;</font>` : ""
                        }

                        // "to me ⌄": everyone it went to, on a click. (The click
                        // area sits beside the Row: inside, it would size the
                        // Row by its own width, without end.)
                        Item {
                            implicitWidth: recipientsRow.implicitWidth
                            implicitHeight: recipientsRow.implicitHeight

                            Row {
                                id: recipientsRow

                                spacing: 2

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                text: (root.mail?.mine ? `to ${(root.mail?.to ?? "").split(",")[0]}` : (root.mail?.details?.toMe ?? true) ? "to me" : `to ${(root.mail?.to ?? "").split(",")[0]}`) + (root.accountEmail ? "  · " : "")
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 13
                            }

                            // The account it came to, with its picture
                            // (only with more than one account).
                            AccountBadge {
                                anchors.verticalCenter: parent.verticalCenter
                                account: root.accountEmail ? (root.mail?.account ?? "") : ""
                                size: 16
                                tip: ""
                            }

                            Label {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: root.accountEmail !== ""
                                text: root.accountEmail
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 13
                            }

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: root.showRecipients ? "expand_less" : "expand_more"
                                size: 18
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
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: 2
                        text: root.mail ? Inbox.whenText(root.mail.epoch) : ""
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                    }

                    IconButton {
                        Layout.alignment: Qt.AlignTop
                        icon: "star"
                        iconFill: (root.mail?.starred ?? false) ? 1 : 0
                        iconColor: (root.mail?.starred ?? false) ? Theme.m3tertiary : Theme.m3onSurfaceVariant
                        tip: (root.mail?.starred ?? false) ? "Unstar" : "Star"
                        size: 34
                        onClicked: Inbox.mark(root.mail.starred ? "unstar" : "star", [root.mail.id])
                    }
                }

                // Everyone it went to.
                Rectangle {
                    Layout.fillWidth: true
                    visible: root.showRecipients
                    implicitHeight: recipients.implicitHeight + 24
                    radius: 16
                    color: Theme.m3surfaceContainer

                    ColumnLayout {
                        id: recipients

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 12
                        spacing: 4

                        Repeater {
                            model: [["From", root.mail ? `${root.mail.fromName} <${root.mail.fromAddress}>` : ""], ["To", root.mail?.to ?? ""], ["Cc", root.mail?.cc ?? ""], ["Date", root.mail?.date ?? ""]].filter(line => line[1])

                            delegate: RowLayout {
                                required property var modelData

                                Layout.fillWidth: true
                                spacing: 10

                                Label {
                                    Layout.preferredWidth: 44
                                    Layout.alignment: Qt.AlignTop
                                    text: parent.modelData[0]
                                    color: Theme.m3onSurfaceVariant
                                    font.pixelSize: 13
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: parent.modelData[1]
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 13
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

                // What this email's template says, as fields you taught.
                FieldsCard {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 680
                    visible: Inbox.developer && (root.mail?.fields ?? null) !== null && !Inbox.teaching
                    card: root.mail?.fields ?? null
                    messageId: root.mail?.id ?? ""
                }

                // Teaching: what to do, over the email.
                Rectangle {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 680
                    visible: Inbox.teaching
                    implicitHeight: teachHint.implicitHeight + 24
                    radius: 16
                    color: Theme.alpha(Theme.m3primary, 0.12)

                    RowLayout {
                        id: teachHint

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 10

                        Icon {
                            name: "text_select_start"
                            size: 20
                            color: Theme.m3primary
                        }

                        Label {
                            Layout.fillWidth: true
                            text: root.teachSurface === "html" ? "Select text in the email (or the subject), then name it in the panel. Teaching on the designed version." : "Select text in the email (or the subject), then name it in the panel. Teaching on the email's text."
                            wrapMode: Text.Wrap
                            color: Theme.m3onSurface
                            font.pixelSize: 13
                        }
                    }
                }

                // The designed version on its own background, the way it was
                // made to be seen. Qt's rich text runs no scripts; the engine
                // already removed anything active (courier_html.py).
                // Designed mail is made 600–640 px wide and centred with
                // max-width, which Qt's rich text ignores, so the card is that
                // wide instead.
                Rectangle {
                    // In the app's colours there is no paper, so no margin either.
                    readonly property int inset: root.themedView ? 0 : 16

                    Layout.fillWidth: true
                    Layout.maximumWidth: 680
                    visible: root.designed
                    implicitHeight: designedText.implicitHeight + 2 * inset
                    radius: 18
                    color: root.paper
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
                        text: root.designed ? root.mail.html : ""
                        onSelectedTextChanged: if (selectedText !== "") root.selectionChanged("body")
                        // Text the email didn't colour, readable on its background.
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

                // A notification's text part, drawn natively (PlainText.formatted):
                // links, lists, quotes and code formatted lightly, the footer
                // folded into one small line.
                // Teaching shows all of it, footer too, every address whole, so a
                // selection lines up with the engine's text (message_text).
                TextEdit {
                    id: plainText

                    Layout.fillWidth: true
                    Layout.maximumWidth: 760
                    visible: root.mode === "plain"
                    renderType: Text.NativeRendering
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    textFormat: TextEdit.RichText
                    persistentSelection: Inbox.teaching
                    text: !visible ? "" : root.teachSurface === "text" ? Inbox.formatted(root.mail.plain || root.mail.full || root.mail.body, -1, true)
                        : Inbox.formatted(root.mail.plain, root.mail.plainFooter ?? -1, false)
                    onSelectedTextChanged: if (selectedText !== "") root.selectionChanged("body")
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 15
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
                    text: root.mail && root.mode === "text" ? Inbox.linked(root.showFull && root.mail.full ? root.mail.full : root.mail.body, Theme.m3primary) : ""
                    color: Theme.m3onSurface
                    selectionColor: Theme.m3primary
                    selectedTextColor: Theme.m3onPrimary
                    font.family: Theme.sans
                    font.pixelSize: 15
                    onLinkActivated: link => Qt.openUrlExternally(link.replace(/&amp;/g, "&"))

                    // TextEdit has no hover cursor for links.
                    HoverHandler {
                        cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor
                    }
                }

                Label {
                    visible: root.mode === "text" && (root.mail?.full ?? "") !== ""
                    text: root.showFull ? "Hide quoted text" : "Show quoted text"
                    color: Theme.m3primary
                    font.weight: Font.Medium

                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -6
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.showFull = !root.showFull
                    }
                }

                // Qt's rich text draws HTML 4 and CSS 2; the browser draws the rest.
                Label {
                    visible: (root.mail?.hasOriginal ?? false) && !Inbox.teaching
                    text: root.mode === "plain" ? "The email's text version, in Courier's colours. Show original"
                        : root.designed ? "Looks off? Open it in the browser ↗" : root.mail?.html ? "This email has a designed version. Show it" : "This email has a designed version. Open it in the browser ↗"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13

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
                        Layout.maximumWidth: 560
                        messageId: root.mail.id
                        file: modelData
                        inTrash: root.inTrash
                    }
                }

                RowLayout {
                    Layout.topMargin: 6
                    visible: !root.inTrash
                    spacing: 12

                    Pill {
                        style: "outlined"
                        icon: "reply"
                        text: "Reply"
                        size: 48
                        fontSize: 15
                        onClicked: Inbox.compose("reply", root.mail.id)
                    }

                    Pill {
                        style: "outlined"
                        icon: "reply_all"
                        text: "Reply all"
                        size: 48
                        fontSize: 15
                        onClicked: Inbox.compose("replyall", root.mail.id)
                    }

                    Pill {
                        style: "outlined"
                        icon: "forward"
                        text: "Forward"
                        size: 48
                        fontSize: 15
                        onClicked: Inbox.compose("forward", root.mail.id)
                    }
                }
            }
        }

        ReplyBar {
            Layout.fillWidth: true
            // Not for no-reply senders: nobody reads replies there.
            visible: root.mail !== null && !root.inTrash && !/no-?reply|do-?not-?reply|notifications?@|mailer-daemon/i.test(root.mail?.fromAddress ?? "")
            mail: root.mail
        }
    }

    // Only one Escape may be live at a time (two cancel each other out), so
    // this one waits while a menu, Compose or Add account has it.
    Shortcut {
        sequence: "Escape"
        enabled: root.visible && Inbox.readerOpen && !menu.visible && !Inbox.composing && !Inbox.addingAccount && !Inbox.pictureCrop && !(Inbox.windowMenu?.visible ?? false)
        onActivated: Inbox.closeMessage()
    }

    PopupMenu {
        id: menu

        anchors.fill: parent
    }
}
