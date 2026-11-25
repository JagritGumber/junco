import QtQuick
import QtQuick.Layouts
import qs.services

// The fields you taught for this email's template, read from this email:
// a label and its value each, a list as a short list, a link as a button.
// An email the template no longer fits says so and shows no values at all
// (never a wrong one), with Teach again on it.
Rectangle {
    id: root

    // courier_templates' card: { template: { id, name, count }, status,
    // missing, fields: [{ name, list, link, value }] }
    property var card: null
    property string messageId: ""
    readonly property bool needsTeaching: card?.status === "reteach"

    implicitHeight: content.implicitHeight + 28
    radius: 20
    color: needsTeaching ? Theme.alpha(Theme.m3error, 0.08) : Theme.m3surfaceContainer
    border.width: 1
    border.color: needsTeaching ? Theme.alpha(Theme.m3error, 0.5) : Theme.alpha(Theme.m3outlineVariant, 0.6)

    ColumnLayout {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 14
        anchors.leftMargin: 16
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Icon {
                name: root.needsTeaching ? "warning" : "dataset"
                size: 20
                color: root.needsTeaching ? Theme.m3error : Theme.m3primary
            }

            Label {
                Layout.fillWidth: true
                text: root.card?.template?.name ?? ""
                elide: Text.ElideRight
                font.pixelSize: 14
                font.weight: Font.Medium
            }

            Pill {
                style: "tonal"
                icon: "table_view"
                text: `All ${root.card?.template?.count ?? 0}`
                size: 32
                fontSize: 13
                tip: "Every email like this one, as a table"
                onClicked: Inbox.openTable(root.card.template.id)
            }

            IconButton {
                visible: !root.needsTeaching
                icon: "edit"
                size: 32
                tip: "Teach this template's fields"
                onClicked: Inbox.teachOn(root.messageId)
            }
        }

        // The template no longer fits: say what's missing, offer to teach.
        RowLayout {
            Layout.fillWidth: true
            visible: root.needsTeaching
            spacing: 12

            Label {
                Layout.fillWidth: true
                text: `Needs re-teaching: Courier can't find ${(root.card?.missing ?? []).join(", ") || "what this template always says"} in this email, so it shows nothing rather than guess.`
                wrapMode: Text.Wrap
                color: Theme.m3onSurface
                font.pixelSize: 13
            }

            Pill {
                style: "filled"
                icon: "dataset"
                text: "Teach again"
                size: 36
                fontSize: 13
                onClicked: Inbox.teachOn(root.messageId)
            }
        }

        GridLayout {
            Layout.fillWidth: true
            visible: !root.needsTeaching
            columns: 2
            columnSpacing: 16
            rowSpacing: 8

            Repeater {
                model: root.needsTeaching ? [] : (root.card?.fields ?? [])

                delegate: Label {
                    required property var modelData
                    required property int index

                    Layout.row: index
                    Layout.column: 0
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredWidth: 110
                    text: modelData.name
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 13
                }
            }

            Repeater {
                model: root.needsTeaching ? [] : (root.card?.fields ?? [])

                delegate: Item {
                    id: cell

                    required property var modelData
                    required property int index
                    readonly property var values: Inbox.asList(modelData.value)

                    Layout.row: index
                    Layout.column: 1
                    Layout.fillWidth: true
                    implicitHeight: valueColumn.implicitHeight

                    Column {
                        id: valueColumn

                        width: parent.width
                        spacing: 2

                        Label {
                            visible: cell.values.length === 0
                            text: "—"
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 13
                        }

                        Repeater {
                            model: cell.values.slice(0, 6)

                            delegate: Label {
                                required property var modelData

                                width: valueColumn.width
                                text: cell.modelData.link ? `${modelData} ↗` : modelData
                                elide: Text.ElideRight
                                color: cell.modelData.link ? Theme.m3primary : Theme.m3onSurface
                                font.pixelSize: 13
                                font.family: /^[0-9a-f]{7,40}$/.test(modelData) ? "monospace" : Theme.sans

                                MouseArea {
                                    anchors.fill: parent
                                    enabled: cell.modelData.link && /^https?:\/\//.test(parent.modelData)
                                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: Qt.openUrlExternally(parent.modelData)
                                }
                            }
                        }

                        Label {
                            visible: cell.values.length > 6
                            text: `and ${cell.values.length - 6} more`
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }
}
