import QtQuick
import QtQuick.Layouts
import qs.services

// A file sent with an email: look at it in the system viewer, or save it to
// Downloads.
Rectangle {
    id: root

    required property string messageId
    required property var file
    // Deleted mail isn't on this PC: its files open once it's restored.
    property bool inTrash: false

    readonly property string kind: {
        const type = file.type ?? "";
        const name = (file.name ?? "").toLowerCase();
        if (type === "application/pdf" || name.endsWith(".pdf"))
            return "picture_as_pdf";
        if (type.startsWith("image/"))
            return "image";
        if (type.startsWith("video/"))
            return "movie";
        if (type.startsWith("audio/"))
            return "audio_file";
        if (/zip|rar|7z|tar|gzip/.test(type) || /\.(zip|rar|7z|tar|gz)$/.test(name))
            return "folder_zip";
        return "description";
    }

    implicitHeight: 66
    radius: 18
    color: Theme.m3surfaceContainer
    border.width: 1
    border.color: Theme.alpha(Theme.m3outlineVariant, 0.6)

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 10
        spacing: 14

        Icon {
            name: root.kind
            size: 26
            color: Theme.m3onSurface
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2

            Label {
                Layout.fillWidth: true
                text: root.file.name
                elide: Text.ElideMiddle
                font.pixelSize: 14
                font.weight: Font.Medium
            }

            Label {
                text: root.file.size
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 12
            }
        }

        Label {
            visible: root.inTrash
            text: "Restore to open"
            color: Theme.m3onSurfaceVariant
            font.pixelSize: 12
        }

        IconButton {
            visible: !root.inTrash
            icon: "visibility"
            tip: "Open in the viewer"
            size: 40
            onClicked: Inbox.previewAttachment(root.messageId, root.file.index)
        }

        IconButton {
            visible: !root.inTrash
            icon: "download"
            tip: "Save to Downloads"
            size: 40
            onClicked: Inbox.saveAttachment(root.messageId, root.file.index)
        }
    }
}
