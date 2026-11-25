import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Framing another picture for an account, the way Caelestia's profile picture
// cropper does: drag to move, scroll (or the zoom bar) to zoom; the circle is
// what the account will wear. The engine cuts that square from the original
// image (account-picture --crop), so it stays sharp. Opened by
// Inbox.setAccountPicture after the file picker.
Item {
    id: root

    readonly property var job: Inbox.pictureCrop
    readonly property var info: Inbox.accounts.find(a => a.id === job?.account) ?? null

    // The square the circle sits in, on screen.
    readonly property int view: 320
    readonly property real naturalWidth: picture.implicitWidth
    readonly property real naturalHeight: picture.implicitHeight
    readonly property bool ready: picture.status === Image.Ready && naturalWidth > 0 && naturalHeight > 0
    // Scale at which the picture just covers the square; zoom multiplies it.
    readonly property real coverScale: ready ? Math.max(view / naturalWidth, view / naturalHeight) : 1
    readonly property real maxZoom: 8
    property real zoom: 1
    readonly property real factor: coverScale * zoom
    // The picture's top-left corner in the square.
    property real offsetX: 0
    property real offsetY: 0
    property bool saving: false
    property string problem: ""

    function close(): void {
        Inbox.pictureCrop = null;
        saving = false;
        problem = "";
    }

    // Keeps the square covered: the picture never slides off an edge.
    function clampOffsets(): void {
        offsetX = Math.min(0, Math.max(view - naturalWidth * factor, offsetX));
        offsetY = Math.min(0, Math.max(view - naturalHeight * factor, offsetY));
    }

    // Zooms keeping the point (px, py) of the square still.
    function zoomTo(next: real, px: real, py: real): void {
        next = Math.max(1, Math.min(maxZoom, next));
        const imageX = (px - offsetX) / factor;
        const imageY = (py - offsetY) / factor;
        zoom = next;
        offsetX = px - imageX * factor;
        offsetY = py - imageY * factor;
        clampOffsets();
    }

    function centre(): void {
        // Computed here, not read from coverScale: this runs as the picture
        // loads, before that binding has caught up.
        const cover = Math.max(view / naturalWidth, view / naturalHeight);
        zoom = 1;
        offsetX = (view - naturalWidth * cover) / 2;
        // Portraits keep their top third in view: that's usually the face.
        offsetY = naturalHeight > naturalWidth ? -(naturalHeight * cover - view) / 6 : (view - naturalHeight * cover) / 2;
        clampOffsets();
    }

    // The square in the image's own pixels: [x, y, size].
    function crop(): var {
        const size = Math.max(1, Math.round(view / factor));
        const x = Math.max(0, Math.min(Math.round(naturalWidth) - size, Math.round(-offsetX / factor)));
        const y = Math.max(0, Math.min(Math.round(naturalHeight) - size, Math.round(-offsetY / factor)));
        return [x, y, size];
    }

    function save(): void {
        if (!ready || saving)
            return;
        saving = true;
        problem = "";
        const account = job.account;
        Inbox.saveAccountPicture(account, job.source, crop(), error => {
            if (Inbox.pictureCrop?.account !== account)
                return;
            saving = false;
            if (error)
                problem = error;
            else
                close();
        });
    }

    visible: job !== null
    z: 97
    onReadyChanged: if (ready)
        Qt.callLater(centre)

    Shortcut {
        sequence: "Escape"
        enabled: root.visible
        onActivated: root.close()
    }

    Shortcut {
        sequences: ["Return", "Enter"]
        enabled: root.visible
        onActivated: root.save()
    }

    Rectangle {
        anchors.fill: parent
        radius: 28
        color: Theme.alpha("#000000", 0.45)

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: if (!root.saving)
                root.close()
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: root.view + 48
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
            spacing: 12

            RowLayout {
                Layout.fillWidth: true

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Label {
                        Layout.fillWidth: true
                        text: "Account picture"
                        font.pixelSize: 22
                        font.weight: Font.Medium
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.info?.email ?? ""
                        elide: Text.ElideRight
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                    }
                }

                IconButton {
                    Layout.alignment: Qt.AlignTop
                    icon: "close"
                    tip: "Cancel (Esc)"
                    size: 38
                    onClicked: root.close()
                }
            }

            Label {
                text: "Drag to move it; scroll or use the bar below to zoom"
                color: Theme.m3onSurfaceVariant
            }

            // The picture, the circle that will show, and the dimmed rest.
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                implicitWidth: root.view
                implicitHeight: root.view
                color: Theme.m3surfaceContainerHighest
                clip: true

                Image {
                    id: picture

                    x: root.offsetX
                    y: root.offsetY
                    width: root.naturalWidth * root.factor
                    height: root.naturalHeight * root.factor
                    // Each part escaped, so a # or ? in a file name stays a name.
                    source: root.job ? "file://" + root.job.source.split("/").map(encodeURIComponent).join("/") : ""
                    autoTransform: true
                    asynchronous: true
                    cache: false
                    smooth: true
                    mipmap: true
                }

                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        const context = getContext("2d");
                        context.reset();
                        context.fillStyle = Qt.rgba(0, 0, 0, 0.55);
                        context.fillRule = Qt.OddEvenFill;
                        context.beginPath();
                        context.rect(0, 0, width, height);
                        context.arc(width / 2, height / 2, width / 2 - 1, 0, 2 * Math.PI);
                        context.fill();
                        context.strokeStyle = Qt.rgba(1, 1, 1, 0.85);
                        context.lineWidth = 2;
                        context.beginPath();
                        context.arc(width / 2, height / 2, width / 2 - 1, 0, 2 * Math.PI);
                        context.stroke();
                    }
                }

                MouseArea {
                    property real lastX
                    property real lastY

                    anchors.fill: parent
                    enabled: root.ready
                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    onPressed: mouse => {
                        lastX = mouse.x;
                        lastY = mouse.y;
                    }
                    onPositionChanged: mouse => {
                        root.offsetX += mouse.x - lastX;
                        root.offsetY += mouse.y - lastY;
                        lastX = mouse.x;
                        lastY = mouse.y;
                        root.clampOffsets();
                    }
                    onWheel: wheel => root.zoomTo(root.zoom * Math.pow(1.0015, wheel.angleDelta.y), wheel.x, wheel.y)
                }

                Label {
                    anchors.centerIn: parent
                    visible: picture.status === Image.Error
                    text: "Couldn't open that picture"
                }
            }

            // Zoom, on a log scale so each step feels the same.
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                IconButton {
                    icon: "zoom_out"
                    tip: "Zoom out"
                    size: 34
                    onClicked: root.zoomTo(root.zoom / 1.25, root.view / 2, root.view / 2)
                }

                Item {
                    id: track

                    Layout.fillWidth: true
                    implicitHeight: 24

                    readonly property real position: Math.log(root.zoom) / Math.log(root.maxZoom)

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        height: 4
                        radius: 2
                        color: Theme.m3surfaceContainerHighest

                        Rectangle {
                            width: parent.width * track.position
                            height: parent.height
                            radius: 2
                            color: Theme.m3primary
                        }
                    }

                    Rectangle {
                        x: track.position * (track.width - width)
                        anchors.verticalCenter: parent.verticalCenter
                        width: 16
                        height: 16
                        radius: 8
                        color: Theme.m3primary
                    }

                    MouseArea {
                        function follow(mouse: var): void {
                            const at = Math.max(0, Math.min(1, mouse.x / track.width));
                            root.zoomTo(Math.pow(root.maxZoom, at), root.view / 2, root.view / 2);
                        }

                        anchors.fill: parent
                        enabled: root.ready
                        cursorShape: Qt.PointingHandCursor
                        onPressed: mouse => follow(mouse)
                        onPositionChanged: mouse => follow(mouse)
                    }
                }

                IconButton {
                    icon: "zoom_in"
                    tip: "Zoom in"
                    size: 34
                    onClicked: root.zoomTo(root.zoom * 1.25, root.view / 2, root.view / 2)
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
                    style: "text"
                    text: "Cancel"
                    onClicked: root.close()
                }

                Pill {
                    style: "filled"
                    icon: root.saving ? "progress_activity" : "check"
                    text: root.saving ? "Saving…" : "Use this picture"
                    enabled: root.ready && !root.saving
                    opacity: enabled ? 1 : 0.5
                    onClicked: root.save()
                }
            }
        }
    }
}
