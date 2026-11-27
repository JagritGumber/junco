import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.services
import qs.components

// Junco Calendar's left sidebar (228 px): a rounded inset smoked-glass pane
// matching Mail's sidebar (same outer inset, 16 px radius and clear-glass
// gutter), with light ink (Theme.sheet*) and zero outlines.
GlassPane {
    id: root

    required property var page

    property bool adding: false
    property string addError: ""

    fill: Theme.glassSidebar

    readonly property var groups: {
        const groups = [];
        for (const account of Calendar.accounts) {
            const own = Calendar.calendars.filter(c => c.source === "google" && c.account === account.id);
            if (own.length > 0)
                groups.push({ title: account.email, calendars: own });
        }
        const shared = Calendar.calendars.filter(c => c.source === "google" && !c.account);
        if (shared.length > 0)
            groups.push({ title: "All accounts", calendars: shared });
        const local = Calendar.calendars.filter(c => c.source === "local");
        if (local.length > 0)
            groups.push({ title: "This PC", calendars: local });
        return groups;
    }

    function nameIn(calendar: var, group: var): string {
        const same = group.calendars.filter(c => c.name === calendar.name);
        const at = same.findIndex(c => c.id === calendar.id);
        return at > 0 ? `${calendar.name} (${at + 1})` : calendar.name;
    }

    function addCalendar(): void {
        const name = newName.text.trim();
        if (name === "") {
            adding = false;
            return;
        }
        Calendar.addCalendar(name, error => {
            root.addError = error;
            if (error === "") {
                newName.text = "";
                root.adding = false;
            }
        });
    }

    function calendarMenu(button: Item, calendar: var): void {
        const entries = [
            { icon: "visibility", label: "Show only this", run: () => Calendar.showOnly(calendar.id) },
            { icon: "select_all", label: "Show all calendars", run: () => Calendar.showAll() }
        ];
        if (calendar.source !== "local")
            entries.push({ separator: true }, { icon: "open_in_new", label: "Open in Google Calendar", run: () => Qt.openUrlExternally("https://calendar.google.com/calendar/r") });
        page.openMenu(button, entries);
    }

    Flickable {
        anchors.fill: parent
        anchors.margins: 14
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: column.implicitHeight

        ColumnLayout {
            id: column

            width: parent.width
            spacing: 14

            AppTitle {
                Layout.topMargin: 2
                Layout.leftMargin: 3
                text: "Calendar"
                icon: `file://${Quickshell.shellDir}/../assets/icons/courier-calendar-tab.svg`
                iconSize: 22
                fontSize: 17
                color: Theme.sheetInk
            }

            Pill {
                Layout.fillWidth: true
                style: "filled"
                icon: "add"
                text: "Create event"
                size: 38
                fontSize: 13
                onClicked: root.page.createEvent(Calendar.selected, -1)
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: month.implicitHeight + 20
                radius: 13
                color: Theme.glass ? Theme.sheetControl : Theme.glassCard
                border.width: Theme.glass ? 0 : 1
                border.color: Theme.glassBorderSubtle

                MiniMonth {
                    id: month

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    selected: Calendar.selected
                    longNames: false
                    ink: Theme.sheetInk
                    inkVariant: Theme.sheetInkVariant
                    pickedFill: Theme.sheetActive
                    onPicked: day => Calendar.selected = day
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 4

                    Label {
                        Layout.fillWidth: true
                        text: "My calendars"
                        color: Theme.sheetInk
                        font.pixelSize: 13
                        weight: Font.Medium
                    }

                    IconButton {
                        icon: "add"
                        tip: "New calendar on this PC"
                        size: 26
                        filled: true
                        fillColor: Theme.sheetControl
                        iconColor: Theme.sheetInk
                        onClicked: {
                            root.adding = true;
                            root.addError = "";
                            newName.forceActiveFocus();
                        }
                    }
                }

                Repeater {
                    model: root.groups

                    delegate: ColumnLayout {
                        id: group

                        required property var modelData

                        Layout.fillWidth: true
                        spacing: 0

                        Label {
                            Layout.fillWidth: true
                            Layout.leftMargin: 4
                            Layout.topMargin: 6
                            Layout.bottomMargin: 2
                            text: group.modelData.title
                            elide: Text.ElideRight
                            color: Theme.sheetInkVariant
                            font.pixelSize: 11
                            weight: Font.Normal
                        }

                        Repeater {
                            model: group.modelData.calendars

                            delegate: Rectangle {
                                id: row

                                required property var modelData
                                readonly property bool on: !Calendar.hidden[modelData.id]

                                Layout.fillWidth: true
                                implicitHeight: 34
                                radius: 9
                                color: rowArea.containsMouse ? Theme.sheetHover : "transparent"

                                MouseArea {
                                    id: rowArea

                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Calendar.setHidden(row.modelData.id, row.on)
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 6
                                    anchors.rightMargin: 2
                                    spacing: 9

                                    CheckBox {
                                        checked: row.on
                                        tint: row.modelData.color
                                        checkColor: "#141826"
                                        border.color: row.modelData.color
                                        onToggled: Calendar.setHidden(row.modelData.id, row.on)
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: root.nameIn(row.modelData, group.modelData)
                                        elide: Text.ElideRight
                                        color: row.on ? Theme.sheetInk : Theme.sheetInkVariant
                                        font.pixelSize: 13
                                    }

                                    IconButton {
                                        id: moreButton

                                        icon: "more_horiz"
                                        tip: `${row.modelData.name} options`
                                        size: 26
                                        iconColor: Theme.sheetInkVariant
                                        onClicked: root.calendarMenu(moreButton, row.modelData)
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    visible: root.adding
                    implicitHeight: 32
                    radius: 9
                    color: Theme.sheetControl
                    border.width: 1
                    border.color: Theme.alpha(Theme.m3primary, 0.72)

                    TextInput {
                        id: newName

                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        verticalAlignment: TextInput.AlignVCenter
                        renderType: Text.NativeRendering
                        color: Theme.sheetInk
                        font.family: Theme.sans
                        font.pixelSize: 13
                        clip: true
                        onAccepted: root.addCalendar()
                        Keys.onEscapePressed: {
                            text = "";
                            root.adding = false;
                        }
                        onActiveFocusChanged: if (!activeFocus && text.trim() === "")
                            root.adding = false

                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: newName.text === ""
                            text: "Calendar name, then Enter"
                            color: Theme.sheetInkVariant
                            font.pixelSize: 12
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 4
                    visible: root.addError !== ""
                    text: root.addError
                    wrapMode: Text.Wrap
                    color: Theme.sheetError
                    font.pixelSize: 11
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: Theme.sheetDivider
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6

                Label {
                    Layout.leftMargin: 4
                    text: "Connected"
                    color: Theme.sheetInk
                    font.pixelSize: 13
                    weight: Font.Medium
                }

                Repeater {
                    model: Calendar.accounts

                    delegate: RowLayout {
                        id: account

                        required property var modelData
                        readonly property string syncState: Calendar.status.state ?? "never"

                        Layout.fillWidth: true
                        Layout.leftMargin: 4
                        Layout.rightMargin: 4
                        spacing: 8

                        Image {
                            Layout.preferredWidth: 22
                            Layout.preferredHeight: 22
                            source: Qt.resolvedUrl("../assets/google-calendar.png")
                            sourceSize: Qt.size(44, 44)
                            smooth: true
                            mipmap: true
                            asynchronous: true
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            Label {
                                text: "Google Calendar"
                                color: Theme.sheetInk
                                font.pixelSize: 12
                                weight: Font.Normal
                            }

                            Label {
                                Layout.fillWidth: true
                                text: account.modelData.email ?? account.modelData.id
                                elide: Text.ElideRight
                                color: Theme.sheetInkVariant
                                font.pixelSize: 11
                            }
                        }

                        Icon {
                            id: stateIcon

                            name: account.syncState === "ok" ? "check_circle" : account.syncState === "error" || account.syncState === "signed-out" ? "error" : "sync"
                            fill: account.syncState === "ok" || account.syncState === "error" ? 1 : 0
                            size: 18
                            color: account.syncState === "ok" ? Theme.sheetSuccess : account.syncState === "error" || account.syncState === "signed-out" ? Theme.sheetError : Theme.sheetInkVariant

                            RotationAnimation on rotation {
                                running: root.visible && account.syncState === "syncing"
                                from: 360
                                to: 0
                                duration: 1200
                                loops: Animation.Infinite
                                onStopped: stateIcon.rotation = 0
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 4
                    visible: Calendar.accounts.length === 0
                    text: "No Google account yet. Add one with courier-auth add <name>."
                    wrapMode: Text.Wrap
                    color: Theme.sheetInkVariant
                    font.pixelSize: 11
                }

                CalendarStatus {
                    Layout.fillWidth: true
                }
            }
        }
    }
}
