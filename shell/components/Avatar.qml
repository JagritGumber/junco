import QtQuick
import qs.services

// Initials for people; a brand mark or an icon for lanes. A person's tone
// comes from their name, so they keep the same colour everywhere.
Rectangle {
    id: root

    property string name
    property string icon: ""
    property string logo: ""          // a key in Brands, e.g. "github"
    property bool accentLogo: false   // brand tile in the primary container
    property string image: ""         // a cached sender picture (brand logo or photo)
    property int size: 44

    readonly property bool isLane: icon !== "" || logo !== ""
    readonly property int tone: {
        let hash = 0;
        for (const ch of name)
            hash = (hash * 31 + ch.charCodeAt(0)) % 997;
        return hash % 3;
    }
    readonly property color ink: logo !== "" ? (accentLogo ? Theme.m3onPrimaryContainer : Theme.m3onSurface) : isLane ? Theme.m3onSecondaryContainer : [Theme.m3onPrimaryContainer, Theme.m3onTertiaryContainer, Theme.m3onSecondaryContainer][tone]

    implicitWidth: size
    implicitHeight: size
    radius: size / 2
    color: logo !== "" ? (accentLogo ? Theme.m3primaryContainer : Theme.m3surfaceContainerHighest) : isLane ? Theme.m3secondaryContainer : [Theme.m3primaryContainer, Theme.m3tertiaryContainer, Theme.m3secondaryContainer][tone]

    Label {
        anchors.centerIn: parent
        visible: !root.isLane
        text: root.name.split(" ").filter(w => w.length > 0).map(w => w[0]).slice(0, 2).join("").toUpperCase()
        color: root.ink
        font.pixelSize: Math.round(root.size * 0.38)
        font.weight: Font.Medium
    }

    Icon {
        anchors.centerIn: parent
        visible: root.icon !== "" && root.logo === ""
        name: root.icon
        color: root.ink
        size: Math.round(root.size * 0.5)
        fill: 1
    }

    // The brand path as an SVG with the theme colour baked in: renders on any
    // scene-graph backend, and the source changes whenever the colour does.
    Image {
        readonly property int glyph: Math.round(root.size * 0.5)

        anchors.centerIn: parent
        width: glyph
        height: glyph
        visible: root.logo !== ""
        sourceSize: Qt.size(glyph * 2, glyph * 2)
        source: root.logo === "" ? "" : "data:image/svg+xml;utf8," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="${root.ink}" d="${Brands[root.logo]}"/></svg>`)
    }

    // The sender's own picture (courier-avatars stores it already round, on
    // a white disc), covering the initials once it has loaded.
    Image {
        anchors.fill: parent
        visible: status === Image.Ready
        source: root.image === "" || root.logo !== "" ? "" : `file://${root.image}`
        sourceSize: Qt.size(root.size * 2, root.size * 2)
        smooth: true
        mipmap: true
        asynchronous: true
    }
}
