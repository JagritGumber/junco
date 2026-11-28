import QtQuick
import QtQuick.Layouts
import qs.services
import qs.components

// Create or edit an event on this PC: title, day, all day or a start and an
// end, place, calendar, reminder and notes. Enter in the title saves, Esc
// closes. Google calendars are read-only to Courier, so new events always
// land in a calendar on this PC.
Item {
    id: root

    property string eventId: ""
    property string day: Calendar.todayDay
    property bool allDay: false
    // Minutes after midnight of `day`; the end may pass 1440 into the next day.
    property int startMinutes: 9 * 60
    property int endMinutes: 10 * 60
    // All-day events: how many days.
    property int spanDays: 1
    property string calendarId: ""
    property var reminders: [10]
    property string error: ""
    property bool saving: false
    // "", "date", "start" or "end": which picker is open, and where.
    property string picker: ""
    property real pickerX: 0
    property real pickerY: 0

    onPickerChanged: {
        const button = picker === "date" ? dateButton : picker === "start" ? startButton : picker === "end" ? endButton : null;
        if (button !== null) {
            const at = button.mapToItem(card, 0, button.height + 6);
            pickerX = at.x;
            pickerY = at.y;
        }
    }

    readonly property var reminderChoices: [
        { label: "None", minutes: [] },
        { label: "At start", minutes: [0] },
        { label: "10 min", minutes: [10] },
        { label: "30 min", minutes: [30] },
        { label: "1 hour", minutes: [60] },
        { label: "1 day", minutes: [1440] }
    ]

    function reset(): void {
        error = "";
        saving = false;
        picker = "";
        title.text = "";
        place.text = "";
        notes.text = "";
        allDay = false;
        spanDays = 1;
        reminders = [10];
        calendarId = Calendar.localCalendars[0]?.id ?? "";
    }

    // minutes < 0: the next hour today, 9 am on other days.
    function create(onDay: string, minutes: int): void {
        reset();
        eventId = "";
        day = onDay;
        const now = new Date();
        startMinutes = minutes >= 0 ? minutes : onDay === Calendar.todayDay ? Math.min(23, now.getHours() + 1) * 60 : 9 * 60;
        endMinutes = startMinutes + 60;
        open();
    }

    function createPrefilled(titleText: string, onDay: string, startMin: int, endMin: int): void {
        reset();
        eventId = "";
        day = onDay || Calendar.selected || Calendar.todayDay;
        title.text = (titleText ?? "").trim();
        const now = new Date();
        startMinutes = startMin >= 0 ? startMin : day === Calendar.todayDay ? Math.min(23, now.getHours() + 1) * 60 : 9 * 60;
        endMinutes = endMin > startMinutes ? endMin : startMinutes + 60;
        open();
        title.cursorPosition = title.text.length;
    }

    function timeOf(stamp: string): int {
        const match = /T(\d\d):(\d\d)/.exec(stamp);
        return match ? Number(match[1]) * 60 + Number(match[2]) : 0;
    }

    // asCopy: the same details as a new event (Duplicate).
    function edit(event: var, asCopy: bool): void {
        reset();
        eventId = asCopy ? "" : event.id;
        title.text = event.title;
        place.text = event.where ?? "";
        notes.text = event.notes ?? "";
        allDay = event.allDay;
        day = event.start.slice(0, 10);
        if (allDay) {
            spanDays = Math.max(1, Calendar.daysBetween(day, event.end.slice(0, 10)));
            startMinutes = 9 * 60;
            endMinutes = 10 * 60;
        } else {
            startMinutes = timeOf(event.start);
            endMinutes = Calendar.daysBetween(day, event.end.slice(0, 10)) * 1440 + timeOf(event.end);
        }
        calendarId = event.calendarId;
        reminders = event.reminders ?? [];
        open();
    }

    function open(): void {
        visible = true;
        title.forceActiveFocus();
    }

    function close(): void {
        visible = false;
        picker = "";
    }

    function stamp(minutes: int): string {
        const date = Calendar.addDays(day, Math.floor(minutes / 1440));
        const within = minutes % 1440;
        return `${date}T${String(Math.floor(within / 60)).padStart(2, "0")}:${String(within % 60).padStart(2, "0")}:00`;
    }

    function submit(): void {
        if (saving)
            return;
        if (title.text.trim() === "") {
            error = "Give the event a title.";
            title.forceActiveFocus();
            return;
        }
        saving = true;
        error = "";
        const event = {
            title: title.text.trim(),
            where: place.text.trim(),
            notes: notes.text.trim(),
            allDay: allDay,
            start: allDay ? day : stamp(startMinutes),
            end: allDay ? Calendar.addDays(day, spanDays) : stamp(endMinutes),
            calendarId: calendarId,
            reminders: reminders
        };
        Calendar.save(eventId, event, reason => {
            root.saving = false;
            if (reason === "") {
                Calendar.selected = root.day;
                root.close();
            } else {
                root.error = reason;
            }
        });
    }

    function sameMinutes(a: var, b: var): bool {
        return JSON.stringify(a) === JSON.stringify(b);
    }

    function duration(minutes: int): string {
        if (minutes < 60)
            return `${minutes} min`;
        const hours = minutes / 60;
        return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} hr${hours === 1 ? "" : "s"}`;
    }

    visible: false
    z: 90

    // The scrim: a click outside closes, like Esc.
    Rectangle {
        anchors.fill: parent
        radius: Theme.effectivePaneRadius
        color: Theme.alpha("#000000", 0.45)

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: root.close()
            onWheel: wheel => wheel.accepted = true
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.visible
        onActivated: root.picker !== "" ? root.picker = "" : root.close()
    }

    Rectangle {
        id: card

        anchors.centerIn: parent
        width: Math.min(500, parent.width - 32)
        height: form.implicitHeight + 32
        radius: 16
        color: Theme.m3popup
        border.width: 1
        border.color: Theme.glassPopupBorder

        MouseArea {
            anchors.fill: parent
            onClicked: root.picker = ""
        }

        ColumnLayout {
            id: form

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 16
            spacing: 16

            RowLayout {
                Layout.fillWidth: true

                Label {
                    Layout.fillWidth: true
                    text: root.eventId === "" ? "New event" : "Edit event"
                    font.pixelSize: 22
                    weight: Font.Medium
                }

                IconButton {
                    icon: "close"
                    tip: "Close (Esc)"
                    size: 38
                    onClicked: root.close()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 54
                radius: 16
                color: Theme.m3surfaceContainerHighest
                border.width: title.activeFocus ? 2 : 0
                border.color: Theme.m3primary

                TextInput {
                    id: title

                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    verticalAlignment: TextInput.AlignVCenter
                    renderType: Text.NativeRendering
                    color: Theme.m3onSurface
                    font.family: Theme.sans
                    font.pixelSize: 18
                    clip: true
                    onAccepted: root.submit()

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: title.text === ""
                        text: "Add a title"
                        color: Theme.m3onSurfaceVariant
                        font.pixelSize: 18
                    }
                }
            }

            // When.
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Icon {
                    name: "schedule"
                }

                Pill {
                    id: dateButton

                    text: root.allDay && root.spanDays > 1 ? `${Calendar.format(root.day, "ddd, d MMM")} – ${Calendar.format(Calendar.addDays(root.day, root.spanDays - 1), "ddd, d MMM")}` : Calendar.format(root.day, "ddd, d MMM yyyy")
                    size: 38
                    fontSize: 13
                    style: root.picker === "date" ? "outlined" : "tonal"
                    onClicked: root.picker = root.picker === "date" ? "" : "date"
                }

                Pill {
                    id: startButton

                    visible: !root.allDay
                    text: Calendar.clock(root.startMinutes)
                    size: 38
                    fontSize: 13
                    style: root.picker === "start" ? "outlined" : "tonal"
                    onClicked: root.picker = root.picker === "start" ? "" : "start"
                }

                Label {
                    visible: !root.allDay
                    text: "–"
                    color: Theme.m3onSurfaceVariant
                }

                Pill {
                    id: endButton

                    visible: !root.allDay
                    text: Calendar.clock(root.endMinutes) + (root.endMinutes >= 1440 ? " +1 day" : "")
                    size: 38
                    fontSize: 13
                    style: root.picker === "end" ? "outlined" : "tonal"
                    onClicked: root.picker = root.picker === "end" ? "" : "end"
                }

                Item {
                    Layout.fillWidth: true
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 34
                spacing: 12

                Label {
                    Layout.fillWidth: true
                    text: "All day"
                }

                Switch {
                    checked: root.allDay
                    onToggled: root.allDay = !root.allDay
                }
            }

            // Where.
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Icon {
                    name: "location_on"
                }

                TextInput {
                    id: place

                    Layout.fillWidth: true
                    renderType: Text.NativeRendering
                    color: Theme.m3onSurface
                    font.family: Theme.sans
                    font.pixelSize: 14
                    clip: true
                    onAccepted: root.submit()

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: place.text === ""
                        text: "Add a place"
                        color: Theme.m3onSurfaceVariant
                    }
                }
            }

            // Which calendar on this PC.
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Icon {
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 6
                    name: "calendar_today"
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8

                    Repeater {
                        model: Calendar.localCalendars

                        delegate: Rectangle {
                            id: choice

                            required property var modelData
                            readonly property bool chosen: root.calendarId === modelData.id

                            implicitWidth: choiceRow.implicitWidth + 26
                            implicitHeight: 34
                            radius: 17
                            color: chosen ? Theme.m3secondaryContainer : (choiceArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent")
                            border.width: chosen ? 0 : 1
                            border.color: Theme.m3outlineVariant

                            Row {
                                id: choiceRow

                                anchors.centerIn: parent
                                spacing: 8

                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 10
                                    height: 10
                                    radius: 5
                                    color: choice.modelData.color
                                }

                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: choice.modelData.name
                                    color: choice.chosen ? Theme.m3onSecondaryContainer : Theme.m3onSurfaceVariant
                                    font.pixelSize: 13
                                    weight: Font.Medium
                                }
                            }

                            MouseArea {
                                id: choiceArea

                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.calendarId = choice.modelData.id
                            }
                        }
                    }
                }
            }

            // Reminder.
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Icon {
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 6
                    name: "notifications"
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8

                    Repeater {
                        model: root.reminderChoices

                        delegate: Chip {
                            required property var modelData

                            text: modelData.label
                            selected: root.sameMinutes(root.reminders, modelData.minutes)
                            onClicked: root.reminders = modelData.minutes
                        }
                    }
                }
            }

            // Notes.
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Icon {
                    Layout.alignment: Qt.AlignTop
                    name: "notes"
                }

                TextEdit {
                    id: notes

                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(44, Math.min(110, contentHeight))
                    renderType: Text.NativeRendering
                    wrapMode: TextEdit.Wrap
                    color: Theme.m3onSurface
                    font.family: Theme.sans
                    font.pixelSize: 14
                    clip: true

                    Label {
                        visible: notes.text === ""
                        text: "Add notes"
                        color: Theme.m3onSurfaceVariant
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                text: "Saved on this PC. Your Google calendars are read-only in Junco."
                wrapMode: Text.Wrap
                color: Theme.m3onSurfaceVariant
                font.pixelSize: 12
            }

            Label {
                Layout.fillWidth: true
                visible: root.error !== ""
                text: root.error
                wrapMode: Text.Wrap
                color: Theme.m3error
                font.pixelSize: 13
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 8

                Item {
                    Layout.fillWidth: true
                }

                Pill {
                    style: "text"
                    text: "Cancel"
                    onClicked: root.close()
                }

                Pill {
                    style: "filled"
                    icon: root.saving ? "hourglass_top" : "check"
                    text: root.eventId === "" ? "Save" : "Save changes"
                    onClicked: root.submit()
                }
            }
        }

        // The day picker, under the date button.
        Rectangle {
            visible: root.picker === "date"
            x: root.pickerX
            y: root.pickerY
            width: 300
            height: pickMonth.implicitHeight + 24
            radius: 20
            color: Theme.m3popupHigh
            border.width: 1
            border.color: Theme.alpha(Theme.m3outlineVariant, 0.6)
            z: 5

            MouseArea {
                anchors.fill: parent
            }

            MiniMonth {
                id: pickMonth

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                selected: root.day
                longNames: true
                onPicked: chosen => {
                    root.day = chosen;
                    root.picker = "";
                }
            }
        }

        // Start and end times in 15-minute steps; the end list counts from the start.
        Rectangle {
            id: times

            readonly property bool forEnd: root.picker === "end"
            visible: root.picker === "start" || root.picker === "end"
            x: root.pickerX
            y: root.pickerY
            width: forEnd ? 220 : 160
            height: 260
            radius: 18
            color: Theme.m3popupHigh
            border.width: 1
            border.color: Theme.alpha(Theme.m3outlineVariant, 0.6)
            clip: true
            z: 5

            onVisibleChanged: if (visible)
                slots.positionViewAtIndex(forEnd ? 3 : Math.floor(root.startMinutes / 15), ListView.Center)

            ListView {
                id: slots

                anchors.fill: parent
                anchors.margins: 6
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: 96

                delegate: Rectangle {
                    id: slot

                    required property int index
                    readonly property int minutes: times.forEnd ? root.startMinutes + (index + 1) * 15 : index * 15
                    readonly property bool current: minutes === (times.forEnd ? root.endMinutes : root.startMinutes)

                    width: ListView.view.width
                    height: 36
                    radius: 10
                    color: current ? Theme.m3secondaryContainer : (slotArea.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent")

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        x: 12
                        text: times.forEnd ? `${Calendar.clock(slot.minutes)}  (${root.duration(slot.minutes - root.startMinutes)})` : Calendar.clock(slot.minutes)
                        color: slot.current ? Theme.m3onSecondaryContainer : Theme.m3onSurface
                        font.pixelSize: 13
                    }

                    MouseArea {
                        id: slotArea

                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (times.forEnd) {
                                root.endMinutes = slot.minutes;
                            } else {
                                // Moving the start keeps the length.
                                const length = root.endMinutes - root.startMinutes;
                                root.startMinutes = slot.minutes;
                                root.endMinutes = slot.minutes + length;
                            }
                            root.picker = "";
                        }
                    }
                }
            }
        }
    }
}
