import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Updates as a table: one taught template's emails as rows (newest first),
// its fields as columns. A header sorts by its column (again: the other
// way); the filter keeps rows that say what you type anywhere. A row opens
// its email beside the table; one that needs re-teaching says so instead of
// showing values, and teaches on a click.
GlassPane {
    id: root

    readonly property var table: Inbox.table
    readonly property var columns: table?.columns ?? []
    property string sortBy: "date"
    property bool ascending: false
    property string filter: ""

    function cell(row, column): string {
        const value = row.values[column.name];
        if (column.list) {
            const items = Inbox.asList(value);
            return items.length > 2 ? `${items.slice(0, 2).join(", ")} +${items.length - 2}` : items.join(", ");
        }
        return value === undefined || value === null ? "" : String(value);
    }

    // Numbers as numbers, lists by length, the rest as text.
    function key(row, name): var {
        if (name === "date")
            return row.epoch;
        if (row.status === "reteach")
            return null;
        const value = row.values[name];
        if (value !== null && typeof value === "object")
            return Inbox.asList(value).length;
        if (value !== undefined && value !== null && /^#?\d+(\.\d+)?$/.test(String(value)))
            return Number(String(value).replace("#", ""));
        return value === undefined || value === null ? null : String(value).toLowerCase();
    }

    readonly property var rows: {
        const needle = filter.trim().toLowerCase();
        const kept = (table?.rows ?? []).filter(row => needle === "" || [row.subject, ...Object.values(row.values).map(value => Inbox.asList(value).join(" "))].join(" ").toLowerCase().includes(needle));
        const name = sortBy;
        const sign = ascending ? 1 : -1;
        return kept.slice().sort((a, b) => {
            const x = key(a, name);
            const y = key(b, name);
            // Empty cells and rows that need teaching go last, either way.
            if (x === null && y === null)
                return b.epoch - a.epoch;
            if (x === null)
                return 1;
            if (y === null)
                return -1;
            return x < y ? -sign : x > y ? sign : b.epoch - a.epoch;
        });
    }

    function sort(name: string): void {
        if (sortBy === name)
            ascending = !ascending;
        else {
            sortBy = name;
            ascending = name !== "date";
        }
    }

    onTableChanged: if (table && !columns.some(c => c.name === sortBy) && sortBy !== "date") sortBy = "date"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            IconButton {
                icon: "arrow_back"
                tip: "Close the table"
                onClicked: Inbox.closeTable()
            }

            Icon {
                name: "table_view"
                size: 24
                color: Theme.m3primary
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Label {
                    Layout.fillWidth: true
                    text: root.table?.template?.name ?? (Inbox.tableLoading ? "Reading…" : "")
                    elide: Text.ElideRight
                    font.pixelSize: 20
                    weight: Font.Medium
                }

                Label {
                    Layout.fillWidth: true
                    visible: root.table !== null
                    text: `${root.rows.length} of ${root.table?.rows?.length ?? 0} emails from ${root.table?.template?.sender ?? ""}` + ((root.table?.flagged ?? 0) > 0 ? ` · ${root.table.flagged} need re-teaching` : "")
                    elide: Text.ElideRight
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }
            }

            FormField {
                Layout.preferredWidth: 240
                hint: "Filter"
                onTextChanged: root.filter = text
            }
        }

        // The header: Date, then each field; a click sorts by it.
        RowLayout {
            id: header

            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            spacing: 12

            Repeater {
                model: [{ name: "date", label: "Date" }, ...root.columns.map(c => ({ name: c.name, label: c.name }))]

                delegate: Item {
                    required property var modelData
                    required property int index

                    Layout.preferredWidth: index === 0 ? 110 : 1
                    Layout.fillWidth: index > 0
                    implicitHeight: 32

                    RowLayout {
                        anchors.fill: parent
                        spacing: 4

                        Label {
                            Layout.fillWidth: true
                            text: parent.parent.modelData.label
                            elide: Text.ElideRight
                            color: root.sortBy === parent.parent.modelData.name ? Theme.m3primary : Theme.m3onSurfaceVariant
                            font.pixelSize: 13
                            weight: Font.Medium
                        }

                        Icon {
                            visible: root.sortBy === parent.parent.modelData.name
                            name: root.ascending ? "arrow_upward" : "arrow_downward"
                            size: 16
                            color: Theme.m3primary
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.sort(parent.modelData.name)
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: Theme.m3outlineVariant
        }

        ListView {
            id: list

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            model: root.rows

            delegate: Rectangle {
                id: tableRow

                required property var modelData
                readonly property bool flagged: modelData.status === "reteach"
                readonly property bool open: modelData.id === Inbox.openId

                width: list.width
                implicitHeight: 48
                radius: 14
                color: open ? Theme.m3secondaryContainer : rowArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.06) : "transparent"

                MouseArea {
                    id: rowArea

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Inbox.openMessage(tableRow.modelData.id, true)
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 12

                    Label {
                        Layout.preferredWidth: 110
                        text: Inbox.whenText(tableRow.modelData.epoch)
                        elide: Text.ElideRight
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 13
                    }

                    // An email that needs re-teaching: no values, a way to teach.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: tableRow.flagged
                        spacing: 10

                        Rectangle {
                            implicitWidth: flagLabel.implicitWidth + 36
                            implicitHeight: 28
                            radius: 14
                            color: Theme.m3errorContainer

                            Row {
                                anchors.centerIn: parent
                                spacing: 6

                                Icon {
                                    anchors.verticalCenter: parent.verticalCenter
                                    name: "warning"
                                    size: 16
                                    color: Theme.m3onErrorContainer
                                }

                                Label {
                                    id: flagLabel

                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "Needs re-teaching"
                                    color: Theme.m3onErrorContainer
                                    font.pixelSize: 12
                                    weight: Font.Medium
                                }
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: `Can't find ${tableRow.modelData.missing.join(", ")} · ${tableRow.modelData.subject}`
                            elide: Text.ElideRight
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 13
                        }

                        Pill {
                            style: "outlined"
                            icon: "dataset"
                            text: "Teach"
                            size: 32
                            fontSize: 13
                            onClicked: Inbox.teachOn(tableRow.modelData.id)
                        }
                    }

                    Repeater {
                        model: tableRow.flagged ? [] : root.columns

                        delegate: Label {
                            required property var modelData

                            Layout.preferredWidth: 1
                            Layout.fillWidth: true
                            text: root.cell(tableRow.modelData, modelData) || "—"
                            elide: Text.ElideRight
                            color: modelData.link ? Theme.m3primary : text === "—" ? Theme.m3onSurfaceVariant : Theme.m3onSurface
                            font.pixelSize: 13
                            font.family: /^[0-9a-f]{7,40}/.test(text) ? "monospace" : Theme.sans
                        }
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                visible: root.rows.length === 0 && !Inbox.tableLoading
                text: root.filter ? "Nothing matches." : "No emails yet."
                color: Theme.m3onSurfaceVariant
            }
        }
    }
}
