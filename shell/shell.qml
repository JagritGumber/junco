//@ pragma DefaultEnv QS_NO_RELOAD_POPUP=1
// The window's class, so docks and bars find courier.desktop (and its icon)
// instead of Quickshell's own entry. Read at startup only.
//@ pragma AppId courier

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.services
import qs.views
import qs.components

// Courier: mail. The folders; the inbox as conversations (or a folder's
// list); the open conversation or email. Run from the app launcher
// (courier.desktop), which shows a running Courier or starts one. The
// calendar is its own app, ../calendar.
ShellRoot {
    // `qs ipc -p <this folder> call courier show` brings the window back.
    IpcHandler {
        target: "courier"

        function show(): void {
            window.visible = true;
        }

        // Opens one email by its Message-ID (e.g. from a notification).
        function open(id: string): void {
            window.visible = true;
            Inbox.openMessage(id, true);
        }
    }

    FloatingWindow {
        id: window

        title: "Junco"
        implicitWidth: 1760
        implicitHeight: 1000
        color: Theme.m3surface

        // Closing the window quits Courier, so the next launch starts it
        // again instead of finding a windowless copy still running.
        onVisibleChanged: if (!visible)
            Qt.quit()

        RowLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 12

            MailSidebar {
                Layout.preferredWidth: 236
                Layout.fillHeight: true
            }

            // The inbox reads as conversations; every other folder as a list.
            ConversationList {
                Layout.preferredWidth: 410
                Layout.fillHeight: true
                visible: Inbox.folder === "smart" && !Inbox.tableTemplate
            }

            MailList {
                Layout.preferredWidth: 410
                Layout.fillHeight: true
                visible: Inbox.folder !== "smart" && !Inbox.tableTemplate
            }

            ConversationView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: Inbox.folder === "smart" && !Inbox.readerOpen && !Inbox.tableTemplate
            }

            // A taught template's emails as a table; a row opens beside it.
            TemplateTable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: Inbox.tableTemplate !== ""
            }

            // An opened email; in the inbox it stands in for the conversation
            // until back or Escape.
            MailReader {
                Layout.fillWidth: !Inbox.tableTemplate
                Layout.preferredWidth: Inbox.tableTemplate ? 640 : -1
                Layout.fillHeight: true
                visible: Inbox.tableTemplate ? Inbox.readerOpen : (Inbox.folder !== "smart" || Inbox.readerOpen)
            }

            // Teach fields, beside the email it's taught on.
            TeachPanel {
                Layout.preferredWidth: 420
                Layout.fillHeight: true
                visible: Inbox.teaching
            }
        }

        ComposeDialog {
            anchors.fill: parent
            anchors.margins: 12
        }

        Shortcut {
            sequence: "Ctrl+N"
            onActivated: Inbox.compose("new", "")
        }

        AddAccountDialog {
            anchors.fill: parent
            anchors.margins: 12
        }

        // Framing another picture for an account.
        PictureDialog {
            anchors.fill: parent
            anchors.margins: 12
        }

        // What just happened: "Deleting…" at once, then "Deleted · Undo".
        // Bottom left over the list, like Gmail, so it never covers the
        // reader's reply box.
        Snackbar {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: 272
            anchors.bottomMargin: 28
            z: 100
        }

        // An account's card, on hovering its circle in the account bar.
        AccountCard {
            id: accountCard

            anchors.fill: parent
            Component.onCompleted: Inbox.accountCard = accountCard
        }

        // For panes too narrow to hold their own menu (the account switcher).
        PopupMenu {
            id: windowMenu

            anchors.fill: parent
            z: 150
            Component.onCompleted: Inbox.windowMenu = windowMenu
        }
    }
}
