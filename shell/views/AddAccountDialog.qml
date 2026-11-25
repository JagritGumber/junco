import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Adding a Google account: a short name for it, then Google's sign-in in the
// browser (courier-auth). Its mail starts syncing right after; the first sync
// of a big mailbox takes a few minutes.
Item {
    id: root

    // "", "waiting" (in the browser) or "done".
    property string stage: ""
    property string problem: ""
    property string added: ""
    // Bumped on close, so the answer to a cancelled sign-in is ignored.
    property int attempt: 0

    // Always lets you out; a sign-in still waiting on the browser is stopped.
    function close(): void {
        if (stage === "waiting")
            Inbox.cancelAddAccount();
        attempt++;
        Inbox.addingAccount = false;
        stage = "";
        problem = "";
        added = "";
        nameField.text = "";
    }

    function start(): void {
        const name = nameField.text.trim().toLowerCase();
        if (!/^[a-z0-9][a-z0-9-]{0,31}$/.test(name)) {
            problem = "Use a short name in lowercase letters, like work or college.";
            return;
        }
        if (Inbox.accounts.some(account => account.id === name)) {
            problem = `There's already an account called ${name}.`;
            return;
        }
        problem = "";
        stage = "waiting";
        const mine = ++attempt;
        Inbox.addAccount(name, (reason, result) => {
            if (mine !== attempt)
                return;
            if (reason) {
                stage = "";
                problem = reason;
            } else {
                stage = "done";
                added = result.email;
            }
        });
    }

    visible: Inbox.addingAccount
    z: 96

    Shortcut {
        sequence: "Escape"
        enabled: root.visible
        onActivated: root.close()
    }

    Rectangle {
        anchors.fill: parent
        radius: 28
        color: Theme.alpha("#000000", 0.45)

        // A click outside closes it, except mid sign-in: coming back from the
        // browser with a click shouldn't cancel. Cancel, ✕ and Esc still do.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: if (root.stage !== "waiting")
                root.close()
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(480, parent.width - 48)
        height: form.implicitHeight + 48
        radius: 28
        color: Theme.m3popup

        MouseArea {
            anchors.fill: parent
        }

        ColumnLayout {
            id: form

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 24
            spacing: 16

            RowLayout {
                Layout.fillWidth: true

                Label {
                    Layout.fillWidth: true
                    text: root.stage === "done" ? "Account added" : "Add an account"
                    font.pixelSize: 22
                    font.weight: Font.Medium
                }

                IconButton {
                    icon: "close"
                    tip: "Close"
                    size: 38
                    onClicked: root.close()
                }
            }

            Label {
                Layout.fillWidth: true
                text: root.stage === "done"
                    ? `${root.added} is signed in. Its mail is downloading now; a big mailbox takes a few minutes. It shows with your other mail, marked with its own colour.`
                    : root.stage === "waiting"
                    ? "Finish signing in in your browser. Keep every box ticked: Courier needs mail and read-only calendar access. If Google shows an error page instead, it can't come back here: press Cancel."
                    : "Courier opens Google in your browser to sign in. Your password never passes through Courier; the sign-in stays in your keyring."
                wrapMode: Text.Wrap
                color: Theme.m3onSurfaceVariant
                lineHeight: 1.15
            }

            ColumnLayout {
                Layout.fillWidth: true
                visible: root.stage === ""
                spacing: 6

                Label {
                    text: "A short name for it"
                    font.weight: Font.Medium
                }

                FormField {
                    id: nameField

                    Layout.fillWidth: true
                    hint: "work, college, personal…"
                    onAccepted: root.start()
                }
            }

            RowLayout {
                visible: root.stage === "waiting"
                spacing: 12

                Icon {
                    id: spinner

                    name: "progress_activity"
                    size: 24
                    color: Theme.m3primary

                    RotationAnimation on rotation {
                        running: root.stage === "waiting"
                        from: 0
                        to: 360
                        duration: 900
                        loops: Animation.Infinite
                    }
                }

                Label {
                    text: "Waiting for you in the browser…"
                }
            }

            Label {
                Layout.fillWidth: true
                visible: root.problem !== ""
                text: root.problem
                wrapMode: Text.Wrap
                color: Theme.m3error
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Item {
                    Layout.fillWidth: true
                }

                Pill {
                    visible: root.stage !== "done"
                    style: "text"
                    text: "Cancel"
                    onClicked: root.close()
                }

                Pill {
                    visible: root.stage === ""
                    style: "filled"
                    icon: "login"
                    text: "Sign in with Google"
                    onClicked: root.start()
                }

                Pill {
                    visible: root.stage === "done"
                    style: "filled"
                    text: "Done"
                    onClicked: root.close()
                }
            }
        }
    }
}
