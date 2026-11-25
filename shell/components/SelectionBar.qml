import QtQuick
import QtQuick.Layouts
import qs.services

// Material 3's contextual top bar: while emails are picked it takes the place
// of a list's header, the way Gmail and Android do it. Close (clear the
// selection) and the count lead; the actions trail: with their words while
// those fit, as icons when they don't, and in a narrow window the less used
// ones go into a ⋮ menu instead of being squeezed.
//
// actions: [{ action, icon, label, primary }]; "primary" ones stay out of the
// ⋮ menu. A click says which: triggered(action), "clear" for close and
// "select-all" for Select all (offered while not everything is picked).
Rectangle {
    id: root

    property int count: 0
    property int total: 0
    // Which list it is, under the count ("Newsletters").
    property string context: ""
    property var actions: []

    // The count while it fades out after the selection empties; the bar
    // keeps what it showed until it has gone.
    property int shownCount: 1
    readonly property var everything: shownCount < total ? [...actions, { action: "select-all", icon: "select_all", label: "Select all", primary: false }] : actions
    // Words, icons or a ⋮ menu: worked out from the text's width, not the
    // buttons' own, so the choice never feeds back into the layout.
    readonly property real room: width - lead.implicitWidth - 48 - 24
    readonly property real wordsWidth: everything.reduce((sum, item) => sum + 24 + 20 + 6 + Math.ceil(metrics.advanceWidth(item.label)), 0) + 4 * Math.max(0, everything.length - 1)
    readonly property real iconsWidth: 40 * everything.length + 4 * Math.max(0, everything.length - 1)
    readonly property int mode: room >= wordsWidth ? 2 : room >= iconsWidth ? 1 : 0
    readonly property var shown: mode > 0 ? everything : everything.filter(item => item.primary)
    readonly property var overflow: mode > 0 ? [] : everything.filter(item => !item.primary)

    signal triggered(string action)

    onCountChanged: if (count > 0)
        shownCount = count

    implicitHeight: 52
    radius: height / 2
    color: Theme.m3secondaryContainer

    FontMetrics {
        id: metrics

        font.family: Theme.sans
        font.pixelSize: 13
        font.weight: Font.Medium
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 8
        spacing: 4

        IconButton {
            icon: "close"
            tip: "Clear selection"
            iconColor: Theme.m3onSecondaryContainer
            onClicked: root.triggered("clear")
        }

        ColumnLayout {
            id: lead

            Layout.leftMargin: 4
            spacing: 0

            Label {
                text: `${root.shownCount} selected`
                color: Theme.m3onSecondaryContainer
                font.pixelSize: 16
                font.weight: Font.Medium
            }

            Label {
                Layout.maximumWidth: 180
                visible: root.context !== ""
                text: root.context
                elide: Text.ElideRight
                color: Theme.alpha(Theme.m3onSecondaryContainer, 0.72)
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

                implicitWidth: words ? content.implicitWidth + 24 : 40
                implicitHeight: 40
                radius: 20
                color: area.containsMouse ? Theme.alpha(Theme.m3onSecondaryContainer, area.pressed ? 0.12 : 0.08) : "transparent"

                Row {
                    id: content

                    anchors.centerIn: parent
                    spacing: 6

                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: button.modelData.icon
                        size: 20
                        color: Theme.m3onSecondaryContainer
                    }

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: button.words
                        text: button.modelData.label
                        color: Theme.m3onSecondaryContainer
                        font.pixelSize: 13
                        font.weight: Font.Medium
                    }
                }

                MouseArea {
                    id: area

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.triggered(button.modelData.action)
                }

                // Icons alone say what they do on hover.
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
            iconColor: Theme.m3onSecondaryContainer
            onClicked: Inbox.windowMenu.show(more, root.overflow.map(item => ({ icon: item.icon, label: item.label, run: () => root.triggered(item.action) })))
        }
    }
}
