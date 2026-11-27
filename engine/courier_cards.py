"""Cards for the notification dock (feed contract v3): the task, not the email.

For each dock item Junco decides three things, by rules written from human
examples (a model may propose later; these rules still check it):
1. the intent: what happened, and what he needs to do;
2. a component from the dock's fixed vocabulary (DecisionPanel, ReviewPanel,
   CommentPanel, StatusSummary, DataTable, SchedulingPanel, Timeline, or the
   Summary fallback);
3. its lane ("action" needs him, "update" is news) and due time.

It fills the component's sections with data only: the dock draws them, and
Junco never sends layout, colours or sizes. Each card stays slim: one hero
element, at most 4 facts or rows, at most 3 buttons; the rest is for the
dock's Details sheet or left out.

Everything here reads an item Junco already made (courier_notify.Feed) and
nothing else, but for the day of a calendar invite, read from Junco's own
copy of his calendar. It never fetches, opens or sends anything: the
buttons it lists act only when pressed (courier_notify.dock_action).
Every string is plain text, pictures are file:// only, and links are
http(s) only.
"""

from __future__ import annotations

import datetime as dt
import re
import time
import urllib.parse

COMPONENTS = ("DecisionPanel", "ReviewPanel", "CommentPanel", "StatusSummary", "DataTable", "SchedulingPanel", "Timeline", "Summary")
# The sections each component reads (contract v3); any other is dropped.
READS = {
    "DecisionPanel": {"question", "facts"},
    "ReviewPanel": {"person", "status", "branch", "size", "stats", "files", "text"},
    "CommentPanel": {"person", "diff", "comment", "thread"},
    "StatusSummary": {"status", "jobs", "failure", "log", "history"},
    "DataTable": {"amount", "table"},
    "SchedulingPanel": {"when", "person", "day", "people", "place"},
    "Timeline": {"steps"},
    "Summary": {"facts", "text"},
}
# The sizes the vocabulary gives each (Junco's own record: the v7 dock draws
# every card one size, and the contract leaves sizes to the dock).
SIZES = {"DecisionPanel": "full", "ReviewPanel": "full", "CommentPanel": "full", "SchedulingPanel": "full",
         "StatusSummary": "full", "DataTable": "full", "Timeline": "half", "Summary": "half"}
TONES = {"error", "success", "primary", "tertiary", ""}
ROLES = {"primary", "secondary", "danger", "quiet"}
TYPES = {"url", "command", "input", "confirm"}
# Caps: what a slim card can hold.
FACTS, ROWS, FILES, DIFF, LOG, FACES, ACTIONS = 4, 4, 3, 3, 20, 5, 3
CURRENCIES = {"₹": "INR", "RS": "INR", "INR": "INR", "$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR", "£": "GBP",
              "GBP": "GBP"}


# Plain text, safe links ------------------------------------------------------------------


