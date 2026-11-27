import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// One message: day divider pill, then a frosted-glass chat bubble or compact
// update card.
Column {
    id: root

    property var message
    property var previous
    readonly property bool mine: message.from === "me"
    readonly property bool newDay: !previous || previous.day !== message.day
    readonly property real maxBubble: Math.min(width * 0.78, 660)
    readonly property bool openable: (message.id ?? "") !== ""

    spacing: 8

    Item {
        width: root.width
        height: root.newDay ? 30 : 0
        visible: root.newDay

        Rectangle {
            anchors.centerIn: parent
            implicitHeight: 22
            implicitWidth: day.implicitWidth + 20
            radius: 11
            color: Theme.glassControl
            border.width: Theme.glass ? 0 : 1
            border.color: Theme.glassBorderSubtle

            Label {
                id: day

                anchors.centerIn: parent
                text: root.message.day ?? ""
                color: Theme.darkGlass ? Theme.alpha(Theme.m3onSurface, 0.86) : Theme.m3onSurfaceVariant
                font.pixelSize: 11
                weight: Font.Medium
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

                readonly property color ink: root.mine ? Theme.glassBubbleMineInk : Theme.m3onSurface

                anchors.right: root.mine ? parent.right : undefined
                anchors.left: root.mine ? undefined : parent.left
                implicitWidth: Math.min(root.maxBubble, Math.max(content.implicitWidth, 96) + 36)
                implicitHeight: content.implicitHeight + 28
                color: root.mine ? Theme.glassBubbleMine : Theme.glassBubbleOther
                border.width: Theme.glass ? 0 : 1
                border.color: root.mine ? Theme.glassBubbleMineBorder : Theme.glassBubbleOtherBorder
                topLeftRadius: 16
                topRightRadius: 16
                bottomLeftRadius: root.mine ? 16 : 6
                bottomRightRadius: root.mine ? 6 : 16

                // Glass: crisp top catch-light, no outline and no vertical stripe.
                GlassEdge {
                    visible: Theme.glass
                    radius: 16
                    fade: 11
                    side: false
                    light: Theme.alpha(Theme.pureWhite, Theme.dark ? 0.18 : 0.22)
                }

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
                    anchors.leftMargin: 18
                    anchors.rightMargin: 18
                    anchors.topMargin: 14
                    spacing: 6

                    Label {
                        visible: !!root.message.subject
                        Layout.maximumWidth: root.maxBubble - 36
                        text: root.message.subject ?? ""
                        color: body.ink
                        font.pixelSize: 14
                        weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Label {
                        Layout.maximumWidth: root.maxBubble - 36
                        Layout.fillWidth: true
                        text: {
                            const htmlBody = (root.message.body ?? "").trim() || (root.message.attachments ?? []).length > 0
                                ? Inbox.linked(root.message.body, Theme.m3primary)
                                : "<i>No text</i>";
                            return `<style>body,p,div{font-family:'Adwaita Sans',sans-serif;}b,strong{font-weight:600;}</style>${htmlBody}`;
                        }
                        textFormat: Text.RichText
                        linkColor: Theme.m3primary
                        onLinkActivated: link => Qt.openUrlExternally(link.replace(/&amp;/g, "&"))
                        color: body.ink
                        wrapMode: Text.Wrap
                        font.pixelSize: 14
                        lineHeight: 1.38
                    }

                    Repeater {
                        model: root.message.attachments ?? []

                        delegate: Rectangle {
                            id: file

                            required property var modelData
                            required property int index
                            readonly property string kind: modelData.name.endsWith(".pdf") ? "description" : "image"

                            Layout.topMargin: 3
                            Layout.preferredWidth: Math.min(root.maxBubble - 26, 320)
                            implicitHeight: 46
                            radius: Theme.controlRadius
                            color: Theme.alpha(body.ink, 0.08)
                            border.width: 1
                            border.color: Theme.glassBorderSubtle

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 6
                                spacing: 9

                                Icon {
                                    name: file.kind
                                    size: 20
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
                                        font.pixelSize: 13
                                        weight: Font.Medium
                                    }

                                    Label {
                                        text: file.modelData.size
                                        color: Theme.alpha(body.ink, 0.65)
                                        font.pixelSize: 11
                                    }
                                }

                                IconButton {
                                    icon: "download"
                                    tip: "Save to Downloads"
                                    iconColor: body.ink
                                    size: 30
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
                            tabular: true
                            text: root.message.time
                            color: Theme.alpha(body.ink, 0.65)
                            font.pixelSize: 11
                        }

                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: root.mine
                            name: root.message.failed ? "error" : root.message.sending ? "schedule" : "done_all"
                            size: 14
                            color: root.message.failed ? Theme.m3error : Theme.alpha(body.ink, 0.72)
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
                info: [Theme.glassControl, Theme.m3onSurfaceVariant, "Update"]
            })[root.message.status] ?? [Theme.glassControl, Theme.m3onSurfaceVariant, "Update"]

            implicitWidth: Math.min(root.width, 740)
            implicitHeight: 64
            radius: Theme.cardRadius
            color: open.containsMouse ? Theme.glassCardHover : Theme.glassCard
            border.width: Theme.glass ? 0 : 1
            border.color: Theme.glassBorderSubtle

            Behavior on color {
                ColorAnimation {
                    duration: Theme.animFast
                    easing.type: Easing.OutCubic
                }
            }

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
                anchors.rightMargin: 14
                spacing: 12

                Rectangle {
                    implicitWidth: 34
                    implicitHeight: 34
                    radius: 10
                    color: card.tone[0]

                    Icon {
                        anchors.centerIn: parent
                        name: root.message.icon
                        size: 18
                        fill: 1
                        color: card.tone[1]
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1

                    Label {
                        Layout.fillWidth: true
                        text: root.message.title
                        elide: Text.ElideRight
                        font.pixelSize: 13
                        weight: Font.Medium
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.message.meta
                        elide: Text.ElideRight
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 11
                    }
                }

                Rectangle {
                    implicitHeight: 20
                    implicitWidth: status.implicitWidth + 14
                    radius: 10
                    color: card.tone[0]

                    Label {
                        id: status

                        anchors.centerIn: parent
                        text: card.tone[2]
                        color: card.tone[1]
                        font.pixelSize: 10
                        weight: Font.Medium
                    }
                }

                Label {
                    text: root.message.time
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 11
                }
            }
        }
    }
}
