import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Events as a list of days: the date on the left, that day's events beside
// it. The Agenda view shows the month this way; search shows its matches.
Item {
    id: root

    property var events: []
    // Days before this one fold into it (an event that began last month).
    property string from: ""
    property string emptyText: "Nothing planned."

    signal picked(var event)

    readonly property var groups: {
        const days = [];
        const index = {};
        for (const event of events) {
            const day = root.from !== "" && event.startDay < root.from ? root.from : event.startDay;
            if (index[day] === undefined) {
                index[day] = days.length;
                days.push({ day: day, events: [] });
            }
            days[index[day]].events.push(event);
        }
        return days;
    }

    Label {
        anchors.centerIn: parent
        visible: root.groups.length === 0
        text: root.emptyText
        color: Theme.m3onSurfaceVariant
        font.pixelSize: 15
    }

    ListView {
        id: list

        anchors.fill: parent
        clip: true
        cacheBuffer: 320
        spacing: 18
        boundsBehavior: Flickable.StopAtBounds
        model: root.groups
        topMargin: 8
        bottomMargin: 16

        delegate: RowLayout {
            id: group

            required property var modelData
            readonly property bool today: modelData.day === Calendar.todayDay
            readonly property bool past: modelData.day < Calendar.todayDay

            width: ListView.view.width
            spacing: 16
            opacity: past ? 0.6 : 1

            ColumnLayout {
                Layout.preferredWidth: 72
                Layout.alignment: Qt.AlignTop
                spacing: 2

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: Calendar.format(group.modelData.day, "ddd")
                    color: group.today ? Theme.m3primary : Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                    weight: Font.Medium
                }

                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    implicitWidth: 42
                    implicitHeight: 42
                    radius: 21
                    color: group.today ? Theme.accentFill : "transparent"

                    Label {
                        anchors.centerIn: parent
                        text: Number(group.modelData.day.slice(8))
                        color: group.today ? Theme.accentFillInk : Theme.m3onSurface
                        font.pixelSize: 22
                        weight: Font.Medium
                    }
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: Calendar.format(group.modelData.day, group.modelData.day.slice(0, 4) === Calendar.todayDay.slice(0, 4) ? "MMM" : "MMM yyyy")
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.rightMargin: 8
                spacing: 8

                Repeater {
                    model: group.modelData.events

                    delegate: EventLine {
                        required property var modelData

                        Layout.fillWidth: true
                        event: modelData
                        onClicked: root.picked(modelData)
                    }
                }
            }
        }
    }
}
