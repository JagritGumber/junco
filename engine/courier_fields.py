"""Fields taught by example, in mail made from a template (a prototype).

You open an automated email (a GitHub notification, say), add a field such as
"repo" or "PR number" and select its text in the email. From one or two
emails taught like that, Courier learns where each field sits in that
template and reads it out of every other email made from the same template.
This is wrapper induction: the template's fixed parts (its markup and the
words it always says) are landmarks, and a field is found by its place
among them.

Offline and read-only: this reads the email it is handed and nothing else.
docs/teach-fields.md has the design and the measurements on real mail.

- sanitize() gives the email's HTML as the reader draws it (courier_html's
  cleaner, without fetching images), and Page parses it into a small tree of
  elements and text pieces ("leaves") in reading order. Each leaf knows its
  path of tags and classes, the link it sits in and its place in the text.
- map_selection() turns a selection in the reader (offsets in the text Qt
  lays out) into offsets in the Page, by lining up the characters that show.
- fingerprint() and templates() say which template an email is made from:
  its sender, the frame of its subject, the skeleton of its header and
  footer, and the words its subjects always say.
- Template.learn() turns taught examples into one Extractor per field: the
  leaf's path (with what differs between examples, and rows, left open),
  anchors for the text just before and after the value inside its leaf, the
  value's shape, and the nearest fixed text before it. The template's other
  emails, untaught, say which text is fixed and which anchors and shape
  hold across it, so one example is often enough.
- Template.extract() reads another email: each field's value (a list for a
  field that repeats) and a verdict. A field that can't be found where it
  should be is missing, and an email whose required fields are missing, or
  that doesn't say what the template always says, is flagged for teaching
  again, never guessed at.
- TextPage reads plain-text email the same way, one leaf per line (lines a
  mail program wrapped joined again).
"""

from __future__ import annotations

import dataclasses
import hashlib
import html
import html.parser
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

# ---------------------------------------------------------------------------
# The email as the reader shows it


def sanitize(markup: str) -> str:
    """The email's HTML as courier_html makes it for the reader, each image
    left as a bare <img> (nothing is fetched or written). Mirrors
    courier_html.designed() up to its image step; a real version would share
    that code rather than copy it."""
    import courier_html as ch

    body = markup.replace("\x00", "")
    body = re.sub(r"<!--\[if[^\]]*\]>.*?<!\[endif\]-->", "", body, flags=re.S | re.I)
    css = ch.safe_css("\n".join(ch.clean_css(block) for block in ch.style_blocks(body)))
    cleaner = ch._Cleaner(ch.hidden_classes(css))
    try:
        cleaner.feed(body)
        cleaner.close()
    except (AssertionError, ValueError):
        pass
    if cleaner.button:
        cleaner.out.append("</td></tr></table>")
    cleaner.out.extend(["</pre></td></tr></table>"] * cleaner.pre + ["</td></tr></table></td></tr></table>"] * cleaner.quotes)
    content = "".join(cleaner.out).strip()
    return re.sub(r"\x00\d+\x00", "<img>", content)


