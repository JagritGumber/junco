import QtQuick
import QtQuick.Layouts
import qs.services

// One event as a compact card: optionally its date ("Mon / 14 Dec"), a bar in
// its calendar's colour, the title, and when. Coming up, the agenda and search
// results use it; a click goes to that day.
Rectangle {
    id: root

    required property var event
    property bool showDate: false

    signal clicked

    implicitHeight: Math.max(64, body.implicitHeight + 24)
    radius: 18
    color: area.containsMouse ? Theme.m3surfaceContainerHigh : Theme.m3surfaceContainer

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: root.showDate ? 12 : 14
        anchors.rightMargin: 14
        anchors.topMargin: 12
        anchors.bottomMargin: 12
        spacing: 14

        ColumnLayout {
            Layout.preferredWidth: 58
            visible: root.showDate
            spacing: 0

            Label {
                Layout.alignment: Qt.AlignHCenter
                text: Calendar.format(root.event.startDay, "ddd")
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 13
            }

            Label {
                Layout.alignment: Qt.AlignHCenter
                text: Calendar.format(root.event.startDay, "d MMM")
                font.pixelSize: 15
                font.weight: Font.Medium
            }
        }

        Rectangle {
            Layout.fillHeight: true
            implicitWidth: 4
            radius: 2
            color: root.event.color || Theme.m3primary
        }

        ColumnLayout {
            id: body

            Layout.fillWidth: true
            spacing: 4

            Label {
                Layout.fillWidth: true
                text: root.event.title
                elide: Text.ElideRight
                font.pixelSize: 15
                font.weight: Font.Medium
            }

            RowLayout {
                spacing: 6

                Icon {
                    name: root.event.allDay ? "calendar_today" : "schedule"
                    size: 16
                }

                Label {
                    Layout.fillWidth: true
                    text: [root.event.time, root.event.where].filter(part => part).join("  ·  ")
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }
            }
        }
    }
}
