#!/usr/bin/env python3
"""Sender and account pictures for Courier, fetched once and cached on this PC.

Brands get the logo they publish for mail clients (BIMI, the DNS record Gmail
reads for its brand logos), else their website's app icon. People get their
Gravatar if they set one; otherwise the app shows initials. Every file is
checked to be a real image before it is kept.

Your own accounts get their own picture the same way: the Google account's
profile photo (through the sign-in Courier already has), else the address's
Gravatar, else the app shows the account's initial. A picture you choose for
an account (courier-mail account-picture) is a separate file and always wins;
nothing here ever writes it.

    courier-avatars fetch     account pictures, then senders of recent mail that have no picture yet
    courier-avatars accounts [--again]   just the account pictures (--again: look every one up anew)
    courier-avatars path <conversation id>
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import courier_sync as sync  # noqa: E402


def __getattr__(name: str):
    if name == "urllib":
        import urllib.error
        import urllib.parse
        import urllib.request

        globals()["urllib"] = urllib
        return urllib
    if name == "courier_html":
        import courier_html as _html

        globals()["courier_html"] = _html
        return _html
    if name == "subprocess":
        import subprocess as _subprocess

        globals()["subprocess"] = _subprocess
        return _subprocess
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Courier-mail-client"
MAX_BYTES = 512 * 1024
RETRY_MISSES_AFTER = 7 * 24 * 3600
LOOKUPS_PER_RUN = 120
# Addresses at these domains belong to people, never to a brand.
FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com", "zoho.com", "rediffmail.com", "yandex.com",
}


def cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "courier" / "avatars"


def index_path() -> Path:
    # In state, not cache, so the app can watch it and reload when pictures land.
    return sync.state_dir() / "avatars.json"


def load_index() -> dict:
    try:
        return json.loads(index_path().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def key_for(conversation_id: str) -> str | None:
    """Picture key for a conversation: a person's address or a brand's domain."""
    kind, _, value = conversation_id.partition(":")
    if kind == "p" and value:
        domain = value.rpartition("@")[2]
        # A role address at a company ("support@brand.com") wears the brand.
        local = value.partition("@")[0]
        if domain not in FREEMAIL and (local in sync.ROLE_WORDS or sync.ROBOT_SENDER.search(local)):
            return f"d:{domain}"
        return f"p:{value}"
    if kind == "u" and value:
        return f"d:{value}"
    return None


def picture_for(conversation_id: str, index: dict | None = None) -> str:
    return picture_for_key(key_for(conversation_id) or "", index)


def picture_for_key(key: str, index: dict | None = None) -> str:
    entry = (index if index is not None else load_index()).get(key)
    if entry and entry.get("file"):
        path = cache_dir() / entry["file"]
        if path.exists():
            return str(path)
    return ""


# Fetching ----------------------------------------------------------------------


class LookupFailed(Exception):
    """Couldn't ask (offline, Google refused the sign-in, a server error), as
    opposed to asking and hearing there is no picture. Try again later."""


def fetch(url: str) -> tuple[bytes, str] | None:
    try:
        return download(url)
    except LookupFailed:
        return None


def download(url: str) -> tuple[bytes, str] | None:
    """Like fetch, but only "it isn't there" (404, 410, too big, or an
    address Courier won't fetch from) is None; not being able to ask raises
    LookupFailed. A sender names these addresses (its domain, its BIMI
    record, its page's icons), so they go through courier_html.public_get:
    public addresses only, https only, every redirect checked, 512 KB and
    6 seconds at most."""
    import http.client
    import urllib.parse

    import courier_html

    host = urllib.parse.urlsplit(url).hostname
    try:
        status, kind, data = courier_html.public_get(url, accept="image/*,text/html;q=0.8,*/*;q=0.5", limit=MAX_BYTES,
                                                     timeout=6, https_only=True)
    except courier_html.Blocked:
        return None
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise LookupFailed(f"can't reach {host}: {error}") from None
    if status in (404, 410) or (status == 200 and data is None):
        return None
    if status != 200:
        raise LookupFailed(f"{host} answered {status}")
    return data, kind


def image_kind(data: bytes) -> str | None:
    """The file type, judged from its bytes rather than the server's word."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x00\x00\x01\x00"):
        return "ico"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    head = data[:2048].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or (head.startswith(b"<!--") and b"<svg" in head):
        return "svg"
    return None


def bimi_logo(domain: str) -> str | None:
    """The logo URL from a domain's BIMI record (default._bimi.<domain>)."""
    import subprocess

    try:
        result = subprocess.run(
            ["resolvectl", "query", "--legend=no", "-t", "TXT", f"default._bimi.{domain}"],
            capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"v=BIMI1;.*?\bl=(https://[^;\"\s]+)", result.stdout)
    return match.group(1) if match else None


def _extract_icon_links(markup: str) -> list[tuple[int, str]]:
    import html.parser

    class _IconLinks(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.icons: list[tuple[int, str]] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag != "link":
                return
            values = {key: value or "" for key, value in attrs}
            rel = values.get("rel", "").lower()
            href = values.get("href", "")
            if not href or "icon" not in rel or "mask" in rel:
                return
            sizes = [int(number) for number in re.findall(r"(\d+)x\d+", values.get("sizes", ""))]
            score = max(sizes, default=0)
            if "apple-touch-icon" in rel:
                score = max(score, 180)
            if values.get("type", "").endswith("svg") or href.lower().split("?")[0].endswith(".svg"):
                score = max(score, 160)
            self.icons.append((score, href))

    parser = _IconLinks()
    try:
        parser.feed(markup)
    except (AssertionError, ValueError):
        pass
    return parser.icons


def site_icon(domain: str) -> tuple[bytes, str] | None:
    import urllib.parse

    for host in (domain, f"www.{domain}"):
        page = fetch(f"https://{host}/")
        if page is None:
            continue
        icons = _extract_icon_links(page[0].decode("utf-8", "replace"))
        for _, href in sorted(icons, reverse=True):
            found = fetch(urllib.parse.urljoin(f"https://{host}/", href))
            if found and (kind := image_kind(found[0])):
                return found[0], kind
        found = fetch(f"https://{host}/favicon.ico")
        if found and (kind := image_kind(found[0])):
            return found[0], kind
    return None


def public_domain(domain: str) -> bool:
    """Whether a sender's domain looks like one on the internet: a dotted
    name of letters, digits and hyphens, not an IP address or a single word
    like "localhost". Anything else isn't looked up at all."""
    import ipaddress

    domain = domain.strip().lower().rstrip(".")
    try:
        ipaddress.ip_address(domain.strip("[]"))
        return False
    except ValueError:
        pass
    labels = domain.split(".")
    return len(labels) >= 2 and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels) \
        and not labels[-1].isdigit()


def brand_picture(domain: str) -> tuple[bytes, str] | None:
    if not public_domain(domain):
        return None
    candidates = list(dict.fromkeys([domain, base_domain(domain)]))
    for name in candidates:
        url = bimi_logo(name)
        if url and (found := fetch(url)) and image_kind(found[0]) == "svg":
            return found[0], "svg"
    for name in reversed(candidates):  # The main site has the better icon.
        if found := site_icon(name):
            return found
    return None


def gravatar_url(address: str, size: int = 160) -> str:
    import hashlib

    # d=404: no generated placeholder; no Gravatar means no picture.
    digest = hashlib.sha256(address.strip().lower().encode()).hexdigest()
    return f"https://gravatar.com/avatar/{digest}?d=404&s={size}"


def person_picture(address: str) -> tuple[bytes, str] | None:
    found = fetch(gravatar_url(address))
    if found and (kind := image_kind(found[0])):
        return found[0], kind
    return None


def base_domain(domain: str) -> str:
    labels = domain.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"ac", "co", "com", "edu", "gov", "net", "org"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


PICTURE_SIZE = 256
# Smaller icons would be blown up into a blur; initials look better.
SMALLEST_ICON = 32
# The biggest picture decoded, a side. MAX_BYTES caps the file, not the
# picture: a few KB of PNG can claim 50,000 × 50,000 and take gigabytes to
# decode. Real photos and logos are far smaller; the disc is 256 px.
LARGEST_PICTURE = 4096
# Each kind (judged from the bytes) is opened only as that format; an SVG
# is a PNG by then. Anything else Pillow reads is never tried.
FORMATS = {"png": ["PNG"], "jpg": ["JPEG"], "ico": ["ICO"], "webp": ["WEBP"], "svg": ["PNG"]}
# rsvg-convert may use this much memory (it needs about 200 MB to start).
SVG_MEMORY = 512 * 1024 * 1024


def round_png(data: bytes, kind: str) -> bytes | None:
    """The picture as a round PNG on a white disc, the way mail clients show
    senders. Tiles with opaque corners fill the disc; transparent logos sit
    centred with breathing room. The app then needs no clipping at all."""
    import io
    import subprocess
    from PIL import Image, ImageDraw, ImageOps

    if kind == "svg":
        try:
            # prlimit, not preexec_fn: senders are looked up in threads.
            raster = subprocess.run(
                ["prlimit", f"--as={SVG_MEMORY}", "rsvg-convert", "-w", str(PICTURE_SIZE), "-h", str(PICTURE_SIZE), "-a"],
                input=data, capture_output=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if raster.returncode != 0:
            return None
        data = raster.stdout
    try:
        image = decode(data, kind)
    except Exception:  # Pillow raises many kinds of errors for bad (or too big) images.
        return None
    if image is None or max(image.size) < SMALLEST_ICON:
        return None

    size = PICTURE_SIZE
    corners = [image.getpixel(point)[3] for point in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1))]
    disc = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    if min(corners) > 200:
        tile = ImageOps.fit(image, (size, size), Image.LANCZOS)
        disc.alpha_composite(tile)
    else:
        logo = ImageOps.contain(image, (int(size * 0.64), int(size * 0.64)), Image.LANCZOS)
        disc.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
    # A smooth circle: draw it four times larger, then shrink.
    big = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    round_picture = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    round_picture.paste(disc, (0, 0), big.resize((size, size), Image.LANCZOS))
    out = io.BytesIO()
    round_picture.save(out, "PNG", optimize=True)
    return out.getvalue()


def decode(data: bytes, kind: str):
    """The picture, decoded as RGBA; None when it's over LARGEST_PICTURE a
    side, judged from its header before decoding. Raises for a bad one."""
    import io
    from PIL import Image

    import courier_html

    with courier_html.pixel_limit(LARGEST_PICTURE * LARGEST_PICTURE):
        image = Image.open(io.BytesIO(data), formats=FORMATS.get(kind, ["PNG", "JPEG", "ICO", "WEBP"]))
        if kind == "ico" and hasattr(image, "ico"):
            # Pillow picks the frame by size, and decodes it as it switches.
            image.size = max(image.ico.sizes())
        if max(image.size) > LARGEST_PICTURE:
            return None
        # A JPEG decodes at 1/2 to 1/8 scale when that still covers the disc.
        image.draft(None, (PICTURE_SIZE, PICTURE_SIZE))
        return image.convert("RGBA")


def store(key: str, data: bytes, kind: str) -> str | None:
    import hashlib

    picture = round_png(data, kind)
    if picture is None:
        return None
    name = hashlib.sha1(key.encode()).hexdigest()[:16] + ".png"
    cache_dir().mkdir(parents=True, exist_ok=True)
    (cache_dir() / name).write_bytes(picture)
    return name


def look_up(key: str) -> tuple[str, str | None]:
    kind, _, value = key.partition(":")
    found = brand_picture(value) if kind == "d" else person_picture(value)
    return key, (store(key, *found) if found else None)


def upgrade(index: dict) -> bool:
    """Turns pictures cached before round PNGs existed into round PNGs."""
    changed = False
    for key, entry in index.items():
        name = entry.get("file")
        if not name or entry.get("round"):
            continue
        old = cache_dir() / name
        try:
            data = old.read_bytes()
        except OSError:
            data = b""
        new = store(key, data, image_kind(data) or "") if data else None
        if new != name:
            old.unlink(missing_ok=True)
        entry.update(file=new, round=True)
        changed = True
    return changed


def wanted_keys() -> list[str]:
    """Senders of the conversations the app shows, newest first."""
    import courier_mail

    index = courier_mail.Index()
    try:
        conversations = courier_mail.conversations(index)
    finally:
        index.close()
    keys = [key_for(entry["id"]) for entry in conversations]
    # Every sender in the Newsletters and Updates lists gets a logo per row.
    lane_index = courier_mail.Index()
    try:
        for number, message in enumerate(lane_index.newest_first("tag:newsletters or tag:updates")):
            if number >= 800:
                break
            sender = courier_mail.address_of(message.header("from"))[1]
            if sender and sender not in lane_index.me:
                keys.append(f"d:{base_domain(sender.rpartition('@')[2])}")
    finally:
        lane_index.close()
    return list(dict.fromkeys(key for key in keys if key))


def fetch_missing() -> int:
    index = load_index()
    if upgrade(index):
        sync.write_private(index_path(), json.dumps(index, indent=1) + "\n")
    now = time.time()
    todo = [
        key for key in wanted_keys()
        if key not in index or (index[key].get("file") is None and now - index[key].get("checked", 0) > RETRY_MISSES_AFTER)
    ][:LOOKUPS_PER_RUN]
    if not todo:
        return 0
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for key, name in pool.map(look_up, todo):
            index[key] = {"file": name, "checked": int(now), "round": True}
    sync.write_private(index_path(), json.dumps(index, indent=1) + "\n")
    return sum(1 for key in todo if index[key]["file"])


# Your accounts -------------------------------------------------------------------

# Google's OpenID Connect userinfo. The `openid email` sign-in Courier already
# has returns the account's `picture` (checked 2026-11-23 on both accounts);
# nothing here asks Google for a new permission.
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
# Google's photo URLs end in a size (=s96-c); ask for one as big as the disc.
GOOGLE_PHOTO_HOST = ".googleusercontent.com"
# After a failed lookup (offline, signed out), wait this long before asking again.
RETRY_ERRORS_AFTER = 3600


def accounts_dir() -> Path:
    """Where both pictures of an account live: <id>.png is the one you chose
    (courier-mail account-picture), <id>.default.png the account's own."""
    return sync.xdg("XDG_DATA_HOME", ".local/share") / "courier" / "accounts"


def default_picture_path(account_id: str) -> Path:
    # Account ids are [a-z0-9-] (courier-auth), so "x.default" can never be
    # another account's "<id>.png".
    return accounts_dir() / f"{account_id}.default.png"


def account_index_path() -> Path:
    # In state, like avatars.json, so the app can watch it.
    return sync.state_dir() / "account-pictures.json"


def load_account_index() -> dict:
    try:
        return json.loads(account_index_path().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def default_source(account_id: str, index: dict | None = None) -> str:
    """Where the account's own picture came from: "google", "gravatar", or ""
    when there is none (the app shows its initial)."""
    if not default_picture_path(account_id).exists():
        return ""
    return ((index if index is not None else load_account_index()).get(account_id) or {}).get("source") or ""


def google_photo(account: dict) -> tuple[bytes, str] | None:
    """The Google account's profile photo, or None when Google has none."""
    import urllib.error
    import urllib.parse
    import urllib.request

    try:
        token = sync.auth_token(account["id"])
    except sync.SignedOut:
        raise LookupFailed("Google no longer accepts the sign-in") from None
    except sync.SyncError as error:
        raise LookupFailed(str(error)) from None
    request = urllib.request.Request(USERINFO_URL, headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            info = json.loads(response.read(64 * 1024))
    except urllib.error.HTTPError as error:
        raise LookupFailed(f"Google's userinfo answered {error.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise LookupFailed(f"can't reach Google: {getattr(error, 'reason', error)}") from None
    url = info.get("picture") or ""
    parts = urllib.parse.urlsplit(url)
    # Only ever Google's own photo host, over https.
    if parts.scheme != "https" or not (parts.hostname or "").endswith(GOOGLE_PHOTO_HOST):
        return None
    found = download(re.sub(r"=s\d+(-c)?$", "", url) + f"=s{PICTURE_SIZE}-c")
    if found is None:
        raise LookupFailed("Google's photo link answered 404")
    kind = image_kind(found[0])
    return (found[0], kind) if kind else None


def account_photo(account: dict) -> tuple[str, bytes, str] | None:
    """(source, image, kind) for an account: its Google profile photo, else
    its Gravatar, else None (initials). Raises LookupFailed when Google
    couldn't be asked and Gravatar has nothing either, so a moment offline
    never turns into "no picture"."""
    google_error = None
    try:
        found = google_photo(account)
        if found:
            return ("google", *found)
    except LookupFailed as error:
        # Not signed in to Google (or not right now): Gravatar may still have one.
        google_error = error
    found = download(gravatar_url(account["email"], PICTURE_SIZE))
    if found and (kind := image_kind(found[0])):
        return ("gravatar", found[0], kind)
    if google_error:
        raise google_error
    return None


def write_default(account_id: str, data: bytes, kind: str) -> bool:
    picture = round_png(data, kind)
    if picture is None:
        return False
    path = default_picture_path(account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(picture)
    os.replace(temporary, path)
    return True


def needs_lookup(account: dict, entry: dict | None, now: float) -> bool:
    """Whether an account's own picture should be looked up (again) now.

    A Google photo is kept: fetched once. A Gravatar or "none" is checked
    again weekly, like senders without a picture, so Google wins once it
    can be asked. A failed lookup is retried after an hour."""
    if not entry or entry.get("email") != account["email"]:
        return True
    if entry.get("failed"):
        return now - entry["failed"] > RETRY_ERRORS_AFTER
    if entry.get("source") and not default_picture_path(account["id"]).exists():
        return True
    if entry.get("source") == "google":
        return False
    return now - entry.get("checked", 0) > RETRY_MISSES_AFTER


def fetch_account_pictures(again: bool = False) -> dict:
    """Looks up each account's own picture once and caches it as a round PNG.
    Returns {account id: "google" | "gravatar" | "" | "error: …"} for the
    accounts looked up this time."""
    index_path = account_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    # The avatars service and the app can both start this; the second waits,
    # then finds the pictures already there.
    import fcntl

    with open(index_path.with_name(index_path.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        index = load_account_index()
        accounts = sync.load_accounts()
        now = time.time()
        looked_up: dict[str, str] = {}
        for account in accounts:
            account_id, entry = account["id"], index.get(account["id"])
            if not again and not needs_lookup(account, entry, now):
                continue
            if entry and entry.get("email") != account["email"]:
                # The name now belongs to another address: its picture goes.
                default_picture_path(account_id).unlink(missing_ok=True)
                entry = None
            try:
                found = account_photo(account)
            except LookupFailed as error:
                # Keep whatever picture it had; just remember to ask again later.
                index[account_id] = {**(entry or {"email": account["email"], "source": None}), "failed": int(now), "error": str(error)}
                looked_up[account_id] = f"error: {error}"
                continue
            source = None
            if found and write_default(account_id, found[1], found[2]):
                source = found[0]
            else:
                default_picture_path(account_id).unlink(missing_ok=True)
            index[account_id] = {"email": account["email"], "source": source, "checked": int(now)}
            looked_up[account_id] = source or ""
        # An account that's gone takes its picture with it (never the one you chose).
        known = {account["id"] for account in accounts}
        for account_id in [name for name in index if name not in known]:
            default_picture_path(account_id).unlink(missing_ok=True)
            del index[account_id]
            looked_up[account_id] = "removed"
        if looked_up:
            sync.write_private(index_path, json.dumps(index, indent=1) + "\n")
    return looked_up


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["fetch"]:
        try:
            for account_id, outcome in fetch_account_pictures().items():
                print(f"{account_id}: {outcome or 'no picture (initials)'}")
        except Exception as error:  # Never at the cost of sender pictures.
            print(f"courier-avatars: account pictures: {error!r}", file=sys.stderr)
        found = fetch_missing()
        print(f"{found} new pictures")
        return 0
    if args[:1] == ["accounts"] and set(args[1:]) <= {"--again"}:
        print(json.dumps(fetch_account_pictures(again="--again" in args)))
        return 0
    if args[:1] == ["path"] and len(args) == 2:
        print(picture_for(args[1]))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
