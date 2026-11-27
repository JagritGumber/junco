import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// One calm, luminous conversation row (~92 px tall):
// unselected rows breathe directly on the glass with zero boxy chrome;
// the selected row floats as a soft accent-tinted frosted capsule with a
// delicate GlassEdge top specular sheen, confident 46 px circular avatar,
// generous 18 px avatar-to-text air gap, crisp Adwaita Sans 3-line hierarchy,
// and disciplined 2-anchor right column (tabular timestamp + 8 px unread dot
// top-right, interactive star button bottom-right).
Rectangle {
    id: root

    property var conversation
    property bool isLast: false
    property bool nextSelected: false

    readonly property bool selected: Inbox.selectedId === conversation.id
    readonly property bool unread: (conversation.unread ?? 0) > 0
    readonly property bool starred: Boolean(conversation.starred)
    readonly property bool hovered: rowHover.hovered
    readonly property string subjectText: (conversation.subject ?? "").trim() || (conversation.preview ?? "")
    readonly property string snippetText: {
        const s = (conversation.snippet ?? conversation.preview ?? "").trim();
        return s === subjectText ? "" : s;
    }
    readonly property bool hasExpiry: (conversation.expiry ?? null) !== null

    // Responsive horizontal rhythm: full flagship proportions at standard width,
    // gracefully tightened below 310 px for half-screen tiles (950x1040).
    readonly property int innerPadX: width >= 310 ? 16 : 12
    readonly property int avatarSize: width >= 310 ? 46 : 42
    readonly property int avatarGap: width >= 310 ? 18 : 14
    readonly property int rightBuffer: width >= 310 ? 16 : 12

    implicitHeight: (snippetText !== "" ? 92 : 80) + (hasExpiry ? 24 : 0)
    radius: Theme.rowRadius
    color: selected ? Theme.glassSelectedRow : (hovered ? Theme.glassHover : "transparent")
    border.width: !Theme.glass && selected ? 1 : 0
    border.color: Theme.glassActiveBorder

    Behavior on color {
        ColorAnimation {
            duration: Theme.animFast
            easing.type: Easing.OutCubic
        }
    }

    // Delicate top specular glass highlight on the floating selected capsule.
    GlassEdge {
        visible: Theme.glass && root.selected
        radius: root.radius
        fade: 10
        side: false
        light: Theme.alpha(Theme.pureWhite, Theme.dark ? 0.22 : 0.34)
    }

    HoverHandler {
        id: rowHover
    }

    MouseArea {
        id: area

        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: Inbox.open(root.conversation.id)
    }

    RowLayout {
        z: 1
        anchors.fill: parent
        anchors.leftMargin: root.innerPadX
        anchors.rightMargin: root.innerPadX
        anchors.topMargin: 16
        anchors.bottomMargin: 16
        spacing: 0

        Avatar {
            Layout.alignment: Qt.AlignVCenter
            name: root.conversation.name
            icon: root.conversation.icon ?? ""
            logo: root.conversation.logo ?? ""
            accentLogo: root.conversation.logo === "linear"
            image: root.conversation.avatar ?? ""
            size: root.avatarSize
        }

        // Generous air gap between avatar and 3-line text stack.
        Item {
            Layout.preferredWidth: root.avatarGap
            Layout.fillHeight: true
        }

        // 3-line typographic stack (Adwaita Sans, crisp optical hierarchy).
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 0

            // Line 1: Sender (15 px, Adwaita Sans SemiBold 600, tight -0.25 tracking)
            Label {
                Layout.fillWidth: true
                text: root.conversation.name
                elide: Text.ElideRight
                color: Theme.m3onSurface
                font.pixelSize: 15
                weight: Font.DemiBold
            }

            // Line 2: Subject (13 px, Adwaita Sans Medium 500, 4 px below Sender)
            Label {
                Layout.fillWidth: true
                Layout.topMargin: 4
                text: root.subjectText
                elide: Text.ElideRight
                color: Theme.m3onSurface
                opacity: root.unread || root.selected ? 1.0 : 0.90
                font.pixelSize: 13
                weight: Font.Medium
            }

            // Line 3: Snippet (13 px, Adwaita Sans Regular 400, 3 px below Subject)
            Label {
                Layout.fillWidth: true
                Layout.topMargin: 3
                visible: root.snippetText !== ""
                text: root.snippetText
                elide: Text.ElideRight
                color: Theme.m3onSurfaceVariant
                opacity: 0.84
                font.pixelSize: 13
                weight: Font.Normal
            }

            // Subtle compact expiry pill shown ONLY when scheduled for deletion.
            ExpiryBadge {
                Layout.topMargin: 5
                visible: root.hasExpiry
                expiry: root.conversation.expiry ?? null
                compact: true
            }
        }

        // Horizontal buffer between text stack and right 2-anchor column.
        Item {
            Layout.preferredWidth: root.rightBuffer
            Layout.fillHeight: true
        }

        // Disciplined 2-anchor right column:
        //   Top-right: tabular timestamp + 8 px gap + vivid 8 px unread dot
        //   Bottom-right: subtle interactive star button cleanly aligned with Line 3
        ColumnLayout {
            Layout.fillHeight: true
            spacing: 0

            Row {
                Layout.alignment: Qt.AlignRight | Qt.AlignTop
                Layout.topMargin: 1
                spacing: 8

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    tabular: true
                    text: root.conversation.time
                    color: Theme.m3onSurfaceVariant
                    opacity: root.unread ? 0.95 : 0.82
                    font.pixelSize: 12
                    weight: root.unread ? Font.Medium : Font.Normal
                }

                Rectangle {
                    visible: root.unread
                    anchors.verticalCenter: parent.verticalCenter
                    width: 8
                    height: 8
                    radius: 4
                    color: Theme.complementDot
                }
            }

            Item {
                Layout.fillHeight: true
            }

            IconButton {
                Layout.alignment: Qt.AlignRight | Qt.AlignBottom
                Layout.bottomMargin: -4
                Layout.rightMargin: -4
                icon: "star"
                filled: false
                iconFill: root.starred ? 1 : 0
                iconColor: root.starred ? Theme.m3tertiary : Theme.alpha(Theme.m3onSurfaceVariant, root.hovered ? 0.88 : 0.65)
                tip: root.starred ? "Unstar" : "Star"
                size: 28
                iconSize: 18
                onClicked: {
                    const targetId = root.conversation.latestId ?? "";
                    if (targetId !== "")
                        Inbox.mark(root.starred ? "unstar" : "star", [targetId]);
                }
            }
        }
    }

    // Whisper-faint inset horizontal divider aligned with the text column,
    // never bleeding to the card edges, hidden directly above/below selected row.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: root.innerPadX + root.avatarSize + root.avatarGap
        anchors.rightMargin: root.innerPadX
        y: parent.height + 1.5
        height: 1
        visible: !root.selected && !root.hovered && !root.isLast && !root.nextSelected
        color: Theme.glassDivider
        opacity: 0.55
    }
}
