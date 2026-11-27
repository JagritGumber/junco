"""Designed (HTML) email, made safe for Qt's own rich-text engine.

The reader draws HTML with Qt's rich text (the engine behind QML Text and
TextEdit): HTML 4 tables, inline CSS, <style> rules and images, and no
scripting of any kind. This keeps only what that engine draws: known tags
and attributes, web and mailto links, and images, and drops what mail apps
hide (preview text, tracking pixels) and anything active (scripts, forms,
frames, other stylesheets).

Every image becomes a local file with its exact size, so Qt lays the email
out once, correctly, and never fetches anything itself: images sent inside
the email are written to a private folder, and web images are downloaded
here (no cookies, size-capped, cached for a month).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import html
import html.parser
import ipaddress
import os
import re
import socket
import stat
import tempfile
import threading
import time
import urllib.parse
import warnings
from pathlib import Path

# Qt's rich-text subset (https://doc.qt.io/qt-6/richtext-html-subset.html).
KEPT = {
    "a", "address", "b", "big", "blockquote", "br", "center", "cite", "code", "dd", "del", "dfn", "div", "dl",
    "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "kbd", "li", "nobr", "ol", "p",
    "pre", "s", "samp", "small", "span", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "tt", "u", "ul", "var",
}
# Newer or rarer tags drawn as their nearest kept one.
RENAMED = {
    "section": "div", "article": "div", "header": "div", "footer": "div", "main": "div", "nav": "div",
    "aside": "div", "figure": "div", "figcaption": "div", "caption": "div", "summary": "div", "details": "div",
    "strike": "s", "ins": "u", "mark": "span", "abbr": "span", "time": "span", "label": "span", "button": "span",
    "picture": "span", "o:p": "span",
}
# Dropped with everything inside them.
DROPPED = {"script", "noscript", "title", "iframe", "frame", "frameset", "object", "embed", "applet", "svg", "math",
           "video", "audio", "canvas", "template", "select", "textarea", "map", "head", "style"}
VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "wbr", "source", "param", "track", "embed"}
ATTRIBUTES = {
    "*": {"style", "class", "align", "valign", "dir", "bgcolor", "width", "height", "title"},
    "a": {"href"},
    "font": {"color", "face", "size"},
    "table": {"border", "cellspacing", "cellpadding"},
    "td": {"colspan", "rowspan", "nowrap"},
    "th": {"colspan", "rowspan", "nowrap"},
    "ol": {"type", "start"},
    "ul": {"type"},
}
HIDDEN_STYLE = re.compile(
    r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all|max-height\s*:\s*0(?:px)?\s*(?:!important)?\s*(?:;|$)"
    r"|opacity\s*:\s*0(?:\.0+)?\s*(?:!important)?\s*(?:;|$))",
    re.I,
)
# Qt can't size or place background images (no background-size), so they
# would tile under the text; the background colour stays.
URLS = re.compile(r"url\([^)]*\)", re.I)
IMAGE_LIMIT = 8 * 1024 * 1024
# Qt decodes every image the reader draws, whole, at 4 bytes a pixel, so a
# few KB of PNG claiming 50,000 × 50,000 would take gigabytes. An image is
# drawn only up to IMAGE_PIXELS (a 50-megapixel phone photo is 8160 × 6120),
# and one email's images only up to EMAIL_PIXELS in all; past either, an
# image shows its description, like one that didn't load.
IMAGE_PIXELS = 50_000_000
EMAIL_PIXELS = 100_000_000
# What Pillow reads from mail (and from the picture chooser), and so all
# Qt is ever handed: the web's picture types. Not icons: Pillow sizes an
# .ico by its biggest frame, Qt draws its first, so the size checked
# wouldn't be the one decoded.
PICTURE_FORMATS = ("PNG", "JPEG", "GIF", "WEBP", "BMP")
# Web images per email, how long each may take, how long an email waits for
# them all, and how long they're kept.
IMAGE_COUNT = 60
IMAGE_TIMEOUT = 4
# Web images come only from the public internet, on the usual ports, after
# at most a few redirects (every hop checked again).
IMAGE_PORTS = {80, 443}
IMAGE_REDIRECTS = 3
IMAGE_WAIT = 2.5
CACHE_DAYS = 30
# An image without a width shows at its own width, up to the usual email width.
NATURAL_WIDTH = 600
WIDEST = 800
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
# Open-tracking "images": pages rather than pictures, or paths that say so.
TRACKER_PATH = re.compile(r"\.(?:html?|aspx?|php|jsp|cgi)$|(?:^|[/._-])(?:open|opened|track|tracking|trk|pixel|beacon)(?:[/._-]|$)", re.I)


def private_dir(*parts: str) -> Path:
    """A folder only this user can read, for files made from mail (images
    sent inside an email, attachment previews, originals): in
    $XDG_RUNTIME_DIR/courier, or when that isn't set, in this user's own
    cache ($XDG_CACHE_HOME/courier/tmp), never a shared /tmp. Each level is
    checked before it is used: a symlink or someone else's folder is
    refused, and one of ours that others could open is closed (0700)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    root = Path(runtime) / "courier" if runtime else cache / "courier" / "tmp"
    root.parent.mkdir(parents=True, exist_ok=True)
    level = root
    for part in (None, *parts):
        level = level if part is None else level / part
        try:
            os.mkdir(level, 0o700)
        except FileExistsError:
            pass
        info = os.lstat(level)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError(f"{level} isn't a private folder of this user's")
        if info.st_mode & 0o077:
            os.chmod(level, 0o700)
    return level


