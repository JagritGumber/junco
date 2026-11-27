pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

// Junco's frosted-glass theme, paired with Hyprland's own compositor blur.
//
// The glass is neutral, the way real frosted glass (and CSS glassmorphism)
// works: the colour comes from what's behind it, not from a tint.
//
//   1. Hyprland blurs what's behind the window; Junco can't see those
//      pixels on Wayland, so the blur recipe (strength, saturation via
//      decoration.blur.vibrancy, contrast, noise) is Hyprland's and global.
//      Junco chooses where to blur (BackgroundEffect.blurRegion, shell.qml)
//      and paints only what sits on top.
//   2. Two levels of glass: the window is one translucent sheet, and the
//      sidebar plus main panes (list, reader, calendar, day panel) are
//      matching inset rounded panes separated by a uniform 6 px gutter.
//      - Light glass: clear white sheet (0.07) with smoked sidebar (black 0.30)
//        and raised milky cards (white 0.27; +0.09 behind dense lists).
//      - Dark glass: neutral smoked sheet (black 0.64) with raised translucent
//        cards (white 0.048 veil on top of the sheet) so wallpaper colour and
//        shapes still read richly through Hyprland's B3 blur without muddy
//        opaque slabs or colour tints.
//   3. Glass edges, not paint, and no outlines anywhere: a pane is defined
//      by its fill step, a soft light entering its top and left edge
//      (GlassEdge), a soft low static shadow (9-slice PNG) and a faint 4%
//      static grain (tiled PNG). No colour tints, no sheen gradients.
//   4. Dynamic 2-color complementary color-theory palette driven live by
//      Caelestia's wallpaper scheme.json (zero polling via FileView):
//      - Primary accent (actions & focus): extracted from scheme.json's
//        wallpaper primary hue, luminance-tuned for WCAG AA (>= 4.5:1) in
//        both Light and Dark glass. Used for Compose, Create event, Join,
//        Send, active tabs/filters, Today marker, unread count badge, and
//        soft selected-row wash.
//      - Complementary accent (live & passive status): true warm<->cool
//        complement (~160-175 deg hue rotation from the dynamic primary),
//        luminance-tuned for WCAG AA in both modes. Used for unread dots,
//        Synced dot, Live now badge, Expiring badges, Carry over tags, and
//        Skip starred / match status chips.
//      - Semantic red is reserved strictly for real errors and destructive
//        delete confirmations.
//   5. Junco's Hyprland rule (border_size 0, no_shadow, rounding 22, opacity
//      1.0 override) makes the sheet the window's shape.
//   6. No QML shaders, MultiEffect/GaussianBlur passes or idle animations.
//
// Environment overrides:
//   - COURIER_GLASS_MODE=dark|light  force dark or light glass polarity while
//                                    still deriving the dynamic 2-color hue
//                                    pair from Caelestia's live scheme.json.
//   - COURIER_THEME=solid            disable frosted glass and use opaque UI.
//
// Roles carry Caelestia's m3 prefix: QML treats a property named onX as a
// signal handler when X exists, so plain onSurface would read back as black.
Singleton {
    id: root

    property var scheme: ({})
    property string schemeMode: "dark"
    readonly property string envModeOverride: {
        const value = (Quickshell.env("COURIER_GLASS_MODE") || "").trim().toLowerCase();
        return value === "dark" || value === "light" ? value : "";
    }
    // In-process runtime override toggled from the Command Palette (never mutates Caelestia).
    property string runtimeModeOverride: ""
    readonly property string modeOverride: runtimeModeOverride !== "" ? runtimeModeOverride : envModeOverride
    readonly property string mode: modeOverride !== "" ? modeOverride : schemeMode
    readonly property bool dark: mode !== "light"
    readonly property bool schemeMatchesMode: modeOverride === "" || modeOverride === schemeMode

    function toggleGlassMode(): void {
        runtimeModeOverride = dark ? "light" : "dark";
    }

    // Frosted glass is on by default; COURIER_THEME=solid disables it.
    property bool glassPref: Quickshell.env("COURIER_THEME") !== "solid"
    readonly property bool glass: glassPref
    readonly property bool lightGlass: glass && !dark
    readonly property bool darkGlass: glass && dark

    function role(name: string, fallback: string): color {
        if (!schemeMatchesMode)
            return fallback;
        const value = scheme[name];
        return value ? `#${String(value).replace("#", "")}` : fallback;
    }

    // Reads a colour from Caelestia's scheme.json regardless of COURIER_GLASS_MODE
    // polarity override, so wallpaper hue always stays live-synced.
    function schemeColor(name: string): string {
        const value = scheme[name];
        if (!value)
            return "";
        const hex = String(value).trim().replace(/^#/, "");
        return /^[0-9a-fA-F]{6}$/.test(hex) ? `#${hex}` : "";
    }

    function alpha(base: color, opacity: real): color {
        return Qt.rgba(base.r, base.g, base.b, opacity);
    }

    // a + (b - a) * t, with an explicit alpha.
    function mix(a: color, b: color, t: real, opacity: real): color {
        return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, opacity);
    }

    // WCAG relative luminance for sRGB channels in [0, 1].
    function linChannel(c: real): real {
        return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }

    function srgbLum(c: color): real {
        return 0.2126 * linChannel(c.r) + 0.7152 * linChannel(c.g) + 0.0722 * linChannel(c.b);
    }

    function clamp01(v: real, lo: real, hi: real): real {
        return Math.max(lo, Math.min(hi, v));
    }

    // HSL (h in [0, 360), s & l in [0, 1]) -> Qt color.
    function hslColor(hDeg: real, s: real, l: real, a: real): color {
        const h = (((hDeg % 360) + 360) % 360) / 360.0;
        return Qt.hsla(h, clamp01(s, 0, 1), clamp01(l, 0, 1), a === undefined ? 1.0 : a);
    }

    // Binary-search HSL lightness so any wallpaper hue hits the exact target
    // WCAG relative luminance (guarantees consistent >= 4.5:1 contrast across
    // blues, greens, yellows, corals and violets alike).
    function tuneTone(hDeg: real, sat: real, targetLum: real, a: real): color {
        let lo = 0.08;
        let hi = 0.98;
        for (let i = 0; i < 12; i++) {
            const mid = (lo + hi) * 0.5;
            if (srgbLum(hslColor(hDeg, sat, mid, 1.0)) < targetLum)
                lo = mid;
            else
                hi = mid;
        }
        return hslColor(hDeg, sat, (lo + hi) * 0.5, a === undefined ? 1.0 : a);
    }

    // High-contrast ink on any filled accent surface (>= 7:1 across all hues).
    function pickInk(bg: color): color {
        return srgbLum(bg) > 0.34 ? "#14182e" : "#ffffff";
    }

    // Legacy Caelestia transparency fields (kept for solid-mode fallback).
    property bool transparent: false
    property real base: 0.85
    property real layers: 0.40

    // Dynamic 2-color complementary engine (from live Caelestia scheme.json) -----
    readonly property color seedColor: Qt.color(
        schemeColor("primaryPaletteKeyColor")
        || schemeColor("primary_paletteKeyColor")
        || schemeColor("primary")
        || "#6676a5"
    )
    readonly property bool seedIsGray: seedColor.hslSaturation < 0.08
    readonly property real primaryHue: seedIsGray ? 224.0 : (((seedColor.hslHue * 360.0) % 360.0) + 360.0) % 360.0
    readonly property real primarySat: seedIsGray ? 0.58 : clamp01(Math.max(seedColor.hslSaturation * 1.45, 0.62), 0.58, 0.78)
    // True warm<->cool complement: cool blues/periwinkles (210..255 deg) rotate
    // 160 deg to warm coral-peach; other hues rotate 175 deg across the wheel
    // (e.g. green/teal <-> warm rose-coral, amber/sunset <-> ocean sky blue).
    readonly property real complementHue: (primaryHue >= 210 && primaryHue <= 255)
        ? (primaryHue + 160.0) % 360.0
        : (primaryHue + 175.0) % 360.0
    readonly property real complementSat: clamp01(Math.max(primarySat, 0.64), 0.60, 0.80)

    // Primary accent (Actions & Focus): vivid mid-tone base + deep badge fill.
    readonly property color accent: tuneTone(primaryHue, primarySat, 0.34, 1.0)
    // Badges, today circle and calendar now-line: deep enough for >= 5:1 crisp
    // white ink across every wallpaper hue.
    readonly property color accentFill: glass ? tuneTone(primaryHue, Math.min(0.84, primarySat + 0.08), 0.155, 1.0) : m3primary
    readonly property color accentFillInk: glass ? "#ffffff" : m3onPrimary

    // Complementary accent (Live & Passive Status Signals): unread dots, Synced
    // dot, Live now badge, Expiring badges, Carry over, Skip starred / matches.
    readonly property color complement: tuneTone(complementHue, complementSat, dark ? 0.46 : 0.34, 1.0)
    readonly property color complementDot: glass
        ? (dark ? tuneTone(complementHue, 0.78, 0.54, 1.0) : tuneTone(complementHue, 0.80, 0.28, 1.0))
        : m3tertiary
    readonly property color complementSheetDot: glass && !frostedSheet
        ? tuneTone(complementHue, 0.78, 0.56, 1.0)
        : complementDot

    // Material 3 accent & semantic roles (luminance-tuned for >= 4.5:1 on glass).
    readonly property color m3primary: lightGlass
        ? tuneTone(primaryHue, Math.min(0.82, primarySat + 0.06), 0.024, 1.0)
        : darkGlass ? tuneTone(primaryHue, primarySat, 0.82, 1.0)
        : role("primary", dark ? "#b0c0f4" : "#4e5e8b")
    readonly property color m3onPrimary: glass ? pickInk(m3primary) : role("onPrimary", dark ? "#142650" : "#f9f8ff")
    readonly property color m3primaryContainer: lightGlass
        ? mix(Qt.rgba(1, 1, 1, 1), accent, 0.34, 0.92)
        : darkGlass ? alpha(accent, 0.24)
        : role("primaryContainer", dark ? "#344470" : "#b0c0f4")
    readonly property color m3onPrimaryContainer: lightGlass
        ? inkNavy
        : darkGlass ? tuneTone(primaryHue, 0.50, 0.90, 1.0)
        : role("onPrimaryContainer", dark ? "#e0e7ff" : "#2a3b66")

    readonly property color m3secondaryContainer: glass ? alpha(m3primary, dark ? 0.20 : 0.18) : role("secondaryContainer", "#2c3350")
    readonly property color m3onSecondaryContainer: glass ? m3onSurface : role("onSecondaryContainer", "#f8faff")

    readonly property color m3tertiary: lightGlass
        ? tuneTone(complementHue, Math.min(0.84, complementSat + 0.06), 0.024, 1.0)
        : darkGlass ? tuneTone(complementHue, complementSat, 0.82, 1.0)
        : role("tertiary", dark ? "#f5b097" : "#8c4a35")
    readonly property color m3tertiaryContainer: lightGlass
        ? mix(Qt.rgba(1, 1, 1, 1), complement, 0.32, 0.90)
        : darkGlass ? alpha(complement, 0.24)
        : role("tertiaryContainer", dark ? "#5c3326" : "#ffdbcf")
    readonly property color m3onTertiaryContainer: lightGlass
        ? inkNavy
        : darkGlass ? tuneTone(complementHue, 0.50, 0.90, 1.0)
        : role("onTertiaryContainer", dark ? "#ffede7" : "#3a1b12")

    // Semantic error stays red strictly for real errors / destructive actions;
    // passive success/live status harmonizes into the dynamic complement.
    readonly property color m3error: darkGlass ? "#ff94a8" : role("error", dark ? "#ff8da1" : "#a83836")
    readonly property color m3success: glass ? m3tertiary : role("success", dark ? "#8be0b8" : "#2e7d5b")
    readonly property color m3errorContainer: glass ? (dark ? Qt.rgba(255 / 255, 110 / 255, 138 / 255, 0.24) : alpha(role("errorContainer", "#ffdad6"), 0.85)) : role("errorContainer", "#5c1b29")
    readonly property color m3onErrorContainer: glass ? (dark ? "#ffe8ed" : role("onErrorContainer", "#5c1b1a")) : role("onErrorContainer", "#ffe5ea")

    // Solid base colours (used for COURIER_THEME=solid and HTML contrast mapping).
    readonly property color solidSurface: role("surface", dark ? "#121318" : "#f7f9fd")
    readonly property color solidSurfaceLow: role("surfaceContainerLow", dark ? "#171920" : "#f0f4f8")
    readonly property color solidSurfaceContainer: role("surfaceContainer", dark ? "#1d2028" : "#e9eef4")
    readonly property color solidSurfaceHigh: role("surfaceContainerHigh", dark ? "#252934" : "#e3e9ef")
    readonly property color solidSurfaceHighest: role("surfaceContainerHighest", dark ? "#2e3340" : "#dde3ea")

    readonly property color m3surface: glass ? "transparent" : solidSurface
    readonly property color m3surfaceContainerLow: glass ? glassCardPane : solidSurfaceLow
    readonly property color m3surfaceContainer: glass ? glassCard : solidSurfaceContainer
    readonly property color m3surfaceContainerHigh: glass ? glassControl : solidSurfaceHigh
    readonly property color m3surfaceContainerHighest: glass ? Qt.rgba(1, 1, 1, dark ? 0.14 : 0.62) : solidSurfaceHighest

    // Floating menus & dialogs: dense neutral frost so overlapping content stays crisp.
    readonly property color m3popup: glass ? (dark ? Qt.rgba(16 / 255, 17 / 255, 22 / 255, 0.92) : mix(Qt.rgba(1, 1, 1, 1), islandTint, 0.35, 0.96)) : solidSurfaceHigh
    readonly property color m3popupHigh: glass ? (dark ? Qt.rgba(20 / 255, 22 / 255, 28 / 255, 0.94) : mix(Qt.rgba(1, 1, 1, 1), islandTint, 0.25, 0.98)) : solidSurfaceHighest

    // Snackbar / inverse surfaces.
    readonly property color m3inverseSurface: role("inverseSurface", dark ? "#f2f5fc" : "#2d3135")
    readonly property color m3inverseOnSurface: role("inverseOnSurface", dark ? "#15192a" : "#eef1f6")
    readonly property color m3inversePrimary: role("inversePrimary", dark ? "#4e5e8b" : "#b0c0f4")
    readonly property color m3shadow: role("shadow", "#05070e")

    // Ink. On light milky cards: deep navy. On dark smoked glass: crisp off-white
    // (kept bright so worst-5% patches over bright wallpaper stay >= 4.5:1).
    readonly property color inkNavy: "#1a1b4a"
    readonly property color inkNavyVariant: "#1f2150"
    readonly property color m3onSurface: glass ? (dark ? "#fafbff" : inkNavy) : role("onSurface", dark ? "#f2f4fb" : "#2c3338")
    readonly property color m3onSurfaceVariant: glass ? (dark ? "#dfe4f2" : inkNavyVariant) : role("onSurfaceVariant", dark ? "#aab3cc" : "#586066")
    readonly property color m3outline: role("outline", dark ? "#7d88a8" : "#747c82")
    readonly property color m3outlineVariant: glass ? (dark ? Qt.rgba(1, 1, 1, 0.18) : alpha(m3onSurface, 0.16)) : role("outlineVariant", dark ? "#3b435e" : "#abb3b9")

    // Frosted-glass material ------------------------------------------------------
    readonly property color pureWhite: "#ffffff"
    readonly property color windowBg: glass ? "transparent" : solidSurface
    // Dense frost base for popups and menus.
    readonly property color islandTint: dark ? Qt.rgba(16 / 255, 17 / 255, 22 / 255, 1) : Qt.rgba(248 / 255, 248 / 255, 252 / 255, 1)

    // Level 1, the sheet: the whole window, neutral translucent glass.
    readonly property real sheetAlpha: 0.07
    readonly property real cardAlpha: 0.27
    readonly property bool frostedSheet: lightGlass && sheetAlpha >= 0.2
    readonly property color glassSheet: glass ? (dark ? Qt.rgba(6 / 255, 7 / 255, 10 / 255, 0.64) : Qt.rgba(1, 1, 1, sheetAlpha)) : solidSurface

    // Level 2, raised glass cards (list, reader, calendar main, day panel).
    readonly property color glassCardPane: glass ? (dark ? Qt.rgba(1, 1, 1, 0.048) : Qt.rgba(1, 1, 1, cardAlpha)) : solidSurfaceLow
    readonly property color glassIsland: glassCardPane

    // The sidebar: neutral smoked glass pane on the sheet, inset with matching
    // 16 px corners and 6 px clear-glass gutter.
    readonly property color glassSidebar: glass ? (dark ? Qt.rgba(0, 0, 0, 0.08) : frostedSheet ? "transparent" : Qt.rgba(0, 0, 0, 0.30)) : solidSurfaceLow

    // Dense text panes (thread list, calendar grid, day panel): extra frost lift
    // on light glass; neutral translucent glass on dark glass.
    readonly property real listLift: 0.09
    readonly property color glassList: glass ? (dark ? Qt.rgba(1, 1, 1, 0.042) : Qt.rgba(1, 1, 1, cardAlpha + listLift)) : solidSurfaceLow
    readonly property color glassPanel: glassCardPane

    // Glass edges (GlassEdge): no outline. Soft white light enters along the
    // top (and weaker, the left) and fades over glassEdgeFade px into the glass.
    readonly property color glassEdgeLight: glass ? Qt.rgba(1, 1, 1, dark ? 0.14 : 0.22) : "transparent"
    readonly property color glassEdgeSideLight: glass ? Qt.rgba(1, 1, 1, dark ? 0.085 : 0.15) : "transparent"
    readonly property real glassEdgeFade: 12
    // The frost: static 4% grain tile over the glass (assets/glass/grain.png).
    readonly property real grainOpacity: glass ? 0.04 : 0

    // Nested cards, bubbles and controls inside a raised glass card: pure
    // neutral white steps, never tinted slabs and never outlined.
    readonly property color glassCard: glass ? (dark ? Qt.rgba(1, 1, 1, 0.055) : Qt.rgba(1, 1, 1, 0.28)) : solidSurfaceContainer
    readonly property color glassCardHover: glass ? (dark ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(1, 1, 1, 0.40)) : solidSurfaceHigh
    readonly property color glassControl: glass ? (dark ? Qt.rgba(1, 1, 1, 0.075) : Qt.rgba(1, 1, 1, 0.30)) : solidSurfaceHigh
    readonly property color glassControlHover: glass ? (dark ? Qt.rgba(1, 1, 1, 0.13) : Qt.rgba(1, 1, 1, 0.45)) : alpha(m3onSurface, 0.08)
    readonly property color glassHover: glass ? (dark ? Qt.rgba(1, 1, 1, 0.065) : Qt.rgba(1, 1, 1, 0.16)) : alpha(m3onSurface, 0.06)

    // On the smoked sidebar: light ink and clean pill highlights (no left bar).
    readonly property color sheetInk: frostedSheet ? inkNavy : glass ? "#f7f8fc" : m3onSurface
    readonly property color sheetInkVariant: frostedSheet ? inkNavyVariant : glass ? "#d8dced" : m3onSurfaceVariant
    readonly property color sheetAccentInk: frostedSheet ? m3primary : glass ? tuneTone(primaryHue, 0.56, 0.78, 1.0) : role("onSecondaryContainer", dark ? "#f8faff" : "#0b1d28")
    readonly property color sheetActive: glass ? Qt.rgba(1, 1, 1, dark ? 0.14 : frostedSheet ? 0.38 : 0.22) : role("secondaryContainer", dark ? "#2c3350" : "#d1e5f3")
    readonly property color sheetHover: glass ? Qt.rgba(1, 1, 1, dark ? 0.08 : 0.11) : glassHover
    readonly property color sheetControl: glass ? Qt.rgba(1, 1, 1, dark ? 0.10 : 0.14) : glassControl
    readonly property color sheetControlHover: glass ? Qt.rgba(1, 1, 1, dark ? 0.18 : 0.24) : glassControlHover
    readonly property color sheetDivider: glass ? Qt.rgba(1, 1, 1, dark ? 0.14 : 0.22) : glassBorderSubtle
    readonly property color sheetRim: "transparent"
    // Status colours that read cleanly on the smoked sidebar.
    readonly property color sheetError: glass && !frostedSheet ? "#ff9eb0" : m3error
    readonly property color sheetSuccess: glass && !frostedSheet ? complementSheetDot : m3success

    // Primary accent pill (Compose, Create event, Join, Send, active chip/tab):
    // dynamic wallpaper primary tuned to a luminous pastel with high-contrast dark ink.
    readonly property color pill: glass ? alpha(tuneTone(primaryHue, primarySat, dark ? 0.54 : 0.56, 1.0), dark ? 0.92 : 0.94) : m3primary
    readonly property color pillInk: glass ? pickInk(pill) : m3onPrimary
    // Selected row in Mail's thread list: soft inset dynamic primary pill wash
    // with zero outlines and no vertical left stripe.
    readonly property color glassSelectedRow: glass
        ? (dark ? alpha(accent, 0.22) : alpha(mix(Qt.rgba(1, 1, 1, 1), accent, 0.32, 1), 0.74))
        : m3secondaryContainer
    // Active non-row surface (Calendar picked day, toggle button): neutral glass.
    readonly property color glassActive: glass ? (dark ? Qt.rgba(1, 1, 1, 0.13) : Qt.rgba(1, 1, 1, 0.44)) : m3secondaryContainer
    readonly property color glassActiveBorder: "transparent"
    readonly property color selectedMarker: glass ? accent : "transparent"

    // Outlines: none on glass. Cards, rows, chips, buttons and fields are
    // filled shapes; border tokens stay for solid mode only.
    readonly property color glassBorder: glass ? "transparent" : alpha(m3outlineVariant, 0.5)
    readonly property color glassBorderSubtle: glass ? "transparent" : alpha(m3outlineVariant, 0.4)
    readonly property color glassDivider: glass ? (dark ? Qt.rgba(1, 1, 1, 0.09) : alpha(m3onSurface, 0.08)) : alpha(m3outlineVariant, 0.45)
    // Calendar grid lines: a hairline at very low alpha, never a bright stroke.
    readonly property color glassGrid: glass ? (dark ? Qt.rgba(1, 1, 1, 0.07) : alpha(m3onSurface, 0.07)) : alpha(m3outlineVariant, 0.45)
    readonly property color glassPopupBorder: glass ? (dark ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(1, 1, 1, 0.85)) : alpha(m3outlineVariant, 0.6)

    // Chat bubbles: neutral glass steps (no tinted slabs, no outlines).
    readonly property color glassBubbleMine: glass ? (dark ? Qt.rgba(1, 1, 1, 0.085) : Qt.rgba(1, 1, 1, 0.34)) : m3primaryContainer
    readonly property color glassBubbleMineBorder: "transparent"
    readonly property color glassBubbleMineInk: glass ? m3onSurface : m3onPrimaryContainer
    readonly property color glassBubbleOther: glass ? (dark ? Qt.rgba(1, 1, 1, 0.055) : Qt.rgba(1, 1, 1, 0.30)) : solidSurfaceHigh
    readonly property color glassBubbleOtherBorder: "transparent"

    // Calendar events on glass: filled, never outlined. On light glass the
    // calendar's colour becomes a pastel wash with navy ink; on dark glass a
    // rich smoked tint with crisp off-white ink (keeping the calendar colour
    // subtle on the event block).
    function eventFill(tone: color, hovered: bool): color {
        if (lightGlass)
            return mix(pureWhite, tone, 0.28, hovered ? 0.94 : 0.84);
        return Qt.rgba(tone.r * 0.32 + 0.02, tone.g * 0.32 + 0.02, tone.b * 0.32 + 0.03, hovered ? 0.56 : 0.44);
    }
    readonly property color eventInk: lightGlass ? inkNavy : m3onSurface

    // Subtle hover pill colour for invisible SplitHandle resize targets.
    readonly property color splitHandleHover: dark ? Qt.rgba(1, 1, 1, 0.32) : alpha(inkNavy, 0.24)
    readonly property color splitHandleDrag: alpha(accent, dark ? 0.80 : 0.72)

    // Whether Hyprland blurs behind the whole sheet (true) or only behind cards.
    readonly property bool sheetBlur: true

    // Layout: the window is the sheet (22 px corners, like Hyprland's rule);
    // panes sit 6 px in from its edges and 6 px apart, with 16 px corners
    // (concentric with the sheet). Screen space first on a 15" 1920x1080.
    readonly property int windowMargin: 0
    readonly property int cardInset: glass ? 6 : 0
    readonly property int paneGap: glass ? 6 : 0
    readonly property int paneRadius: glass ? 22 : 10
    readonly property int cardPaneRadius: glass ? 16 : 0
    readonly property int cardRadius: 11
    readonly property int controlRadius: 10
    readonly property int chipRadius: 9

    // Typography: Rubik[wght].ttf has OS/2 usWeightClass=300 and a 300..900
    // wght variable axis. In Qt 6's FreeType matcher, setting font.weight > 400
    // marks bold=true and over-thickens / synthetically double-bolds glyphs.
    // Driving wght via font.variableAxes at font.weight: Font.Normal produces a
    // clean, refined hierarchy without faux-bold bloat.
    readonly property string sans: "Rubik"
    readonly property string iconFont: "Material Symbols Rounded"
    readonly property int weightRegular: 400
    readonly property int weightMedium: 470
    readonly property int weightHeading: 525

    property string _lastShellJson: ""
    property string _lastSchemeJson: ""

    FileView {
        path: `${Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config"}/caelestia/shell.json`
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            const raw = text();
            if (raw === root._lastShellJson)
                return;
            root._lastShellJson = raw;
            try {
                const appearance = JSON.parse(raw).appearance ?? {};
                const transparency = appearance.transparency ?? {};
                if (appearance.juncoGlass !== undefined && Quickshell.env("COURIER_THEME") === "")
                    root.glassPref = Boolean(appearance.juncoGlass);
                root.transparent = transparency.enabled ?? false;
                if (transparency.base !== undefined)
                    root.base = transparency.base;
                if (transparency.layers !== undefined)
                    root.layers = transparency.layers;
            } catch (error) {
                console.warn("Courier: could not read Caelestia's shell.json:", error);
            }
        }
    }

    FileView {
        path: `${Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state"}/caelestia/scheme.json`
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            const raw = text();
            if (raw === root._lastSchemeJson)
                return;
            root._lastSchemeJson = raw;
            try {
                const data = JSON.parse(raw);
                root.scheme = data.colours ?? data;
                root.schemeMode = data.mode ?? "dark";
            } catch (error) {
                console.warn("Courier: could not read the Caelestia scheme:", error);
            }
        }
    }
}
