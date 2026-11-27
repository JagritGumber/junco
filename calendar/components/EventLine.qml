import QtQuick
import QtQuick.Layouts
import qs.services

// Compact frosted-glass event row for Coming Up, Agenda, and search results.
Rectangle {
    id: root

    required property var event
    property bool showDate: false

    signal clicked

    implicitHeight: Math.max(58, body.implicitHeight + 24)
    radius: Theme.cardRadius
    color: area.containsMouse ? Theme.glassCardHover : Theme.glassCard
    border.width: Theme.glass ? 0 : 1
    border.color: Theme.glassBorderSubtle

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
        spacing: 12

        ColumnLayout {
            Layout.preferredWidth: 46
            visible: root.showDate
            spacing: 0

            Label {
                Layout.alignment: Qt.AlignHCenter
                text: Calendar.format(root.event.startDay, "ddd")
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 11
            }

            Label {
                Layout.alignment: Qt.AlignHCenter
                text: Calendar.format(root.event.startDay, "d MMM")
                font.pixelSize: 12
                weight: Font.Medium
            }
        }

        Rectangle {
            Layout.fillHeight: true
            implicitWidth: 3
            radius: 1.5
            color: root.event.color || Theme.m3primary
        }

        ColumnLayout {
            id: body

            Layout.fillWidth: true
            spacing: 2

            Label {
                Layout.fillWidth: true
                text: root.event.title
                elide: Text.ElideRight
                font.pixelSize: 13
                weight: Font.Medium
            }

            RowLayout {
                spacing: 4

                Icon {
                    name: root.event.allDay ? "calendar_today" : "schedule"
                    size: 13
                }

                Label {
                    Layout.fillWidth: true
                    text: [root.event.time, root.event.where].filter(part => part).join("  ·  ")
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 11
                }
            }
        }
    }
}