def cache_dir() -> Path:
    folder = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "courier" / "images"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def write_private(path: Path, data: bytes) -> None:
    """Writes a 0600 file through a fresh temporary of a random name (never
    a fixed one that a link left in its place could redirect)."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_image(data: bytes) -> Path:
    """An image from inside an email, as a private file."""
    path = private_dir("inline") / hashlib.sha1(data).hexdigest()[:24]
    if not path.exists():
        write_private(path, data)
    return path


def tracker(url: str) -> bool:
    return bool(TRACKER_PATH.search(urllib.parse.urlsplit(url).path))


def fetch_all(urls: list[str]) -> dict[str, Path | None]:
    """Downloads several at once and waits at most IMAGE_WAIT; whatever isn't
    in by then is left out (the threads die with the process)."""
    pending = list(urls)
    found: dict[str, Path | None] = {}
    lock = threading.Lock()

    def work() -> None:
        while True:
            with lock:
                if not pending:
                    return
                url = pending.pop(0)
            path = fetch(url)
            with lock:
                found[url] = path

    workers = [threading.Thread(target=work, daemon=True) for _ in range(min(8, len(urls)))]
    for worker in workers:
        worker.start()
    deadline = time.monotonic() + IMAGE_WAIT
    for worker in workers:
        worker.join(max(0.0, deadline - time.monotonic()))
    with lock:
        return dict(found)


def fetch(url: str) -> Path | None:
    """A web image, downloaded once into the cache; None if it isn't one or
    may not be fetched (download)."""
    path = cache_dir() / hashlib.sha1(url.encode()).hexdigest()[:24]
    if path.exists():
        return path
    data = download(url)
    if data is None:
        return None
    write_private(path, data)
    return path


class Blocked(Exception):
    """A web address Courier won't fetch from."""


def public(address: str) -> bool:
    """Whether an IP address is on the public internet: not loopback,
    private, link-local, shared (CGNAT), multicast, reserved or unspecified,
    counting IPv4 tucked inside IPv6 (::ffff:10.0.0.1, 6to4, Teredo)."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6:
        inner = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if inner is not None and not public(str(inner)):
            return False
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local
                                 or ip.is_private or ip.is_unspecified)


def resolve_public(host: str, port: int) -> str:
    """The address to connect to for a name. Every address the name
    resolves to must be public (one private answer is enough to refuse),
    and the connection then goes to the address checked, so the name can't
    answer differently a moment later (DNS rebinding)."""
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise Blocked(f"can't resolve {host}") from None
    addresses = [answer[4][0] for answer in answers]
    if not addresses or not all(public(address) for address in addresses):
        raise Blocked(f"{host} isn't on the public internet")
    return addresses[0]


def _connection(scheme: str, name: str, address: str, port: int, timeout: float):
    """An HTTP(S) connection to an address already checked. For HTTPS the
    certificate is checked against the name (and SNI sent for it), not the
    address. Imported here: ssl isn't needed while every image is cached."""
    import http.client

    if scheme == "http":
        return http.client.HTTPConnection(address, port, timeout=timeout)
    import ssl

    context = ssl.create_default_context()

    class Pinned(http.client.HTTPSConnection):
        def connect(self) -> None:
            raw = socket.create_connection((self.host, self.port), self.timeout)
            self.sock = context.wrap_socket(raw, server_hostname=name)

    return Pinned(address, port, timeout=timeout, context=context)


def download(url: str) -> bytes | None:
    """The image at a web address, or None: public_get, then only a 200 that
    says it is an image and fits IMAGE_LIMIT."""
    import http.client

    try:
        status, kind, data = public_get(url)
    except (Blocked, OSError, ValueError, http.client.HTTPException):
        return None
    return data if status == 200 and kind.startswith("image/") and data else None


