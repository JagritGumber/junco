import QtQuick
import QtQuick.Controls
import qs.services

// Compact frosted-glass tooltip built lazily on hover via Loader.
ToolTip {
    id: root

    readonly property bool below: {
        const window = parent?.Window.window ?? null;
        if (!parent || !window)
            return true;
        return parent.mapToItem(null, 0, parent.height).y + implicitHeight + 12 <= window.height;
    }

    visible: true
    delay: 420
    margins: 6
    padding: 0
    x: Math.round(((parent?.width ?? 0) - implicitWidth) / 2)
    y: below ? (parent?.height ?? 0) + 5 : -implicitHeight - 5

    contentItem: Text {
        renderType: Text.NativeRendering
        leftPadding: 9
        rightPadding: 9
        topPadding: 4
        bottomPadding: 5
        text: root.text
        color: Theme.m3onSurface
        font.family: Theme.sans
        font.pixelSize: 11
        font.weight: Font.Normal
        font.variableAxes: ({ "wght": Theme.weightMedium })
    }

    background: Rectangle {
        radius: 8
        color: Theme.m3popupHigh
        border.width: 1
        border.color: Theme.glassPopupBorder
    }

    enter: Transition {
        NumberAnimation {
            property: "opacity"
            from: 0
            to: 1
            duration: 110
        }
    }

    exit: Transition {
        NumberAnimation {
            property: "opacity"
            from: 1
            to: 0
            duration: 75
        }
    }
}
