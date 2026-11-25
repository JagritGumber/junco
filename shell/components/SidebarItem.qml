import QtQuick
import QtQuick.Layouts
import qs.services

// One row of a sidebar: an icon, a name and, when there is one, a count.
Rectangle {
    id: root

    property string icon
    property string text
    property int count: 0
    property bool active: false

    signal clicked

    implicitHeight: 38
    radius: 14
    color: active ? Theme.m3secondaryContainer : (area.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.06) : "transparent")

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 10
        spacing: 14

        Icon {
            name: root.icon
            size: 22
            fill: root.active ? 1 : 0
            color: root.active ? Theme.m3onSecondaryContainer : Theme.m3onSurfaceVariant
        }

        Label {
            Layout.fillWidth: true
            text: root.text
            elide: Text.ElideRight
            color: root.active ? Theme.m3onSecondaryContainer : Theme.m3onSurface
            font.pixelSize: 14
            font.weight: root.active ? Font.DemiBold : Font.Normal
        }

        Rectangle {
            visible: root.count > 0
            implicitWidth: Math.max(24, number.implicitWidth + 14)
            implicitHeight: 22
            radius: 11
            color: root.active ? Theme.alpha(Theme.m3onSecondaryContainer, 0.14) : Theme.m3surfaceContainerHighest

            Label {
                id: number

                anchors.centerIn: parent
                text: root.count > 999 ? "999+" : root.count
                color: root.active ? Theme.m3onSecondaryContainer : Theme.m3onSurfaceVariant
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
        }
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
