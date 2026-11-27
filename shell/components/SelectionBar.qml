import QtQuick
import QtQuick.Layouts
import qs.services

// Contextual frosted-glass top bar when emails are selected.
Rectangle {
    id: root

    property int count: 0
    property int total: 0
    property string context: ""
    property var actions: []

    property int shownCount: 1
    readonly property var everything: shownCount < total ? [...actions, { action: "select-all", icon: "select_all", label: "Select all", primary: false }] : actions
    readonly property real room: width - lead.implicitWidth - 40 - 20
    readonly property real wordsWidth: everything.reduce((sum, item) => sum + 20 + 18 + 5 + Math.ceil(metrics.advanceWidth(item.label)), 0) + 4 * Math.max(0, everything.length - 1)
    readonly property real iconsWidth: 32 * everything.length + 4 * Math.max(0, everything.length - 1)
    readonly property int mode: room >= wordsWidth ? 2 : room >= iconsWidth ? 1 : 0
    readonly property var shown: mode > 0 ? everything : everything.filter(item => item.primary)
    readonly property var overflow: mode > 0 ? [] : everything.filter(item => !item.primary)

    signal triggered(string action)

    onCountChanged: if (count > 0)
        shownCount = count

    implicitHeight: 38
    radius: Theme.controlRadius
    color: Theme.glassActive
    border.width: 1
    border.color: Theme.glassActiveBorder

    FontMetrics {
        id: metrics

        font.family: Theme.sans
        font.pixelSize: 12
        font.weight: Font.Normal
        font.variableAxes: ({ "wght": Theme.weightMedium })
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 6
        spacing: 4

        IconButton {
            icon: "close"
            tip: "Clear selection"
            size: 30
            iconColor: Theme.m3onSurface
            onClicked: root.triggered("clear")
        }

        RowLayout {
            id: lead

            Layout.leftMargin: 2
            spacing: 6

            Label {
                text: `${root.shownCount} selected`
                color: Theme.m3onSurface
                font.pixelSize: 13
                weight: Font.Medium
            }

            Label {
                Layout.maximumWidth: 160
                visible: root.context !== ""
                text: `· ${root.context}`
                elide: Text.ElideRight
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 12
            }
        }

        Item {
            Layout.fillWidth: true
        }

        Repeater {
            model: root.shown

            delegate: Rectangle {
                id: button

                required property var modelData
                readonly property bool words: root.mode === 2

                implicitWidth: words ? content.implicitWidth + 18 : 30
                implicitHeight: 30
                radius: 9
                color: area.containsMouse ? Theme.glassControlHover : "transparent"

                Row {
                    id: content

                    anchors.centerIn: parent
                    spacing: 5

                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: button.modelData.icon
                        size: 17
                        color: Theme.m3onSurface
                    }

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: button.words
                        text: button.modelData.label
                        color: Theme.m3onSurface
                        font.pixelSize: 12
                        weight: Font.Medium
                    }
                }

                MouseArea {
                    id: area

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.triggered(button.modelData.action)
                }

                Loader {
                    active: area.containsMouse && !button.words
                    sourceComponent: Tooltip {
                        parent: button
                        text: button.modelData.label
                    }
                }
            }
        }

        IconButton {
            id: more

            visible: root.overflow.length > 0
            icon: "more_vert"
            tip: "More"
            size: 30
            iconColor: Theme.m3onSurface
            onClicked: Inbox.windowMenu.show(more, root.overflow.map(item => ({ icon: item.icon, label: item.label, run: () => root.triggered(item.action) })))
        }
    }
}
