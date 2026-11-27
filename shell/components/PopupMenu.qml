import QtQuick
import QtQuick.Layouts
import qs.services

// A frosted-glass dropdown menu that opens under the button that asked for it.
// entries: [{ icon, label, run, checked?, danger? }]; { separator: true } draws a line.
Item {
    id: root

    property var entries: []

    function show(button: Item, items: var): void {
        entries = items;
        const height = items.reduce((sum, entry) => sum + (entry.separator ? 9 : 34), 12);
        const at = button.mapToItem(root, 0, 0);
        card.x = Math.max(8, Math.min(at.x + button.width - card.width, root.width - card.width - 8));
        const below = at.y + button.height + 6;
        card.y = below + height > root.height - 8 ? Math.max(8, at.y - height - 6) : below;
        visible = true;
    }

    function close(): void {
        visible = false;
    }

    visible: false
    z: 100

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onPressed: root.close()
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.visible
        onActivated: root.close()
    }

    Rectangle {
        id: card

        width: 248
        implicitHeight: list.implicitHeight + 12
        height: implicitHeight
        radius: 13
        color: Theme.m3popupHigh
        border.width: 1
        border.color: Theme.glassPopupBorder

        MouseArea {
            anchors.fill: parent
        }

        ColumnLayout {
            id: list

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 6
            spacing: 1

            Repeater {
                model: root.entries

                delegate: Item {
                    id: entry

                    required property var modelData
                    readonly property color ink: modelData.danger ? Theme.m3error : Theme.m3onSurface

                    Layout.fillWidth: true
                    implicitHeight: modelData.separator ? 9 : 34

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        height: 1
                        visible: entry.modelData.separator === true
                        color: Theme.glassDivider
                    }

                    Rectangle {
                        anchors.fill: parent
                        visible: entry.modelData.separator !== true
                        radius: 8
                        color: area.containsMouse ? Theme.glassControlHover : "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 10

                            Icon {
                                name: entry.modelData.icon ?? ""
                                size: 18
                                color: entry.modelData.danger ? Theme.m3error : Theme.m3onSurfaceVariant
                            }

                            Label {
                                Layout.fillWidth: true
                                text: entry.modelData.label ?? ""
                                elide: Text.ElideRight
                                color: entry.ink
                                font.pixelSize: 13
                            }

                            Icon {
                                visible: entry.modelData.checked === true
                                name: "check"
                                size: 18
                                color: Theme.m3primary
                            }
                        }

                        MouseArea {
                            id: area

                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                root.close();
                                entry.modelData.run();
                            }
                        }
                    }
                }
            }
        }
    }
}
