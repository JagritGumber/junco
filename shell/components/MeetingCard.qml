import QtQuick
import QtQuick.Layouts
import qs.services

// The meeting an email invites to, read from its invite: when, how you join,
// and whether it's on your calendar (or a button to put it there).
Rectangle {
    id: root

    required property var meeting

    implicitHeight: content.implicitHeight + 22
    radius: Theme.cardRadius
    color: Theme.glassCard
    border.width: 1
    border.color: Theme.glassBorderSubtle

    RowLayout {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 11
        spacing: 10

        Icon {
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 2
            name: "calendar_month"
            size: 26
            color: Theme.m3onSurface
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3

                    Label {
                        text: "Meeting"
                        font.pixelSize: 15
                        weight: Font.Medium
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.meeting.when ?? ""
                        wrapMode: Text.Wrap
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                    }
                }

                // On your calendar already, or one click away.
                Rectangle {
                    Layout.alignment: Qt.AlignTop
                    visible: root.meeting.added ?? false
                    implicitWidth: addedRow.implicitWidth + 20
                    implicitHeight: 28
                    radius: 14
                    color: Theme.m3primary

                    Row {
                        id: addedRow

                        anchors.centerIn: parent
                        spacing: 4

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Added to calendar"
                            color: Theme.m3onPrimary
                            font.pixelSize: 12
                            weight: Font.Medium
                        }

                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: "check"
                            size: 15
                            color: Theme.m3onPrimary
                        }
                    }
                }

                Pill {
                    Layout.alignment: Qt.AlignTop
                    // Only for meetings still ahead.
                    visible: !(root.meeting.added ?? true) && !(root.meeting.past ?? true)
                    style: "tonal"
                    icon: "event_available"
                    text: "Add to calendar"
                    size: 32
                    fontSize: 12
                    onClicked: Inbox.addMeeting(root.meeting)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: (root.meeting.provider ?? "") !== "" || (root.meeting.where ?? "") !== "" || (root.meeting.eventLink ?? "") !== ""
                spacing: 8

                Icon {
                    name: (root.meeting.provider ?? "") !== "" ? "videocam" : "location_on"
                    size: 20
                    color: (root.meeting.provider ?? "") !== "" ? Theme.m3primary : Theme.m3onSurfaceVariant
                }

                Label {
                    Layout.fillWidth: true
                    text: root.meeting.provider || root.meeting.where || ""
                    elide: Text.ElideRight
                    font.pixelSize: 14
                }

                Pill {
                    visible: (root.meeting.link ?? "") !== ""
                    style: "filled"
                    text: "Join"
                    size: 32
                    fontSize: 12
                    // The engine only passes http(s); checked here again
                    // before anything goes to the system.
                    onClicked: if (/^https?:\/\//i.test(root.meeting.link ?? ""))
                        Qt.openUrlExternally(root.meeting.link)
                }

                Pill {
                    visible: (root.meeting.eventLink ?? "") !== ""
                    style: "tonal"
                    icon: "open_in_new"
                    text: "Open event"
                    size: 32
                    fontSize: 12
                    onClicked: if (/^https?:\/\//i.test(root.meeting.eventLink ?? ""))
                        Qt.openUrlExternally(root.meeting.eventLink)
                }
            }
        }
    }
}
