import QtQuick
import QtQuick.Layouts
import qs.services

// Spotlight card for Today's next upcoming (or currently live) meeting:
// relative countdown, calendar colour dot, time range, location/attendees,
// one-click Join button, and one-click Add prep actionable.
Rectangle {
    id: root

    required property var event

    signal join(string url)
    signal addPrep
    signal more(Item button)

    readonly property bool live: Calendar.isEventLive(event, Calendar.nowMs)
    readonly property string countdown: Calendar.countdownLabel(event, Calendar.nowMs)
    readonly property string details: [event.where ?? "", Calendar.attendeeLabel(event)].filter(part => part !== "").join(" · ")
    readonly property color accent: event.color || Theme.m3primary

    // Live status uses the dynamic complementary pair; upcoming countdown uses
    // the dynamic primary container, both luminance-tuned for >= 4.5:1 contrast.
    readonly property color badgeBg: live ? Theme.m3tertiaryContainer : Theme.m3primaryContainer
    readonly property color badgeInk: live ? Theme.m3onTertiaryContainer : Theme.m3onPrimaryContainer

    implicitHeight: content.implicitHeight + 26
    radius: 14
    color: Theme.glassControl
    border.width: Theme.glass ? 0 : 1
    border.color: Theme.glassBorderSubtle

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
        anchors.leftMargin: 14
        anchors.rightMargin: 12
        anchors.topMargin: 13
        spacing: 9

        // Calendar dot + name on the left; live/upcoming countdown badge on the right
        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Row {
                spacing: 6

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 8
                    height: 8
                    radius: 4
                    color: root.accent
                }

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.event.calendar || "Next up"
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                    weight: Font.Medium
                }
            }

            Item {
                Layout.fillWidth: true
            }

            Rectangle {
                implicitWidth: countdownRow.implicitWidth + 14
                implicitHeight: 22
                radius: 11
                color: root.badgeBg

                Row {
                    id: countdownRow

                    anchors.centerIn: parent
                    spacing: 5

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: root.live
                        width: 6
                        height: 6
                        radius: 3
                        color: root.badgeInk
                    }

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.countdown
                        color: root.badgeInk
                        font.pixelSize: 11
                        weight: Font.Medium
                    }
                }
            }
        }

        // Title
        Label {
            Layout.fillWidth: true
            text: root.event.title ?? ""
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
            font.pixelSize: 15
            weight: Font.Medium
            lineHeight: 1.15
        }

        // Time range & location / attendee count
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Icon {
                    name: "schedule"
                    size: 15
                    color: Theme.m3onSurfaceVariant
                }

                Label {
                    Layout.fillWidth: true
                    text: root.event.time ?? ""
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: root.details !== ""
                spacing: 6

                Icon {
                    name: (root.event.video ?? "") !== "" ? "videocam" : "location_on"
                    size: 15
                    color: Theme.m3onSurfaceVariant
                }

                Label {
                    Layout.fillWidth: true
                    text: root.details
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }
        }

        // Quick actions: one-click Join + one-click Add prep + More
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 2
            spacing: 6

            Pill {
                visible: (root.event.video ?? "") !== ""
                style: "filled"
                icon: "videocam"
                text: "Join"
                size: 30
                fontSize: 12
                onClicked: root.join(root.event.video)
            }

            Pill {
                style: "tonal"
                icon: "checklist"
                text: "Add prep"
                size: 30
                fontSize: 12
                tip: "Add a prep actionable for this meeting"
                onClicked: root.addPrep()
            }

            Item {
                Layout.fillWidth: true
            }

            IconButton {
                id: moreButton

                icon: "more_horiz"
                tip: "More options"
                size: 28
                onClicked: root.more(moreButton)
            }
        }
    }
}
