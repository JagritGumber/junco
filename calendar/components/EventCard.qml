import QtQuick
import QtQuick.Layouts
import qs.services

// Compact frosted-glass event card in the right-side Today & Actionables panel:
// calendar colour dot, title, time/location/attendees, one-click Join, Prep, and More.
Rectangle {
    id: root

    required property var event
    property bool dimmed: false

    signal edit
    signal more(Item button)
    signal addPrep

    readonly property string metaLine: [
        event.startDay === event.endDay ? (event.time ?? "") : `${event.time ?? ""}, until ${Calendar.format(event.endDay, "d MMM")}`,
        event.where ?? "",
        Calendar.attendeeLabel(event)
    ].filter(part => part !== "").join(" · ")

    implicitHeight: content.implicitHeight + 22
    radius: Theme.cardRadius
    color: Theme.glassCard
    border.width: Theme.glass ? 0 : 1
    border.color: Theme.glassBorderSubtle
    opacity: dimmed ? 0.68 : 1.0

    GlassEdge {
        visible: Theme.glass
        radius: root.radius
        side: false
    }

    ColumnLayout {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 12
        anchors.rightMargin: 10
        anchors.topMargin: 11
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Rectangle {
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 5
                width: 8
                height: 8
                radius: 4
                color: root.event.color || Theme.m3primary
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                Label {
                    Layout.fillWidth: true
                    text: root.event.title ?? ""
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    font.pixelSize: 13
                    weight: Font.Medium
                }

                Label {
                    Layout.fillWidth: true
                    text: root.metaLine
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }

            IconButton {
                id: moreButton

                Layout.alignment: Qt.AlignTop
                icon: "more_horiz"
                tip: "More options"
                size: 28
                onClicked: root.more(moreButton)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 16
            visible: !root.dimmed
            spacing: 6

            Pill {
                visible: (root.event.video ?? "") !== ""
                style: "filled"
                icon: "videocam"
                text: "Join"
                size: 28
                fontSize: 12
                // The engine passes only validated web links; checked again here.
                onClicked: if (/^https?:\/\//i.test(root.event.video ?? ""))
                    Qt.openUrlExternally(root.event.video)
            }

            Pill {
                style: "tonal"
                icon: "checklist"
                text: "Prep"
                size: 28
                fontSize: 12
                tip: "Add prep actionable"
                onClicked: root.addPrep()
            }

            Item {
                Layout.fillWidth: true
            }
        }
    }
}
