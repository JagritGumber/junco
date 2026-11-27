import QtQuick
import qs.services

// One account, small: its picture (the one you chose, else its own Google
// photo or Gravatar), or its first letter on its colour. Mail rows wear it on the corner of the sender's picture, so with
// several accounts you can tell which one each email came to. It hides
// itself while only one account is connected.
//
// A ring in the colour behind it separates it from the picture it overlaps;
// pass that colour as `ring` and a `ringWidth`.
Item {
    id: root

    property string account: ""
    // The disc's diameter, without the ring.
    property int size: 18
    property int ringWidth: 0
    property color ring: "transparent"
    // On hover: the account's address.
    property string tip: info?.email ?? ""

    readonly property var info: Inbox.accounts.find(a => a.id === account) ?? null
    readonly property color tint: Inbox.accountColor(account)
    readonly property bool hasPicture: picture.status === Image.Ready

    visible: account !== "" && Inbox.accounts.length > 1
    implicitWidth: size + 2 * ringWidth
    implicitHeight: size + 2 * ringWidth
    width: implicitWidth
    height: implicitHeight

    Rectangle {
        anchors.fill: parent
        visible: root.ringWidth > 0
        radius: width / 2
        color: root.ring
    }

    Rectangle {
        anchors.centerIn: parent
        width: root.size
        height: root.size
        radius: root.size / 2
        color: root.tint

        Label {
            anchors.centerIn: parent
            visible: !root.hasPicture
            // From the name the app calls it by (the "Work" chip), not
            // the address, which may start with any letter.
            text: (root.info?.label || root.info?.email || root.account).charAt(0).toUpperCase()
            color: Theme.pickInk(root.tint)
            font.pixelSize: Math.round(root.size * 0.45) + 1
            weight: Font.DemiBold
        }

        // Saved already round by the engine (account-picture, courier-avatars).
        Image {
            id: picture

            anchors.fill: parent
            visible: root.hasPicture
            source: root.info?.picture ? `file://${root.info.picture}?v=${Inbox.pictureVersion}` : ""
            sourceSize: Qt.size(root.size * 2, root.size * 2)
            fillMode: Image.PreserveAspectCrop
            cache: false
            asynchronous: true
        }
    }

    // A HoverHandler, not a MouseArea: the row under it keeps its hover and
    // its clicks.
    HoverHandler {
        id: hover
    }

    Loader {
        active: hover.hovered && root.tip !== ""
        sourceComponent: Tooltip {
            parent: root
            text: root.tip
        }
    }
}
