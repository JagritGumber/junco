import QtQuick
import QtQuick.Layouts
import qs.services

// Says why the calendar is empty when it isn't syncing, with the fix one
// click away (e.g. turning on the Google Calendar API).
Rectangle {
    id: root

    readonly property var status: Calendar.status
    readonly property bool problem: status.state === "error" || status.state === "signed-out"

    visible: problem || status.state === "never"
    implicitHeight: content.implicitHeight + 28
    radius: 20
    color: problem ? Theme.m3errorContainer : Theme.m3surfaceContainerHigh

    ColumnLayout {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 14
        spacing: 10

        RowLayout {
            spacing: 10

            Icon {
                name: root.problem ? "event_busy" : "sync"
                color: root.problem ? Theme.m3onErrorContainer : Theme.m3onSurfaceVariant
            }

            Label {
                Layout.fillWidth: true
                text: root.problem ? (root.status.message ?? "Calendar sync failed.") : "Copying your calendars…"
                wrapMode: Text.Wrap
                color: root.problem ? Theme.m3onErrorContainer : Theme.m3onSurfaceVariant
                font.pixelSize: 13
            }
        }

        RowLayout {
            visible: root.problem
            spacing: 8

            Rectangle {
                visible: (root.status.action ?? "") !== ""
                implicitWidth: fix.implicitWidth + 28
                implicitHeight: 34
                radius: 17
                color: Theme.m3onErrorContainer

                Label {
                    id: fix

                    anchors.centerIn: parent
                    text: "Turn it on"
                    color: Theme.m3errorContainer
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Qt.openUrlExternally(root.status.action)
                }
            }

            Rectangle {
                implicitWidth: retry.implicitWidth + 28
                implicitHeight: 34
                radius: 17
                color: "transparent"
                border.width: 1
                border.color: Theme.m3onErrorContainer

                Label {
                    id: retry

                    anchors.centerIn: parent
                    text: "Try again"
                    color: Theme.m3onErrorContainer
                    font.pixelSize: 13
                    font.weight: Font.Medium
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Calendar.syncNow()
                }
            }
        }
    }
}
