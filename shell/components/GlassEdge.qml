import QtQuick
import qs.services

// How a pane of frosted glass catches light at its edge: no outline at all.
// A soft, wide light enters along the top (and, a little weaker, the left)
// and fades out over `fade` px into the glass, like light entering the
// glass's thickness. The pane's shape otherwise comes from its fill step and
// its soft shadow (GlassPane), with an anti-aliased boundary.
//
// Two rounded rectangles with a three-stop fade each (an approximation of
// light falling off inside the glass): static, no shader, no animation.
// Fill the parent pane and set `radius` to its corner radius.
Item {
    id: root

    property real radius: Theme.paneRadius
    property real fade: Theme.glassEdgeFade
    property color light: Theme.glassEdgeLight
    property color sideLight: Theme.glassEdgeSideLight
    // Nested cards with uneven corners (bubbles) take only the top light.
    property bool side: true

    anchors.fill: parent

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        gradient: Gradient {
            GradientStop {
                position: 0
                color: root.light
            }
            GradientStop {
                position: Math.min(0.99, 0.35 * root.fade / Math.max(1, root.height))
                color: Theme.alpha(root.light, root.light.a * 0.42)
            }
            GradientStop {
                position: Math.min(1, root.fade / Math.max(1, root.height))
                color: Theme.alpha(root.light, 0)
            }
        }
    }

    Rectangle {
        visible: root.side
        anchors.fill: parent
        radius: root.radius
        gradient: Gradient {
            orientation: Gradient.Horizontal

            GradientStop {
                position: 0
                color: root.sideLight
            }
            GradientStop {
                position: Math.min(0.99, 0.35 * root.fade / Math.max(1, root.width))
                color: Theme.alpha(root.sideLight, root.sideLight.a * 0.42)
            }
            GradientStop {
                position: Math.min(1, root.fade / Math.max(1, root.width))
                color: Theme.alpha(root.sideLight, 0)
            }
        }
    }
}
