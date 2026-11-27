import QtQuick
import qs.services

// Invisible drag-to-resize split handle between panes. At rest nothing is
// drawn (keeps the frosted-glass gaps clean); on hover the cursor becomes
// Qt.SplitHCursor and a subtle translucent pill appears. Double-click resets
// the pane to its default width.
Item {
    id: root

    // Ancestor Item with stable coordinates (typically the window canvas or page).
    required property Item dragScope
    // Current pixel width of the pane being resized.
    required property int value
    // +1 for left-anchored panes (drag right grows), -1 for right-anchored panes.
    property int direction: 1

    signal resized(int nextValue)
    signal resizeFinished
    signal resetRequested

    readonly property bool dragging: area.pressed
    readonly property bool active: area.containsMouse || dragging

    z: 40

    MouseArea {
        id: area

        property real startX: 0
        property int startValue: 0
        property bool moved: false

        anchors.fill: parent
        anchors.leftMargin: -4
        anchors.rightMargin: -4
        hoverEnabled: true
        preventStealing: true
        cursorShape: Qt.SplitHCursor

        onPressed: mouse => {
            startX = mapToItem(root.dragScope, mouse.x, 0).x;
            startValue = root.value;
            moved = false;
        }

        onPositionChanged: mouse => {
            if (!pressed)
                return;
            const curX = mapToItem(root.dragScope, mouse.x, 0).x;
            const delta = Math.round((curX - startX) * root.direction);
            if (delta !== 0) {
                moved = true;
                root.resized(startValue + delta);
            }
        }

        onReleased: {
            if (moved)
                root.resizeFinished();
        }

        onDoubleClicked: {
            moved = false;
            root.resetRequested();
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: 3
        height: root.dragging ? 48 : 34
        radius: 1.5
        color: root.dragging ? Theme.splitHandleDrag : Theme.splitHandleHover
        opacity: root.active ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: 120
                easing.type: Easing.OutCubic
            }
        }

        Behavior on height {
            NumberAnimation {
                duration: 120
                easing.type: Easing.OutCubic
            }
        }
    }
}
