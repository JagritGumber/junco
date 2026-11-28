import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.services

// What just happened, at the bottom of the window: "Deleting…" with a spinner
// the moment you act, then "Deleted · Undo" once Gmail has it, or what went
// wrong. Material's inverse surface, so it reads against every panel.
Item {
    id: root

    readonly property var notice: Inbox.notice
    // The last notice, kept while the bar slides away.
    property var shown: null

    onNoticeChanged: if (notice)
        shown = notice

    implicitWidth: Math.min(Math.max(280, row.implicitWidth + 32), 520)
    implicitHeight: 44
    opacity: notice ? 1 : 0
    visible: opacity > 0

    Behavior on opacity {
        NumberAnimation {
            duration: 160
            easing.type: Easing.OutCubic
        }
    }

    transform: Translate {
        y: root.notice ? 0 : 16

        Behavior on y {
            NumberAnimation {
                duration: 200
                easing.type: Easing.OutCubic
            }
        }
    }

    // Static pre-rendered 9-slice shadow (zero QML shaders).
    BorderImage {
        visible: root.visible
        z: -1
        anchors.fill: bar
        anchors.margins: -12
        source: `file://${Quickshell.shellDir}/../assets/glass/card-shadow.png`
        border.left: 28
        border.right: 28
        border.top: 28
        border.bottom: 28
        horizontalTileMode: BorderImage.Stretch
        verticalTileMode: BorderImage.Stretch
        smooth: true
    }

    Rectangle {
        id: bar
        objectName: "snackbarBar"

        anchors.fill: parent
        radius: 12
        color: root.shown?.error ? Theme.m3errorPopup : Theme.m3popupHigh
        border.width: 1
        border.color: root.shown?.error ? Theme.alpha(Theme.m3error, 0.5) : Theme.glassPopupBorder

        RowLayout {
            id: row

            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 6
            spacing: 10

            // A spinner while Gmail is still doing it, else what was done.
            Icon {
                id: mark

                name: root.shown?.pending ? "progress_activity" : root.shown?.error ? "error" : (root.shown?.icon ?? "check_circle")
                size: 18
                color: root.shown?.error ? Theme.m3onErrorContainer : Theme.m3primary

                RotationAnimation on rotation {
                    running: root.visible && (root.shown?.pending ?? false)
                    from: 0
                    to: 360
                    duration: 900
                    loops: Animation.Infinite
                    onStopped: mark.rotation = 0
                }
            }

            Text {
                objectName: "snackbarLabel"
                Layout.fillWidth: true
                renderType: Text.NativeRendering
                textFormat: Text.PlainText
                text: root.shown?.text ?? ""
                elide: Text.ElideRight
                color: root.shown?.error ? Theme.m3onErrorContainer : Theme.m3onSurface
                font.family: Theme.sans
                font.pixelSize: 13
                font.weight: Font.Normal
                font.variableAxes: ({ "wght": Theme.weightMedium })
            }

            Rectangle {
                visible: (root.shown?.undo ?? null) !== null && !(root.shown?.pending ?? false)
                implicitWidth: undoLabel.implicitWidth + 20
                implicitHeight: 30
                radius: 15
                color: undoArea.containsMouse ? Theme.glassActive : "transparent"

                Text {
                    id: undoLabel

                    anchors.centerIn: parent
                    renderType: Text.NativeRendering
                    text: "Undo"
                    color: root.shown?.error ? Theme.m3onErrorContainer : Theme.m3primary
                    font.family: Theme.sans
                    font.pixelSize: 13
                    font.weight: Font.Normal
                    font.variableAxes: ({ "wght": Theme.weightMedium })
                }

                MouseArea {
                    id: undoArea

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Inbox.undo()
                }
            }

            Rectangle {
                id: closeButton

                implicitWidth: 30
                implicitHeight: 30
                radius: 15
                color: closeArea.containsMouse ? Theme.glassControlHover : "transparent"

                Icon {
                    anchors.centerIn: parent
                    name: "close"
                    size: 18
                    color: root.shown?.error ? Theme.m3onErrorContainer : Theme.m3onSurfaceVariant
                }

                MouseArea {
                    id: closeArea

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Inbox.notice = null
                }

                Loader {
                    active: closeArea.containsMouse
                    sourceComponent: Tooltip {
                        parent: closeButton
                        text: "Dismiss"
                    }
                }
            }
        }
    }
}
