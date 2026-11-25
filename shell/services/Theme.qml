pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// Caelestia's Material 3 colour roles, read from the same scheme.json the
// shell watches, so Courier recolours live with the wallpaper. Fonts follow
// Caelestia (Rubik, Material Symbols Rounded).
//
// Roles carry Caelestia's m3 prefix: QML treats a property named onX as a
// signal handler when X exists, so plain onSurface would read back as black.
Singleton {
    id: root

    property var scheme: ({})
    // Caelestia's scheme says whether the wallpaper made a light or dark theme.
    property string mode: "dark"
    readonly property bool dark: mode !== "light"

    function role(name: string, fallback: string): color {
        const value = scheme[name];
        return value ? `#${String(value).replace("#", "")}` : fallback;
    }

    function alpha(base: color, opacity: real): color {
        return Qt.rgba(base.r, base.g, base.b, opacity);
    }

    // Caelestia's transparency (shell.json appearance.transparency, defaults
    // from its source: base 0.85, layers 0.4). The window background keeps
    // `base` opacity; each surface on it gets `layers`, lightened a touch so
    // stacked surfaces stay legible. Hyprland blurs what shows through. Text,
    // icons and accent colours stay solid.
    property bool transparent: false
    property real base: 0.85
    property real layers: 0.4

    function layer(c: color, depth: int): color {
        if (!transparent)
            return c;
        if (depth === 0)
            return Qt.rgba(c.r, c.g, c.b, base);
        const luminance = Math.sqrt(0.299 * c.r * c.r + 0.587 * c.g * c.g + 0.114 * c.b * c.b);
        if (luminance === 0)
            return Qt.rgba(c.r, c.g, c.b, layers);
        // Caelestia's alterColour, with a typical wallpaper luminance of 0.3.
        const offset = (dark ? 1 : -depth / 2) * (dark ? 0.3 : 0.2) * (1 - base) * (1 + 0.3 * (dark ? 2.5 : 1));
        const scale = (luminance + offset) / luminance;
        const clamp = v => Math.max(0, Math.min(1, v));
        return Qt.rgba(clamp(c.r * scale), clamp(c.g * scale), clamp(c.b * scale), layers);
    }

    readonly property color m3primary: role("primary", "#b9c6ee")
    readonly property color m3onPrimary: role("onPrimary", "#333f61")
    readonly property color m3primaryContainer: role("primaryContainer", "#455274")
    readonly property color m3onPrimaryContainer: role("onPrimaryContainer", "#dbe2ff")
    readonly property color m3secondaryContainer: layer(role("secondaryContainer", "#353b4d"), 1)
    readonly property color m3onSecondaryContainer: role("onSecondaryContainer", "#b9bfd5")
    readonly property color m3tertiary: role("tertiary", "#e0b9de")
    readonly property color m3tertiaryContainer: role("tertiaryContainer", "#5b3f5d")
    readonly property color m3onTertiaryContainer: role("onTertiaryContainer", "#fdd6fb")
    readonly property color m3error: role("error", "#ffb4ab")
    readonly property color m3success: role("success", "#b5ccba")
    readonly property color m3errorContainer: role("errorContainer", "#93000a")
    readonly property color m3onErrorContainer: role("onErrorContainer", "#ffdad6")
    readonly property color m3surface: layer(role("surface", "#0d0e12"), 0)
    readonly property color m3surfaceContainerLow: layer(role("surfaceContainerLow", "#121318"), 1)
    readonly property color m3surfaceContainer: layer(role("surfaceContainer", "#18191f"), 1)
    readonly property color m3surfaceContainerHigh: layer(role("surfaceContainerHigh", "#1d1f26"), 1)
    readonly property color m3surfaceContainerHighest: layer(role("surfaceContainerHighest", "#23262e"), 1)
    // Menus and dialogs float over content, so they stay solid even with
    // transparency on; anything showing through them reads as clutter.
    readonly property color m3popup: role("surfaceContainerHigh", "#1d1f26")
    readonly property color m3popupHigh: role("surfaceContainerHighest", "#23262e")
    // The snackbar: Material's inverse surface, so it reads against any panel.
    readonly property color m3inverseSurface: role("inverseSurface", "#e4e5f0")
    readonly property color m3inverseOnSurface: role("inverseOnSurface", "#2f3036")
    readonly property color m3inversePrimary: role("inversePrimary", "#4f5b80")
    readonly property color m3shadow: role("shadow", "#000000")
    readonly property color m3onSurface: role("onSurface", "#e4e5f0")
    readonly property color m3onSurfaceVariant: role("onSurfaceVariant", "#a9aab5")
    readonly property color m3outline: role("outline", "#73757f")
    readonly property color m3outlineVariant: role("outlineVariant", "#454850")

    readonly property string sans: "Rubik"
    readonly property string iconFont: "Material Symbols Rounded"

    FileView {
        path: `${Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config"}/caelestia/shell.json`
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                const transparency = JSON.parse(text()).appearance?.transparency ?? {};
                root.transparent = transparency.enabled ?? false;
                root.base = transparency.base ?? 0.85;
                root.layers = transparency.layers ?? 0.4;
            } catch (error) {
                console.warn("Courier: could not read Caelestia's shell.json:", error);
            }
        }
    }

    FileView {
        path: `${Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state"}/caelestia/scheme.json`
        watchChanges: true
        onFileChanged: reload()
        onLoaded: {
            try {
                const data = JSON.parse(text());
                root.scheme = data.colours ?? data;
                root.mode = data.mode ?? "dark";
            } catch (error) {
                console.warn("Courier: could not read the Caelestia scheme:", error);
            }
        }
    }
}
