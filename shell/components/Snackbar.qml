import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
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

    implicitWidth: Math.min(Math.max(320, row.implicitWidth + 40), 600)
    implicitHeight: 56
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

    RectangularShadow {
        anchors.fill: bar
        radius: bar.radius
        blur: 24
        spread: 0
        offset.y: 6
        color: Theme.alpha(Theme.m3shadow, 0.45)
    }

    Rectangle {
        id: bar

        anchors.fill: parent
        radius: 16
        color: root.shown?.error ? Theme.m3errorContainer : Theme.m3inverseSurface

        RowLayout {
            id: row

            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 8
            spacing: 14

            // A spinner while Gmail is still doing it, else what was done.
            Icon {
                id: mark

                name: root.shown?.pending ? "progress_activity" : root.shown?.error ? "error" : (root.shown?.icon ?? "check_circle")
                size: 22
                color: root.shown?.error ? Theme.m3onErrorContainer : Theme.m3inverseOnSurface

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
                Layout.fillWidth: true
                renderType: Text.NativeRendering
                textFormat: Text.PlainText
                text: root.shown?.text ?? ""
                elide: Text.ElideRight
                color: root.shown?.error ? Theme.m3onErrorContainer : Theme.m3inverseOnSurface
                font.family: Theme.sans
                font.pixelSize: 14
                font.weight: Font.Medium
            }

            Rectangle {
                visible: (root.shown?.undo ?? null) !== null && !(root.shown?.pending ?? false)
                implicitWidth: undoLabel.implicitWidth + 24
                implicitHeight: 36
                radius: 18
                color: undoArea.containsMouse ? Theme.alpha(Theme.m3inversePrimary, 0.16) : "transparent"

                Text {
                    id: undoLabel

                    anchors.centerIn: parent
                    renderType: Text.NativeRendering
                    text: "Undo"
                    color: Theme.m3inversePrimary
                    font.family: Theme.sans
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
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

                implicitWidth: 36
                implicitHeight: 36
                radius: 18
                color: closeArea.containsMouse ? Theme.alpha(Theme.m3inverseOnSurface, 0.1) : "transparent"

                Icon {
                    anchors.centerIn: parent
                    name: "close"
                    size: 20
                    color: root.shown?.error ? Theme.m3onErrorContainer : Theme.m3inverseOnSurface
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
