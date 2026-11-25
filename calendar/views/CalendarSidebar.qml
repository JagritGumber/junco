import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.services
import qs.components

// The Calendar page's left column: create an event, jump to a day, choose
// which calendars show, and the Google account they come from.
Rectangle {
    id: root

    // The Calendar page, for creating events and opening menus.
    required property var page

    property bool adding: false
    property string addError: ""

    // "My calendars" grouped by where they come from: each Google account's
    // own calendars under its address, Birthdays (from every account's
    // contacts), then the calendars on this PC.
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

    // A calendar's name, numbered when another in the same group has it too
    // (two subscriptions to Google's "Holidays in India", say; their events
    // show once either way).
    function nameIn(calendar: var, group: var): string {
        const same = group.calendars.filter(c => c.name === calendar.name);
        // By id: a Repeater hands each row a copy, so indexOf never matches.
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

    radius: 28
    color: Theme.m3surfaceContainerLow

    Flickable {
        anchors.fill: parent
        anchors.margins: 16
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentHeight: column.implicitHeight

        ColumnLayout {
            id: column

            width: parent.width
            spacing: 18

            AppTitle {
                Layout.topMargin: 6
                Layout.leftMargin: 2
                text: "Calendar"
                icon: `file://${Quickshell.shellDir}/../assets/icons/courier-calendar-tab.svg`
            }

            Pill {
                Layout.fillWidth: true
                style: "filled"
                icon: "add"
                text: "Create event"
                size: 56
                fontSize: 16
                onClicked: root.page.createEvent(Calendar.selected, -1)
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: month.implicitHeight + 24
                radius: 20
                color: Theme.m3surfaceContainer

                MiniMonth {
                    id: month

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 12
                    selected: Calendar.selected
                    longNames: true
                    onPicked: day => Calendar.selected = day
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 10

                    Label {
                        Layout.fillWidth: true
                        text: "My calendars"
                        font.pixelSize: 15
                        font.weight: Font.Medium
                    }

                    IconButton {
                        icon: "add"
                        tip: "New calendar on this PC"
                        size: 36
                        filled: true
                        fillColor: Theme.m3surfaceContainerHigh
                        iconColor: Theme.m3onSurface
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
                            Layout.leftMargin: 10
                            Layout.topMargin: 8
                            Layout.bottomMargin: 2
                            text: group.modelData.title
                            elide: Text.ElideRight
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                            font.weight: Font.Medium
                        }

                        Repeater {
                            model: group.modelData.calendars

                            delegate: Rectangle {
                                id: row

                                required property var modelData
                                readonly property bool on: !Calendar.hidden[modelData.id]

                                Layout.fillWidth: true
                                implicitHeight: 44
                                radius: 14
                                color: rowArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.06) : "transparent"

                                MouseArea {
                                    id: rowArea

                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: Calendar.setHidden(row.modelData.id, row.on)
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 2
                                    spacing: 14

                                    CheckBox {
                                        checked: row.on
                                        tint: row.modelData.color
                                        checkColor: "#1a1c22"
                                        border.color: row.modelData.color
                                        onToggled: Calendar.setHidden(row.modelData.id, row.on)
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: root.nameIn(row.modelData, group.modelData)
                                        elide: Text.ElideRight
                                        color: row.on ? Theme.m3onSurface : Theme.m3onSurfaceVariant
                                    }

                                    IconButton {
                                        id: moreButton

                                        icon: "more_horiz"
                                        tip: `${row.modelData.name} options`
                                        size: 34
                                        onClicked: root.calendarMenu(moreButton, row.modelData)
                                    }
                                }
                            }
                        }
                    }
                }

                // A new calendar on this PC: type a name, Enter adds it.
                Rectangle {
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    visible: root.adding
                    implicitHeight: 44
                    radius: 14
                    color: Theme.m3surfaceContainerHigh
                    border.width: 1
                    border.color: Theme.alpha(Theme.m3primary, 0.6)

                    TextInput {
                        id: newName

                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        verticalAlignment: TextInput.AlignVCenter
                        renderType: Text.NativeRendering
                        color: Theme.m3onSurface
                        font.family: Theme.sans
                        font.pixelSize: 14
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
                            color: Theme.m3onSurfaceVariant
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 10
                    visible: root.addError !== ""
                    text: root.addError
                    wrapMode: Text.Wrap
                    color: Theme.m3error
                    font.pixelSize: 12
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: Theme.m3outlineVariant
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 10

                Label {
                    Layout.leftMargin: 10
                    text: "Connected calendars"
                    font.pixelSize: 15
                    font.weight: Font.Medium
                }

                Repeater {
                    model: Calendar.accounts

                    delegate: RowLayout {
                        id: account

                        required property var modelData
                        readonly property string syncState: Calendar.status.state ?? "never"

                        Layout.fillWidth: true
                        Layout.leftMargin: 10
                        Layout.rightMargin: 8
                        spacing: 12

                        Image {
                            Layout.preferredWidth: 32
                            Layout.preferredHeight: 32
                            source: Qt.resolvedUrl("../assets/google-calendar.png")
                            sourceSize: Qt.size(64, 64)
                            smooth: true
                            mipmap: true
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1

                            Label {
                                text: "Google Calendar"
                                font.weight: Font.Medium
                            }

                            Label {
                                Layout.fillWidth: true
                                text: account.modelData.email ?? account.modelData.id
                                elide: Text.ElideRight
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 12
                            }
                        }

                        Icon {
                            id: stateIcon

                            name: account.syncState === "ok" ? "check_circle" : account.syncState === "error" || account.syncState === "signed-out" ? "error" : "sync"
                            fill: account.syncState === "ok" || account.syncState === "error" ? 1 : 0
                            size: 24
                            color: account.syncState === "ok" ? Theme.m3success : account.syncState === "error" || account.syncState === "signed-out" ? Theme.m3error : Theme.m3onSurfaceVariant

                            RotationAnimation on rotation {
                                running: stateIcon.name === "sync"
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
                    Layout.leftMargin: 10
                    visible: Calendar.accounts.length === 0
                    text: "No Google account yet. Add one with courier-auth add <name>."
                    wrapMode: Text.Wrap
                    color: Theme.m3onSurfaceVariant
                    font.pixelSize: 12
                }

                CalendarStatus {
                    Layout.fillWidth: true
                }
            }
        }
    }
}