VOID = {"br", "img", "hr", "meta", "link", "input", "col", "area", "base", "wbr", "source"}
BLOCK = {"address", "blockquote", "center", "dd", "div", "dl", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li",
         "ol", "p", "pre", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul", "br"}
INLINE = {"a", "b", "big", "cite", "code", "del", "dfn", "em", "font", "i", "kbd", "nobr", "s", "samp", "small", "span",
          "strong", "sub", "sup", "tt", "u", "var"}
# Opening one of these closes a <p> still open around it, as a browser does.
CLOSES_P = BLOCK - {"br", "td", "th", "tr", "tbody", "thead", "tfoot", "li", "dd", "dt"}
# Tags that close an open one of their kind, but never past their container.
IMPLIED = {
    "li": ({"li"}, {"ul", "ol"}),
    "dt": ({"dt", "dd"}, {"dl"}),
    "dd": ({"dt", "dd"}, {"dl"}),
    "tr": ({"tr", "td", "th"}, {"table", "tbody", "thead", "tfoot"}),
    "td": ({"td", "th"}, {"tr", "table"}),
    "th": ({"td", "th"}, {"tr", "table"}),
    "tbody": ({"tr", "td", "th", "tbody", "thead", "tfoot"}, {"table"}),
    "thead": ({"tr", "td", "th", "tbody", "thead", "tfoot"}, {"table"}),
    "tfoot": ({"tr", "td", "th", "tbody", "thead", "tfoot"}, {"table"}),
}


class Element:
    __slots__ = ("tag", "attrs", "parent", "children")

    def __init__(self, tag: str, attrs: dict[str, str], parent: Element | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        # Elements and strings, in order.
        self.children: list[Element | str] = []

    @property
    def sig(self) -> str:
        """Tag and classes: what a step of a path is made of. A modifier
        class (BEM's "Label--orange", "Label--danger") says what state or
        colour a thing is in, which is often the value itself (High vs
        Critical), so it doesn't count."""
        classes = sorted({name for name in self.attrs.get("class", "").split() if "--" not in name})
        return ".".join([self.tag, *classes])


class _Builder(html.parser.HTMLParser):
    """A forgiving tree builder: unclosed <p>, <li>, <tr> and <td> close
    where a browser would close them, and a stray end tag is ignored."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#root", {}, None)
        self.stack = [self.root]

    def _close_to(self, index: int) -> None:
        del self.stack[index:]

    def _implied(self, tag: str) -> None:
        if tag in IMPLIED:
            closes, container = IMPLIED[tag]
            for index in range(len(self.stack) - 1, 0, -1):
                current = self.stack[index].tag
                if current in container:
                    break
                if current in closes:
                    self._close_to(index)
                    break
        if tag in CLOSES_P:
            for index in range(len(self.stack) - 1, 0, -1):
                current = self.stack[index].tag
                if current == "p":
                    self._close_to(index)
                    break
                if current not in INLINE:
                    break

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._implied(tag)
        element = Element(tag, {name.lower(): value or "" for name, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(element)
        if tag not in VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._implied(tag)
        self.stack[-1].children.append(Element(tag, {name.lower(): value or "" for name, value in attrs}, self.stack[-1]))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self._close_to(index)
                return

    def handle_data(self, data: str) -> None:
        children = self.stack[-1].children
        if children and isinstance(children[-1], str):
            children[-1] += data
        else:
            children.append(data)


def parse(markup: str) -> Element:
    builder = _Builder()
    try:
        builder.feed(markup)
        builder.close()
    except (AssertionError, ValueError):
        pass
    return builder.root


Step = tuple[str, int]  # (tag.classes, which one of that kind among its siblings)
Path = tuple[Step, ...]


@dataclass(eq=False)
class Leaf:
    """A piece of text between tags, as shown (whitespace collapsed)."""

    text: str
    path: Path
    # Which text piece of its element this is (0 for the first).
    slot: int
    # The link it sits in, if any.
    href: str
    # Where it starts in the page's text, and its number in reading order.
    start: int
    number: int
    # Whether it sits inside <pre>, where whitespace is kept.
    pre: bool = False

    @property
    def end(self) -> int:
        return self.start + len(self.text)

    @property
    def key(self) -> tuple[Path, int]:
        return self.path, self.slot


WHITESPACE = re.compile(r"[ \t\r\n\f\u200b\u200c\u200d\ufeff\u00ad\u034f]+")
INVISIBLE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00ad\u034f]")


def collapse(text: str) -> str:
    return WHITESPACE.sub(" ", text)


class Page:
    """An email's HTML as a tree, and its text pieces in reading order.
    `text` is the page's text: the leaves joined, with a line break where a
    block (paragraph, cell, row, line break) ends."""

    def __init__(self, markup: str) -> None:
        self.root = parse(markup)
        self.leaves: list[Leaf] = []
        parts: list[str] = []
        self._length = 0
        self._walk(self.root, (), "", False, parts)
        self.text = "".join(parts)

    def _emit(self, parts: list[str], piece: str) -> None:
        parts.append(piece)
        self._length += len(piece)

    def _walk(self, element: Element, path: Path, href: str, pre: bool, parts: list[str]) -> None:
        seen: Counter[str] = Counter()
        slot = 0
        for child in element.children:
            if isinstance(child, str):
                text = INVISIBLE.sub("", child) if pre else collapse(INVISIBLE.sub("", child))
                if not text.strip():
                    if text and parts and not parts[-1].endswith((" ", "\n")):
                        self._emit(parts, " ")
                    continue
                if not pre and parts and parts[-1].endswith((" ", "\n")) and text.startswith(" "):
                    text = text[1:]
                leaf = Leaf(text, path, slot, href, self._length, len(self.leaves), pre)
                self.leaves.append(leaf)
                self._emit(parts, text)
                slot += 1
                continue
            step = (child.sig, seen[child.sig])
            seen[child.sig] += 1
            link = child.attrs.get("href", "") if child.tag == "a" else href
            if child.tag in BLOCK and parts and not parts[-1].endswith("\n"):
                self._emit(parts, "\n")
            self._walk(child, path + (step,), link or href, pre or child.tag == "pre", parts)
            if child.tag in BLOCK and parts and not parts[-1].endswith("\n"):
                self._emit(parts, "\n")

    def leaf_at(self, offset: int) -> Leaf | None:
        """The leaf holding the page-text character at `offset`."""
        low, high = 0, len(self.leaves) - 1
        while low <= high:
            middle = (low + high) // 2
            leaf = self.leaves[middle]
            if offset < leaf.start:
                high = middle - 1
            elif offset >= leaf.end:
                low = middle + 1
            else:
                return leaf
        return None


# Marks Qt puts in a document's text that don't show: an image (U+FFFC),
# line and paragraph breaks, a no-break space, and where a table's frame
# begins and ends (U+FDD0 and U+FDD1: QTextBeginningOfFrame, QTextEndOfFrame).
QT_MARKS = "\ufffc\u2028\u2029\u00a0\ufdd0\ufdd1"


def _visible(text: str) -> tuple[str, list[int]]:
    """The characters that show (no whitespace, no image, paragraph or
    table marks), and where each one is in `text`."""
    chars, where = [], []
    for index, char in enumerate(text):
        if not char.isspace() and char not in QT_MARKS:
            chars.append(char)
            where.append(index)
    return "".join(chars), where


def map_selection(page: Page, shown: str, start: int, end: int) -> tuple[int, int] | None:
    """A selection in the reader, as offsets into page.text. `shown` is the
    text Qt lays out (TextEdit.getText(0, length)) and start/end are
    TextEdit.selectionStart/End. Qt lays the same HTML out with its own
    whitespace, paragraph breaks and a mark per image, but the characters
    that show are the same ones in the same order, so they are matched one
    by one; where they differ (an image's description shown instead of the
    image), difflib lines up the rest. None when the selection falls where
    the two don't match."""
    import difflib

    if end <= start:
        return None
    a, a_at = _visible(shown)
    b, b_at = _visible(page.text)
    first = next((n for n, index in enumerate(a_at) if index >= start), None)
    last = next((n for n in range(len(a_at) - 1, -1, -1) if a_at[n] < end), None)
    if first is None or last is None or last < first:
        return None
    if a == b:
        return b_at[first], b_at[last] + 1
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    mapped = {}
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            mapped[block.a + k] = block.b + k
    if first not in mapped or last not in mapped:
        return None
    return b_at[mapped[first]], b_at[mapped[last]] + 1


# ---------------------------------------------------------------------------
# Which template an email is made from


def skeleton(element: Element) -> str:
    """The markup with its text taken out: tags and classes only. A run of
    siblings of one kind (rows of a list or table) is written once, as the
    first of them, so one commit or five, one failed job or six, give the
    same skeleton."""
    parts: list[str] = []
    previous = None
    for child in element.children:
        if isinstance(child, str):
            if not child.strip():
                continue
            kind, token = "t", "t"
        else:
            kind = child.sig
            token = kind + ("(" + skeleton(child) + ")" if child.children else "")
        if kind == previous:
            continue
        parts.append(token)
        previous = kind
    return " ".join(parts)


def layout(page: Page) -> str:
    """The skeleton of an email's first and last blocks, its header and its
    footer. What lies between is often what someone wrote (a comment, a
    review) and changes every time; the header and footer are the
    template's own. A designed email that is one big table is all of it."""
    blocks = [child for child in page.root.children
              if isinstance(child, Element) and (child.children or child.tag in {"hr", "img"})]
    if not blocks:
        return ""

    def one(element: Element) -> str:
        return element.sig + ("(" + skeleton(element) + ")" if element.children else "")

    return one(blocks[0]) if len(blocks) == 1 else one(blocks[0]) + " … " + one(blocks[-1])


SUBJECT_NOISE = re.compile(r"^(?:(?:re|fwd?|aw|sv)\s*:\s*)+", re.I)
TRAILER = re.compile(r"\(([^()]*)\)\s*$")


def mask(text: str) -> str:
    """Hashes as h and numbers as 0."""
    text = re.sub(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b", "h", text)
    return re.sub(r"\d+", "0", text)


def subject_parts(subject: str) -> tuple[str, str, str]:
    """A subject's [tag], its middle and its trailing (…), without Re:."""
    subject = SUBJECT_NOISE.sub("", collapse(subject).strip())
    tag = trailer = ""
    match = re.match(r"\[[^\]]*\]\s*", subject)
    if match:
        tag, subject = match.group(0).strip(), subject[match.end():]
    match = TRAILER.search(subject)
    if match:
        trailer, subject = match.group(1), subject[:match.start()].rstrip()
    return tag, subject, trailer


def subject_frame(subject: str) -> str:
    """What every subject of a template shares: a leading [tag] or not, and
    the shape of a short trailing (…) such as (PR #0) or (h). The middle,
    often a title, is … here; subject_labels() finds the words a
    template's middles always say."""
    tag, _, trailer = subject_parts(subject)
    frame = "[*] …" if tag else "…"
    if trailer:
        shape = mask(trailer)
        frame += f" ({shape if len(shape.split()) <= 2 else '…'})"
    return frame


def words_pattern(texts: list[str], keep: float = 0.8) -> str:
    """The words said in at least `keep` of the texts, with * for every
    stretch of other words, as most of them have it."""
    split = [text.split() for text in texts]
    counts = Counter(word for words in split for word in set(words))
    fixed = {word for word, n in counts.items() if n >= keep * len(texts)}
    shapes: Counter[str] = Counter()
    for words in split:
        out: list[str] = []
        for word in words:
            token = word if word in fixed else "*"
            if not (token == "*" and out and out[-1] == "*"):
                out.append(token)
        shapes[" ".join(out)] += 1
    return shapes.most_common(1)[0][0] if shapes else ""


def subject_labels(subjects: list[str], threads: list[str] | None = None) -> list[str]:
    """Each subject's template, within emails of one layout. When their
    middles share fixed words ("Run failed: * - *"), that pattern is the
    template. When they share none, either each is a title (a PR's, an
    issue's) or the layout is a generic one carrying several notices
    ("A third-party OAuth application has been added…", "Payment
    receipt…"); a middle said word for word in 3 or more threads is a
    notice of its own, and the rest are titles."""
    middles = [mask(subject_parts(subject)[1]) for subject in subjects]
    threads = threads or subjects
    labels: list[str | None] = [None] * len(subjects)
    remaining = list(range(len(subjects)))
    while len(remaining) >= 3:
        pattern = words_pattern([middles[n] for n in remaining])
        # A word only counts as the template's when it's said across
        # threads: one PR's title repeated in its own thread isn't.
        fixed = [word for word in pattern.split() if word != "*"
                 and len({threads[n] for n in remaining if word in middles[n].split()}) >= 3]
        members = [n for n in remaining if fixed and all(word in middles[n].split() for word in fixed)]
        if len(members) < 3:
            break
        for n in members:
            labels[n] = pattern
        remaining = [n for n in remaining if labels[n] is None]
    seen: dict[str, set[str]] = {}
    for n in remaining:
        seen.setdefault(middles[n], set()).add(threads[n])
    for n in remaining:
        labels[n] = middles[n] if len(seen[middles[n]]) >= 3 else "*"
    return [label or "*" for label in labels]


def sender_of(address: str) -> str:
    """The address in a From header, lowercased (the display name may hold
    an @ of its own)."""
    import email.utils

    return email.utils.parseaddr(address or "")[1].lower()


def fingerprint(sender: str, subject: str, page: Page | None) -> str:
    """Which layout an email is made from: its sender, its subject's frame
    and the skeleton of its header and footer (or "text" for plain text)."""
    body = layout(page) if page is not None and not isinstance(page, TextPage) else "text"
    return f"{sender_of(sender)}|{subject_frame(subject)}|{hashlib.sha1(body.encode()).hexdigest()[:10]}"


@dataclass(eq=False)
class Email:
    """What the learner reads of one email."""

    sender: str
    subject: str
    html: str = ""
    text: str = ""
    thread: str = ""
    _page: Page | None = field(default=None, repr=False)

    @property
    def page(self) -> Page:
        """The HTML as the reader shows it, or the text when there's no HTML."""
        if self._page is None:
            self._page = Page(sanitize(self.html)) if self.html.strip() else TextPage(self.text)
        return self._page

    @property
    def text_page(self) -> TextPage:
        return TextPage(self.text)


def templates(emails: list[Email]) -> dict[str, list[int]]:
    """Emails grouped by template: by fingerprint, then by subject_labels.
    Keys are "sender|frame|layout|subject pattern"."""
    groups: dict[str, list[int]] = {}
    for number, mail in enumerate(emails):
        groups.setdefault(fingerprint(mail.sender, mail.subject, mail.page), []).append(number)
    out: dict[str, list[int]] = {}
    for key, members in groups.items():
        labels = subject_labels([emails[n].subject for n in members], [emails[n].thread or emails[n].subject for n in members])
        for number, label in zip(members, labels):
            out.setdefault(f"{key}|{label}", []).append(number)
    return out


# ---------------------------------------------------------------------------
# Fixed text: what a template always says


def text_shape(text: str) -> str:
    """Text with what changes between emails of a template written as a
    class (numbers 0, hashes h), and a noun after a number made singular,
    so "pushed 1 commit." and "pushed 3 commits." read the same."""
    text = mask(collapse(text).strip())
    text = re.sub(r"\b0 (\w+?)ies\b", r"0 \1y", text)
    return re.sub(r"\b0 (\w+?)s\b", r"0 \1", text)


def fixed_texts(pages: Iterable[Page], share: float = 0.5) -> dict[str, float]:
    """The text pieces a template says in at least `share` of its emails,
    with how often: its landmarks."""
    counts: Counter[str] = Counter()
    total = 0
    for page in pages:
        total += 1
        counts.update({text_shape(leaf.text) for leaf in page.leaves})
    if not total:
        return {}
    return {text: n / total for text, n in counts.items() if text and n / total >= share}


# ---------------------------------------------------------------------------
# Learning fields from examples


@dataclass
class Taught:
    """One field taught on one email. In the reader, `start` and `end` are
    the selection's offsets in the page's text; without them, `value`'s
    first appearance (after the text `after`, when given) stands in for
    the selection. A `link` field is the address of the link selected; a
    `many` field repeats (rows of a list or table); a `subject` field is
    selected in the subject line."""

    name: str
    value: str = ""
    start: int | None = None
    end: int | None = None
    after: str = ""
    link: bool = False
    many: bool = False
    subject: bool = False


SHAPES = [
    r"\d+",
    r"#\d+",
    r"[0-9a-f]{7,40}",
    r"@?[\w.-]+(?:\[bot\])?",
    r"[\w.-]+/[\w.-]+",
    r"[\w.-]+/[\w.-]+#\d+",
    r"https?://\S+",
    r"[^\n]+",
]


def value_shapes(values: list[str]) -> list[str]:
    """Every one of SHAPES all the values fit, tightest first: digits, a
    hash, a name, owner/name, a web address, any one line. Two examples
    that both say "approved" fit a single word, but the template may say
    "requested changes on"; the corpus decides (Template._choose)."""
    fits = [shape for shape in SHAPES if values and all(re.fullmatch(shape, value) for value in values)]
    return fits or [r"[\s\S]+"]


def value_shape(values: list[str]) -> str:
    return value_shapes(values)[0]


TOKEN = re.compile(r"\s+|\d+|[^\W\d_]+|[^\w\s]")


def _token_regex(token: str, loose: bool) -> tuple[str, float]:
    """A token of the text next to a value as a regular expression, and how
    much it pins down: a word as itself (a longer one may grow, "commit" to
    "commits"), punctuation as itself; a number as any number and,
    loosely, a word as any word, which pin down nothing and cost a little,
    so the shortest such anchor wins."""
    if token.isspace():
        # Real whitespace, so an anchor ends where a word does: "@[a-z]+ "
        # must not match the "@greptile" of "@greptile-apps[bot] ".
        return r"\s+", 0
    if token.isdigit():
        return r"\d+", -0.1
    if re.fullmatch(r"[^\W\d_]+", token):
        if loose:
            return r"[^\W\d_]+", -0.1
        return re.escape(token) + (r"\w*" if len(token) >= 3 else ""), 3
    return re.escape(token), 0.5 if loose else 2


def anchor_variants(contexts: list[str], side: str, most: int = 4) -> list[tuple[str, float]]:
    """Regular expressions for the text beside a value, each true of every
    example (at the end of the text before it, or the start of the text
    after it), with a score for how much each pins down. "^" and "$" stand
    for the leaf's own edge, "" for no anchor at all.

    Three kinds, from tight to loose: the words themselves ("pushed",
    growing to "pushes"); the same with every word as any word
    (punctuation and numbers kept); and runs of non-space characters, as
    their shape or as anything, for text beside the value that is itself
    another field ("@someone[bot] pushed"). Not yet: some words literal and
    some loose ("(<any level> severity)"); see docs/teach-fields.md."""
    variants: dict[str, float] = {"": 0}
    if all(not context.strip() for context in contexts):
        variants["^" if side == "left" else "$"] = 6
        return sorted(variants.items(), key=lambda item: -item[1])

    def keep(regex: str, score: float, edge: bool, literal: bool) -> None:
        for anchored in ((False, True) if edge else (False,)):
            full = (r"^\s*" + regex if side == "left" else regex + r"\s*$") if anchored else regex
            if side == "left":
                fits = all(re.search(f"(?:{full})$", context) for context in contexts)
            else:
                fits = all(re.match(full, context) for context in contexts)
            if fits:
                bonus = (2 if literal else 0.3) if anchored else 0
                variants[full] = max(variants.get(full, float("-inf")), score + bonus)

    tokens = TOKEN.findall(contexts[0])
    if side == "left":
        tokens = tokens[::-1]
    words = [n for n, token in enumerate(tokens) if not token.isspace()]
    # An anchor stops at a bracket that bounds the value: past "]" in
    # "[owner/repo] Title" lies the title, which says nothing about where
    # the repo ends, however often titles start with "Fix".
    stops = ")]}" if side == "right" else "([{)]}"
    for cut_at, n in enumerate(words):
        if tokens[n] in stops:
            words = words[: cut_at + 1]
            break
    for count in range(1, min(most, len(words)) + 1):
        # Up to the count-th token, keeping the whitespace touching the value.
        chosen = tokens[: words[count - 1] + 1]
        for loose in (False, True):
            parts = [_token_regex(token, loose) for token in chosen]
            if side == "left":
                parts = parts[::-1]
            keep("".join(part for part, _ in parts), sum(score for _, score in parts), count == len(words), not loose)
    # Runs of non-space characters, nearest first.
    chunks = re.findall(r"\s+|\S+", contexts[0])
    if side == "left":
        chunks = chunks[::-1]
    solid = [n for n, chunk in enumerate(chunks) if not chunk.isspace()]
    for count in range(1, min(3, len(solid)) + 1):
        chosen = chunks[: solid[count - 1] + 1]
        # Each chunk as its shape (a hash, an @name, owner/repo), or as any.
        for shaped in (True, False):
            parts = [r"\s+" if chunk.isspace() else (chunk_shape(chunk) if shaped else r"\S+") for chunk in chosen]
            if side == "left":
                parts = parts[::-1]
            keep("".join(parts), (-0.1 if shaped else -0.2) * count, count == len(solid), False)
    return sorted(variants.items(), key=lambda item: -item[1])


def chunk_shape(chunk: str) -> str:
    """The tightest of SHAPES a run of non-space characters fits, short of
    "any text"."""
    for shape in SHAPES[:-1]:
        if re.fullmatch(shape, chunk):
            return f"(?:{shape})"
    return r"\S+"


def compile_cut(left: str, right: str, shape: str) -> re.Pattern:
    """One regular expression for a value between its anchors."""
    head = r"^\s*" if left == "^" else left
    tail = r"\s*$" if right == "$" else right
    # With an anchor after it, the value is as short as can be (lazy), so it
    # ends at the first ")" after it, not the last. Lazy goes on the
    # repetition itself: "(?:x+)?" would only make the value optional.
    if tail != "" and "|" not in shape and shape.endswith(("+", "*", "}")):
        shape += "?"
    return re.compile(f"{head}(?P<v>(?:{shape})){tail}")


def cut(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = match.group("v").strip()
    return value or None


@dataclass
class Extractor:
    """Where one field sits in its template, learned from examples."""

    name: str
    # The leaf's path; None in a step's place means any one of that kind.
    path: tuple[tuple[str, int | None], ...]
    slot: int | None
    # Regular expressions for the text just before and after the value in
    # its leaf ("^" and "$": the leaf's own edges), and for the value.
    left: str
    right: str
    shape: str
    link: bool = False
    many: bool = False
    subject: bool = False
    # A link field's label when the template always says the same one
    # ("View it on GitHub").
    label: str = ""
    # The nearest fixed text before the value: which of several matches.
    landmark: str = ""
    # Found in every taught example, so missing means the template changed.
    required: bool = True

    @property
    def pattern(self) -> re.Pattern:
        return compile_cut(self.left, self.right, self.shape)


def find_value(page_text: str, value: str, after: str = "") -> tuple[int, int] | None:
    """Where a value appears in the page's text (after `after`, if given),
    whitespace-insensitively."""
    begin = 0
    if after:
        found = find_value(page_text, after)
        if found is None:
            return None
        begin = found[1]
    index = page_text.find(value, begin)
    if index >= 0:
        return index, index + len(value)
    pattern = r"\s+".join(re.escape(part) for part in value.split())
    match = re.compile(pattern).search(page_text, begin)
    return match.span() if match else None


def _path_matches(pattern: tuple[tuple[str, int | None], ...], path: Path) -> bool:
    if len(pattern) != len(path):
        return False
    return all(sig == step[0] and (nth is None or nth == step[1]) for (sig, nth), step in zip(pattern, path))


def _generalize(paths: list[Path]) -> tuple[tuple[str, int | None], ...] | None:
    """One path for all examples: a step whose position differs becomes
    "any"; paths of different shape can't be one."""
    first = paths[0]
    if any(len(p) != len(first) or any(a[0] != b[0] for a, b in zip(p, first)) for p in paths):
        return None
    return tuple((step[0], step[1] if all(p[i][1] == step[1] for p in paths) else None) for i, step in enumerate(first))


def _row_depth(page: Page, leaf: Leaf) -> int | None:
    """The deepest step of a leaf's path whose element has siblings of the
    same kind: the row of the list or table it belongs to."""
    element = page.root
    counts = []
    for sig, nth in leaf.path:
        found = [child for child in element.children if isinstance(child, Element) and child.sig == sig]
        if nth >= len(found):
            return None
        element = found[nth]
        counts.append(len(found))
    for depth in range(len(counts) - 1, -1, -1):
        if counts[depth] > 1:
            return depth
    return None


@dataclass
class Located:
    leaf: Leaf
    left: str
    right: str
    value: str


def locate(page: Page, taught: Taught) -> Located | None:
    """The leaf a taught value sits in, and its text either side of it. A
    selection running over several leaves keeps to the first."""
    if taught.start is not None and taught.end is not None:
        span: tuple[int, int] | None = (taught.start, taught.end)
    else:
        span = find_value(page.text, taught.value, taught.after)
    if span is None:
        return None
    leaf = page.leaf_at(span[0])
    if leaf is None:
        return None
    start = span[0] - leaf.start
    end = min(span[1], leaf.end) - leaf.start
    return Located(leaf, leaf.text[:start], leaf.text[end:], leaf.text[start:end].strip())


def preceding_fixed(page: Page, leaf: Leaf, fixed: dict[str, float], reach: int = 25) -> str:
    """The nearest text before a leaf that the template always says."""
    for index in range(leaf.number - 1, max(-1, leaf.number - 1 - reach), -1):
        shape = text_shape(page.leaves[index].text)
        if shape in fixed:
            return shape
    return ""


@dataclass
class Result:
    """One email read with a template: each field's value (a list for a
    field that repeats), what couldn't be found, and the verdict."""

    values: dict[str, str | list[str] | None]
    missing: list[str]
    status: str  # "ok", "partial" (an optional field missing) or "reteach"
    reason: str = ""


Example = tuple[Page, str, list[Taught]]


@dataclass
class Template:
    """A template's fields, learned from taught emails; extract() reads
    them out of others."""

    fixed: dict[str, float] = field(default_factory=dict)
    extractors: list[Extractor] = field(default_factory=list)
    # Fields taught that couldn't be learned from what was selected.
    unlearned: list[str] = field(default_factory=list)
    # How much of the template's always-said text an email must say to be
    # read as made from it.
    coverage: float = 0.6

    @classmethod
    def learn(cls, examples: list[Example], corpus: Iterable[tuple[Page, str]] = ()) -> Template:
        """Fields from 1-2 taught emails, each (page, subject, fields taught
        on it). `corpus` is other emails of the template, untaught, as
        (page, subject): they say which text is fixed, and choose among
        anchors that all fit the examples the one that holds across the
        template, so one example is often enough."""
        corpus = list(corpus)
        template = cls(fixed=fixed_texts([page for page, _, _ in examples] + [page for page, _ in corpus]))
        names = list(dict.fromkeys(taught.name for _, _, fields in examples for taught in fields))
        for name in names:
            found = [(page, subject, taught) for page, subject, fields in examples for taught in fields if taught.name == name]
            learned = (template._learn_subject if found[0][2].subject else template._learn_body)(name, found, corpus)
            if learned is None:
                # The reader says so ("couldn't learn 'app' from that
                # selection; try selecting it again"), never drops it quietly.
                template.unlearned.append(name)
                continue
            learned.required = len(found) == len(examples)
            template.extractors.append(learned)
        return template

    def _learn_body(self, name: str, found: list[tuple[Page, str, Taught]], corpus: list[tuple[Page, str]]) -> Extractor | None:
        first = found[0][2]
        located = [(page, spot) for page, _, taught in found if (spot := locate(page, taught)) is not None]
        if not located:
            return None
        if first.link and all(isinstance(page, TextPage) for page, _ in located):
            # In plain text an address is its own text ("View results:
            # https://…"): read as text, anchored by the words before it.
            first = dataclasses.replace(first, link=False)
        paths: list[Path] = [spot.leaf.path for _, spot in located]
        exact = _generalize(paths)
        if exact is None:
            return None
        pages = [page for page, _ in corpus]
        if first.many:
            # The rows: wherever the examples, or the template's other
            # emails, have several of a step's kind side by side. Taught on
            # an email with one commit, the list still reads five.
            depths = {_row_depth(page, spot.leaf) for page, spot in located} | _repeating_depths(pages, exact)
            exact = tuple((sig, None if i in depths else nth) for i, (sig, nth) in enumerate(exact))
        loose = tuple((sig, None) for sig, _ in exact)
        slots = {spot.leaf.slot for _, spot in located}
        slot = slots.pop() if len(slots) == 1 else None
        label = ""
        if first.link:
            # The link's words, when the template always says the same ones
            # ("View it on GitHub"): not an address shown as itself, and not
            # words most emails merely happen to share (one repo's URL).
            labels = {text_shape(spot.leaf.text) for _, spot in located}
            only = next(iter(labels)) if len(labels) == 1 else ""
            if only and self.fixed.get(only, 0) >= 0.9 and not re.match(r"(?i)https?://|www\.", only):
                label = only
        # The exact path, unless the template's other emails say its rows
        # or blocks move about (the loose one finds the field in more).
        path = exact
        if pages and _reach(pages, loose, slot, label) > _reach(pages, exact, slot, label) + 0.05:
            path = loose
        if first.link:
            return Extractor(name, path, slot, "", "", r"https?://\S+|mailto:\S+", link=True, many=first.many,
                             label=label, landmark=self._landmark(located))
        values = [spot.value for _, spot in located]
        lefts = anchor_variants([spot.left for _, spot in located], "left")
        rights = anchor_variants([spot.right for _, spot in located], "right")
        left, right, shape = self._choose(lefts, rights, value_shapes(values), located, pages, path, slot, first.many)
        if left is None:
            return None
        return Extractor(name, path, slot, left, right, shape, many=first.many, landmark=self._landmark(located))

    def _choose(self, lefts, rights, shapes, located, pages, path, slot, many) -> tuple[str | None, str | None, str]:
        texts = [[leaf.text for leaf in page.leaves if _path_matches(path, leaf.path) and (slot is None or leaf.slot == slot)]
                 for page in pages]
        examples = [(spot.leaf.text, spot.value) for _, spot in located]
        return choose_cut(lefts, rights, shapes, examples, texts, rows=many)

    def _landmark(self, located: list[tuple[Page, Located]]) -> str:
        marks = {preceding_fixed(page, spot.leaf, self.fixed) for page, spot in located}
        return marks.pop() if len(marks) == 1 else ""

    def _learn_subject(self, name: str, found: list[tuple[Page, str, Taught]], corpus: list[tuple[Page, str]]) -> Extractor | None:
        lefts, rights, values = [], [], []
        for _, subject, taught in found:
            subject = SUBJECT_NOISE.sub("", collapse(subject).strip())
            index = subject.find(taught.value)
            if index < 0:
                return None
            lefts.append(subject[:index])
            rights.append(subject[index + len(taught.value):])
            values.append(taught.value)
        subjects = [[SUBJECT_NOISE.sub("", collapse(subject).strip())] for _, subject in corpus]
        examples = [(l + v + r, v) for l, v, r in zip(lefts, values, rights)]
        left, right, shape = choose_cut(anchor_variants(lefts, "left"), anchor_variants(rights, "right"),
                                        value_shapes(values), examples, subjects)
        if left is None:
            return None
        return Extractor(name, (), None, left, right, shape, subject=True)

    # -- reading ------------------------------------------------------------

    def covers(self, page: Page) -> float:
        """How much of what the template always says this email says."""
        strong = [text for text, share in self.fixed.items() if share >= 0.9]
        if not strong:
            return 1.0
        said = {text_shape(leaf.text) for leaf in page.leaves}
        return sum(1 for text in strong if text in said) / len(strong)

    def extract(self, page: Page, subject: str = "") -> Result:
        values: dict[str, str | list[str] | None] = {}
        for extractor in self.extractors:
            values[extractor.name] = self.read(extractor, page, subject)
        missing = [name for name, value in values.items() if value in (None, [])]
        required = [e.name for e in self.extractors if e.required and e.name in missing]
        if self.covers(page) < self.coverage:
            return Result(values, missing, "reteach", "it doesn't say what this template always says")
        if required:
            return Result(values, missing, "reteach", "can't find " + ", ".join(required))
        return Result(values, missing, "partial" if missing else "ok")

    def read(self, extractor: Extractor, page: Page, subject: str = "") -> str | list[str] | None:
        if extractor.subject:
            return cut(extractor.pattern, SUBJECT_NOISE.sub("", collapse(subject).strip()))
        pattern = extractor.pattern
        found: list[tuple[Leaf, str]] = []
        for leaf in page.leaves:
            if not _path_matches(extractor.path, leaf.path) or (extractor.slot is not None and leaf.slot != extractor.slot):
                continue
            if extractor.link:
                if extractor.label and text_shape(leaf.text) != extractor.label:
                    continue
                value = leaf.href if re.fullmatch(extractor.shape, leaf.href or "") else None
            else:
                value = cut(pattern, leaf.text)
            if value:
                found.append((leaf, value))
        if extractor.many:
            return [value for _, value in found]
        if len(found) > 1 and extractor.landmark:
            near = [item for item in found if preceding_fixed(page, item[0], self.fixed) == extractor.landmark]
            found = near or found
        return found[0][1] if found else None

    def to_json(self) -> dict:
        """What Courier stores for this template (courier_templates)."""
        return {"fixed": self.fixed, "coverage": self.coverage, "unlearned": self.unlearned,
                "fields": [dataclasses.asdict(e) | {"path": [[sig, nth] for sig, nth in e.path]} for e in self.extractors]}

    @classmethod
    def from_json(cls, data: dict) -> Template:
        """A template as to_json() wrote it, ready to read emails without
        learning again."""
        known = {f.name for f in dataclasses.fields(Extractor)}
        extractors = [Extractor(**({k: v for k, v in item.items() if k in known}
                                   | {"path": tuple((sig, nth) for sig, nth in item.get("path", []))}))
                      for item in data.get("fields", [])]
        return cls(fixed=dict(data.get("fixed", {})), extractors=extractors, coverage=float(data.get("coverage", 0.6)),
                   unlearned=list(data.get("unlearned", [])))


def _reach(pages: list[Page], path, slot, label: str = "") -> float:
    """The share of pages with a leaf at this path (saying `label`, if given)."""
    return sum(1 for page in pages if any(_path_matches(path, leaf.path) and (slot is None or leaf.slot == slot)
                                          and (not label or text_shape(leaf.text) == label)
                                          for leaf in page.leaves)) / len(pages)


def _repeating_depths(pages: list[Page], path) -> set[int]:
    """The steps of a path where some page has several elements of that
    step's kind side by side: rows."""
    depths: set[int] = set()
    for page in pages:
        level = [page.root]
        for depth, (sig, nth) in enumerate(path):
            following = []
            for element in level:
                found = [child for child in element.children if isinstance(child, Element) and child.sig == sig]
                if len(found) > 1:
                    depths.add(depth)
                following.extend(found)
            level = following
            if not level:
                break
    return depths


# Choosing among anchors and shapes, at most this many of the template's
# other emails are tried, and a choice may find a value in this much less
# of them than the best and still win by being more specific.
SAMPLE = 250
SLACK = 0.01


def _family(anchor: str) -> str:
    """An anchor with its words, literal or loose, written as W."""
    return re.sub(r"\[\^\\W\\d_\]\+|(?<!\\)[A-Za-z]+(?:\\w\*)?", "W", anchor)


def kind_of(value: str) -> str:
    """A value's kind, coarsely: a number, a hash, an address, or words."""
    value = value.strip()
    if re.fullmatch(r"[#$€£]?\d[\d,.:]*%?", value):
        return "number"
    if re.fullmatch(r"(?=[0-9a-f]*\d)[0-9a-f]{7,40}", value):
        return "hash"
    if re.match(r"(?i)https?://|mailto:", value):
        return "address"
    return "words"


def choose_cut(lefts, rights, shapes, examples, texts, rows: bool = False) -> tuple[str | None, str | None, str]:
    """Of the (left anchor, right anchor, shape) choices that give back
    every taught value exactly, the most specific one among those that find
    a value in (nearly) as many of the template's other emails as the best.
    Specific means literal anchor text first, then the tightest shape.
    `examples` is (leaf text, taught value); `texts` is, per other email,
    the texts of its leaves at the field's path.

    A field that repeats (`rows`) then gets a second look, one side at a
    time with the other kept: an anchor on "failed" finds a job in every CI
    email, but not the cancelled and skipped jobs beside it, so each side
    is loosened as far as finding more rows needs."""
    texts = texts[:: max(1, len(texts) // SAMPLE)] if texts else []

    def gives_back(pattern: re.Pattern) -> bool:
        return all(cut(pattern, text) == value for text, value in examples)

    def emails_found(pattern: re.Pattern) -> float:
        return sum(1 for leaves in texts if any(cut(pattern, text) for text in leaves)) / len(texts) if texts else 1.0

    def rows_found(pattern: re.Pattern) -> int:
        return sum(1 for leaves in texts for text in leaves if cut(pattern, text))

    scored = []
    for left, left_score in lefts:
        for right, right_score in rights:
            for tightness, shape in enumerate(shapes):
                pattern = compile_cut(left, right, shape)
                if gives_back(pattern):
                    scored.append((emails_found(pattern), left_score + right_score, -tightness, left, right, shape))
    if not scored:
        return None, None, ""
    best = max(item[0] for item in scored)
    reach, anchors, tightness, left, right, shape = max((item for item in scored if item[0] >= best - SLACK),
                                                        key=lambda item: (item[1], item[2]))
    # A looser shape is only worth it when most of the template needs it
    # (two "approved"s, while most say "commented on"). When a tighter one,
    # with anchors as good, still reads three quarters as many emails, the
    # rest are emails whose template changed ("@x force-pushed the branch"
    # where a count should be): they are flagged, not read as "the".
    tighter = [item for item in scored if item[2] > tightness and item[1] >= anchors and item[0] >= 0.75 * reach]
    if tighter:
        _, _, _, t_left, t_right, t_shape = max(tighter, key=lambda item: (item[2], item[1], item[0]))
        # Only when what the looser one adds is a different kind of value
        # ("the" where a count was taught). "Deploy preview" beside a taught
        # "CI" is the same kind: a workflow with a longer name.
        loose, tight = compile_cut(left, right, shape), compile_cut(t_left, t_right, t_shape)
        added = {kind_of(value) for leaves in texts for text in leaves
                 if (value := cut(loose, text)) is not None and cut(tight, text) is None}
        if not added & {kind_of(value) for _, value in examples}:
            left, right, shape = t_left, t_right, t_shape
    if rows and texts:
        for side in ("right", "left"):
            options = []
            kept = left if side == "left" else right
            for anchor, score in (rights if side == "right" else lefts):
                # Only the same anchor with its words loosened: "failed" may
                # become any word, but "(2 annotations" stays, and a hash
                # never becomes "any text", which in plain text (one path
                # for every line) would take every line for a row.
                if _family(anchor) != _family(kept):
                    continue
                pattern = compile_cut(left, anchor, shape) if side == "right" else compile_cut(anchor, right, shape)
                if gives_back(pattern):
                    options.append((rows_found(pattern), score, anchor))
            most = max(found for found, _, _ in options)
            chosen = max((option for option in options if option[0] >= most * (1 - SLACK)), key=lambda option: option[1])[2]
            if side == "right":
                right = chosen
            else:
                left = chosen
    return left, right, shape


# ---------------------------------------------------------------------------
# Plain-text email


# A line that starts a row of its own: a bullet, a number, a hash, an address.
ROW_START = re.compile(r"\s*(?:[-*\u2022+>]\s|\d+[.)]\s|[0-9a-f]{7,40}\b|https?://)")


def wrapped(previous: str, line: str, width: int) -> bool:
    """Whether `line` goes on from `previous`, broken there by a mail
    program wrapping text at `width` (it's wrapped when the line's first
    word wouldn't have fitted on the one before). Rows of a list, an
    address and the line after a "Label:" stand alone."""
    if not 60 <= width <= 80 or not previous.strip() or not line.strip():
        return False
    if ROW_START.match(line) or previous.rstrip().endswith(":"):
        return False
    return len(previous.rstrip()) + 1 + len(line.split()[0]) > width


class TextPage(Page):
    """A plain-text email read like a page: each line a leaf, after lines
    a mail program wrapped are joined again (GitHub's account notices wrap
    at about 72 characters, so where a sentence breaks depends on the
    names in it). All lines share one path, so a field is placed by its
    anchors and by the nearest fixed line before it ("the address after
    'View it on GitHub:'"), not by markup. A line that is a web address is
    its own link. `text` is the joined text, one leaf to a line."""

    def __init__(self, text: str) -> None:  # Page.__init__ parses HTML; not wanted here.
        self.root = Element("#root", {}, None)
        self.leaves = []
        raw = (text or "").replace("\r\n", "\n").split("\n")
        # The wrap width: the longest line that isn't an address.
        width = max((len(line.rstrip()) for line in raw if "://" not in line), default=0)
        lines: list[str] = []
        previous = ""
        for line in raw:
            if lines and wrapped(previous, line, width):
                lines[-1] += " " + line.strip()
            else:
                lines.append(line.rstrip())
            previous = line
        self.text = "\n".join(lines)
        offset = 0
        for line in lines:
            stripped = line.strip()
            if stripped:
                start = offset + line.index(stripped)
                href = stripped if re.fullmatch(r"https?://\S+", stripped) else ""
                self.leaves.append(Leaf(stripped, (("line", 0),), 0, href, start, len(self.leaves)))
            offset += len(line) + 1

    def leaf_at(self, offset: int) -> Leaf | None:
        for leaf in self.leaves:
            if leaf.start <= offset < leaf.end:
                return leaf
        return None