def public_get(url: str, *, accept: str = "image/*", limit: int | None = None, timeout: float | None = None,
               https_only: bool = False) -> tuple[int, str, bytes | None]:
    """GET a web address from the public internet only, for anything Courier
    fetches because of what a sender wrote (images in mail, sender logos,
    Gravatars): the name resolved once and refused unless every address is
    public (resolve_public), the connection made to that checked address,
    ports 80 and 443 only (https only if asked), no user:password@, at most
    IMAGE_REDIRECTS redirects with every hop checked again, `timeout`
    seconds in all.

    Returns (status, content type, body) of the final answer; the body is
    b"" for anything but a 200, None when it is larger than `limit`. Raises
    Blocked when an address, scheme, port or redirect isn't allowed, and
    OSError, ValueError or http.client.HTTPException when the server can't
    be reached or answers nonsense."""
    import http.client

    # Read now, not when defined, so the limits can be changed at run time.
    limit = IMAGE_LIMIT if limit is None else limit
    deadline = time.monotonic() + (IMAGE_TIMEOUT if timeout is None else timeout)
    schemes = {"https"} if https_only else {"http", "https"}
    for _ in range(IMAGE_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(url)
        scheme = parts.scheme.lower()
        port = parts.port or (443 if scheme == "https" else 80)
        if (scheme not in schemes or not parts.hostname or port not in IMAGE_PORTS
                or parts.username is not None or parts.password is not None):
            raise Blocked(f"won't fetch {scheme}://{parts.hostname}:{port}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("took too long")
        address = resolve_public(parts.hostname, port)
        connection = _connection(scheme, parts.hostname, address, port, remaining)
        try:
            target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            connection.request("GET", target, headers={"Host": parts.netloc, "User-Agent": USER_AGENT, "Accept": accept,
                                                       "Connection": "close"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location") or ""
                if not location:
                    return response.status, "", b""
                url = urllib.parse.urljoin(url, location.strip())
                continue
            kind = response.headers.get_content_type()
            if response.status != 200:
                return response.status, kind, b""
            length = response.getheader("Content-Length") or ""
            if length.isdigit() and int(length) > limit:
                return response.status, kind, None
            data = bytearray()
            while len(data) <= limit:
                if time.monotonic() > deadline:
                    raise TimeoutError("took too long")
                chunk = response.read(65536)
                if not chunk:
                    break
                data += chunk
            return response.status, kind, bytes(data) if len(data) <= limit else None
        finally:
            connection.close()
    raise Blocked("too many redirects")


def prune_cache() -> None:
    """Web images not opened for a month go; checked once a day."""
    folder = cache_dir()
    stamp = folder / ".pruned"
    now = time.time()
    try:
        if now - stamp.stat().st_mtime < 86400:
            return
    except OSError:
        pass
    stamp.touch()
    for path in folder.iterdir():
        try:
            if path.name != ".pruned" and now - path.stat().st_atime > CACHE_DAYS * 86400:
                path.unlink()
        except OSError:
            pass


_PIXEL_LIMIT = threading.RLock()


@contextlib.contextmanager
def pixel_limit(pixels: int):
    """Inside this, Pillow refuses any picture over `pixels` before decoding
    it. Pillow checks a picture's size as it opens it, and each icon frame
    (which it decodes as it opens), against its own limit, MAX_IMAGE_PIXELS:
    about 89 million, and only a warning below twice that. This lowers the
    limit and makes it an error. The limit is one for the whole process
    (courier-avatars decodes in threads), so one picture at a time is
    opened under it."""
    from PIL import Image

    with _PIXEL_LIMIT, warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        saved, Image.MAX_IMAGE_PIXELS = Image.MAX_IMAGE_PIXELS, pixels
        try:
            yield
        finally:
            Image.MAX_IMAGE_PIXELS = saved


def image_size(path: Path) -> tuple[int, int] | None:
    """An image's size, read from its header (nothing is decoded here); None
    when it isn't one of PICTURE_FORMATS or is over IMAGE_PIXELS, so it
    never reaches Qt."""
    try:
        from PIL import Image

        with pixel_limit(IMAGE_PIXELS), Image.open(path, formats=PICTURE_FORMATS) as image:
            return image.size
    except Exception:  # Pillow raises many kinds for files it can't read, or too big.
        return None


LINE_HEIGHT = re.compile(r"line-height\s*:\s*([^;}]+)", re.I)
# Clamp heavy CSS weights (>= 700 / bold) to 600 so Qt 6 RichText renders crisp
# Adwaita Sans (Inter) SemiBold without synthetic double-bolding or heavy bloat.
HEAVY_WEIGHT = re.compile(r"font-weight\s*:\s*(?:bold|bolder|[789]\d\d)(\s*!important)?", re.I)


def fix_font_weight(declarations: str) -> str:
    return HEAVY_WEIGHT.sub(lambda m: f"font-weight:600{m.group(1) or ''}", declarations)


def fix_line_height(declarations: str) -> str:
    """Line heights as px, which Qt treats as a minimum, like a browser.
    Unitless and % heights scale the whole line in Qt, image included (a
    300 px image gains 120 px under it), and 0 squashes the line onto the
    next."""
    size = pixels(style_value(declarations, "font-size")) or 16

    def fix(match: re.Match) -> str:
        value = match.group(1).lower().replace("!important", "").strip()
        number = re.fullmatch(r"(\d*\.?\d+)\s*(px|%|em)?", value)
        if not number:
            return match.group(0)
        amount = float(number.group(1))
        unit = number.group(2)
        height = amount if unit == "px" else amount * size / 100 if unit == "%" else amount * size
        return f"line-height:{round(height)}px" if height >= 2 else ""

    return LINE_HEIGHT.sub(fix, declarations)


def clean_css(css: str) -> str:
    """A <style> block without @-rules (media queries, fonts, imports) or
    url()s."""
    out = []
    depth = 0
    at_rule = False
    start = 0
    for i, char in enumerate(css):
        if char == "@" and depth == 0:
            out.append(css[start:i])
            at_rule = True
        elif char == ";" and at_rule and depth == 0:
            at_rule = False
            start = i + 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
            if at_rule and depth == 0:
                at_rule = False
                start = i + 1
    if not at_rule:
        out.append(css[start:])
    kept = re.sub(r"\{([^{}]*)\}", lambda match: "{" + fix_font_weight(fix_line_height(match.group(1))) + "}", "".join(out))
    return URLS.sub("none", kept)


# Characters CSS here never needs that could break out of it: "<" could
# open a tag or close the <style> it goes back into, "&" could spell one as
# an entity, and a backslash escape could spell url( past the check.
CSS_UNSAFE = re.compile(r"[<&\\]")


def safe_css(css: str) -> str:
    """CSS that can only end where its own </style> does, and loads nothing."""
    return URLS.sub("none", CSS_UNSAFE.sub("", css))


class _Styles(html.parser.HTMLParser):
    """The text of each <style> block, read by the same parser as the rest
    of the email, so styles and markup agree on where a block ends."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self.inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "style":
            self.inside = True
            self.blocks.append("")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        pass

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self.inside = False

    def handle_data(self, data: str) -> None:
        if self.inside:
            self.blocks[-1] += data


def style_blocks(markup: str) -> list[str]:
    styles = _Styles()
    try:
        styles.feed(markup)
        styles.close()
    except (AssertionError, ValueError):
        pass
    return styles.blocks


def hidden_classes(css: str) -> set[str]:
    """Classes a <style> block hides (display: none), e.g. the preview text."""
    found = set()
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if HIDDEN_STYLE.search(body):
            for selector in selectors.split(","):
                match = re.fullmatch(r"\s*(?:[a-z0-9]+)?\.([\w-]+)\s*", selector, re.I)
                if match:
                    found.add(match.group(1))
    return found


def solid_color(value: str) -> str:
    """A colour QML can read (#rgb, #rrggbb or a name), or "" for none or
    see-through."""
    value = value.strip().lower()
    match = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", value)
    if match:
        if match.group(4) is not None and float(match.group(4)) < 1:
            return ""
        return "#" + "".join(f"{min(255, int(part)):02x}" for part in match.groups()[:3])
    if value in {"", "transparent", "none", "inherit", "initial"}:
        return ""
    return value if re.fullmatch(r"#[0-9a-f]{3}|#[0-9a-f]{6}|[a-z]+", value) else ""


def safe_href(href: str) -> str:
    href = href.strip()
    return href if re.match(r"(?i)^(https?:|mailto:)", href) else ""


def pixels(value: str | None) -> int | None:
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*$", value or "")
    return int(float(match.group(1))) if match else None


def style_value(style: str, name: str) -> str:
    match = re.search(rf"(?:^|;)\s*{name}\s*:\s*([^;]+)", style or "", re.I)
    return match.group(1).strip() if match else ""


def is_dark(colour: str) -> bool:
    """Whether a #rgb / #rrggbb colour (or a few names) is dark."""
    colour = colour.strip().lower()
    if colour in {"black", "navy", "darkblue", "darkslategray", "darkslategrey"}:
        return True
    match = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", colour)
    if not match:
        return False
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 110


# Code and quotes as GitHub draws them, light or dark by the email's background:
# code block, inline code, quote bar, quote text.
TINTS = {False: ("#f6f8fa", "#eff1f3", "#d0d7de", "#57606a"), True: ("#2d333b", "#373e47", "#545d68", "#adbac7")}


def background_of(values: dict[str, str]) -> str:
    """An element's solid background colour from bgcolor or its style."""
    style = values.get("style", "")
    found = style_value(style, "background-color") or next(
        (part for part in style_value(style, "background").split() if solid_color(part)), "")
    return solid_color(values.get("bgcolor", "") or found)


def without(style: str, *names: str) -> str:
    """A style attribute without these properties (and their -top… forms)."""
    pattern = "|".join(re.escape(name) for name in names)
    return re.sub(rf"(?:^|;)\s*(?:{pattern})(?:-[a-z]+)?\s*:[^;]*", "", style, flags=re.I).strip("; ")


def padding_style(style: str) -> str:
    top, right, bottom, left = padding_of(style)
    return f"padding-top:{top}px;padding-right:{right}px;padding-bottom:{bottom}px;padding-left:{left}px"


def padding_of(style: str) -> list[int]:
    """Top, right, bottom, left padding in px from a style attribute."""
    sides = [0, 0, 0, 0]
    values = [pixels(part) or 0 for part in style_value(style, "padding").split()][:4]
    if len(values) == 1:
        sides = values * 4
    elif len(values) == 2:
        sides = values * 2
    elif len(values) == 3:
        sides = [values[0], values[1], values[2], values[1]]
    elif len(values) == 4:
        sides = values
    for number, side in enumerate(("top", "right", "bottom", "left")):
        value = pixels(style_value(style, f"padding-{side}"))
        if value is not None:
            sides[number] = value
    return sides


class _Cleaner(html.parser.HTMLParser):
    def __init__(self, hidden: set[str]) -> None:
        super().__init__(convert_charrefs=False)
        self.hidden = hidden
        self.out: list[str] = []
        # Images, drawn once their files and sizes are known.
        self.pictures: list[dict] = []
        # Inside a dropped or hidden element: (tag, nesting of that tag).
        self.skip: tuple[str, int] | None = None
        # Inside a link drawn as a button (a one-cell table).
        self.button = False
        # Open code blocks and quotes, each drawn inside a one-cell table.
        self.pre = 0
        self.quotes = 0
        # Qt paints a cell's background only behind its text, so a cell with a
        # background holds a full-width table that carries it. Open cells as
        # (table depth, holds such a table); each row's background by depth.
        self.depth = 0
        self.cells: list[tuple[int, bool]] = []
        self.rows: dict[int, str] = {}
        self.background = ""
        self.has_design = False
        # For classify(): every solid background, links drawn as buttons, and
        # the largest font size the email asks for.
        self.backgrounds: list[str] = []
        self.buttons = 0
        self.largest_font = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.start(tag, attrs, closed=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.start(tag, attrs, closed=True)

    def start(self, tag: str, attrs: list[tuple[str, str | None]], closed: bool) -> None:
        tag = tag.lower()
        if self.skip:
            if tag == self.skip[0] and not closed and tag not in VOID:
                self.skip = (tag, self.skip[1] + 1)
            return
        values = {name.lower(): value or "" for name, value in attrs}
        if tag == "body":
            found = re.search(r"background(?:-color)?\s*:\s*(#[0-9a-f]{3,8}|rgba?\([^)]*\)|[a-z]+)", values.get("style", ""), re.I)
            self.background = solid_color(values.get("bgcolor", "") or (found.group(1) if found else ""))
            return
        hidden = HIDDEN_STYLE.search(values.get("style", "")) or "hidden" in values or set(values.get("class", "").split()) & self.hidden
        if tag in DROPPED or hidden:
            if not closed and tag not in VOID:
                self.skip = (tag, 1)
            return
        tag = RENAMED.get(tag, tag)
        if tag in KEPT and tag != "img":
            found = background_of(values)
            if found:
                self.backgrounds.append(found)
            size = pixels(style_value(values.get("style", ""), "font-size"))
            if size:
                self.largest_font = max(self.largest_font, size)
        if tag == "img":
            picture = self.picture(values)
            if picture is not None:
                self.out.append(f"\x00{len(self.pictures)}\x00")
                self.pictures.append(picture)
                self.has_design = True
            return
        if tag not in KEPT:
            return
        if tag in {"td", "th"}:
            self.close_cell()
            background = background_of(values) or self.rows.get(self.depth, "")
            if background:
                style = values.get("style", "")
                inner = padding_style(style)
                values = {name: value for name, value in values.items() if name != "bgcolor"}
                values["style"] = without(style, "padding", "background")
                cell_align = "".join(f' {name}="{html.escape(values[name])}"' for name in ("align", "valign") if values.get(name))
                self.out.append(self.open_tag(tag, values))
                self.out.append(f'<table width="100%" cellspacing="0" cellpadding="0" bgcolor="{background}"><tr><td{cell_align} style="{inner}">')
            else:
                self.out.append(self.open_tag(tag, values))
            self.cells.append((self.depth, bool(background)))
            return
        if tag == "tr":
            self.close_cell()
            self.rows[self.depth] = background_of(values)
        if tag == "table":
            self.has_design = True
            self.out.append(self.open_tag(tag, values))
            self.depth += 1
            return
        if tag == "a" and not self.button:
            self.button_start(values.get("style", ""))
        if tag in {"pre", "code", "blockquote"}:
            self.code_or_quote(tag, values)
            return
        self.out.append(self.open_tag(tag, values))

    def code_or_quote(self, tag: str, values: dict[str, str]) -> None:
        """Code and quotes the way GitHub draws them: a code block in a shaded,
        padded box whose long lines wrap (Qt would clip them), inline code on a
        tint, a quote behind a bar. Qt pads and shades only table cells, so the
        box and the bar are one-cell tables."""
        block, inline, bar, muted = TINTS[is_dark(self.background)]
        style = values.get("style", "")
        if tag == "pre":
            self.out.append(f'<table width="100%" cellspacing="0" cellpadding="0" bgcolor="{block}"><tr>'
                            '<td style="padding-top:10px;padding-right:12px;padding-bottom:10px;padding-left:12px">')
            kept = without(style, "white-space", "background", "margin", "padding")
            self.out.append(self.open_tag("pre", values | {"style": ";".join(filter(None, ("white-space:pre-wrap;margin:0", kept)))}))
            self.pre += 1
        elif tag == "code":
            if self.pre:
                self.out.append(self.open_tag("code", values))
            else:
                kept = without(style, "background")
                self.out.append(self.open_tag("code", values | {"style": ";".join(filter(None, (f"background-color:{inline}", kept)))}))
        else:
            # Qt won't draw one side of a cell's border, so the bar is the
            # outer table's colour showing through 3px of padding beside an
            # inner table in the page's own colour.
            paper = self.background or "#ffffff"
            self.out.append(f'<table width="100%" cellspacing="0" cellpadding="0" bgcolor="{bar}"><tr><td style="padding-left:3px">'
                            f'<table width="100%" cellspacing="0" cellpadding="0" bgcolor="{paper}"><tr><td style="padding-left:12px;color:{muted}">')
            self.quotes += 1

    def close_cell(self) -> None:
        """Closes the open cell of the current table, if any (a new cell, a
        row's end or the table's end closes one left open)."""
        if self.cells and self.cells[-1][0] == self.depth:
            _, wrapped = self.cells.pop()
            self.out.append("</td></tr></table></td>" if wrapped else "</td>")

    def open_tag(self, tag: str, values: dict[str, str]) -> str:
        kept = []
        for name, value in values.items():
            if name not in ATTRIBUTES["*"] and name not in ATTRIBUTES.get(tag, set()):
                continue
            if name == "href":
                value = safe_href(value)
                if not value:
                    continue
            if name == "style":
                value = fix_font_weight(fix_line_height(safe_css(value)))
            kept.append((name, value))
        rendered = "".join(f' {name}="{html.escape(value, quote=True)}"' for name, value in kept)
        return f"<{tag}{rendered}>"

    def button_start(self, style: str) -> None:
        """A link styled as a button (a padded block with a background) as a
        one-cell table, since Qt pads table cells but not links."""
        shown = style_value(style, "display").lower()
        background = background_of({"style": style})
        if shown not in {"block", "inline-block"} or not background:
            return
        self.out.append(f'<table cellspacing="0" cellpadding="0" bgcolor="{background}"><tr><td style="{padding_style(style)}">')
        self.button = True
        self.buttons += 1

    def picture(self, values: dict[str, str]) -> dict | None:
        """What it takes to draw an image, or None to leave it out."""
        source = values.get("src", "").strip()
        style = values.get("style", "")
        width = pixels(values.get("width")) or pixels(style_value(style, "width"))
        height = pixels(values.get("height")) or pixels(style_value(style, "height"))
        # Tracking pixels say so.
        if (width is not None and width <= 2) or (height is not None and height <= 2):
            return None
        if not re.match(r"(?i)^(cid:|data:image/|https?://)", source) or (source.lower().startswith("http") and tracker(source)):
            return None
        return {"source": source, "width": width, "alt": values.get("alt", ""), "align": values.get("align", "")}

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip:
            if tag == self.skip[0]:
                depth = self.skip[1] - 1
                self.skip = (tag, depth) if depth else None
            return
        tag = RENAMED.get(tag, tag)
        if tag in {"td", "th"}:
            self.close_cell()
            return
        if tag == "tr":
            self.close_cell()
            self.rows.pop(self.depth, None)
        if tag == "table" and self.depth:
            self.close_cell()
            self.rows.pop(self.depth, None)
            self.depth -= 1
        if tag == "pre" and self.pre:
            self.out.append("</pre></td></tr></table>")
            self.pre -= 1
            return
        if tag == "blockquote":
            if self.quotes:
                self.out.append("</td></tr></table></td></tr></table>")
                self.quotes -= 1
            return
        if tag in KEPT and tag not in VOID:
            self.out.append(f"</{tag}>")
        if tag == "a" and self.button:
            self.out.append("</td></tr></table>")
            self.button = False

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self.skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip:
            self.out.append(f"&#{name};")


def image_files(parsed, pictures: list[dict]) -> list[Path | None]:
    """Each image's file: from inside the email, from a data: URI, or
    downloaded (several at once)."""
    inside = {}
    if any(p["source"].lower().startswith("cid:") for p in pictures):
        for part in parsed.walk():
            content_id = (part.get("Content-ID") or "").strip("<> ")
            if content_id and part.get_content_maintype() == "image":
                inside[content_id] = part
    files: list[Path | None] = []
    web: dict[str, list[int]] = {}
    for number, picture in enumerate(pictures):
        source = picture["source"]
        files.append(None)
        if source.lower().startswith("cid:"):
            part = inside.get(source[4:].strip("<> "))
            data = part.get_payload(decode=True) if part is not None else b""
            if data and len(data) <= IMAGE_LIMIT:
                files[number] = write_image(data)
        elif source.lower().startswith("data:"):
            match = re.match(r"data:image/[\w.+-]+;base64,(.*)", source, re.S | re.I)
            try:
                data = base64.b64decode(match.group(1)) if match else b""
            except ValueError:
                data = b""
            if data and len(data) <= IMAGE_LIMIT:
                files[number] = write_image(data)
        elif len(web) < IMAGE_COUNT or source in web:
            web.setdefault(source, []).append(number)
    if web:
        prune_cache()
        folder = cache_dir()
        cached = {url: folder / hashlib.sha1(url.encode()).hexdigest()[:24] for url in web}
        missing = [url for url, path in cached.items() if not path.exists()]
        found = {url: path for url, path in cached.items() if url not in missing}
        found.update(fetch_all(missing) if missing else {})
        for source, numbers in web.items():
            for number in numbers:
                files[number] = found.get(source)
    return files


def image_tag(picture: dict, path: Path | None, drawn: dict[Path, int], theme=None) -> str:
    """An image at its exact size, so the layout is right before it draws;
    an image that didn't load leaves its description; a 1×1 leaves nothing.
    `drawn` is this email's images so far, by file, with their pixels: one
    that would take the email past EMAIL_PIXELS leaves its description too."""
    size = image_size(path) if path else None
    if size is not None and path not in drawn:
        if sum(drawn.values()) + size[0] * size[1] > EMAIL_PIXELS:
            size = None
        else:
            drawn[path] = size[0] * size[1]
    if size is None:
        return f"<span>{html.escape(picture['alt'])}</span>" if picture["alt"].strip() else ""
    natural_width, natural_height = size
    if natural_width <= 2 or natural_height <= 2:
        return ""
    width = min(picture["width"] or min(natural_width, NATURAL_WIDTH), WIDEST)
    height = max(1, round(width * natural_height / natural_width))
    if theme is not None and path is not None:
        backed = backed_image(path, theme, natural_width / width)
        if backed is not None:
            path, pad = backed
            width, height = width + 2 * pad, height + 2 * pad
    align = f' align="{html.escape(picture["align"])}"' if picture["align"].lower() in {"left", "right", "middle", "top", "bottom"} else ""
    return f'<img src="{html.escape(path.as_uri())}" width="{width}" height="{height}" alt="{html.escape(picture["alt"])}"{align}>'


# Signs that a plain-text email was written in Markdown; two different ones
# are needed, so ordinary text with a list or a link stays text.
MARKDOWN_SIGNS = [re.compile(pattern) for pattern in (
    r"(?m)^#{1,6} \S",                                # heading
    r"(?m)^(```|~~~)",                                 # code fence
    r"\*\*[^*\n]+\*\*|__[^_\n]+__",                    # bold
    r"\[[^\]\n]+\]\(https?://[^)\s]+\)",                # [link](url)
    r"(?m)(^[ \t]*[-*+] \S.*\n){2,}",                   # bullets
    r"(?m)(^[ \t]*\d+\. \S.*\n){2,}",                  # numbered list
    r"(?m)^\|.*\|[ \t]*\n\|[ :\-|]+\|",                 # table
    r"`[^`\n]+`",                                      # inline code
)]
CODE_PARTS = re.compile(r"(?s)(^```.*?^```[ \t]*$|^~~~.*?^~~~[ \t]*$|`[^`\n]+`)", re.M)


def looks_like_markdown(text: str) -> bool:
    return sum(1 for sign in MARKDOWN_SIGNS if sign.search(text)) >= 2


def markdown_html(text: str) -> str:
    """Markdown (CommonMark, plus tables and strikethrough) as HTML. Raw HTML
    in the text stays text; a line break stays a line break, as in a plain
    email; bare web addresses become links, except inside code."""
    from markdown_it import MarkdownIt

    parts = CODE_PARTS.split(text)
    for number in range(0, len(parts), 2):
        parts[number] = re.sub(r"(?<![(<\[`])\bhttps?://[^\s<>()\[\]`]+[^\s<>()\[\]`.,;:!?'\"]", lambda m: f"<{m.group(0)}>", parts[number])
    renderer = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable(["table", "strikethrough"])
    # Tables with GitHub's thin grid lines.
    return renderer.render("".join(parts)).replace(
        "<table>", '<table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;border-color:#d0d7de">')


# Images whose pixels stand out less than this against the theme's surface,
# around transparent edges, get a light backing (a black logo on dark).
VANISHES = 2.0
BACKING = "#eceef1"


def backed_image(path: Path, theme, scale: float) -> tuple[Path, int] | None:
    """A copy of a see-through image on a rounded light card, when its
    visible pixels would vanish on the theme's surface; with the padding
    (display pixels) the card adds. None when it reads fine as it is."""
    try:
        from PIL import Image, ImageDraw

        import courier_theme

        with pixel_limit(4_000_000), Image.open(path, formats=PICTURE_FORMATS) as image:
            if image.mode not in {"RGBA", "LA", "PA"} and not (image.mode == "P" and "transparency" in image.info):
                return None
            rgba = image.convert("RGBA")
    except Exception:  # Unreadable or too big: drawn as it is.
        return None
    small = rgba.copy()
    small.thumbnail((96, 96))
    pixels_ = list(getattr(small, "get_flattened_data", small.getdata)())
    clear = sum(1 for p in pixels_ if p[3] < 40)
    seen = [p for p in pixels_ if p[3] >= 128]
    if clear < len(pixels_) * 0.1 or not seen:
        return None
    average = tuple(sum(p[i] for p in seen) / len(seen) / 255 for i in range(3))
    if courier_theme.contrast(average, theme.surface) >= VANISHES:
        return None
    pad = 6
    # Drawn at most twice its displayed size (sharp on a HiDPI screen), so a
    # picture shown small but stored huge never makes a huge card.
    display = max(1, min(WIDEST, round(rgba.width / max(scale, 0.01))))
    if rgba.width > 2 * display:
        rgba = rgba.resize((2 * display, max(1, round(rgba.height * 2 * display / rgba.width))))
    scale = rgba.width / display
    margin, radius = max(1, round(pad * scale)), max(2, round(10 * scale))
    if (rgba.width + 2 * margin) * (rgba.height + 2 * margin) > 4_000_000:
        return None
    card = Image.new("RGBA", (rgba.width + 2 * margin, rgba.height + 2 * margin), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius, fill=BACKING)
    card.alpha_composite(rgba, (margin, margin))
    folder = private_dir("inline")
    target = folder / (hashlib.sha1(str(path).encode() + b"backed").hexdigest()[:24] + ".png")
    card.save(target)
    target.chmod(0o600)
    return target, pad


# What makes an email designed rather than written: hero images, background
# images, coloured blocks (measured on 2026-11-24 against Jagrit's mail;
# see classify()).
HERO_WIDTH, HERO_HEIGHT = 300, 100
# Bounded scans (attacker-written HTML must not make this slow).
BACKGROUND_IMAGE = re.compile(r"background-image\s*:\s*url\(|<(?:table|td|th|div|body)\b[^<>]{0,2000}?\sbackground\s*=\s*[\"']?(?:https?:|cid:)"
                              r"|background\s*:[^;\"'}<>]{0,500}url\(", re.I)
# How much of the email classify() reads for background images.
CLASSIFY_LIMIT = 2 * 1024 * 1024


def classify(cleaner, sizes: list[tuple[int, int] | None], markup: str, paper: str) -> tuple[str, dict]:
    """"simple" (mostly text: notifications, personal mail, plain receipts)
    or "designed" (newsletters and marketing), with the signals it read."""
    import courier_theme

    shown = []
    for picture, size in zip(cleaner.pictures, sizes):
        if size:
            width = min(picture["width"] or min(size[0], NATURAL_WIDTH), WIDEST)
            shown.append((width, round(width * size[1] / max(1, size[0]))))
        elif picture["width"]:
            shown.append((picture["width"], 0))
    hero = any(width >= HERO_WIDTH and (height >= HERO_HEIGHT or height == 0) for width, height in shown)
    big = sum(1 for width, _ in shown if width >= 120)
    page = courier_theme.parse(paper or "#ffffff") or (1, 1, 1, 1)
    page_l = courier_theme.oklch(page[:3])[0]
    colours, greys = set(), set()
    for value in cleaner.backgrounds:
        rgb = courier_theme.parse(value)
        if rgb is None or rgb[3] < 0.5:
            continue
        lightness, chroma, _ = courier_theme.oklch(rgb[:3])
        if chroma >= 0.04:
            colours.add(courier_theme.hex_of(rgb[:3]))
        elif abs(lightness - page_l) > 0.03:
            greys.add(courier_theme.hex_of(rgb[:3]))
    signals = {
        "hero image": hero,
        "background image": bool(BACKGROUND_IMAGE.search(markup[:CLASSIFY_LIMIT])),
        "images": big,
        "coloured blocks": len(colours),
        "grey blocks": len(greys),
        "buttons": cleaner.buttons,
        "largest font": cleaner.largest_font,
    }
    designed_ = (signals["background image"] or hero or big >= 3 or len(colours) >= 3
                 or (len(colours) >= 2 and (big >= 1 or cleaner.buttons >= 1))
                 or (cleaner.largest_font >= 26 and (big >= 1 or len(colours) >= 1)))
    return ("designed" if designed_ else "simple"), signals


def designed(parsed, markup: str, theme=None, colours: str = "auto") -> dict | None:
    """The email's HTML as Qt rich text: {"html", "background", "layout",
    "kind", "themed"}. `layout` is true when it has tables or images, i.e.
    it was designed rather than just typed; `kind` is classify()'s verdict.
    With a theme (courier_theme.Theme), a simple email (or any, with
    colours="dark") comes back in the theme's colours, and see-through
    images that would vanish on it get a light backing; colours="original"
    leaves it as it is. None when nothing is left to show."""
    # NUL marks where images go, so none may come from the email.
    body = markup.replace("\x00", "")
    # Outlook-only blocks ([if mso]) are comments to every other client.
    body = re.sub(r"<!--\[if[^\]]*\]>.*?<!\[endif\]-->", "", body, flags=re.S | re.I)
    # The <style> blocks as the cleaner's own parser reads them (it drops
    # them from the body), so a crafted "</style >" or a "<style>" inside an
    # attribute can't make the two disagree; then made safe to put back.
    css = safe_css("\n".join(clean_css(block) for block in style_blocks(body)))
    cleaner = _Cleaner(hidden_classes(css))
    try:
        cleaner.feed(body)
        cleaner.close()
    except (AssertionError, ValueError):
        pass
    if cleaner.button:
        cleaner.out.append("</td></tr></table>")
    cleaner.out.extend(["</pre></td></tr></table>"] * cleaner.pre + ["</td></tr></table></td></tr></table>"] * cleaner.quotes)
    content = "".join(cleaner.out).strip()
    files = image_files(parsed, cleaner.pictures)
    kind, signals = classify(cleaner, [image_size(path) if path else None for path in files], body, cleaner.background)
    use_theme = theme is not None and (colours == "dark" or (colours == "auto" and kind == "simple"))
    drawn: dict[Path, int] = {}
    content = re.sub(r"\x00(\d+)\x00", lambda match: image_tag(cleaner.pictures[int(match.group(1))], files[int(match.group(1))], drawn,
                                                                  theme if use_theme else None), content)
    if not re.sub(r"<[^>]+>|&nbsp;|\s", "", content) and "<img" not in content:
        return None
    head = f"<style>{css}</style>" if css.strip() else ""
    page = f"<html><head>{head}</head><body>{content}</body></html>"
    if use_theme:
        import courier_theme

        page = courier_theme.themed(page, theme, cleaner.background)
    return {"html": page, "background": "" if use_theme else cleaner.background, "layout": cleaner.has_design,
            "kind": kind, "signals": signals, "themed": use_theme}
