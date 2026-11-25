"""Courier's colours for simple HTML mail ("Dark"): the email's own colours
mapped onto the app's theme, so a GitHub notice reads like the rest of the
app instead of on white paper.

The theme comes from the app (the reader's surface, its text, muted text and
link colours). Every colour the sanitised HTML still carries is mapped in
OKLCH (perceptual lightness L, chroma C, hue h):

- backgrounds: near-grey ones become the theme's surface, a shade lighter
  the further they were from the email's paper (so a grey box stays a box);
  coloured ones keep their hue, darkened until the theme's text reads on
  them at 4.5:1;
- text: near-grey colours flip their lightness (dark grey on white becomes
  light grey on dark); coloured ones keep their hue and get just enough
  lightness for 4.5:1 against the surface;
- borders: like backgrounds, kept visible;
- links: the theme's link colour.

On a light theme the same rules keep colours as they are, nudged only where
contrast is short.
"""

from __future__ import annotations

import html
import math
import re

# Below this chroma a colour counts as grey (white, black, the greys of text
# and dividers); above it, as a colour with a hue worth keeping.
GREY = 0.035
TEXT_CONTRAST = 4.5

NAMES = {
    "black": "#000000", "white": "#ffffff", "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0",
    "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3", "darkgray": "#a9a9a9", "darkgrey": "#a9a9a9",
    "dimgray": "#696969", "dimgrey": "#696969", "gainsboro": "#dcdcdc", "whitesmoke": "#f5f5f5",
    "red": "#ff0000", "darkred": "#8b0000", "maroon": "#800000", "green": "#008000", "darkgreen": "#006400",
    "lime": "#00ff00", "blue": "#0000ff", "navy": "#000080", "darkblue": "#00008b", "royalblue": "#4169e1",
    "steelblue": "#4682b4", "teal": "#008080", "aqua": "#00ffff", "cyan": "#00ffff", "purple": "#800080",
    "orange": "#ffa500", "darkorange": "#ff8c00", "yellow": "#ffff00", "gold": "#ffd700", "brown": "#a52a2a",
    "pink": "#ffc0cb", "olive": "#808000", "crimson": "#dc143c", "tomato": "#ff6347", "coral": "#ff7f50",
    "slategray": "#708090", "slategrey": "#708090", "darkslategray": "#2f4f4f", "darkslategrey": "#2f4f4f",
    "aliceblue": "#f0f8ff", "ghostwhite": "#f8f8ff", "ivory": "#fffff0", "beige": "#f5f5dc", "linen": "#faf0e6",
    "snow": "#fffafa", "seashell": "#fff5ee", "lavender": "#e6e6fa", "honeydew": "#f0fff0", "mintcream": "#f5fffa",
}

COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b[a-zA-Z]+\b")


# Colour maths -----------------------------------------------------------------


def parse(value: str) -> tuple[float, float, float, float] | None:
    """(r, g, b, alpha) in 0..1 from #rgb, #rrggbb(aa), rgb(a)() or a name."""
    value = value.strip().lower()
    value = NAMES.get(value, value)
    match = re.fullmatch(r"#([0-9a-f]{3,8})", value)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        if len(digits) not in (6, 8):
            return None
        parts = [int(digits[i : i + 2], 16) / 255 for i in range(0, len(digits), 2)]
        return (parts[0], parts[1], parts[2], parts[3] if len(parts) == 4 else 1.0)
    number = r"((?:\d+(?:\.\d+)?|\.\d+)%?)"
    match = re.fullmatch(rf"rgba?\(\s*{number}\s*[, ]\s*{number}\s*[, ]\s*{number}\s*(?:[,/]\s*{number}\s*)?\)", value)
    if match:
        def channel(text: str) -> float:
            return float(text[:-1]) / 100 if text.endswith("%") else float(text) / 255

        alpha = match.group(4)
        a = 1.0 if alpha is None else (float(alpha[:-1]) / 100 if alpha.endswith("%") else float(alpha))
        return (min(1, channel(match.group(1))), min(1, channel(match.group(2))), min(1, channel(match.group(3))), min(1.0, a))
    return None


