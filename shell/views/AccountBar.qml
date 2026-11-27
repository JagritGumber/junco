import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// The foot of the sidebar: accounts as circles (full row when expanded,
// single active circle in compact rail mode — hover or click opens AccountCard).
ColumnLayout {
    id: root

    property bool compact: false

    readonly property string current: Inbox.account !== "" ? Inbox.account : Inbox.accounts.length === 1 ? Inbox.accounts[0].id : ""
    readonly property var others: {
        if (Inbox.accounts.length < 2)
            return [];
        const ids = Inbox.accounts.map(a => a.id).filter(id => id !== root.current);
        return root.current === "" ? ids : ["", ...ids];
    }
    readonly property var downloading: Inbox.accounts.filter(a => Inbox.progressOf(a.id) >= 0)

    function menuFor(id: string, item: Item): void {
        Inbox.accountCard?.close();
        if (id === "") {
            Inbox.windowMenu.show(item, [{ icon: "person_add", label: "Add account…", run: () => Inbox.addingAccount = true }]);
            return;
        }
        const info = Inbox.accounts.find(a => a.id === id);
        Inbox.windowMenu.show(item, [{ icon: "alternate_email", label: info?.email ?? id, run: () => {} }, { separator: true }, ...Inbox.pictureActions(id)]);
    }

    spacing: 4

    Repeater {
        model: root.compact ? [] : root.downloading

        delegate: ColumnLayout {
            id: download

            required property var modelData
            readonly property var entry: Inbox.syncStatus[modelData.id] ?? ({})

            Layout.fillWidth: true
            Layout.leftMargin: 4
            Layout.rightMargin: 4
            spacing: 4

            Label {
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                text: `Downloading ${download.modelData.email}`
                color: Theme.sheetInk
                elide: Text.ElideRight
                font.pixelSize: 11
                weight: Font.Medium
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 3
                radius: 1.5
                color: Theme.sheetControl

                Rectangle {
                    width: parent.width * Math.max(0.02, Inbox.progressOf(download.modelData.id))
                    height: parent.height
                    radius: 1.5
                    color: Theme.m3primary
                }
            }

            Label {
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                text: `${(download.entry.have ?? 0).toLocaleString()} of ${(download.entry.expected ?? 0).toLocaleString()} emails.`
                wrapMode: Text.Wrap
                color: Theme.sheetInkVariant
                font.pixelSize: 10
            }
        }
    }

    // Compact rail: single active circle centered.
    Item {
        Layout.fillWidth: true
        implicitHeight: compactCircle.implicitHeight
        visible: root.compact

        AccountCircle {
            id: compactCircle

            anchors.centerIn: parent
            account: root.current
            size: 32
            onClicked: mouse => mouse.button === Qt.RightButton ? root.menuFor(root.current, compactCircle) : Inbox.accountCard?.showNow(compactCircle, root.current)
        }
    }

    // Expanded sidebar: compact row of account circles + add button.
    Flow {
        Layout.fillWidth: true
        visible: !root.compact
        spacing: 2

        AccountCircle {
            id: big

            account: root.current
            size: 34
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
                    size: 24
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

        Item {
            width: 30
            height: big.implicitHeight

            Rectangle {
                id: addButton

                anchors.centerIn: parent
                width: 24
                height: 24
                radius: 12
                color: add.containsMouse ? Theme.sheetControlHover : Theme.sheetControl
                border.width: 1
                border.color: Theme.sheetRim

                Icon {
                    anchors.centerIn: parent
                    name: "add"
                    size: 15
                    color: Theme.sheetInk
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
