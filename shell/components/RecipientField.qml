import QtQuick
import QtQuick.Layouts
import qs.services

// One address line of an email (To, Cc or Bcc). People show as chips; typing
// suggests people you write to. Enter or Tab takes the highlighted suggestion,
// a comma adds exactly what's typed, Backspace on an empty line removes the
// last person.
Item {
    id: root

    property string label
    // "Name <address>" or a bare address.
    property var people: []
    property int highlighted: 0
    readonly property alias typing: input.activeFocus

    signal edited(var people)

    readonly property var suggestions: {
        const needle = input.text.trim().toLowerCase();
        if (needle === "")
            return [];
        const taken = new Set(people.map(person => addressOf(person)));
        return Inbox.contacts.filter(c => !taken.has(c.address) && `${c.name} ${c.address}`.toLowerCase().includes(needle)).slice(0, 6);
    }
    readonly property bool suggesting: input.activeFocus && suggestions.length > 0

    function addressOf(person: string): string {
        const match = /<([^>]+)>/.exec(person);
        return (match ? match[1] : person).trim().toLowerCase();
    }

    function nameOf(person: string): string {
        const match = /^\s*"?([^"<]*?)"?\s*</.exec(person);
        return match && match[1].trim() ? match[1].trim() : addressOf(person);
    }

    function add(person: string): void {
        const text = person.trim().replace(/[,;]+$/, "").trim();
        if (text === "")
            return;
        people = people.concat([text]);
        input.text = "";
        highlighted = 0;
        edited(people);
    }

    function take(contact: var): void {
        add(contact.name ? `${contact.name} <${contact.address}>` : contact.address);
    }

    function remove(number: int): void {
        people = people.filter((_, at) => at !== number);
        edited(people);
    }

    // A typed address not added yet still counts, so Send never drops it.
    // Half a name stays as typed, for a suggestion to finish.
    function flush(): void {
        if (input.text.includes("@"))
            add(input.text);
    }

    function focusInput(): void {
        input.forceActiveFocus();
    }

    implicitHeight: Math.max(46, flow.implicitHeight + 14)
    z: suggesting ? 10 : 0

    Label {
        id: caption

        y: 13
        width: 44
        text: root.label
        color: Theme.m3onSurfaceVariant
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.IBeamCursor
        onClicked: input.forceActiveFocus()
    }

    Flow {
        id: flow

        anchors.left: caption.right
        anchors.right: parent.right
        y: 7
        spacing: 6

        Repeater {
            model: root.people

            delegate: Rectangle {
                id: chip

                required property string modelData
                required property int index

                height: 32
                width: chipRow.implicitWidth + 18
                radius: 16
                color: Theme.m3secondaryContainer

                Row {
                    id: chipRow

                    x: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.nameOf(chip.modelData)
                        color: Theme.m3onSecondaryContainer
                        font.pixelSize: 13
                        font.weight: Font.Medium
                    }

                    IconButton {
                        anchors.verticalCenter: parent.verticalCenter
                        icon: "close"
                        tip: `Remove ${root.addressOf(chip.modelData)}`
                        size: 22
                        iconColor: Theme.m3onSecondaryContainer
                        onClicked: root.remove(chip.index)
                    }
                }
            }
        }

        TextInput {
            id: input

            width: root.people.length > 0 ? Math.min(220, flow.width) : flow.width
            height: 32
            verticalAlignment: TextInput.AlignVCenter
            renderType: Text.NativeRendering
            color: Theme.m3onSurface
            selectionColor: Theme.m3primary
            selectedTextColor: Theme.m3onPrimary
            font.family: Theme.sans
            font.pixelSize: 14
            clip: true
            onTextChanged: {
                root.highlighted = 0;
                if (/[,;]$/.test(text))
                    root.add(text);
            }
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || (event.key === Qt.Key_Tab && text.trim() !== "")) {
                    if (event.modifiers & Qt.ControlModifier) {
                        event.accepted = false;
                        return;
                    }
                    if (root.suggestions.length > 0)
                        root.take(root.suggestions[root.highlighted]);
                    else
                        root.add(text);
                    event.accepted = true;
                } else if (event.key === Qt.Key_Backspace && text === "" && root.people.length > 0) {
                    root.remove(root.people.length - 1);
                    event.accepted = true;
                } else if (event.key === Qt.Key_Down && root.suggestions.length > 0) {
                    root.highlighted = (root.highlighted + 1) % root.suggestions.length;
                    event.accepted = true;
                } else if (event.key === Qt.Key_Up && root.suggestions.length > 0) {
                    root.highlighted = (root.highlighted + root.suggestions.length - 1) % root.suggestions.length;
                    event.accepted = true;
                }
            }
            onActiveFocusChanged: if (!activeFocus)
                root.flush()
        }
    }

    // Suggestions under the line.
    Rectangle {
        visible: root.suggesting
        x: caption.width
        y: parent.height + 2
        width: Math.min(420, parent.width - caption.width)
        height: list.implicitHeight + 12
        radius: 16
        color: Theme.m3popupHigh
        border.width: 1
        border.color: Theme.alpha(Theme.m3outlineVariant, 0.6)

        Column {
            id: list

            x: 6
            y: 6
            width: parent.width - 12

            Repeater {
                model: root.suggestions

                delegate: Rectangle {
                    id: suggestion

                    required property var modelData
                    required property int index

                    width: list.width
                    height: 48
                    radius: 10
                    color: index === root.highlighted || pick.containsMouse ? Theme.alpha(Theme.m3onSurface, 0.08) : "transparent"

                    Column {
                        x: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 24

                        Label {
                            width: parent.width
                            text: suggestion.modelData.name || suggestion.modelData.address
                            elide: Text.ElideRight
                            font.weight: Font.Medium
                        }

                        Label {
                            width: parent.width
                            visible: suggestion.modelData.name !== ""
                            text: suggestion.modelData.address
                            elide: Text.ElideRight
                            color: Theme.m3onSurfaceVariant
                            font.pixelSize: 12
                        }
                    }

                    MouseArea {
                        id: pick

                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.take(suggestion.modelData);
                            input.forceActiveFocus();
                        }
                    }
                }
            }
        }
    }
}
