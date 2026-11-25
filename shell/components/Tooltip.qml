import QtQuick
import QtQuick.Controls
import qs.services

// What an icon-only button does, after a moment's hover: Material's plain
// tooltip, a small dark label. It sits under the button, or above it near
// the window's bottom edge. Buttons build it only while hovered (Loader), so
// a list of hundreds of buttons costs nothing.
//
//     Loader {
//         active: area.containsMouse && root.tip !== ""
//         sourceComponent: Tooltip { parent: root; text: root.tip }
//     }
ToolTip {
    id: root

    // Under the button unless that would run off the window.
    readonly property bool below: {
        const window = parent?.Window.window ?? null;
        if (!parent || !window)
            return true;
        return parent.mapToItem(null, 0, parent.height).y + implicitHeight + 14 <= window.height;
    }

    visible: true
    delay: 450
    margins: 8
    padding: 0
    x: Math.round(((parent?.width ?? 0) - implicitWidth) / 2)
    y: below ? (parent?.height ?? 0) + 6 : -implicitHeight - 6

    contentItem: Text {
        renderType: Text.NativeRendering
        leftPadding: 10
        rightPadding: 10
        topPadding: 5
        bottomPadding: 6
        text: root.text
        color: Theme.m3inverseOnSurface
        font.family: Theme.sans
        font.pixelSize: 12
        font.weight: Font.Medium
    }

    background: Rectangle {
        radius: 8
        color: Theme.m3inverseSurface
    }

    enter: Transition {
        NumberAnimation {
            property: "opacity"
            from: 0
            to: 1
            duration: 120
        }
    }

    exit: Transition {
        NumberAnimation {
            property: "opacity"
            from: 1
            to: 0
            duration: 80
        }
    }
}
