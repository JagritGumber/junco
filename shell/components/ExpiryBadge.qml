import QtQuick
import QtQuick.Layouts
import qs.services

// Subtle frosted-glass pill showing a thread's scheduled deletion ("Deletes in 2y · college"
// or "Auto-delete · 5d"). Interactive mode (reader header) offers one-click
// Change and Cancel controls with zero outlines.
Rectangle {
    id: root

    property var expiry: null
    property bool interactive: false
    property bool compact: false

    signal changeClicked
    signal cancelClicked

    readonly property bool isRule: expiry?.is_rule ?? false
    readonly property string remaining: expiry?.remaining ?? ""
    readonly property string note: expiry?.note ?? ""
    readonly property string exactDate: (expiry?.expires_at ?? "").slice(0, 10)
    readonly property string labelText: {
        if (!expiry)
            return "";
        if (compact) {
            if (isRule)
                return `Auto-delete · ${remaining}`;
            return note ? `${remaining} · ${note}` : `Deletes in ${remaining}`;
        }
        const base = isRule ? `Auto-delete · ${remaining}` : `Deletes in ${remaining}`;
        return note ? `${base} · ${note}` : base;
    }

    // Both rule-based and manual expiry badges are passive status signals,
    // using the dynamic complementary container for crisp >= 4.5:1 contrast.
    readonly property color bgColor: Theme.m3tertiaryContainer
    readonly property color fgColor: Theme.m3onTertiaryContainer

    visible: expiry !== null && expiry !== undefined
    implicitHeight: compact ? 20 : 28
    implicitWidth: row.implicitWidth + (compact ? 12 : 18)
    radius: implicitHeight / 2
    color: bgColor
    border.width: 0

    RowLayout {
        id: row

        anchors.centerIn: parent
        spacing: root.compact ? 4 : 6

        Icon {
            name: root.isRule ? "auto_delete" : "schedule"
            size: root.compact ? 12 : 15
            color: root.fgColor
        }

        Label {
            text: root.labelText
            color: root.fgColor
            font.pixelSize: root.compact ? 10 : 12
            weight: Font.Medium
        }

        Label {
            visible: root.interactive && root.exactDate !== ""
            text: `(${root.exactDate})`
            color: Theme.alpha(root.fgColor, 0.78)
            font.pixelSize: 11
            weight: Font.Normal
        }

        Rectangle {
            visible: root.interactive
            implicitWidth: 1
            implicitHeight: 13
            color: Theme.alpha(root.fgColor, 0.24)
        }

        Item {
            visible: root.interactive
            implicitWidth: changeLabel.implicitWidth + 10
            implicitHeight: 22

            Rectangle {
                anchors.fill: parent
                radius: 11
                color: changeArea.containsMouse ? Theme.alpha(root.fgColor, 0.14) : "transparent"
            }

            Label {
                id: changeLabel

                anchors.centerIn: parent
                text: "Change"
                color: root.fgColor
                font.pixelSize: 12
                weight: Font.Medium
            }

            MouseArea {
                id: changeArea

                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.changeClicked()
            }
        }

        Item {
            visible: root.interactive
            implicitWidth: 22
            implicitHeight: 22

            Rectangle {
                anchors.fill: parent
                radius: 11
                color: cancelArea.containsMouse ? Theme.alpha(root.fgColor, 0.14) : "transparent"
            }

            Icon {
                anchors.centerIn: parent
                name: "close"
                size: 14
                color: root.fgColor
            }

            MouseArea {
                id: cancelArea

                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.cancelClicked()
            }

            Loader {
                active: cancelArea.containsMouse
                sourceComponent: Tooltip {
                    parent: cancelArea
                    text: "Cancel scheduled deletion"
                }
            }
        }
    }
}
