import QtQuick
import qs.services

// One account as a circle: its picture (the one you chose, else its own Google
// photo or Gravatar), or its first letter on its colour. Account "" is "All":
// every account's mail together, drawn as one circle split between the
// accounts' pictures (AccountsPicture). While the account downloads its mail
// for the first time, a ring fills around it. (No colour dot: emails wear the
// account's picture now, and a circle without one is its colour already.)
//
// Hovering it a moment shows the account's card (Inbox.accountCard): name,
// address, storage and picture actions.
Item {
    id: root

    property string account: ""
    property int size: 30

    readonly property var info: Inbox.accounts.find(a => a.id === account) ?? null
    readonly property real progress: account ? Inbox.progressOf(account) : -1
    readonly property color tint: account ? Inbox.accountColor(account) : Theme.m3surfaceContainerHighest
    readonly property bool hovered: area.containsMouse

    signal clicked(var mouse)

    implicitWidth: size + 8
    implicitHeight: size + 8

    // The download ring.
    Canvas {
        id: ring

        anchors.fill: parent
        visible: root.progress >= 0
        onPaint: {
            const context = getContext("2d");
            context.reset();
            if (root.progress < 0)
                return;
            const middle = width / 2;
            context.lineWidth = 2.5;
            context.lineCap = "round";
            context.strokeStyle = Theme.alpha(Theme.m3onSurface, 0.15);
            context.beginPath();
            context.arc(middle, middle, middle - 1.5, 0, 2 * Math.PI);
            context.stroke();
            context.strokeStyle = Theme.m3primary;
            context.beginPath();
            context.arc(middle, middle, middle - 1.5, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * Math.max(0.02, root.progress));
            context.stroke();
        }

        Connections {
            function onProgressChanged(): void {
                ring.requestPaint();
            }

            target: root
        }
    }

    Rectangle {
        id: disc

        anchors.centerIn: parent
        width: root.size
        height: root.size
        radius: root.size / 2
        // All: clear, so the gaps between the accounts show what's behind.
        color: root.account === "" ? "transparent" : root.tint

        // All: every account's picture in one circle.
        AccountsPicture {
            anchors.centerIn: parent
            visible: root.account === ""
            size: root.size
        }

        // The account's picture or first letter. Shown even with one
        // account; its card names it.
        AccountBadge {
            id: face

            anchors.centerIn: parent
            visible: root.account !== ""
            account: root.account
            size: root.size
            tip: ""
        }

        // The hover outline, over the picture.
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: "transparent"
            border.width: root.hovered ? 2 : 0
            border.color: Theme.alpha(Theme.m3onSurface, 0.35)
        }
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onContainsMouseChanged: Inbox.accountCard?.hover(root, root.account, containsMouse)
        onClicked: mouse => root.clicked(mouse)
    }
}
