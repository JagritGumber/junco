import QtQuick
import QtQuick.Layouts
import qs.services

// An event in the day panel: an icon for what it is, the title, when and
// where, then Edit and More. Events on this PC edit here; Google's open in
// Google Calendar, since Courier only has read access to them.
Rectangle {
    id: root

    required property var event

    signal edit
    signal more(Item button)

    implicitHeight: content.implicitHeight + 36
    radius: 22
    color: Theme.m3surfaceContainer

    Rectangle {
        x: 0
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: 14
        anchors.bottomMargin: 14
        width: 4
        radius: 2
        color: root.event.color || Theme.m3primary
    }

    ColumnLayout {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 20
        anchors.rightMargin: 16
        anchors.topMargin: 18
        spacing: 14

        RowLayout {
            spacing: 14

            Rectangle {
                Layout.alignment: Qt.AlignTop
                implicitWidth: 48
                implicitHeight: 48
                radius: 24
                color: Theme.m3surfaceContainerHighest

                Icon {
                    anchors.centerIn: parent
                    name: Calendar.iconFor(root.event)
                    size: 24
                    color: Theme.m3onSurface
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5

                Label {
                    Layout.fillWidth: true
                    text: root.event.title
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }

                RowLayout {
                    spacing: 6

                    Icon {
                        name: root.event.allDay ? "calendar_today" : "schedule"
                        size: 18
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.event.startDay === root.event.endDay ? root.event.time : `${root.event.time}, until ${Calendar.format(root.event.endDay, "d MMM")}`
                        elide: Text.ElideRight
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                    }
                }

                RowLayout {
                    visible: root.event.where !== ""
                    spacing: 6

                    Icon {
                        name: "location_on"
                        size: 18
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.event.where
                        elide: Text.ElideRight
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                    }
                }
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8

            Pill {
                visible: root.event.video !== ""
                style: "filled"
                icon: "videocam"
                text: "Join"
                size: 38
                fontSize: 13
                // The engine passes only web links; checked again here.
                onClicked: if (/^https?:\/\//i.test(root.event.video ?? ""))
                    Qt.openUrlExternally(root.event.video)
            }

            Pill {
                visible: root.event.local || root.event.link !== ""
                style: "outlined"
                icon: root.event.local ? "edit" : "open_in_new"
                text: root.event.local ? "Edit" : "Edit in Google"
                size: 38
                fontSize: 13
                onClicked: root.edit()
            }

            Pill {
                id: moreButton

                style: "outlined"
                icon: "more_horiz"
                text: "More"
                size: 38
                fontSize: 13
                onClicked: root.more(moreButton)
            }
        }
    }
}
