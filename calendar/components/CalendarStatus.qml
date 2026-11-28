import QtQuick
import QtQuick.Layouts
import qs.services

// Says why the calendar isn't syncing, with the fix one click away:
// re-authenticating expired Google accounts via browser OAuth, enabling the
// Google Calendar API, or running a fresh sync with immediate visual feedback.
Rectangle {
    id: root

    readonly property var status: Calendar.status
    readonly property string reauthAccount: Calendar.reauthAccountFor(status)
    readonly property bool needsReauth: reauthAccount !== ""
    readonly property bool problem: status.state === "error" || status.state === "signed-out"
    readonly property bool busy: Calendar.syncing || Calendar.signingIn
    readonly property bool hasActionUrl: /^https?:\/\//i.test(status.action ?? "")
    readonly property bool errorTone: problem && !busy
    readonly property color inkColor: errorTone ? Theme.m3onErrorContainer : Theme.sheetInk
    readonly property color mutedInkColor: errorTone ? Theme.m3onErrorContainer : Theme.sheetInkVariant

    readonly property string statusMessage: {
        if (Calendar.signingIn)
            return `Finish signing in to ${Calendar.signingInAccount} in your browser…`;
        if (Calendar.syncing)
            return "Syncing Google Calendar…";
        if (needsReauth && status.state === "signed-out")
            return `Google sign-in expired for ${reauthAccount}.`;
        if (problem)
            return status.message ?? "Calendar sync failed.";
        return "Copying your calendars…";
    }

    visible: problem || status.state === "never" || busy
    implicitHeight: content.implicitHeight + 28
    radius: Theme.cardRadius
    color: errorTone ? Theme.m3errorContainer : Theme.sheetControl

    Behavior on color {
        ColorAnimation {
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
    }

    ColumnLayout {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Icon {
                id: statusIcon

                name: root.busy ? "progress_activity" : root.needsReauth ? "passkey" : root.problem ? "event_busy" : "sync"
                color: root.mutedInkColor

                RotationAnimation on rotation {
                    running: root.visible && root.busy
                    from: 0
                    to: 360
                    duration: 1000
                    loops: Animation.Infinite
                    onStopped: statusIcon.rotation = 0
                }
            }

            Label {
                objectName: "calendarStatusLabel"
                Layout.fillWidth: true
                text: root.statusMessage
                wrapMode: Text.Wrap
                color: root.inkColor
                font.pixelSize: 13
            }
        }

        // Flow wraps cleanly inside the 228 px sidebar without clipping.
        Flow {
            Layout.fillWidth: true
            visible: root.problem || root.busy
            spacing: 8

            // Primary action when signing in: disabled busy pill + Cancel button.
            Rectangle {
                id: busyPill

                visible: root.busy
                implicitWidth: busyLabel.implicitWidth + 24
                implicitHeight: 32
                width: implicitWidth
                height: implicitHeight
                radius: 16
                color: Theme.sheetControl
                opacity: 0.78

                Label {
                    id: busyLabel

                    anchors.centerIn: parent
                    text: Calendar.signingIn ? "Signing in…" : "Syncing…"
                    color: Theme.sheetInk
                    font.pixelSize: 12
                    weight: Font.Medium
                }
            }

            Rectangle {
                id: cancelButton
                objectName: "calendarCancelSignInButton"

                visible: Calendar.signingIn
                implicitWidth: cancelLabel.implicitWidth + 24
                implicitHeight: 32
                width: implicitWidth
                height: implicitHeight
                radius: 16
                color: cancelArea.containsMouse ? Theme.sheetControlHover : Theme.sheetControl

                Label {
                    id: cancelLabel

                    anchors.centerIn: parent
                    text: "Cancel"
                    color: Theme.sheetInk
                    font.pixelSize: 12
                    weight: Font.Medium
                }

                MouseArea {
                    id: cancelArea

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Calendar.cancelSignIn()
                }
            }

            // Re-auth primary pill: opens browser OAuth for the expired account.
            Rectangle {
                id: signInButton
                objectName: "calendarSignInButton"

                visible: !root.busy && root.needsReauth
                implicitWidth: signInLabel.implicitWidth + 24
                implicitHeight: 32
                width: implicitWidth
                height: implicitHeight
                radius: 16
                color: signInArea.pressed
                    ? Qt.tint(Theme.errorPill, Theme.alpha(Theme.errorPillInk, 0.18))
                    : signInArea.containsMouse
                    ? Qt.tint(Theme.errorPill, Theme.alpha(Theme.errorPillInk, 0.10))
                    : Theme.errorPill

                Label {
                    id: signInLabel
                    objectName: "calendarSignInLabel"

                    anchors.centerIn: parent
                    text: "Sign in again"
                    color: Theme.errorPillInk
                    font.pixelSize: 12
                    weight: Font.DemiBold
                }

                MouseArea {
                    id: signInArea

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Calendar.signInAgain(root.reauthAccount)
                }
            }

            // API console link pill (e.g. Google Calendar API disabled).
            Rectangle {
                id: fixButton
                objectName: "calendarActionUrlButton"

                visible: !root.busy && root.hasActionUrl
                implicitWidth: fixLabel.implicitWidth + 24
                implicitHeight: 32
                width: implicitWidth
                height: implicitHeight
                radius: 16
                color: fixArea.pressed
                    ? Qt.tint(Theme.errorPill, Theme.alpha(Theme.errorPillInk, 0.18))
                    : fixArea.containsMouse
                    ? Qt.tint(Theme.errorPill, Theme.alpha(Theme.errorPillInk, 0.10))
                    : Theme.errorPill

                Label {
                    id: fixLabel
                    objectName: "calendarActionUrlLabel"

                    anchors.centerIn: parent
                    text: "Turn it on"
                    color: Theme.errorPillInk
                    font.pixelSize: 12
                    weight: Font.DemiBold
                }

                MouseArea {
                    id: fixArea

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Qt.openUrlExternally(root.status.action)
                }
            }

            // Retry sync pill: primary on transient errors, secondary alongside
            // "Sign in again" / "Turn it on".
            Rectangle {
                id: retryButton
                objectName: "calendarRetryButton"

                readonly property bool filled: !root.needsReauth && !root.hasActionUrl

                visible: !root.busy && root.problem
                implicitWidth: retryLabel.implicitWidth + 24
                implicitHeight: 32
                width: implicitWidth
                height: implicitHeight
                radius: 16
                color: filled
                    ? (retryArea.pressed
                        ? Qt.tint(Theme.errorPill, Theme.alpha(Theme.errorPillInk, 0.18))
                        : retryArea.containsMouse
                        ? Qt.tint(Theme.errorPill, Theme.alpha(Theme.errorPillInk, 0.10))
                        : Theme.errorPill)
                    : (Theme.glass
                        ? Theme.alpha(Theme.m3onErrorContainer, retryArea.pressed ? 0.22 : retryArea.containsMouse ? 0.17 : 0.12)
                        : (retryArea.containsMouse ? Theme.alpha(Theme.m3onErrorContainer, 0.12) : "transparent"))
                border.width: Theme.glass || filled ? 0 : 1
                border.color: Theme.m3onErrorContainer

                Label {
                    id: retryLabel
                    objectName: "calendarRetryLabel"

                    anchors.centerIn: parent
                    text: "Try again"
                    color: retryButton.filled ? Theme.errorPillInk : Theme.m3onErrorContainer
                    font.pixelSize: 12
                    weight: retryButton.filled ? Font.DemiBold : Font.Medium
                }

                MouseArea {
                    id: retryArea

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Calendar.syncNow()
                }
            }
        }
    }
}
