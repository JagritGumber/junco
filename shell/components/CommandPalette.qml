import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import Quickshell
import qs.services

// Floating frosted-glass Command Palette (Ctrl+K) shared by Junco Mail & Calendar.
//
// Strictly follows Junco Round 10 + 2-color complementary glass rules:
//   - Dense neutral frosted card (Theme.m3popupHigh) + GlassEdge inner top/left light
//     + static 9-slice shadow (card-shadow.png).
//   - Zero 1px light outlines around card, input, rows, chips or keycaps.
//   - Zero vertical left accent stripes on rows.
//   - Zero font.bold / font.weight > Font.Normal (uses Label's Rubik wght axis).
//   - Zero QML blur shaders or continuous idle animations (130 ms open/close only).
Item {
    id: root

    property string placeholder: "Type a command or search…"
    property string modeLabel: ""
    property string emptyHint: ""
    property var items: []
    property string query: ""
    property string activeBadge: ""
    property string activeBadgeTone: "complement"
    property bool open: false
    property int currentIndex: 0
    property var previousFocus: null

    signal triggered(var item)
    signal tabRequested(string currentQuery, var selectedItem)
    signal opened
    signal closed

    function show(): void {
        const win = root.Window.window;
        previousFocus = win ? win.activeFocusItem : null;
        query = "";
        currentIndex = 0;
        open = true;
        opened();
        if (overlayLoader.item) {
            overlayLoader.item.syncInput("");
            overlayLoader.item.focusInput();
        }
        Qt.callLater(() => {
            if (root.open && overlayLoader.item)
                overlayLoader.item.focusInput();
        });
    }

    function close(restoreFocus): void {
        if (!open)
            return;
        open = false;
        closed();
        const shouldRestore = restoreFocus === undefined ? true : Boolean(restoreFocus);
        const target = previousFocus;
        previousFocus = null;
        if (shouldRestore && target && typeof target.forceActiveFocus === "function") {
            Qt.callLater(() => {
                try {
                    if (target && !root.open)
                        target.forceActiveFocus();
                } catch (e) {
                    // Previous focus item was destroyed while palette was open.
                }
            });
        }
    }

    function toggle(): void {
        if (open)
            close(true);
        else
            show();
    }

    function setQuery(nextText: string): void {
        const value = nextText ?? "";
        query = value;
        if (overlayLoader.item)
            overlayLoader.item.syncInput(value);
    }

    function moveSelection(delta: int): void {
        const count = items ? items.length : 0;
        if (count <= 0) {
            currentIndex = 0;
            return;
        }
        currentIndex = ((currentIndex + delta) % count + count) % count;
        if (overlayLoader.item)
            overlayLoader.item.ensureVisible(currentIndex);
    }

    function activateCurrent(): void {
        const count = items ? items.length : 0;
        if (count <= 0 || currentIndex < 0 || currentIndex >= count)
            return;
        const item = items[currentIndex];
        if (!item || item.disabled)
            return;
        triggered(item);
    }

    onItemsChanged: {
        const count = items ? items.length : 0;
        if (count === 0)
            currentIndex = 0;
        else if (currentIndex >= count || currentIndex < 0)
            currentIndex = 0;
        if (count > 0 && overlayLoader.item)
            overlayLoader.item.ensureVisible(currentIndex);
    }

    visible: open || opacity > 0.001
    opacity: open ? 1.0 : 0.0
    z: 180

    Behavior on opacity {
        NumberAnimation {
            duration: 130
            easing.type: Easing.OutCubic
        }
    }

    // Lazily instantiate the modal card, 9-slice shadow, TextInput and ListView
    // only while open/fading so closed palettes cost ~0 MB RAM and 0 ms at startup.
    Loader {
        id: overlayLoader

        anchors.fill: parent
        active: root.open || root.opacity > 0.001
        sourceComponent: overlayComponent
    }

    Component {
        id: overlayComponent

        Item {
            id: overlay

            anchors.fill: parent

            function syncInput(value: string): void {
                if (searchInput.text !== value)
                    searchInput.text = value;
                searchInput.cursorPosition = value.length;
                searchInput.forceActiveFocus();
            }

            function focusInput(): void {
                searchInput.forceActiveFocus();
            }

            function ensureVisible(idx: int): void {
                resultsList.positionViewAtIndex(idx, ListView.Contain);
            }

            // Scrim: click outside dismisses and restores focus.
            Rectangle {
                anchors.fill: parent
                radius: Theme.paneRadius
                color: Theme.dark ? Theme.alpha("#000000", 0.36) : Theme.alpha("#0e1328", 0.20)

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onClicked: root.close(true)
                    onWheel: wheel => wheel.accepted = true
                }
            }

            Shortcut {
                sequence: "Escape"
                enabled: root.open
                onActivated: root.close(true)
            }

            // Floating frosted-glass modal centered in upper-middle third.
            Rectangle {
                id: card

                readonly property int maxCardHeight: Math.max(200, Math.min(440, overlay.height - 48))
                readonly property int chromeHeight: 54 + 1 + 1 + 34 + 12
                readonly property int desiredListHeight: root.items.length === 0
                    ? 124
                    : Math.min(maxCardHeight - chromeHeight, Math.max(64, resultsList.contentHeight + 6))

                width: Math.min(584, Math.max(320, overlay.width - 32))
                height: Math.min(maxCardHeight, chromeHeight + desiredListHeight)
                x: Math.round((overlay.width - width) / 2)
                y: Math.max(24, Math.min(Math.round(overlay.height * 0.14), overlay.height - height - 24))
                radius: 18
                color: Theme.m3popupHigh
                border.width: 0

                transform: Translate {
                    y: root.open ? 0 : -8

                    Behavior on y {
                        NumberAnimation {
                            duration: 130
                            easing.type: Easing.OutCubic
                        }
                    }
                }

                // Static pre-rendered 9-slice shadow (zero QML shaders).
                BorderImage {
                    visible: Theme.glass
                    z: -1
                    anchors.fill: parent
                    anchors.margins: -14
                    source: `file://${Quickshell.shellDir}/../assets/glass/card-shadow.png`
                    border.left: 28
                    border.right: 28
                    border.top: 28
                    border.bottom: 28
                    horizontalTileMode: BorderImage.Stretch
                    verticalTileMode: BorderImage.Stretch
                    smooth: true
                }

                // Soft top & left inner light (zero outline stroke).
                GlassEdge {
                    visible: Theme.glass
                    z: 2
                    radius: card.radius
                }

                // Absorb clicks inside the card so they don't hit the scrim.
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: wheel => wheel.accepted = false
                }

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    // Top search bar
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 54
                        Layout.leftMargin: 16
                        Layout.rightMargin: 14
                        spacing: 10

                        Icon {
                            name: "search"
                            size: 19
                            color: root.query.trim() !== "" ? Theme.m3primary : Theme.m3onSurfaceVariant
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            TextInput {
                                id: searchInput

                                anchors.fill: parent
                                verticalAlignment: TextInput.AlignVCenter
                                renderType: Text.NativeRendering
                                color: Theme.m3onSurface
                                selectionColor: Theme.m3primary
                                selectedTextColor: Theme.m3onPrimary
                                font.family: Theme.sans
                                font.pixelSize: 15
                                font.weight: Font.Normal
                                clip: true
                                text: root.query
                                onTextChanged: {
                                    if (root.query !== text) {
                                        root.query = text;
                                        root.currentIndex = 0;
                                    }
                                }

                                Keys.onUpPressed: event => {
                                    event.accepted = true;
                                    root.moveSelection(-1);
                                }
                                Keys.onDownPressed: event => {
                                    event.accepted = true;
                                    root.moveSelection(1);
                                }
                                Keys.onEscapePressed: event => {
                                    event.accepted = true;
                                    root.close(true);
                                }
                                Keys.onTabPressed: event => {
                                    event.accepted = true;
                                    const selected = root.items && root.currentIndex >= 0 && root.currentIndex < root.items.length
                                        ? root.items[root.currentIndex]
                                        : null;
                                    root.tabRequested(root.query, selected);
                                }
                                Keys.onReturnPressed: event => {
                                    event.accepted = true;
                                    root.activateCurrent();
                                }
                                Keys.onEnterPressed: event => {
                                    event.accepted = true;
                                    root.activateCurrent();
                                }
                                Keys.onPressed: event => {
                                    if (event.modifiers & Qt.ControlModifier) {
                                        if (event.key === Qt.Key_N) {
                                            event.accepted = true;
                                            root.moveSelection(1);
                                        } else if (event.key === Qt.Key_P) {
                                            event.accepted = true;
                                            root.moveSelection(-1);
                                        } else if (event.key === Qt.Key_K) {
                                            event.accepted = true;
                                            root.close(true);
                                        }
                                    }
                                }

                                Label {
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: searchInput.text === ""
                                    text: root.placeholder
                                    color: Theme.alpha(Theme.m3onSurfaceVariant, 0.78)
                                    font.pixelSize: 15
                                }
                            }
                        }

                        // Active smart-command pill badge
                        Rectangle {
                            visible: root.activeBadge !== ""
                            implicitWidth: modeBadgeLabel.implicitWidth + 16
                            implicitHeight: 24
                            radius: 12
                            border.width: 0
                            color: root.activeBadgeTone === "primary" ? Theme.m3primaryContainer : Theme.m3tertiaryContainer

                            Label {
                                id: modeBadgeLabel

                                anchors.centerIn: parent
                                text: root.activeBadge
                                color: root.activeBadgeTone === "primary" ? Theme.m3onPrimaryContainer : Theme.m3onTertiaryContainer
                                font.pixelSize: 11
                                weight: Font.Medium
                            }
                        }

                        // Clear query button
                        IconButton {
                            visible: searchInput.text !== ""
                            icon: "close"
                            tip: "Clear"
                            size: 26
                            onClicked: root.setQuery("")
                        }

                        // Subtle Ctrl K keycap when query is empty
                        Rectangle {
                            visible: searchInput.text === "" && root.activeBadge === ""
                            implicitWidth: ctrlKLabel.implicitWidth + 14
                            implicitHeight: 24
                            radius: 7
                            border.width: 0
                            color: Theme.glassControl

                            Label {
                                id: ctrlKLabel

                                anchors.centerIn: parent
                                text: "Ctrl K"
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 11
                                weight: Font.Medium
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 1
                        color: Theme.glassDivider
                    }

                    // Results area
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.topMargin: 6
                        Layout.bottomMargin: 6

                        // Empty state
                        ColumnLayout {
                            anchors.centerIn: parent
                            width: parent.width - 48
                            visible: root.items.length === 0
                            spacing: 6

                            Icon {
                                Layout.alignment: Qt.AlignHCenter
                                name: "search_off"
                                size: 28
                                color: Theme.alpha(Theme.m3onSurfaceVariant, 0.72)
                            }

                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: "No matching commands or items"
                                color: Theme.m3onSurface
                                font.pixelSize: 13
                                weight: Font.Medium
                            }

                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                Layout.fillWidth: true
                                visible: root.emptyHint !== ""
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                                text: root.emptyHint
                                color: Theme.m3onSurfaceVariant
                                font.pixelSize: 11
                            }
                        }

                        ListView {
                            id: resultsList

                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            visible: root.items.length > 0
                            clip: true
                            cacheBuffer: 240
                            spacing: 2
                            boundsBehavior: Flickable.StopAtBounds
                            currentIndex: root.currentIndex
                            model: root.items

                            section.property: "group"
                            section.criteria: ViewSection.FullString
                            section.delegate: Item {
                                required property string section

                                width: resultsList.width
                                height: 26

                                Label {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 10
                                    anchors.bottom: parent.bottom
                                    anchors.bottomMargin: 4
                                    text: section
                                    color: Theme.alpha(Theme.m3onSurfaceVariant, 0.84)
                                    font.pixelSize: 11
                                    weight: Font.Medium
                                }
                            }

                            delegate: Rectangle {
                                id: rowItem

                                required property var modelData
                                required property int index

                                readonly property bool isSelected: index === root.currentIndex
                                readonly property bool isDisabled: Boolean(modelData.disabled)
                                readonly property string badgeText: modelData.badge ?? ""
                                readonly property string badgeTone: modelData.badgeTone ?? ""
                                readonly property string shortcutText: modelData.shortcut ?? ""
                                readonly property string subtitleText: modelData.subtitle ?? ""

                                width: resultsList.width
                                height: subtitleText !== "" ? 50 : 40
                                radius: 11
                                border.width: 0
                                color: isSelected
                                    ? Theme.glassSelectedRow
                                    : (rowArea.containsMouse ? Theme.glassHover : "transparent")
                                opacity: isDisabled ? 0.58 : 1.0

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 10

                                    // Leading icon chip (fill-step only, zero outline)
                                    Rectangle {
                                        Layout.alignment: Qt.AlignVCenter
                                        implicitWidth: 30
                                        implicitHeight: 30
                                        radius: 9
                                        border.width: 0
                                        color: rowItem.badgeTone === "complement" && (rowItem.modelData.group === "Next up" || rowItem.modelData.group === "Smart command")
                                            ? Theme.m3tertiaryContainer
                                            : rowItem.isSelected
                                                ? Theme.alpha(Theme.m3primary, Theme.dark ? 0.22 : 0.14)
                                                : Theme.glassControl

                                        Icon {
                                            anchors.centerIn: parent
                                            name: rowItem.modelData.icon || "chevron_right"
                                            size: 17
                                            color: rowItem.badgeTone === "complement" && (rowItem.modelData.group === "Next up" || rowItem.modelData.group === "Smart command")
                                                ? Theme.m3onTertiaryContainer
                                                : rowItem.isSelected
                                                    ? Theme.m3primary
                                                    : Theme.m3onSurfaceVariant
                                        }
                                    }

                                    // Title + concise subtitle
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.alignment: Qt.AlignVCenter
                                        spacing: 1

                                        Label {
                                            Layout.fillWidth: true
                                            text: rowItem.modelData.title ?? ""
                                            elide: Text.ElideRight
                                            color: Theme.m3onSurface
                                            font.pixelSize: 13
                                            weight: rowItem.isSelected ? Font.DemiBold : Font.Medium
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            visible: rowItem.subtitleText !== ""
                                            text: rowItem.subtitleText
                                            elide: Text.ElideRight
                                            color: Theme.m3onSurfaceVariant
                                            font.pixelSize: 11
                                            weight: Font.Normal
                                        }
                                    }

                                    // Complementary / primary live status pill
                                    Rectangle {
                                        visible: rowItem.badgeText !== ""
                                        Layout.alignment: Qt.AlignVCenter
                                        implicitWidth: badgeLabel.implicitWidth + 14
                                        implicitHeight: 22
                                        radius: 11
                                        border.width: 0
                                        color: rowItem.badgeTone === "complement"
                                            ? Theme.m3tertiaryContainer
                                            : rowItem.badgeTone === "primary"
                                                ? Theme.m3primaryContainer
                                                : rowItem.badgeTone === "pill"
                                                    ? Theme.pill
                                                    : rowItem.badgeTone === "error"
                                                        ? Theme.m3errorContainer
                                                        : Theme.glassControl

                                        Label {
                                            id: badgeLabel

                                            anchors.centerIn: parent
                                            text: rowItem.badgeText
                                            color: rowItem.badgeTone === "complement"
                                                ? Theme.m3onTertiaryContainer
                                                : rowItem.badgeTone === "primary"
                                                    ? Theme.m3onPrimaryContainer
                                                    : rowItem.badgeTone === "pill"
                                                        ? Theme.pillInk
                                                        : rowItem.badgeTone === "error"
                                                            ? Theme.m3onErrorContainer
                                                            : Theme.m3onSurfaceVariant
                                            font.pixelSize: 11
                                            weight: Font.Medium
                                        }
                                    }

                                    // Shortcut keycap / time tag
                                    Rectangle {
                                        visible: rowItem.shortcutText !== ""
                                        Layout.alignment: Qt.AlignVCenter
                                        implicitWidth: shortcutLabel.implicitWidth + 12
                                        implicitHeight: 22
                                        radius: 6
                                        border.width: 0
                                        color: Theme.glassControl

                                        Label {
                                            id: shortcutLabel

                                            anchors.centerIn: parent
                                            text: rowItem.shortcutText
                                            color: Theme.m3onSurfaceVariant
                                            font.pixelSize: 11
                                            weight: Font.Medium
                                        }
                                    }
                                }

                                MouseArea {
                                    id: rowArea

                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: rowItem.isDisabled ? Qt.ArrowCursor : Qt.PointingHandCursor
                                    onPositionChanged: {
                                        if (root.currentIndex !== rowItem.index)
                                            root.currentIndex = rowItem.index;
                                    }
                                    onClicked: {
                                        root.currentIndex = rowItem.index;
                                        root.activateCurrent();
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 1
                        color: Theme.glassDivider
                    }

                    // Minimal bottom footer bar
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        Layout.leftMargin: 16
                        Layout.rightMargin: 16
                        spacing: 8

                        Label {
                            Layout.fillWidth: true
                            text: "↑↓ Navigate  ·  ↵ Run  ·  Tab Complete  ·  Esc Close"
                            elide: Text.ElideRight
                            color: Theme.alpha(Theme.m3onSurfaceVariant, 0.82)
                            font.pixelSize: 11
                        }

                        Label {
                            visible: root.modeLabel !== ""
                            text: root.modeLabel
                            color: Theme.alpha(Theme.m3onSurfaceVariant, 0.85)
                            font.pixelSize: 11
                            weight: Font.Medium
                        }
                    }
                }
            }
        }
    }
}