def plain(value, most: int = 160) -> str:
    """One line of plain text: inert (no tag, link or control character)."""
    import courier_notify as cn

    text = cn.inert(str(value if value is not None else ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def prose(value, most: int = 4000) -> str:
    """Written text with its lines (a comment, a description): no tag can
    open, no Markdown link or image, no control character."""
    import courier_notify as cn

    text = cn.inert_markup(str(value or "")).strip()
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def web(url) -> str:
    """An http(s) address with a plain host, else "": courier_sync.web_link
    (no credentials, a real port), and no backslash anywhere nor "@" in the
    host part, which browsers and Python read differently
    ("https://evil.example\\@google.com" is evil.example to a browser)."""
    import courier_sync

    if not isinstance(url, str) or "\\" in url or not courier_sync.web_link(url):
        return ""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if "@" in parts.netloc or parts.netloc.lower() not in (host, f"{host}:{parts.port}" if parts.port else host):
        return ""
    return url


def on_domain(url: str, domain: str) -> bool:
    if not web(url):
        return False
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    domain = (domain or "").lower()
    return bool(domain) and (host == domain or host.endswith("." + domain))


def picture(value) -> str:
    return value if isinstance(value, str) and value.startswith("file:///") and not re.search(r"[\s\x00-\x1f]", value) else ""


# Reading an email for its card (at note time; courier_notify.note_for) --------------------

HREF = re.compile(r"<a\b[^>]*?\bhref\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a>", re.I | re.S)
BARE = re.compile(r"https?://[^\s<>\"')\]]+")


def links_of(html: str, text: str, most: int = 200) -> list[tuple[str, str]]:
    """An email's links as (words, address): its HTML's anchors, then its
    text's bare addresses. Only http(s)."""
    import html as htmllib

    found: list[tuple[str, str]] = []
    for _, href, words in HREF.findall(html or "")[:most]:
        url = web(htmllib.unescape(href.strip()))
        if url:
            found.append((re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", words))).strip(), url))
    for url in BARE.findall(text or "")[:most]:
        url = web(url.rstrip(".,;:"))
        if url:
            found.append(("", url))
    return found


SECURE_WORDS = re.compile(r"secur|activity|sessions?|password|protect|review|check|not (?:you|me)|wasn.t (?:you|me)|recover|lock", re.I)
PAY_WORDS = re.compile(r"\bpay\b|pay (?:now|bill|invoice)|view (?:invoice|bill|statement)|invoice|billing|make (?:a )?payment|renew", re.I)


def pick_link(links: list[tuple[str, str]], domain: str, words: re.Pattern) -> str:
    """The first link on the sender's own (verified) domain whose words or
    address say it's the one ("Check activity", ".../security"); "" if none."""
    for label, url in links:
        if on_domain(url, domain) and (words.search(label) or words.search(urllib.parse.urlsplit(url).path)):
            return url
    return ""


AMOUNT = re.compile(r"(₹|Rs\.?|INR|\$|USD|€|EUR|£|GBP)\s?(\d[\d,]*(?:\.\d{1,2})?)", re.I)
DUE_WORDS = re.compile(r"(?:total|minimum|min\.?|amount|balance|outstanding|payable|bill)\s*(?:amount\s*)?(?:due|payable|outstanding)?", re.I)
MONTHS = {m.lower(): n for n, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})|(\d{1,2})[ -/](?:([A-Za-z]{3,9})|(\d{1,2}))[ -/,]*(\d{4})?|([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? ?(\d{4})?")
DUE = re.compile(r"(?:due (?:date)?|pay (?:by|before)|payable by|due on|due by|is due)\s*[:\-]?\s*(today|tomorrow|[A-Za-z0-9 ,/-]{4,24})", re.I)


def money(text: str) -> tuple[float, str] | None:
    """The amount an email asks for: the one after "total/amount/minimum
    due" words, else the first; (value, currency code)."""
    best = None
    for match in AMOUNT.finditer(text or ""):
        code = CURRENCIES.get(match.group(1).upper().rstrip("."), "INR")
        try:
            value = float(match.group(2).replace(",", ""))
        except ValueError:
            continue
        before = (text or "")[max(0, match.start() - 40): match.start()]
        if DUE_WORDS.search(before):
            return value, code
        best = best or (value, code)
    return best


def date_in(text: str, now: float) -> dt.date | None:
    """A date as emails write it ("16 Nov 2026", "Nov 16", "16/11/2026",
    "2026-11-16", "today", "tomorrow"); the year is this one when left out."""
    text = (text or "").strip().lower()
    today = dt.date.fromtimestamp(now)
    if text.startswith("today"):
        return today
    if text.startswith("tomorrow"):
        return today + dt.timedelta(days=1)
    match = DATE.search(text)
    if not match:
        return None
    try:
        if match.group(1):
            return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if match.group(4):
            month = MONTHS.get((match.group(5) or "")[:3].lower()) if match.group(5) else int(match.group(6))
            year = int(match.group(7)) if match.group(7) else today.year
            return dt.date(year, int(month), int(match.group(4))) if month else None
        month = MONTHS.get(match.group(8)[:3].lower())
        year = int(match.group(10)) if match.group(10) else today.year
        return dt.date(year, month, int(match.group(9))) if month else None
    except (TypeError, ValueError):
        return None


def due_in(text: str, now: float) -> dt.date | None:
    for match in DUE.finditer(text or ""):
        day = date_in(match.group(1), now)
        if day:
            return day
    return None


def mail_facts(kind: str, subject: str, html: str, text: str, domain: str, now: float) -> dict:
    """What a service email's card needs that its fields don't hold: the
    security page and the payment page on the sender's own domain, the
    amount and the due date. Read once, when the note is made."""
    words = f"{subject}\n{text}"
    links = links_of(html, text)
    facts: dict = {}
    if kind == "security-alert":
        facts["secure"] = pick_link(links, domain, SECURE_WORDS)
    if kind in ("bill", "payment-failed", "statement", "invoice", "domain-expiring"):
        found = money(words)
        if found:
            facts["amount"], facts["currency"] = found
        least = re.search(r"minimum (?:amount )?(?:due|payable)\D{0,12}?((?:₹|Rs\.?|INR|\$|USD|€|EUR|£|GBP)\s?\d[\d,]*(?:\.\d{1,2})?)", words, re.I)
        if least:
            facts["minimum"] = least.group(1)
        due = due_in(words, now)
        if due:
            facts["due"] = due.isoformat()
        facts["pay"] = pick_link(links, domain, PAY_WORDS)
        card = re.search(r"(?:(card|a/c|account)\D{0,24}?)?(?:ending|xx|\*{2,}|••)\s?(?:with |in )?(\d{4})\b", words, re.I)
        if card:
            facts["card"] = card.group(2)
            facts["number"] = "card" if (card.group(1) or "").lower() == "card" else "account" if card.group(1) else "card"
        period = re.search(r"(?:for the period|period)\s*:?\s*([\w -]{6,40}?\d{4})\s*(?:to|-|–)\s*([\w -]{6,40}?\d{4})", words, re.I) \
            or re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:to|-|–)\s*(\d{4}-\d{2}-\d{2})", subject or "")
        if period:
            first, last = date_in(period.group(1), now), date_in(period.group(2), now)
            facts["period"] = f"{first:%-d %b} – {last:%-d %b %Y}" if first and last else f"{period.group(1).strip()} – {period.group(2).strip()}"
        if re.search(r"receipt|\bpaid\b|payment (?:received|successful|confirmed)|thank(?:s| you) for your payment|renewal is confirmed", subject or "", re.I):
            facts["paid"] = True
        if re.search(r"auto-?renew|auto-?debit|auto-?pay|will be (?:charged|debited)", subject or "", re.I):
            facts["paid"] = True  # the service takes it by itself: news, nothing to pay
            facts["auto"] = True
        merchant = re.search(r"(?:invoice|receipt|bill) from ([A-Z][\w&.,' -]{1,40}?)(?: #| for |\s*$|\.|,| is )", subject or "")
        if merchant:
            facts["merchant"] = merchant.group(1).strip()
    if kind == "parcel":
        facts |= parcel_of(subject, now)
    if kind in ("deploy", "incident"):
        state = deploy_state(subject)
        if state:
            facts["step"] = state
    return {key: value for key, value in facts.items() if value not in ("", None)}


PARCEL_STATES = [("delivered", r"^delivered\b|has been delivered|was delivered"),
                 ("out", r"out for delivery|arriving today"),
                 ("shipped", r"^shipped\b|has (?:been )?shipped|dispatched|in transit|on (?:its|the) way"),
                 ("ordered", r"^ordered\b|order (?:confirmed|placed|received)")]
PARCEL_STEPS = [("ordered", "Ordered"), ("shipped", "Shipped"), ("out", "Out for delivery"), ("delivered", "Delivered")]


def parcel_of(subject: str, now: float) -> dict:
    state = next((name for name, pattern in PARCEL_STATES if re.search(pattern, subject or "", re.I)), "")
    product = re.search(r"[\"“”']([^\"“”']{2,80})[\"“”']", subject or "")
    return {"step": state, "product": product.group(1).strip().rstrip(".…") if product else "", "at": now} if state else {}


DEPLOY_STATES = [("failed", r"fail|error|could(?:n't| not) deploy|crashed"), ("live", r"ready|live|succeeded|successful|deployed|complete"),
                 ("deploy", r"deploying|in progress|started|promot"), ("build", r"build(?:ing)?|queued")]


def deploy_state(subject: str) -> str:
    return next((name for name, pattern in DEPLOY_STATES if re.search(pattern, subject or "", re.I)), "")


# The rules ------------------------------------------------------------------------------


def field(item: dict, key: str):
    return next((f.get("value") for f in item.get("fields", []) if f.get("key") == key), "")


def iso(at: float) -> str:
    return dt.datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds")


def epoch(value) -> float:
    try:
        return dt.datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def end_of(day: str) -> str:
    """A due day as the end of that day, local time."""
    try:
        moment = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(23, 59, 59)).astimezone()
    except (TypeError, ValueError):
        return ""
    return moment.isoformat(timespec="seconds")


def ago(at: float, now: float) -> str:
    gone = max(0, int(now - at))
    if gone < 90:
        return "just now"
    if gone < 3600:
        return f"{gone // 60} min ago"
    if gone < 86400:
        return f"{gone // 3600} h ago"
    return f"{gone // 86400} d ago"


def clock(at: float) -> str:
    return time.strftime("%H:%M", time.localtime(at)) if at else ""


def card_data(item: dict) -> dict:
    return item.get("card") if isinstance(item.get("card"), dict) else {}


def kind_of(item: dict) -> str:
    """Junco's own kind for the item (the v3 file's "kind" is a label)."""
    return str(item.get("jkind") or item.get("kind") or "")


RULES: list[tuple[str, callable]] = []


def rule(name: str):
    def register(build):
        RULES.append((name, build))
        return build
    return register


class Context:
    """What a rule may look at besides the item: a day of his calendar
    (courier_calendar.events_between by default), and whether Junco may
    answer invitations for an account (it never assumes so)."""

    def __init__(self, calendar=None, can_answer=None) -> None:
        self.calendar = calendar
        self.can_answer = can_answer or (lambda account: False)


def card(item: dict, now: float | None = None, calendar=None, can_answer=None) -> dict:
    """The item's v3 card: {component, lane, due, kind, title, subtitle,
    badge, symbol, sections, actions, original, intent, size}. `calendar`
    gives a day's events for an invite; `can_answer(account)` says whether
    Junco may answer its invitations (without it: no). The first rule that
    takes the item wins; Summary takes the rest."""
    now = now or time.time()
    context = Context(calendar, can_answer)
    for name, build in RULES:
        made = build(item, now, context)
        if made:
            made["rule"] = name
            return validate(made, item)
    return validate(summary(item, now), item)


def base(item: dict, component: str, lane: str, kind: str, title: str, intent: str, **extra) -> dict:
    made = {"component": component, "lane": lane, "kind": kind, "title": title, "intent": intent, "subtitle": "", "due": None,
            "badge": None, "symbol": "", "sections": [], "actions": [], "original": original(item)}
    made.update(extra)
    return made


def original(item: dict) -> dict | None:
    """The quiet link back to the source: the item's own page (GitHub's,
    the service's), else the email in Gmail on the web."""
    link = web(item.get("link", ""))
    source = plain(item.get("source") or "the source", 40)
    if link:
        return {"label": f"Original · {source}", "url": link}
    mail = (item.get("messages") or [""])[-1]
    email = item.get("account_email") or ""
    if mail and email:
        query = urllib.parse.quote(f"rfc822msgid:{mail.strip('<>')}", safe="")
        return {"label": f"Original email · {source}", "url": f"https://mail.google.com/mail/?authuser={urllib.parse.quote(email)}#search/{query}"}
    return None


def act(id_: str, label: str, type_: str, role: str = "secondary", icon: str = "", **extra) -> dict:
    action = {"id": id_, "label": label, "type": type_, "role": role}
    if icon:
        action["icon"] = icon
    action.update({key: value for key, value in extra.items() if value not in (None, "")})
    return action


# DecisionPanel: a yes/no only he can answer ---------------------------------------------

DEVICE = re.compile(r"\b(?:an? )?((?:Chrome|Firefox|Safari|Edge|Opera|Brave)(?: Mobile)?(?: on (?:Windows|macOS|Mac|Linux|Android|iOS))?"
                    r"|(?:Linux|Windows|Mac|macOS|Android|iOS|iPhone|iPad|Pixel|Samsung)\b(?: (?:laptop|phone|desktop|computer|tablet))?)")
PLACE = re.compile(r"(?:\b(?:Location|Where|Approximate location)\s*:\s*([A-Z][\w.'-]+(?: [A-Z][\w.'-]+)*(?:, ?[A-Z][\w.'-]+(?: [A-Z][\w.'-]+)*){0,2})"
                   r"|\b(?:from|in|near) ([A-Z][a-z]+(?: [A-Z][a-z]+)?(?:, ?[A-Z][a-z]+(?: [A-Z][a-z]+)?){1,2}))")
IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


@rule("security alert → DecisionPanel")
def decision(item: dict, now: float, context) -> dict | None:
    if kind_of(item) not in ("security-alert", "login"):
        return None
    brand = plain(field(item, "service") or item.get("source") or "your", 40)
    words = f"{field(item, 'notice')}\n{item.get('body', '')}"
    event = plain(field(item, "event") or "New sign-in", 40)
    device = plain(field(item, "device") or (DEVICE.search(words).group(1) if DEVICE.search(words) else ""), 40)
    found = PLACE.search(words)
    place = plain(field(item, "place") or ((found.group(1) or found.group(2)) if found else ""), 40)
    at = epoch(item.get("time"))
    facts = [{"icon": "computer", "label": "Device", "value": device} if device else None,
             {"icon": "schedule", "label": "When", "value": clock(at), "detail": ago(at, now)} if at else None,
             {"icon": "location_on", "label": "Where", "value": place, "detail": "Approximate"} if place else None,
             {"icon": "account_circle", "label": "Account", "value": plain(item.get("account") or "", 30).capitalize()}
             if item.get("account") else None]
    ip = IP.search(words)
    if ip and sum(1 for f in facts if f) < 3:
        facts.append({"icon": "lan", "label": "IP", "value": ip.group(1)})
    secure = web(card_data(item).get("secure", ""))
    actions = [act("its-me", "Yes, this was me", "command", "primary", "check", resolves=True)]
    if secure and on_domain(secure, item.get("domain", "")):
        actions.append(act("secure", "No, secure my account", "url", "danger", "lock", url=secure))
    title = f"{event} on {device}" if device and event.startswith("New") else event
    return base(item, "DecisionPanel", "action", "Security alert", title,
                f"{brand} saw a {event.lower()}; only he knows if it was him: confirm it, or secure the account.",
                symbol="shield", subtitle=brand,
                badge={"text": "Needs an answer", "icon": "gpp_maybe", "tone": "tertiary"},
                sections=[{"type": "question", "text": "Was this you?", "icon": "shield_person",
                           "detail": f"A {event.lower()} to your {brand} account."},
                          {"type": "facts", "items": [f for f in facts if f][:FACTS]}],
                actions=actions)


# GitHub: review, comment, CI --------------------------------------------------------------


def where(item: dict) -> dict:
    return item.get("github") if isinstance(item.get("github"), dict) else {}


def pr_label(item: dict) -> str:
    repo = plain(field(item, "repo"), 40)
    number = plain(field(item, "pr"), 12)
    return " ".join(part for part in (repo, number) if part)


@rule("review requested → ReviewPanel")
def review(item: dict, now: float, context) -> dict | None:
    if kind_of(item) != "review-requested":
        return None
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    who = plain(field(item, "who") or "", 40)
    sections = [{"type": "person", "name": who, "image": picture(item.get("image")), "detail": "asked for your review"}] if who else []
    ci = {"passing": "passed", "failing": "failed", "running": "running"}.get(meta.get("ci", ""))
    if ci:
        sections.append({"type": "status", "state": ci, "label": {"passed": "CI passing", "failed": "CI failing", "running": "CI running"}[ci]})
    if meta.get("base") and meta.get("head"):
        sections.append({"type": "branch", "base": plain(meta["base"], 40), "head": plain(meta["head"], 60)})
    if str(meta.get("additions", "")).isdigit() and str(meta.get("deletions", "")).isdigit():
        sections.append({"type": "size", "additions": int(meta["additions"]), "deletions": int(meta["deletions"])})
    stats = [{"icon": "description", "value": int(meta["files"]), "label": "files"} if str(meta.get("files", "")).isdigit() else None,
             {"icon": "commit", "value": int(meta["commits"]), "label": "commits"} if str(meta.get("commits", "")).isdigit() else None]
    if any(stats):
        sections.append({"type": "stats", "items": [s for s in stats if s]})
    files = item.get("files") if isinstance(item.get("files"), list) else []
    if files:
        sections.append({"type": "files", "items": [{"path": plain(f.get("path"), 120), "additions": int(f.get("additions") or 0),
                                                     "deletions": int(f.get("deletions") or 0)} for f in files[:FILES]],
                         "more": max(0, len(files) - FILES)})
    if item.get("body"):
        sections.append({"type": "text", "text": prose(item["body"], 1200)})
    actions = []
    if where(item).get("kind") == "pr":
        actions.append(act("approve", "Approve", "confirm", "primary", "check", hint="Click again to approve", resolves=True))
    link = web(item.get("link", ""))
    if link:
        actions.append(act("open", "Open PR", "url", "secondary", url=link))
    if where(item).get("number"):
        actions.append(act("comment", "Comment", "input", "quiet", "chat_bubble", hint="Comment on the PR"))
    title = plain(field(item, "pr-title") or item.get("title", ""), 90)
    return base(item, "ReviewPanel", "action", "Review request", title,
                f"{who or 'Someone'} asked for his review of {pr_label(item)}: read it, then approve or comment.",
                symbol="rate_review", subtitle=pr_label(item), sections=sections, actions=actions)


def diff_lines(context: dict) -> dict | None:
    """A review comment's last diff lines, numbered (the comment sits under
    the hunk's end): {file, lines: [{n, kind, text}]}."""
    hunk = [line for line in context.get("hunk") or [] if isinstance(line, str)]
    head = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", hunk[0]) if hunk else None
    if not head:
        return None
    old, new = int(head.group(1)), int(head.group(2))
    rows = []
    for line in hunk[1:]:
        mark, text = line[:1], line[1:]
        if mark == "+":
            rows.append({"n": new, "kind": "add", "text": text})
            new += 1
        elif mark == "-":
            rows.append({"n": old, "kind": "del", "text": text})
            old += 1
        else:
            rows.append({"n": new, "kind": "ctx", "text": text})
            old, new = old + 1, new + 1
    place = plain(context.get("file"), 100) + (f":{context['line']}" if isinstance(context.get("line"), int) and context["line"] else "")
    return {"type": "diff", "file": place, "lines": [{"n": r["n"], "kind": r["kind"], "text": plain(r["text"], 160)} for r in rows[-DIFF:]]}


@rule("PR comment → CommentPanel")
def comment(item: dict, now: float, context) -> dict | None:
    kind = kind_of(item)
    if kind not in ("comment", "issue-comment", "review-comment", "review", "commit-comment"):
        return None
    who = plain((field(item, "who") or "").split(",")[-1].strip(), 40)
    said = item.get("body") or field(item, "comment") or ""
    sections = [{"type": "person", "name": who, "image": picture(item.get("image"))}] if who else []
    context = item.get("context") if isinstance(item.get("context"), dict) else {}
    diff = diff_lines(context) if context else None
    if diff:
        sections.append(diff)
    if said:
        sections.append({"type": "comment", "text": prose(said, 4000)})
    thread = item.get("thread") if isinstance(item.get("thread"), list) else []
    if thread:
        names = list(dict.fromkeys(plain(t.get("who"), 40) for t in thread if isinstance(t, dict) and t.get("who")))
        faces = {plain(t.get("who"), 40): picture(t.get("avatar")) for t in thread if isinstance(t, dict)}
        sections.append({"type": "thread", "count": len(thread), "people": [{"name": n, "image": faces.get(n, "")} for n in names[:FACES]]})
    anchor = where(item).get("anchor")
    verdict = plain(field(item, "verdict"), 30)
    # An approval with nothing said is news, not a question.
    quiet = kind == "review" and not said.strip() and verdict.lower().startswith("approv")
    actions = []
    if anchor and not quiet:
        first = who.split()[0] if who and not who.startswith("@") else who
        actions.append(act("reply", "Reply", "input", "primary", "reply", hint=f"Reply to {first}" if first else "Reply"))
        if anchor in ("issue-comment", "review-comment"):
            actions.append(act("react-plus1", "+1", "command", "secondary", "thumb_up"))
        if anchor == "review-comment":
            actions.append(act("resolve-thread", "Resolve", "command", "secondary", "check", resolves=True))
    label = {"review-comment": "Review comment", "review": "Review"}.get(kind, "Comment")
    target = plain(context.get("file"), 60) if context.get("file") else plain(field(item, "pr-title"), 60)
    if kind == "review" and verdict:
        title = f"{who or 'Someone'} {verdict} {target}".strip()
    else:
        title = f"{who or 'Someone'} commented" + (f" on {target}" if target else "")
    intent = (f"{who or 'Someone'} approved {pr_label(item) or 'his PR'}: news, nothing to answer." if quiet else
              f"{who or 'Someone'} wrote to him on {pr_label(item) or 'GitHub'}; it wants an answer: reply, +1 or resolve.")
    return base(item, "CommentPanel", "update" if quiet else "action", label, title, intent,
                symbol="chat", subtitle=pr_label(item), sections=sections, actions=actions,
                badge={"text": "Approved", "icon": "check_circle", "tone": "success"} if quiet else None)


def job_states(item: dict) -> list[dict]:
    jobs = item.get("jobs") if isinstance(item.get("jobs"), list) else []
    if jobs:
        return [{"name": plain(j.get("name"), 60), "state": j.get("state") if j.get("state") in ("passed", "failed", "running") else "failed"}
                for j in jobs if isinstance(j, dict) and j.get("name")]
    found = card_data(item).get("jobs")
    if isinstance(found, list) and found:
        return [{"name": plain(j.get("name"), 60), "state": j.get("state", "failed")} for j in found if isinstance(j, dict)]
    failed = field(item, "jobs") or []
    return [{"name": plain(str(j).split(" · ")[0], 60), "state": "failed"} for j in (failed if isinstance(failed, list) else [failed])]


GENERIC = re.compile(r"Process completed with exit code \d+|exit status \d+$", re.I)


def failure_of(log: list) -> dict | None:
    """The failing step's one line that says what broke: GitHub's own error
    annotation ("##[error]…", the specific one before "Process completed with
    exit code 1"), else a test runner's failure (✗, FAIL, AssertionError…)."""
    lines = [str(line) for line in log or [] if isinstance(line, str)]

    def found(index: int, title: str) -> dict:
        rest = [l.strip() for l in lines[index + 1: index + 6] if l.strip() and not l.startswith(("──", "##["))]
        location = next((m.group(0) for l in [lines[index]] + rest for m in [re.search(r"[\w./-]+\.\w+:\d+(?::\d+)?", l)] if m), "")
        return {"type": "failure", "title": plain(title, 120), "detail": plain(rest[0], 160) if rest else "", "location": plain(location, 100)}

    errors = [(i, line.split("##[error]", 1)[1].strip()) for i, line in enumerate(lines) if "##[error]" in line]
    specific = [(i, text) for i, text in errors if text and not GENERIC.search(text)]
    if specific or errors:
        index, title = (specific or errors)[0]
        return found(index, title)
    for index, line in enumerate(lines):
        if line.startswith("──") or re.search(r"\b0 failed\b|warning", line, re.I):
            continue
        if re.search(r"✗|✕|×|\bFAIL(?:ED)?\b|AssertionError|\bError:|\bfailed\b", line, re.I):
            return found(index, line.strip(" ✗✕×"))
    return None


@rule("CI → StatusSummary")
def status(item: dict, now: float, context) -> dict | None:
    kind = kind_of(item)
    if kind not in ("ci-failed", "ci-passed"):
        return None
    failed = kind == "ci-failed"
    jobs = job_states(item)
    bad = sum(1 for j in jobs if j["state"] == "failed")
    label = (f"{bad} of {len(jobs)} jobs failed" if len(jobs) > bad else f"{bad} job{'s' if bad != 1 else ''} failed") if failed and jobs \
        else "Failed" if failed else f"All {len(jobs)} jobs passed" if jobs else "Passed"
    sections = [{"type": "status", "state": "failed" if failed else "passed", "label": label}]
    if jobs:
        sections.append({"type": "jobs", "items": jobs[:12]})
    log = item.get("log") if isinstance(item.get("log"), list) else []
    if failed:
        found = failure_of(log)
        if found:
            sections.append(found)
        shown = [line for line in log if isinstance(line, str) and not re.match(r"##\[(?:end)?group\]", line)]
        if shown:
            sections.append({"type": "log", "lines": [plain(line.replace("##[error]", "", 1), 200) for line in shown[-LOG:]]})
    at = epoch(item.get("updated") or item.get("time"))
    actions = []
    if failed and where(item).get("kind") == "run":
        actions.append(act("rerun-failed", "Re-run failed jobs", "command", "primary", "replay"))
    link = web(item.get("link", ""))
    if link:
        actions.append(act("open-run", "Open run", "url", "quiet", url=link))
    where_ = " · ".join(p for p in (plain(field(item, "repo"), 40), plain(field(item, "branch"), 50)) if p)
    workflow = plain(field(item, "workflow") or "CI", 40)
    return base(item, "StatusSummary", "action" if failed else "update", "CI", f"{workflow} {'failed' if failed else 'passed'}",
                f"{workflow} on {where_ or 'a branch'} {'failed: see which job, then re-run or fix it' if failed else 'is green again: nothing to do'}.",
                symbol="build", subtitle=where_, sections=sections, actions=actions,
                badge={"text": f"Failed {ago(at, now)}" if failed else "Passed", "icon": "error" if failed else "check_circle",
                       "tone": "error" if failed else "success"})


# Money: bills, statements, failed payments, renewals ---------------------------------------


def amount_section(data: dict, label: str) -> dict | None:
    if not isinstance(data.get("amount"), (int, float)) or data["amount"] <= 0:
        return None
    value = data["amount"]
    return {"type": "amount", "value": int(value) if float(value).is_integer() else round(float(value), 2),
            "currency": data.get("currency") or "INR", "label": label}


def day_words(day: str) -> str:
    try:
        return dt.date.fromisoformat(day).strftime("%-d %b")
    except (TypeError, ValueError):
        return ""


@rule("bill, statement, payment → DataTable")
def money_table(item: dict, now: float, context) -> dict | None:
    kind = kind_of(item)
    if kind not in ("bill", "payment-failed", "statement", "invoice", "domain-expiring"):
        return None
    data = card_data(item)
    brand = plain(field(item, "service") or item.get("source") or "", 40)
    merchant = plain(data.get("merchant") or field(item, "merchant") or brand, 40)
    due = data.get("due") or ""
    today = dt.date.fromtimestamp(now).isoformat()
    has_amount = isinstance(data.get("amount"), (int, float)) and data["amount"] > 0
    # An invoice with money and a day it's due, not a receipt, is a bill.
    owing = kind in ("bill", "payment-failed") or (kind in ("statement", "invoice") and has_amount and bool(due) and not data.get("paid"))
    renew = kind == "domain-expiring"
    rows = []
    if renew:
        rows += [{"label": "Domain", "value": plain(field(item, "domain"), 60), "mono": True} if field(item, "domain") else None,
                 {"label": "Expires", "value": plain(field(item, "expires") or day_words(due), 30), "tone": "tertiary"}]
    if due and owing:
        rows.append({"label": "Due", "value": day_words(due) + (" · today" if due == today else " · overdue" if due < today else ""),
                     "tone": "tertiary" if due <= today else ""})
    if data.get("minimum") and owing:
        rows.append({"label": "Minimum due", "value": plain(data["minimum"], 30)})
    if data.get("card") or field(item, "card"):
        rows.append({"label": "Account" if data.get("number") == "account" else "Card",
                     "value": f"•• {plain(data.get('card') or field(item, 'card'), 20).replace('ending ', '')}", "mono": True})
    if data.get("period"):
        rows.append({"label": "Period", "value": plain(data["period"], 60)})
    if merchant and merchant != brand:
        rows.append({"label": "From", "value": merchant})
    if not owing and not renew and epoch(item.get("time")):
        rows.append({"label": "Received", "value": dt.date.fromtimestamp(epoch(item.get("time"))).strftime("%-d %b")})
    rows = [r for r in rows if r and r.get("value")][:ROWS]
    hero = amount_section(data, {"bill": "Amount due", "payment-failed": "Payment failed", "statement": "Statement total" if owing else "Statement",
                                 "invoice": "Invoice", "domain-expiring": "Renewal"}[kind])
    sections = ([hero] if hero else []) + ([{"type": "table", "rows": rows}] if rows else [])
    actions = []
    pay = web(data.get("pay", ""))
    if pay and on_domain(pay, item.get("domain", "")) and (owing or renew):
        actions.append(act("pay", "Renew" if renew else "Pay now" if kind != "payment-failed" else "Fix payment", "url", "primary",
                           "open_in_new", url=pay))
    if owing or renew:
        actions.append(act("mark-paid", "Mark renewed" if renew else "Mark paid", "command", "secondary", "done", resolves=True))
    label = {"bill": "Bill", "payment-failed": "Payment failed", "statement": "Statement", "invoice": "Bill" if owing else "Invoice",
             "domain-expiring": "Renewal"}[kind]
    titles = {"bill": f"{merchant} bill due" if merchant else "Bill due", "payment-failed": f"Payment to {merchant} failed",
              "statement": f"{brand} statement",
              "invoice": f"{merchant or brand} invoice due" if owing else f"{brand} auto-renewal" if data.get("auto") else
              f"{brand} renewal confirmed" if re.search(r"renew", field(item, "notice") or "", re.I) else
              f"{merchant or brand} receipt" if data.get("paid") else f"{merchant or brand} invoice",
              "domain-expiring": f"{plain(field(item, 'domain'), 60) or brand} expires"}
    intents = {"bill": "a bill is due: pay it at the bank or service, or mark it paid",
               "payment-failed": "a payment failed: fix it at the service before it lapses",
               "statement": "a statement arrived" + (": pay what's due by the due date" if owing else ": nothing to do unless something looks wrong"),
               "invoice": "an invoice is open: pay it by the due day, or mark it paid" if owing else "an invoice or receipt arrived: nothing to do",
               "domain-expiring": "something expires: renew it or let it go"}
    lane = "action" if owing or renew else "update"
    return base(item, "DataTable", lane, label, titles[kind], f"{merchant or brand}: {intents[kind]}.",
                symbol={"payment-failed": "credit_card_off", "domain-expiring": "language"}.get(kind, "receipt_long"),
                subtitle=brand if merchant and merchant != brand else "", sections=sections, actions=actions,
                due=end_of(due) if due and lane == "action" else None,
                badge={"text": "Failed", "icon": "error", "tone": "error"} if kind == "payment-failed" else None)


# SchedulingPanel: a calendar invite ------------------------------------------------------


def events_that_day(start: dt.datetime, calendar) -> list[dict]:
    if calendar is None:
        import courier_calendar

        calendar = courier_calendar.events_between
    day = start.date()
    try:
        return list(calendar(day, day + dt.timedelta(days=1)))
    except Exception:  # noqa: BLE001 - no calendar copy: the strip shows only the invite
        return []


@rule("calendar invite → SchedulingPanel")
def scheduling(item: dict, now: float, context) -> dict | None:
    if kind_of(item) != "invite":
        return None
    invite = card_data(item).get("invite") if isinstance(card_data(item).get("invite"), dict) else {}
    try:
        start = dt.datetime.fromisoformat(invite["start"])
        end = dt.datetime.fromisoformat(invite.get("end") or invite["start"])
    except (KeyError, TypeError, ValueError):
        return None
    sections = [{"type": "when", "start": start.isoformat(), "end": end.isoformat()}]
    organizer = invite.get("organizer") or {}
    if organizer.get("name") or organizer.get("email"):
        sections.append({"type": "person", "name": plain(organizer.get("name") or organizer.get("email"), 50), "detail": "invited you"})
    clashes, events = [], []
    response = invite.get("response", "")
    # The event on his calendar (Google's page for it, to answer there).
    page = web(item.get("link", "")) if item.get("demo") else ""
    if not invite.get("all_day"):
        # A made-up invite (courier-notify demo) brings its own day.
        day = invite["events"] if isinstance(invite.get("events"), list) else events_that_day(start, context.calendar)
        for event in day:
            if invite.get("uid") and event.get("uid") == invite.get("uid"):
                response = event.get("response") or response  # his answer, as his calendar has it
                page = web(event.get("link", "")) or page
                continue
            if event.get("allDay") or event.get("kind") == "birthday":
                continue
            try:
                e_start, e_end = dt.datetime.fromisoformat(event["start"]), dt.datetime.fromisoformat(event["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if invite.get("title") and event.get("title") == invite.get("title") and e_start == start:
                continue  # the invite itself, on his calendar already
            events.append({"title": plain(event.get("title"), 60), "start": e_start.isoformat(), "end": e_end.isoformat()})
            if e_start < end and e_end > start:
                clashes.append(plain(event.get("title"), 40))
        hours = [start.hour, end.hour + (1 if end.minute else 0)] + [dt.datetime.fromisoformat(e["start"]).hour for e in events] \
            + [dt.datetime.fromisoformat(e["end"]).hour + (1 if dt.datetime.fromisoformat(e["end"]).minute else 0) for e in events]
        low, high = max(0, min(min(hours), start.hour - 2)), min(24, max(max(hours) + 1, end.hour + 2))
        sections.append({"type": "day", "from": low, "to": max(high, low + 4), "events": events[:8]})
    people = [p for p in invite.get("attendees") or [] if isinstance(p, dict)]
    if people:
        sections.append({"type": "people", "summary": f"{len(people)} invited",
                         "people": [{"name": plain(p.get("name") or p.get("email"), 40)} for p in people[:FACES]]})
    place = invite.get("conference") or invite.get("where") or ""
    if place:
        meet = bool(re.search(r"meet\.google|zoom\.us|teams\.microsoft|google meet|\bzoom\b|\bteams\b", place, re.I))
        sections.append({"type": "place", "kind": "meet" if meet else "place",
                         "label": "Google Meet" if "meet.google" in place else "Zoom" if "zoom.us" in place else
                         "Microsoft Teams" if "teams.microsoft" in place else plain(place, 60)})
    answered = response in ("accepted", "declined", "tentative")
    writable = bool(context.can_answer(invite.get("account", "")))
    if answered:
        actions = []
    elif writable:
        actions = [act("accept", "Accept", "command", "primary", "check", resolves=True),
                   act("maybe", "Maybe", "command", "secondary", "help"),
                   act("decline", "Decline", "command", "secondary", "close", resolves=True)]
    else:
        # Junco may only read his calendar: the answer happens on Google's
        # own page for the event (no button that would fail).
        actions = [act("answer-in-calendar", "Answer in Google Calendar", "url", "primary", "event", url=page)] if page else []
    badge = {"text": f"Clashes with {clashes[0]}" + (f" +{len(clashes) - 1}" if len(clashes) > 1 else ""), "icon": "event_busy",
             "tone": "tertiary"} if clashes else {"text": "You're free then", "icon": "event_available", "tone": "success"} if not invite.get("all_day") else None
    if answered:
        badge = {"text": {"accepted": "You said yes", "declined": "You said no", "tentative": "You said maybe"}[response],
                 "icon": "event_available", "tone": "primary"}
    who = plain(organizer.get("name") or organizer.get("email") or "Someone", 40)
    return base(item, "SchedulingPanel", "update" if answered else "action", "Invitation", plain(invite.get("title") or "Invitation", 90),
                f"{who} invited him to a meeting" + (f" that clashes with {clashes[0]}" if clashes else "")
                + (": accept, maybe or decline." if writable else ": answer it in Google Calendar (Junco may only read his calendar)."),
                symbol="event", subtitle=start.strftime("%a %-d %b · %H:%M") + f"–{end.strftime('%H:%M')}", sections=sections,
                actions=actions, badge=badge, due=start.isoformat(), clashes=clashes)


# Timeline: parcels and deploys ------------------------------------------------------------


@rule("parcel, deploy → Timeline")
def timeline(item: dict, now: float, context) -> dict | None:
    kind = kind_of(item)
    data = card_data(item)
    if kind == "parcel":
        seen = data.get("steps") if isinstance(data.get("steps"), dict) else {}
        order = [name for name, _ in PARCEL_STEPS]
        reached = max((order.index(s) for s in seen if s in order), default=-1)
        steps = [{"label": label, "state": "done" if i < reached or (i == reached and name == "delivered") else "current" if i == reached
                  else "pending", **({"at": iso(seen[name])} if name in seen else {})} for i, (name, label) in enumerate(PARCEL_STEPS)]
        state = order[reached] if reached >= 0 else ""
        product = plain(data.get("product") or "Your order", 70)
        badge = {"delivered": ("Delivered", "inventory_2", "success"), "out": ("Out for delivery", "local_shipping", "primary"),
                 "shipped": ("Shipped", "local_shipping", "primary"), "ordered": ("Ordered", "shopping_bag", "tertiary")}.get(state)
        return base(item, "Timeline", "update", "Parcel", product, f"A parcel from {plain(item.get('source'), 30)} moved on: nothing to do"
                    + (", it's here." if state == "delivered" else " until it arrives."), symbol="package_2",
                    subtitle=plain(item.get("source"), 40), sections=[{"type": "steps", "items": steps}],
                    badge={"text": badge[0], "icon": badge[1], "tone": badge[2]} if badge else None)
    if kind == "deploy" or (kind == "incident" and data.get("step") == "failed" and re.search(r"deploy|build", field(item, "event") or "", re.I)):
        seen = data.get("steps") if isinstance(data.get("steps"), dict) else {}
        order = ["build", "deploy", "live"]
        failed = "failed" in seen
        reached = max((order.index(s) for s in seen if s in order), default=0)
        steps = []
        for i, name in enumerate(order):
            state = "done" if i < reached or (name == "live" and "live" in seen) else ("failed" if failed else "current") if i == reached else "pending"
            steps.append({"label": name.capitalize(), "state": state, **({"at": iso(seen[name])} if name in seen else {})})
        return base(item, "Timeline", "action" if failed else "update", "Deploy", plain(field(item, "event") or item.get("title"), 90),
                    f"A deploy at {plain(item.get('source'), 30)} " + ("failed: look at the build." if failed else "moved on: nothing to do."),
                    symbol="rocket_launch", subtitle=plain(item.get("source"), 40), sections=[{"type": "steps", "items": steps}],
                    badge={"text": "Failed", "icon": "error", "tone": "error"} if failed else
                    {"text": "Live", "icon": "check_circle", "tone": "success"} if "live" in seen else None)
    return None


# Summary: everything else -----------------------------------------------------------------


FACT_ICONS = {"device": "computer", "place": "location_on", "at": "schedule", "when": "schedule", "amount": "payments", "domain": "language",
              "expires": "event", "merchant": "storefront", "card": "credit_card", "event": "info", "who": "person", "repo": "folder"}


def summary(item: dict, now: float) -> dict:
    words = item.get("summary") or field(item, "notice") or ""
    facts = [{"icon": FACT_ICONS.get(f.get("key"), "info"), "label": plain(f.get("label"), 20), "value": plain(f.get("value"), 40)}
             for f in item.get("fields", []) if isinstance(f, dict) and isinstance(f.get("value"), str)
             and f.get("key") not in ("service", "notice", "comment", "count") and 0 < len(f["value"]) <= 40][:FACTS]
    sections = ([{"type": "facts", "items": facts}] if facts else []) + ([{"type": "text", "text": prose(words, 600)}] if words else [])
    return base(item, "Summary", "update", plain(item.get("source") or "Update", 30), plain(item.get("title"), 90),
                f"News from {plain(item.get('source'), 30) or 'a sender'}: nothing to do but read it.", symbol="notifications",
                subtitle=plain(words, 90), sections=sections)


# Checking a card against the vocabulary --------------------------------------------------


def clean(value, key: str = "", written: bool = False):
    """Every string in a section plain text ("text" of a comment or text
    section keeps its lines, inert), pictures file:// only, numbers and
    flags as they are; anything else dropped."""
    if isinstance(value, dict):
        return {k: clean(v, k, written) for k, v in value.items() if isinstance(k, str)}
    if isinstance(value, list):
        return [clean(v, key, written) for v in value[:40]]
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if key in ("image", "avatar"):
            return picture(value)
        return prose(value, 4000) if written and key == "text" else plain(value, 200)
    return None


def validate(made: dict, item: dict) -> dict:
    """The card as the contract allows it: a known component (else
    Summary), only the sections it reads (capped), plain text, file://
    pictures, http(s) links, at most 3 known actions. Whatever a rule (or,
    later, a model) proposes passes through here."""
    component = made.get("component") if made.get("component") in COMPONENTS else "Summary"
    sections = []
    for section in made.get("sections") or []:
        if not isinstance(section, dict) or section.get("type") not in READS[component]:
            continue
        section = clean(section, written=section["type"] in ("comment", "text"))
        if section["type"] == "facts":
            section["items"] = [{k: v for k, v in dict(f, value=plain(f.get("value"), 40), label=plain(f.get("label"), 20),
                                                        detail=plain(f.get("detail"), 40)).items() if v != ""}
                                for f in section.get("items", []) if isinstance(f, dict) and f.get("value")][:FACTS]
            if not section["items"]:
                continue
        if section["type"] == "table":
            section["rows"] = section.get("rows", [])[:ROWS]
        if section["type"] in ("person",):
            section["image"] = picture(section.get("image"))
            if not section["image"]:
                section.pop("image")
        if section["type"] in ("people", "thread"):
            for person in section.get("people", []):
                if not picture(person.get("image")):
                    person.pop("image", None)
        if section.get("tone") not in TONES:
            section.pop("tone", None)
        sections.append(section)
    actions = []
    for action in made.get("actions") or []:
        if not isinstance(action, dict) or action.get("type") not in TYPES or not action.get("id"):
            continue
        if action["type"] == "url" and not web(action.get("url")):
            continue
        action = dict(action, label=plain(action.get("label"), 30))
        if action.get("role") not in ROLES:
            action.pop("role", None)
        actions.append(action)
    made.update(component=component, sections=sections, actions=actions[:ACTIONS], size=SIZES[component],
                title=plain(made.get("title"), 90), subtitle=plain(made.get("subtitle"), 90), kind=plain(made.get("kind"), 30))
    badge = made.get("badge")
    made["badge"] = {"text": plain(badge.get("text"), 40), "icon": plain(badge.get("icon"), 30),
                     "tone": badge.get("tone") if badge.get("tone") in TONES else ""} if isinstance(badge, dict) and badge.get("text") else None
    found = made.get("original")
    made["original"] = {"label": plain(found.get("label"), 50), "url": found["url"]} if isinstance(found, dict) and web(found.get("url")) else None
    if made.get("lane") not in ("action", "update"):
        made["lane"] = "update"
    return made


# The feed's v3 item ----------------------------------------------------------------------

# Keys a v3 file carries for the dock; the item's own (Junco's) stay beside them.
V3_KEYS = ("component", "lane", "due", "subtitle", "badge", "symbol", "sections", "original")
# Keys whose meaning differs in v3: Junco's own value is kept as "j" + key.
SHADOWED = ("kind", "title")


# The dock's own (contract v3): kept off the card's buttons, run by its Open
# in Junco and Mark read (which marks the mail read and lets the item go).
DOCK_OWNED = [{"id": "open-junco", "label": "Open in Junco", "type": "command"},
              {"id": "mark-read", "label": "Mark read", "type": "command", "resolves": True}]


def v3_item(item: dict, now: float | None = None, calendar=None, can_answer=None) -> dict:
    """The item as a version-3 feed writes it: Junco's own keys (so it reads
    it back), its card's keys, and its actions in v3 form: the card's own
    (at most 3), then the dock's Open in Junco and Mark read."""
    made = card(item, now, calendar, can_answer)
    out = dict(item)
    for key in SHADOWED:
        out["j" + key] = item.get(key, "")
    out.update({key: made.get(key) for key in V3_KEYS})
    out.update(kind=made["kind"], title=made["title"], actions=made["actions"] + [dict(a) for a in DOCK_OWNED])
    return out


def from_v3(item: dict) -> dict:
    """A v3 file's item back as Junco keeps it."""
    for key in SHADOWED:
        if "j" + key in item:
            item[key] = item.pop("j" + key)
    for key in V3_KEYS:
        item.pop(key, None)
    return item