def hex_of(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * max(c, 0.0) ** (1 / 2.4) - 0.055


def oklch(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in rgb[:3])
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    big_l = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return big_l, math.hypot(a, bb), math.atan2(bb, a)


def _rgb_from(big_l: float, chroma: float, hue: float) -> tuple[float, float, float]:
    a, b = chroma * math.cos(hue), chroma * math.sin(hue)
    l = (big_l + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (big_l - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (big_l - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (_gamma(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            _gamma(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            _gamma(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s))


def from_oklch(big_l: float, chroma: float, hue: float) -> tuple[float, float, float]:
    """sRGB for an OKLCH colour, its chroma lowered until it fits sRGB."""
    big_l = max(0.0, min(1.0, big_l))
    low, high = 0.0, chroma
    rgb = _rgb_from(big_l, chroma, hue)
    if all(-1e-4 <= c <= 1 + 1e-4 for c in rgb):
        return tuple(max(0.0, min(1.0, c)) for c in rgb)
    for _ in range(24):
        middle = (low + high) / 2
        rgb = _rgb_from(big_l, middle, hue)
        if all(-1e-4 <= c <= 1 + 1e-4 for c in rgb):
            low = middle
        else:
            high = middle
    return tuple(max(0.0, min(1.0, c)) for c in _rgb_from(big_l, low, hue))


def luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_linear(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(one: tuple[float, float, float], two: tuple[float, float, float]) -> float:
    a, b = sorted((luminance(one), luminance(two)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def with_contrast(hue: float, chroma: float, start: float, against: tuple[float, float, float], ratio: float,
                  upward: bool) -> tuple[float, float, float]:
    """The colour of this hue and chroma nearest lightness `start` (moving
    up or down) that reads at `ratio` against `against`."""
    ratio += 0.03  # A margin, so rounding to #rrggbb never lands just short.
    rgb = from_oklch(start, chroma, hue)
    if contrast(rgb, against) >= ratio:
        return rgb
    low, high = (start, 1.0) if upward else (0.0, start)
    for _ in range(24):
        middle = (low + high) / 2
        if (contrast(from_oklch(middle, chroma, hue), against) >= ratio) == upward:
            high = middle
        else:
            low = middle
    return from_oklch(high if upward else low, chroma, hue)


# The theme -----------------------------------------------------------------------


class Theme:
    """The app's colours the email is mapped onto."""

    def __init__(self, surface: str, text: str, muted: str = "", link: str = "") -> None:
        self.surface = (parse(surface) or (0.07, 0.07, 0.09, 1))[:3]
        self.text = (parse(text) or (0.89, 0.9, 0.94, 1))[:3]
        self.muted = (parse(muted) or self.text + (1,))[:3]
        self.link = (parse(link) or (0.73, 0.78, 0.93, 1))[:3]
        self.dark = luminance(self.surface) < luminance(self.text)
        self.surface_l, self.surface_c, self.surface_h = oklch(self.surface)
        self.text_l = oklch(self.text)[0]
        # The faintest grey text still reads at 4.5:1.
        self.faint_l = oklch(with_contrast(self.surface_h, 0.0, self.surface_l, self.surface, TEXT_CONTRAST, upward=self.dark))[0]

    @classmethod
    def from_json(cls, data: dict) -> "Theme":
        return cls(str(data.get("surface", "")), str(data.get("text", "")), str(data.get("muted", "")), str(data.get("link", "")))

    def background(self, value: str, paper: tuple[float, float, float] = (1, 1, 1)) -> str | None:
        rgb = parse(value)
        if rgb is None or rgb[3] < 0.05:
            return None
        big_l, chroma, hue = oklch(rgb[:3])
        paper_l = oklch(paper)[0]
        if chroma < GREY:
            # Greys take the surface's own tint.
            chroma, hue = self.surface_c, self.surface_h
            if not self.dark:
                # Light theme: white paper becomes the surface, greys keep their step.
                return hex_of(from_oklch(self.surface_l - max(0.0, paper_l - big_l), chroma, hue))
            if big_l >= 0.5:
                # A shade off the paper: the same step up from the surface.
                return hex_of(from_oklch(self.surface_l + min(0.16, max(0.0, paper_l - big_l) * 0.7), chroma, hue))
            # A dark band on light paper (a footer, a header) stays darkish.
            return hex_of(from_oklch(max(self.surface_l + 0.04, min(big_l, self.surface_l + 0.14)), chroma, hue))
        if not self.dark:
            return hex_of(rgb[:3])
        # A coloured block keeps its hue, deep enough for the theme's text.
        return hex_of(with_contrast(hue, chroma * 0.85, min(big_l, 0.5), self.text, TEXT_CONTRAST, upward=False))

    def foreground(self, value: str) -> str | None:
        rgb = parse(value)
        if rgb is None or rgb[3] < 0.05:
            return None
        big_l, chroma, hue = oklch(rgb[:3])
        if chroma < GREY:
            if self.dark:
                # Near-black body text, and white text (on a coloured block,
                # which stays dark): the theme's text.
                if big_l < 0.32 or big_l > 0.88:
                    return hex_of(self.text)
                # Greys flip, keeping their emphasis: the darker on white,
                # the nearer the theme's text; the lightest, the faintest
                # grey that still reads.
                share = (big_l - 0.32) / (0.88 - 0.32)
                big_l = self.text_l - share * (self.text_l - self.faint_l)
                return hex_of(with_contrast(self.surface_h, min(chroma, self.surface_c), big_l, self.surface, TEXT_CONTRAST, upward=True))
            return hex_of(with_contrast(hue, chroma, big_l, self.surface, TEXT_CONTRAST, upward=False))
        return hex_of(with_contrast(hue, chroma, big_l, self.surface, TEXT_CONTRAST, upward=self.dark))

    def border(self, value: str, paper: tuple[float, float, float] = (1, 1, 1)) -> str | None:
        mapped = self.background(value, paper)
        if mapped is None:
            return None
        rgb = parse(mapped)[:3]
        if contrast(rgb, self.surface) < 1.4:
            big_l, chroma, hue = oklch(rgb)
            rgb = with_contrast(hue, chroma, big_l, self.surface, 1.4, upward=self.dark)
        return hex_of(rgb)


# The email ----------------------------------------------------------------------

TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
ATTRIBUTE = re.compile(r"""(\s)([a-zA-Z-]+)="([^"]*)\"""")


def _declarations(style: str, theme: Theme, paper, in_link: bool) -> str:
    out = []
    for declaration in style.split(";"):
        name, colon, value = declaration.partition(":")
        if not colon:
            if declaration.strip():
                out.append(declaration)
            continue
        key = name.strip().lower()
        if key == "color":
            mapped = hex_of(theme.link) if in_link else theme.foreground(value.replace("!important", "").strip())
            value = f" {mapped}" if mapped else value
        elif key in {"background", "background-color"}:
            value = COLOUR.sub(lambda m: theme.background(m.group(0), paper) or m.group(0), value)
        elif key.startswith("border") and ("color" in key or key in {"border", "border-top", "border-right", "border-bottom", "border-left"}):
            value = COLOUR.sub(lambda m: theme.border(m.group(0), paper) or m.group(0) if parse(m.group(0)) else m.group(0), value)
        out.append(f"{name}:{value}")
    return ";".join(out)


def themed(markup: str, theme: Theme, paper: str = "") -> str:
    """The sanitised HTML (courier_html.designed) in the theme's colours."""
    page = (parse(paper) or (1, 1, 1, 1))[:3]
    depth = 0

    def tag(match: re.Match) -> str:
        nonlocal depth
        closing, name, rest = match.group(1), match.group(2).lower(), match.group(3)
        if name == "a":
            depth = max(0, depth + (-1 if closing else 1))
        if closing or not rest.strip():
            return match.group(0)
        in_link = depth > 0

        def attribute(found: re.Match) -> str:
            space, key, value = found.group(1), found.group(2).lower(), html.unescape(found.group(3))
            if key == "style":
                value = _declarations(value, theme, page, in_link)
            elif key == "bgcolor":
                value = theme.background(value, page) or value
            elif key == "color":
                value = hex_of(theme.link) if in_link else (theme.foreground(value) or value)
            else:
                return found.group(0)
            return f'{space}{found.group(2)}="{html.escape(value, quote=True)}"'

        return f"<{name}{ATTRIBUTE.sub(attribute, rest)}>"

    def style_block(match: re.Match) -> str:
        css = match.group(1)

        def rule(found: re.Match) -> str:
            selectors, body = found.group(1), found.group(2)
            in_link = bool(re.search(r"(^|[\s,>+~])a(\b|:|\.|$)", selectors.strip(), re.I))
            return f"{selectors}{{{_declarations(body, theme, page, in_link)}}}"

        css = re.sub(r"([^{}]+)\{([^{}]*)\}", rule, css)
        return f"<style>{css}\na{{color:{hex_of(theme.link)}}}</style>"

    head, separator, body = markup.partition("<body>")
    if separator:
        if "<style>" in head:
            head = re.sub(r"<style>(.*?)</style>", style_block, head, flags=re.S)
        else:
            head = head.replace("<head>", f"<head><style>a{{color:{hex_of(theme.link)}}}</style>", 1)
        return head + separator + TAG.sub(tag, body)
    return TAG.sub(tag, markup)
