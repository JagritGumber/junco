import QtQuick

// An app's title with its icon before it: Pip for Mail, Tab for Calendar.
// Compact proportions tuned for 15" 16:9 screens; decorative only.
Item {
    id: root

    required property string text
    required property string icon
    property int iconSize: 22
    property int gap: 8
    property int fontSize: 18
    property alias color: title.color

    implicitWidth: title.x + title.implicitWidth
    implicitHeight: Math.max(iconSize, title.implicitHeight)

    TextMetrics {
        id: capitals

        font: title.font
        text: "M"
    }

    Image {
        width: root.iconSize
        height: root.iconSize
        y: Math.round(title.y + title.baselineOffset - capitals.tightBoundingRect.height / 2 - root.iconSize / 2)
        source: root.icon
        sourceSize: Qt.size(root.iconSize, root.iconSize)
        fillMode: Image.PreserveAspectFit
        smooth: true
        Accessible.ignored: true
    }

    Label {
        id: title

        x: root.iconSize + root.gap
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        font.pixelSize: root.fontSize
        weight: Font.DemiBold
    }
}
