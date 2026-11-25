import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The foot of the sidebar: your accounts as circles. The one shown is big;
// the small ones switch to another account (or All, every account together,
// drawn as one circle split between their pictures); + adds one. Each wears
// its own picture (its Google photo or Gravatar) unless you chose another.
// Hovering a circle a moment, or clicking the big one, shows its card
// (AccountCard): name, address, storage as a bar, Change picture. Right-click
// opens the same actions as a menu. A first download shows as a ring and a
// progress line.
ColumnLayout {
    id: root

    // The account shown: "" is All, unless there is only one account.
    readonly property string current: Inbox.account !== "" ? Inbox.account : Inbox.accounts.length === 1 ? Inbox.accounts[0].id : ""
    readonly property var others: {
        if (Inbox.accounts.length < 2)
            return [];
        const ids = Inbox.accounts.map(a => a.id).filter(id => id !== root.current);
        return root.current === "" ? ids : ["", ...ids];
    }
    readonly property var downloading: Inbox.accounts.filter(a => Inbox.progressOf(a.id) >= 0)

    // Right-click: the card's actions as a menu (its storage bar is on the card).
    function menuFor(id: string, item: Item): void {
        Inbox.accountCard?.close();
        if (id === "") {
            Inbox.windowMenu.show(item, [{ icon: "person_add", label: "Add account…", run: () => Inbox.addingAccount = true }]);
            return;
        }
        const info = Inbox.accounts.find(a => a.id === id);
        Inbox.windowMenu.show(item, [{ icon: "alternate_email", label: info?.email ?? id, run: () => {} }, { separator: true }, ...Inbox.pictureActions(id)]);
    }

    spacing: 6

    // A first download, so new mail arriving bit by bit isn't a mystery.
    Repeater {
        model: root.downloading

        delegate: ColumnLayout {
            id: download

            required property var modelData
            readonly property var entry: Inbox.syncStatus[modelData.id] ?? ({})

            Layout.fillWidth: true
            Layout.leftMargin: 6
            Layout.rightMargin: 6
            spacing: 5

            // preferredWidth 0: long text wraps or elides instead of widening
            // the sidebar.
            Label {
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                text: `Downloading ${download.modelData.email}`
                elide: Text.ElideRight
                font.pixelSize: 12
                font.weight: Font.Medium
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 4
                radius: 2
                color: Theme.m3surfaceContainerHighest

                Rectangle {
                    width: parent.width * Math.max(0.02, Inbox.progressOf(download.modelData.id))
                    height: parent.height
                    radius: 2
                    color: Theme.m3primary
                }
            }

            Label {
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                text: `${(download.entry.have ?? 0).toLocaleString()} of ${(download.entry.expected ?? 0).toLocaleString()} emails. They show up as they arrive.`
                wrapMode: Text.Wrap
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 11
            }
        }
    }

    // Wraps onto another line when there are many accounts. Each small
    // circle and + sits in a slot as tall as the big circle, so a line stays
    // centred.
    Flow {
        Layout.fillWidth: true
        spacing: 2

        AccountCircle {
            id: big

            account: root.current
            size: 44
            onClicked: mouse => mouse.button === Qt.RightButton ? root.menuFor(root.current, big) : Inbox.accountCard?.showNow(big, root.current)
        }

        Repeater {
            model: root.others

            delegate: Item {
                id: slot

                required property string modelData

                width: small.implicitWidth
                height: big.implicitHeight

                AccountCircle {
                    id: small

                    anchors.centerIn: parent
                    account: slot.modelData
                    size: 30
                    onClicked: mouse => {
                        if (mouse.button === Qt.RightButton) {
                            root.menuFor(slot.modelData, small);
                            return;
                        }
                        Inbox.accountCard?.close();
                        Inbox.setAccount(slot.modelData);
                    }
                }
            }
        }

        // + : add an account.
        Item {
            width: 38
            height: big.implicitHeight

            Rectangle {
                id: addButton

                anchors.centerIn: parent
                width: 30
                height: 30
                radius: 15
                color: add.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.1) : "transparent"
                border.width: 1.5
                border.color: Theme.alpha(Theme.m3onSurface, 0.3)

                Icon {
                    anchors.centerIn: parent
                    name: "add"
                    size: 18
                    color: Theme.m3onSurfaceVariant
                }
            }

            MouseArea {
                id: add

                anchors.fill: addButton
                anchors.margins: -4
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: Inbox.addingAccount = true
            }

            Loader {
                active: add.containsMouse
                sourceComponent: Tooltip {
                    parent: addButton
                    text: "Add an account"
                }
            }
        }
    }
}
