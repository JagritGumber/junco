import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// One message: a day divider when the day changes, then a chat bubble for
// people or a compact card for machine updates (GitHub, Linear, newsletters).
Column {
    id: root

    property var message
    property var previous
    readonly property bool mine: message.from === "me"
    readonly property bool newDay: !previous || previous.day !== message.day
    readonly property real maxBubble: Math.min(width * 0.68, 620)
    // Sent bubbles waiting for the server have no id yet.
    readonly property bool openable: (message.id ?? "") !== ""

    spacing: 10

    Item {
        width: root.width
        height: root.newDay ? 34 : 0
        visible: root.newDay

        Rectangle {
            anchors.centerIn: parent
            implicitHeight: 26
            implicitWidth: day.implicitWidth + 24
            radius: 13
            color: Theme.m3surfaceContainerHigh

            Label {
                id: day

                anchors.centerIn: parent
                text: root.message.day ?? ""
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 12
                font.weight: Font.Medium
            }
        }
    }

    Loader {
        width: root.width
        sourceComponent: root.message.kind === "update" ? updateCard : bubble
    }

    Component {
        id: bubble

        Item {
            implicitHeight: body.implicitHeight

            Rectangle {
                id: body

                readonly property color ink: root.mine ? Theme.m3onPrimaryContainer : Theme.m3onSurface

                anchors.right: root.mine ? parent.right : undefined
                anchors.left: root.mine ? undefined : parent.left
                implicitWidth: Math.min(root.maxBubble, Math.max(content.implicitWidth, 96) + 40)
                implicitHeight: content.implicitHeight + 28
                color: root.mine ? Theme.m3primaryContainer : Theme.m3surfaceContainerHigh
                topLeftRadius: 22
                topRightRadius: 22
                bottomLeftRadius: root.mine ? 22 : 6
                bottomRightRadius: root.mine ? 6 : 22

                // Under the text, so links still take their own clicks.
                MouseArea {
                    anchors.fill: parent
                    enabled: root.openable
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Inbox.openMessage(root.message.id, true)
                }

                ColumnLayout {
                    id: content

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 20
                    anchors.topMargin: 14
                    spacing: 6

                    Label {
                        visible: !!root.message.subject
                        Layout.maximumWidth: root.maxBubble - 40
                        text: root.message.subject ?? ""
                        color: body.ink
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Label {
                        Layout.maximumWidth: root.maxBubble - 40
                        Layout.fillWidth: true
                        // An email sent without any words (it happens from
                        // phones) says so instead of drawing an empty bubble.
                        text: (root.message.body ?? "").trim() || (root.message.attachments ?? []).length > 0 ? Inbox.linked(root.message.body, "") : "<i>No text</i>"
                        textFormat: Text.StyledText
                        linkColor: root.mine ? Theme.m3onPrimaryContainer : Theme.m3primary
                        onLinkActivated: link => Qt.openUrlExternally(link.replace(/&amp;/g, "&"))
                        color: body.ink
                        wrapMode: Text.Wrap
                        font.pixelSize: 15
                        lineHeight: 1.15
                    }

                    Repeater {
                        model: root.message.attachments ?? []

                        delegate: Rectangle {
                            id: file

                            required property var modelData
                            required property int index
                            readonly property string kind: modelData.name.endsWith(".pdf") ? "description" : "image"

                            Layout.topMargin: 4
                            Layout.preferredWidth: Math.min(root.maxBubble - 40, 360)
                            implicitHeight: 62
                            radius: 18
                            color: Theme.alpha(body.ink, 0.08)

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 10
                                spacing: 12

                                Icon {
                                    name: file.kind
                                    size: 24
                                    color: body.ink
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1

                                    Label {
                                        Layout.fillWidth: true
                                        text: file.modelData.name
                                        elide: Text.ElideMiddle
                                        color: body.ink
                                        font.pixelSize: 14
                                        font.weight: Font.Medium
                                    }

                                    Label {
                                        text: file.modelData.size
                                        color: Theme.alpha(body.ink, 0.65)
                                        font.pixelSize: 12
                                    }
                                }

                                IconButton {
                                    icon: "download"
                                    tip: "Save to Downloads"
                                    iconColor: body.ink
                                    size: 38
                                    visible: root.openable
                                    onClicked: Inbox.saveAttachment(root.message.id, file.index)
                                }
                            }
                        }
                    }

                    Row {
                        Layout.alignment: Qt.AlignRight
                        spacing: 4

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.message.time
                            color: Theme.alpha(body.ink, 0.6)
                            font.pixelSize: 11
                        }

                        // Delivery state of what you sent: sending, sent, or failed.
                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: root.mine
                            name: root.message.failed ? "error" : root.message.sending ? "schedule" : "done_all"
                            size: 16
                            color: root.message.failed ? Theme.m3error : Theme.alpha(body.ink, 0.7)
                        }
                    }
                }
            }
        }
    }

    Component {
        id: updateCard

        Rectangle {
            id: card

            readonly property var tone: ({
                review: [Theme.m3tertiaryContainer, Theme.m3onTertiaryContainer, "Review"],
                merged: [Theme.m3primaryContainer, Theme.m3onPrimaryContainer, "Merged"],
                failed: [Theme.m3errorContainer, Theme.m3onErrorContainer, "Failed"],
                info: [Theme.m3surfaceContainerHighest, Theme.m3onSurfaceVariant, "Update"]
            })[root.message.status] ?? [Theme.m3surfaceContainerHighest, Theme.m3onSurfaceVariant, "Update"]

            implicitWidth: Math.min(root.width, 720)
            implicitHeight: 70
            radius: 20
            color: open.containsMouse ? Theme.m3surfaceContainerHigh : Theme.m3surfaceContainer

            MouseArea {
                id: open

                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: Inbox.openMessage(root.message.id, true)
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 16
                spacing: 14

                Rectangle {
                    implicitWidth: 42
                    implicitHeight: 42
                    radius: 14
                    color: card.tone[0]

                    Icon {
                        anchors.centerIn: parent
                        name: root.message.icon
                        fill: 1
                        color: card.tone[1]
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Label {
                        Layout.fillWidth: true
                        text: root.message.title
                        elide: Text.ElideRight
                        font.pixelSize: 14
                        font.weight: Font.Medium
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.message.meta
                        elide: Text.ElideRight
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 12
                    }
                }

                Rectangle {
                    implicitHeight: 24
                    implicitWidth: status.implicitWidth + 18
                    radius: 12
                    color: card.tone[0]

                    Label {
                        id: status

                        anchors.centerIn: parent
                        text: card.tone[2]
                        color: card.tone[1]
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                }

                Label {
                    text: root.message.time
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }
        }
    }
}
