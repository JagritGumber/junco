"""Teach fields: the templates you taught in the reader, and the fields read
out of every email made from them.

You open an automated email (a forge's PR comment, a CI failure), press
Teach fields, select text and name it ("Repo", "PR", "Author"…).
courier_fields learns where each field sits; this module keeps what you
taught and reads it out of the template's other emails, the ones already
here and each new one after a sync.

What lives where, all in Courier's own state and never in the mail:

    $XDG_STATE_HOME/courier/templates/<account>/
        <id>.json           a template: its sender and fingerprint, its name,
                            the fields as you taught them (Message-IDs and
                            offsets, no mail text) and what was learned
        <id>.values.json    each of its emails' fields: Message-ID ->
                            {status, values, missing} (a cache)
        fingerprints.json   Message-ID -> fingerprint, for the senders you
                            taught (a cache, so each email is read once)

A template belongs to one account and one fingerprint (sender, subject
frame, layout: courier_fields.fingerprint), and its id is a hash of the two.
It is taught on one surface, the one the reader showed: "text" (the plain
text view, what notification mail opens in) or "html" (the designed
version), and every email of it is read from that same surface. The mail
index is only ever read.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import json
import os
import re
import time
from pathlib import Path

import courier_fields as cf
import courier_sync as sync

# The newest emails of a template that teaching learns from and previews.
# More would only slow teaching down: the learner needs a few dozen.
LEARN_FROM = 120
PREVIEW = 40
# Fields a template's panel suggests, in the order shown.
SUGGESTIONS = ["Repo", "PR", "Title", "Author", "Action", "Link", "Status"]
SURFACES = ("text", "html")


class TemplateError(RuntimeError):
    """Something the reader should say in words."""


# Where things are kept ---------------------------------------------------------


def root() -> Path:
    return sync.state_dir() / "templates"


def folder(account: str) -> Path:
    if not re.fullmatch(r"[\w.-]+", account or ""):
        raise TemplateError("That email belongs to no known account.")
    return root() / account


def template_id(account: str, fingerprint: str) -> str:
    return hashlib.sha1(f"{account}\n{fingerprint}".encode()).hexdigest()[:12]


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def _write(path: Path, data) -> None:
    sync.write_private(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def all_templates() -> list[dict]:
    out = []
    if not root().is_dir():
        return out
    for path in sorted(root().glob("*/*.json")):
        if path.name.endswith(".values.json") or path.name == "fingerprints.json":
            continue
        data = _read(path, None)
        if isinstance(data, dict) and data.get("id") == path.stem:
            out.append(data)
    return out


def load_template(tid: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{12}", tid or ""):
        return None
    for path in root().glob(f"*/{tid}.json") if root().is_dir() else []:
        data = _read(path, None)
        if isinstance(data, dict) and data.get("id") == tid:
            return data
    return None


def save_template(template: dict) -> None:
    _write(folder(template["account"]) / f"{template['id']}.json", template)


def load_values(template: dict) -> dict:
    return _read(folder(template["account"]) / f"{template['id']}.values.json", {})


def save_values(template: dict, values: dict) -> None:
    _write(folder(template["account"]) / f"{template['id']}.values.json", values)


def delete_template(tid: str) -> dict:
    template = load_template(tid)
    if template is None:
        raise TemplateError("That template is already gone.")
    for name in (f"{tid}.json", f"{tid}.values.json"):
        (folder(template["account"]) / name).unlink(missing_ok=True)
    return {"deleted": tid}


def templates_for(account: str, address: str) -> list[dict]:
    return [t for t in all_templates() if t.get("account") == account and t.get("sender") == address]


# Reading emails -----------------------------------------------------------------


class Mail:
    """One email as teaching needs it: its headers and its page (the HTML as
    the reader draws it, or the text)."""

    def __init__(self, message) -> None:
        self.id = message.messageid
        self.epoch = int(message.date)
        tags = set(message.tags)
        self.account = next((tag.split("/", 1)[1] for tag in tags if tag.startswith("account/")), "")
        self.path = str(message.path)
        try:
            with open(self.path, "rb") as handle:
                parsed = email.message_from_binary_file(handle, policy=email.policy.default)
        except OSError:
            raise TemplateError("That email's file is gone.") from None
        self.parsed = parsed
        self.subject = str(parsed.get("Subject", "") or "")
        self.sender = str(parsed.get("From", "") or "")
        self.address = cf.sender_of(self.sender)
        rich, plain = parsed.get_body(("html",)), parsed.get_body(("plain",))
        self.html = _text(rich)
        self.text = _text(plain)
        self._page: cf.Page | None = None
        self._pages: dict[str, cf.Page] = {}
        self._fingerprint = ""

    @property
    def page(self) -> cf.Page:
        """The designed version's page (the text when there's no HTML): what
        the fingerprint is made from."""
        if self._page is None:
            self._page = cf.Page(cf.sanitize(self.html)) if self.html.strip() else cf.TextPage(self.text)
        return self._page

    def page_for(self, surface: str) -> cf.Page:
        """The page fields are taught on and read from: the plain text the
        reader's text view shows, or the designed version."""
        if surface == "html":
            return self.page
        if "text" not in self._pages:
            self._pages["text"] = cf.TextPage(self.full_text)
        return self._pages["text"]

    @property
    def full_text(self) -> str:
        """The text the reader's plain view shows: courier_mail.message_text,
        the one source for both, so a selection there lines up here."""
        import courier_mail

        return courier_mail.message_text(self.parsed)

    @property
    def fingerprint(self) -> str:
        """Which template it's made from (from the designed version, whose
        layout tells templates apart best)."""
        if not self._fingerprint:
            self._fingerprint = cf.fingerprint(self.sender, self.subject, self.page)
        return self._fingerprint


def _text(part) -> str:
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, KeyError):
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    return content if isinstance(content, str) else content.decode("utf-8", "replace")


def read_mail(db, message_id: str) -> Mail:
    try:
        message = db.find(message_id)
    except LookupError:
        message = None
    if message is None:
        raise TemplateError("Junco can't find that email any more.")
    return Mail(message)


def _quote(value: str) -> str:
    return '"' + value.replace('"', "") + '"'


def members(db, account: str, address: str, fingerprint: str) -> list[tuple[str, int]]:
    """A template's emails, newest first, as (Message-ID, epoch): this
    account's mail from the sender whose fingerprint is the template's.
    Fingerprints are kept, so each email is read once."""
    cache_path = folder(account) / "fingerprints.json"
    cache = _read(cache_path, {})
    query = f"from:{_quote(address)} and tag:{_quote('account/' + account)} and {sync.HIDDEN}"
    found, changed = [], False
    for message in db.messages(query, sort=type(db).SORT.NEWEST_FIRST):
        message_id = message.messageid
        print_ = cache.get(message_id)
        if print_ is None:
            try:
                print_ = Mail(message).fingerprint
            except TemplateError:
                continue
            cache[message_id] = print_
            changed = True
        if print_ == fingerprint:
            found.append((message_id, int(message.date)))
    if changed:
        _write(cache_path, cache)
    return found


# Teaching -------------------------------------------------------------------------


def _brand(address: str) -> str:
    domain = address.rpartition("@")[2].split(".")
    return (domain[-2] if len(domain) >= 2 else domain[0]).capitalize()


NOUNS = {"PR #0": "pull request", "Issue #0": "issue", "h": "commit"}


def suggested_name(mail: Mail, others: list[Mail]) -> str:
    """A name to start from, which you can change: the sender's brand, what
    the subjects always say or what they're about, and the first thing the
    email itself always says ("Forgeline · pull request · pushed N commits",
    "Forgeline · Run failed")."""
    middles = [cf.mask(cf.subject_parts(other.subject)[1]) for other in [mail, *others]]
    pattern = cf.words_pattern(middles, 0.6) if len(middles) > 2 else ""
    words = [re.sub(r"[^\w\s-]", "", word) for word in pattern.split() if word != "*" and not word.startswith("-")]
    trailer = cf.subject_parts(mail.subject)[2]
    kind = " ".join(word for word in words if word) or NOUNS.get(cf.mask(trailer), "update")
    phrase = ""
    if len(others) >= 2:
        fixed = cf.fixed_texts([other.page for other in others], 0.6)
        for leaf in mail.page.leaves[:3]:
            if cf.text_shape(leaf.text) in fixed and re.search(r"[a-z]{3}", cf.text_shape(leaf.text)):
                phrase = re.sub(r"\d+", "N", leaf.text.strip(" .:"))
                break
    return " · ".join(part for part in (_brand(mail.address), kind, phrase) if part)[:80]


def repeats(page: cf.Page, leaf: cf.Leaf) -> bool:
    """Whether a selection sits in a row of a list or table: an element with
    siblings of its own kind and shape (commits, jobs), not just another
    paragraph."""
    if isinstance(page, cf.TextPage):
        return False
    element = page.root
    chain = []
    for sig, nth in leaf.path:
        kin = [child for child in element.children if isinstance(child, cf.Element) and child.sig == sig]
        element = kin[nth]
        chain.append((element, kin))
    for element, kin in chain:
        shape = cf.skeleton(element)
        if sum(1 for other in kin if cf.skeleton(other) == shape) >= 2:
            return True
    return False


def _field_shape(field: dict) -> dict:
    """A field as the panel keeps it, checked."""
    name = str(field.get("name", "")).strip()
    if not name or len(name) > 40:
        raise TemplateError("A field needs a short name.")
    examples = []
    for example in field.get("examples", []):
        item = {"id": str(example.get("id", "")), "value": str(example.get("value", ""))}
        if not item["id"]:
            continue
        if example.get("start") is not None and example.get("end") is not None:
            item["start"], item["end"] = int(example["start"]), int(example["end"])
        examples.append(item)
    return {"name": name, "list": bool(field.get("list")), "link": bool(field.get("link")),
            "subject": bool(field.get("subject")), "optional": bool(field.get("optional")), "examples": examples}


def learn(db, template: dict, corpus_ids: list[str], mails: dict[str, Mail]) -> cf.Template:
    """courier_fields.Template from the fields as taught, the template's
    other emails (`corpus_ids`) saying what is fixed and what holds."""
    taught: dict[str, list[cf.Taught]] = {}
    for field in template["fields"]:
        for example in field["examples"]:
            taught.setdefault(example["id"], []).append(cf.Taught(
                field["name"], example.get("value", ""), example.get("start"), example.get("end"),
                link=field["link"], many=field["list"], subject=field["subject"]))
    for message_id in list(taught) + corpus_ids:
        if message_id not in mails:
            try:
                mails[message_id] = read_mail(db, message_id)
            except TemplateError:
                taught.pop(message_id, None)
    surface = template.get("surface", "text")
    examples = [(mails[i].page_for(surface), mails[i].subject, fields) for i, fields in taught.items() if i in mails]
    corpus = [(mails[i].page_for(surface), mails[i].subject) for i in corpus_ids if i in mails]
    learned = cf.Template.learn(examples, corpus)
    optional = {field["name"] for field in template["fields"] if field["optional"]}
    for extractor in learned.extractors:
        extractor.required = extractor.name not in optional
    return learned


def read_fields(learned: cf.Template, template: dict, mail: Mail) -> dict:
    """One email's fields: {status, values, missing}. An email that needs
    teaching again shows no values at all, so nothing wrong is ever shown."""
    result = learned.extract(mail.page_for(template.get("surface", "text")), mail.subject)
    values = {name: value for name, value in result.values.items() if value not in (None, [])}
    if result.status == "reteach":
        values = {}
    # A field taught but not learned can't be read: say so, don't hide it.
    missing = result.missing + [name for name in learned.unlearned if name not in result.missing]
    return {"status": result.status, "values": values, "missing": missing, "reason": result.reason}


def _row(mail: Mail, fields: dict) -> dict:
    return {"id": mail.id, "epoch": mail.epoch, "subject": mail.subject} | fields


def start(db, message_id: str, surface: str = "text") -> dict:
    """What the Teach fields panel opens with: this email's template (or a
    new one), its fields as taught, and its other emails read with it.
    `surface` is the reader's view now; a template already taught keeps its
    own, and the panel asks the reader to show that one."""
    if surface not in SURFACES:
        raise TemplateError("Teach on the email's text or its designed version.")
    mail = read_mail(db, message_id)
    if not mail.account:
        raise TemplateError("That email belongs to no known account.")
    tid = template_id(mail.account, mail.fingerprint)
    saved = load_template(tid)
    found = members(db, mail.account, mail.address, mail.fingerprint)
    mails = {mail.id: mail}
    others = []
    for other_id, _ in found[:12]:
        if other_id not in mails:
            mails[other_id] = read_mail(db, other_id)
        if other_id != mail.id:
            others.append(mails[other_id])
    template = saved or {"id": tid, "account": mail.account, "sender": mail.address, "fingerprint": mail.fingerprint,
                         "name": suggested_name(mail, others), "fields": [], "surface": surface}
    template.setdefault("surface", "html")
    return {"template": {k: template[k] for k in ("id", "account", "sender", "fingerprint", "name", "fields", "surface")},
            "saved": saved is not None, "count": len(found), "suggestions": SUGGESTIONS,
            "preview": preview(db, message_id, template, found=found, mails=mails)}


def select(db, message_id: str, selection: dict) -> dict:
    """A selection in the reader as the field example it teaches: offsets in
    the email's page and the value, whether it sits in a link (and where
    that goes), and whether it's in a row that repeats."""
    mail = read_mail(db, message_id)
    if selection.get("subject"):
        value = str(selection.get("value", "")).strip()
        subject = cf.SUBJECT_NOISE.sub("", cf.collapse(mail.subject).strip())
        if not value or value not in subject:
            raise TemplateError("Select some of the subject's words.")
        return {"id": mail.id, "subject": True, "value": value, "link": "", "repeats": False}
    shown = str(selection.get("shown", ""))
    surface = selection.get("surface", "text")
    if surface not in SURFACES:
        raise TemplateError("Teach on the email's text or its designed version.")
    try:
        begin, end = int(selection["start"]), int(selection["end"])
    except (KeyError, TypeError, ValueError):
        raise TemplateError("Select some text in the email first.") from None
    page = mail.page_for(surface)
    mapped = cf.map_selection(page, shown, begin, end)
    if mapped is None:
        raise TemplateError("Junco couldn't place that selection in the email. Try selecting it again.")
    begin, end = mapped
    leaf = page.leaf_at(begin)
    if leaf is None:
        raise TemplateError("Select some text in the email first.")
    # Within one piece of text: the learner reads a field from one piece.
    end = min(end, leaf.end)
    value = page.text[begin:end].strip()
    if not value:
        raise TemplateError("Select some text in the email first.")
    # In plain text an address is its own text: selecting it offers its link.
    href = leaf.href or (value if isinstance(page, cf.TextPage) and re.fullmatch(r"https?://\S+", value) else "")
    return {"id": mail.id, "subject": False, "start": begin, "end": end, "value": value,
            "link": sync.web_link(href) if href else "", "repeats": repeats(page, leaf)}


def preview(db, message_id: str, template: dict, *, found=None, mails=None) -> dict:
    """The fields as taught so far, learned and read from this email and the
    template's newest others: what the panel shows while you teach."""
    mails = mails if mails is not None else {}
    current = mails.get(message_id) or read_mail(db, message_id)
    mails[current.id] = current
    template = dict(template, fields=[_field_shape(f) for f in template.get("fields", [])],
                    surface=template.get("surface", "text") if template.get("surface", "text") in SURFACES else "text")
    if found is None:
        found = members(db, current.account, current.address, current.fingerprint)
    ids = [i for i, _ in found]
    if not template["fields"]:
        rows = []
        for other_id in ids[:PREVIEW]:
            other = mails.get(other_id) or read_mail(db, other_id)
            mails[other_id] = other
            rows.append(_row(other, {"status": "new", "values": {}, "missing": [], "reason": ""}))
        return {"fields": [], "current": {"status": "new", "values": {}, "missing": []}, "rows": rows, "unlearned": []}
    learned = learn(db, template, ids[:LEARN_FROM], mails)
    rows = []
    for other_id in ids[:PREVIEW]:
        other = mails.get(other_id) or read_mail(db, other_id)
        mails[other_id] = other
        rows.append(_row(other, read_fields(learned, template, other)))
    here = read_fields(learned, template, current)
    # While teaching, the panel shows what each field found here even when the
    # email as a whole needs teaching again (the card never does).
    raw = learned.extract(current.page_for(template["surface"]), current.subject)
    fields = [{"name": f["name"], "list": f["list"], "link": f["link"], "subject": f["subject"], "optional": f["optional"],
               "learned": f["name"] not in learned.unlearned, "value": raw.values.get(f["name"]),
               "missing": f["name"] in raw.missing or f["name"] in learned.unlearned} for f in template["fields"]]
    return {"fields": fields, "current": here, "rows": rows, "unlearned": learned.unlearned}


def save(db, message_id: str, template: dict) -> dict:
    """Keeps a template as taught and reads every one of its emails."""
    current = read_mail(db, message_id)
    fields = [_field_shape(f) for f in template.get("fields", [])]
    names = [f["name"] for f in fields]
    if not fields:
        raise TemplateError("Teach at least one field first.")
    if len(set(name.lower() for name in names)) != len(names):
        raise TemplateError("Two fields have the same name.")
    tid = template_id(current.account, current.fingerprint)
    if template.get("id") and template["id"] != tid:
        raise TemplateError("That email is made from another template.")
    name = str(template.get("name", "")).strip()[:80] or suggested_name(current, [])
    surface = template.get("surface", "text")
    if surface not in SURFACES:
        raise TemplateError("Teach on the email's text or its designed version.")
    kept = {"id": tid, "account": current.account, "sender": current.address, "fingerprint": current.fingerprint,
            "name": name, "fields": fields, "surface": surface, "updated": int(time.time())}
    found = members(db, current.account, current.address, current.fingerprint)
    mails = {current.id: current}
    learned = learn(db, kept, [i for i, _ in found[:LEARN_FROM]], mails)
    kept["learned"] = learned.to_json()
    save_template(kept)
    values = {}
    for other_id, _ in found:
        other = mails.get(other_id) or read_mail(db, other_id)
        values[other_id] = _stamp(read_fields(learned, kept, other), other, kept)
    save_values(kept, values)
    flagged = sum(1 for item in values.values() if item["status"] == "reteach")
    return {"id": tid, "name": name, "count": len(values), "flagged": flagged, "unlearned": learned.unlearned}


# Reading taught templates -------------------------------------------------------


def _learned(template: dict) -> cf.Template:
    return cf.Template.from_json(template.get("learned") or {})


def _stamp(fields: dict, mail: Mail, template: dict) -> dict:
    """An email's fields as kept: with what the table shows of it, and which
    teaching of the template they were read with."""
    return fields | {"epoch": mail.epoch, "subject": mail.subject, "of": template.get("updated", 0)}


def _current(item: dict | None, template: dict) -> bool:
    return item is not None and item.get("of") == template.get("updated", 0)


def fields_of(db, message) -> dict | None:
    """The field card for one email (courier-mail message): None unless it is
    made from a template you taught."""
    tags = set(message.tags)
    account = next((tag.split("/", 1)[1] for tag in tags if tag.startswith("account/")), "")
    if not account or not root().is_dir():
        return None
    try:
        with open(str(message.path), "rb") as handle:
            head = email.message_from_binary_file(handle, policy=email.policy.default)
        address = cf.sender_of(str(head.get("From", "")))
    except OSError:
        return None
    candidates = templates_for(account, address)
    if not candidates:
        return None
    mail = Mail(message)
    tid = template_id(account, mail.fingerprint)
    template = next((t for t in candidates if t["id"] == tid), None)
    if template is None:
        return None
    values = load_values(template)
    item = values.get(mail.id)
    if not _current(item, template):
        item = _stamp(read_fields(_learned(template), template, mail), mail, template)
        values[mail.id] = item
        try:
            save_values(template, values)
        except OSError:
            pass
    return _card(template, item, len(values))


def _card(template: dict, item: dict, count: int) -> dict:
    fields = []
    for field in template["fields"]:
        value = item["values"].get(field["name"])
        fields.append({"name": field["name"], "list": field["list"], "link": field["link"],
                       "value": value if value not in (None, []) else None})
    return {"template": {"id": template["id"], "name": template["name"], "count": count},
            "status": item["status"], "missing": item.get("missing", []), "fields": fields}


def table(db, tid: str) -> dict:
    """One template's emails as a table: a row per email (newest first), a
    column per field. Emails that came since it was last read are read now."""
    template = load_template(tid)
    if template is None:
        raise TemplateError("That template is gone.")
    found = members(db, template["account"], template["sender"], template["fingerprint"])
    values = load_values(template)
    learned = None
    changed = False
    rows = []
    for message_id, epoch in found:
        item = values.get(message_id)
        if not _current(item, template):
            learned = learned or _learned(template)
            try:
                mail = read_mail(db, message_id)
            except TemplateError:
                continue
            item = _stamp(read_fields(learned, template, mail), mail, template)
            values[message_id] = item
            changed = True
        rows.append({"id": message_id, "epoch": item.get("epoch", epoch), "subject": item.get("subject", ""),
                     "status": item["status"], "missing": item.get("missing", []),
                     "values": {} if item["status"] == "reteach" else item["values"]})
    if changed:
        save_values(template, values)
    columns = [{"name": f["name"], "list": f["list"], "link": f["link"]} for f in template["fields"]]
    return {"template": {"id": tid, "name": template["name"], "account": template["account"], "sender": template["sender"]},
            "columns": columns, "rows": rows, "flagged": sum(1 for row in rows if row["status"] == "reteach")}


def listing(account: str = "") -> list[dict]:
    """Every template you taught, for the sidebar."""
    out = []
    for template in all_templates():
        if account and template.get("account") != account:
            continue
        values = load_values(template)
        out.append({"id": template["id"], "name": template["name"], "account": template["account"],
                    "sender": template["sender"], "count": len(values),
                    "flagged": sum(1 for item in values.values() if item.get("status") == "reteach"),
                    "fields": [f["name"] for f in template["fields"]]})
    return sorted(out, key=lambda t: t["name"].lower())


def after_sync(db, message_ids: list[str]) -> int:
    """New mail from a sender you taught: read its fields now, so its card
    and its row are ready. Returns how many emails were read."""
    if not message_ids or not root().is_dir():
        return 0
    taught = all_templates()
    if not taught:
        return 0
    by_sender: dict[tuple[str, str], list[dict]] = {}
    for template in taught:
        by_sender.setdefault((template["account"], template["sender"]), []).append(template)
    read = 0
    touched: dict[str, tuple[dict, dict]] = {}
    for message_id in message_ids:
        try:
            mail = read_mail(db, message_id)
        except TemplateError:
            continue
        candidates = by_sender.get((mail.account, mail.address))
        if not candidates:
            continue
        cache_path = folder(mail.account) / "fingerprints.json"
        cache = _read(cache_path, {})
        cache[mail.id] = mail.fingerprint
        _write(cache_path, cache)
        template = next((t for t in candidates if t["fingerprint"] == mail.fingerprint), None)
        if template is None:
            continue
        template_values = touched.get(template["id"], (template, load_values(template)))[1]
        template_values[mail.id] = _stamp(read_fields(_learned(template), template, mail), mail, template)
        touched[template["id"]] = (template, template_values)
        read += 1
    for template, template_values in touched.values():
        save_values(template, template_values)
    return read


# Built-in templates ---------------------------------------------------------------
#
# Courier ships templates for the commonest GitHub notifications
# (builtin_templates/*.json, made by tools/build_builtin_templates.py), so
# their fields are read without anyone teaching them. They hold only
# GitHub's own boilerplate: no repo, person, hash or subject from the mail
# they were learned on. A template you teach for the same fingerprint wins.

BUILTIN = Path(__file__).resolve().parent / "builtin_templates"
_builtins: dict[str, dict] | None = None
_services: dict[str, dict] | None = None


def private_builtin_dir() -> Path:
    """Built-ins made from your own mail that the repo mustn't carry (which
    bank or broker you use): ~/.local/share/courier/builtin_templates, or
    COURIER_PRIVATE_BUILTINS (the replay, before they're installed)."""
    if os.environ.get("COURIER_PRIVATE_BUILTINS"):
        return Path(os.environ["COURIER_PRIVATE_BUILTINS"])
    return sync.xdg("XDG_DATA_HOME", ".local/share") / "courier" / "builtin_templates"


def _builtin_files() -> list[Path]:
    return sorted(BUILTIN.glob("*.json")) + sorted(private_builtin_dir().glob("*.json"))


def builtins() -> dict[str, dict]:
    """Fingerprint -> built-in template ({id, kind, name, surface, fields,
    learned}; a service's also "service"). Read once per process."""
    global _builtins
    if _builtins is None:
        found: dict[str, dict] = {}
        for path in _builtin_files():
            data = _read(path, {})
            for template in data.get("templates", []) if isinstance(data, dict) else []:
                for fingerprint in template.get("fingerprints", []):
                    found.setdefault(fingerprint, template)
        _builtins = found
    return _builtins


def services() -> dict[str, dict]:
    """Sender address -> service ({id, brand, domain}): the automated senders
    (Google's account alerts, Cloudflare, your bank…) whose mail is notified
    by kind (a security alert, a failed payment) even with no template for
    its layout. Read once per process."""
    global _services
    if _services is None:
        found: dict[str, dict] = {}
        for path in _builtin_files():
            data = _read(path, {})
            for service in data.get("services", []) if isinstance(data, dict) else []:
                if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", str(service.get("domain", ""))):
                    continue
                for sender in service.get("senders", []):
                    found.setdefault(str(sender).lower(), service)
        _services = found
    return _services


def builtin_senders() -> set[str]:
    return {fingerprint.split("|", 1)[0] for fingerprint in builtins()} | set(services())


def vouched(mail, domain: str) -> bool:
    """Gmail verified the email as `domain`'s (or a subdomain's)."""
    verified = verified_domain(mail)
    return bool(verified) and bool(domain) and (verified == domain or verified.endswith("." + domain))


def auth_results(value: str) -> tuple[str, list[list[str]]]:
    """An Authentication-Results value (RFC 8601) as its authserv-id and its
    results, each as its tokens ("dmarc=pass", "header.from=github.com").
    Comments and quoted strings go first: they can hold anything, such as
    an envelope sender written by whoever sent the email ("a;dmarc=pass
    header.from=github.com"@evil.test). Unbalanced ones drop the rest."""
    kept: list[str] = []
    depth, quoted, escaped = 0, False, False
    for char in value:
        if escaped:
            escaped = False
        elif (quoted or depth) and char == "\\":
            escaped = True
        elif quoted:
            if char == '"':
                quoted = False
                kept.append('""')
        elif depth:
            depth += {"(": 1, ")": -1}.get(char, 0)
            if not depth:
                kept.append(" ")
        elif char == '"':
            quoted = True
        elif char == "(":
            depth = 1
        else:
            kept.append(char)
    parts = "".join(kept).split(";")
    server = (parts[0].split() or [""])[0].lower()
    return server, [part.lower().split() for part in parts[1:] if part.split()]


def verified_domain(mail) -> str:
    """The From domain Gmail vouched for, or "".

    Only what Gmail itself wrote counts: the headers above its own
    "Received: … by mx.google.com" (an email can't put anything above the
    point it entered Gmail). There, Gmail's ARC-Authentication-Results must
    say DMARC passed for the From address's domain, or the organisational
    domain it belongs to (Gmail reports team@info.hostinger.com's pass as
    header.from=hostinger.com). With no such Received, nothing is vouched
    for. Returns the From address's domain."""
    parsed = getattr(mail, "parsed", None)
    if parsed is None:
        return ""
    domain = mail.address.rpartition("@")[2].lower()
    vouched = False
    for name, value in parsed.items():
        name, value = name.lower(), re.sub(r"\s+", " ", str(value))
        if name == "received" and re.search(r"\bby mx\.google\.com\b", value):
            return domain if vouched else ""
        if name == "arc-authentication-results":
            server, results = auth_results(re.sub(r"^\s*i=\d+\s*;", "", value))
            for tokens in results:
                if server != "mx.google.com" or tokens[0] != "dmarc=pass":
                    continue
                passed = [token.split("=", 1)[1] for token in tokens[1:] if token.startswith("header.from=")]
                if any(re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", d) and (domain == d or domain.endswith("." + d))
                       for d in passed):
                    vouched = True
    return ""


def match(mail: Mail, taught: list[dict] | None = None) -> dict | None:
    """The template an email is made from: one you taught for its account
    and fingerprint, else a built-in one, else None. The result carries
    "kind" (what notifications key on: a built-in's, the built-in's for a
    template you taught over one, or "taught") and "builtin".

    A built-in template is GitHub's word for what an email is ("CI failed",
    urgent), so it's only taken for mail Gmail verified as GitHub's
    (verified_domain): copying GitHub's markup and From line isn't enough."""
    builtin = builtins().get(mail.fingerprint)
    service = services().get(mail.address)
    if builtin is not None and builtin.get("service"):
        # A service's layout: only for that service's own verified senders.
        builtin = builtin | {"brand": service["brand"], "domain": service["domain"], "alerts": service.get("alerts", [])} \
            if service and service.get("id") == builtin["service"] else None
    domain = (builtin or {}).get("domain") or mail.fingerprint.split("|", 1)[0].rpartition("@")[2]
    if builtin is not None and not vouched(mail, domain):
        builtin = None
    if builtin is None and service is not None and vouched(mail, service["domain"]):
        # A service's mail in a layout no template was made for (its rare
        # alerts): its kind comes from what it says, its fields are none.
        builtin = {"id": f"{service['id']}.mail", "kind": "service", "service": service["id"], "brand": service.get("brand", ""),
                   "domain": service["domain"], "alerts": service.get("alerts", []), "surface": "html", "fields": [],
                   "learned": {}}
    candidates = taught if taught is not None else templates_for(mail.account, mail.address)
    mine = next((t for t in candidates if t.get("account") == mail.account and t.get("fingerprint") == mail.fingerprint), None)
    if mine is not None:
        return mine | {k: v for k, v in (builtin or {}).items() if k in ("service", "brand", "domain", "alerts")} \
            | {"kind": (builtin or {}).get("kind", "taught"), "builtin": False}
    if builtin is not None:
        return builtin | {"builtin": True}
    return None


# A taught field's name as the built-ins call it ("Repo" -> repo, "PR" -> number).
FIELD_NAMES = {"pr": "number", "pr #": "number", "issue": "number"}


def fields_for(mail: Mail, taught: list[dict] | None = None) -> tuple[dict, dict] | None:
    """An email's template and its fields ({status, values, missing}), or
    None when no template, taught or built-in, makes it.

    A template you taught over a built-in one wins, and its values are laid
    over the built-in's (its names matched to theirs): you may have taught
    only Repo and Workflow, but a notification still needs the branch and
    which jobs failed."""
    template = match(mail, taught)
    if template is None:
        return None
    fields = read_fields(_learned(template), template, mail)
    builtin = builtins().get(mail.fingerprint) if not template.get("builtin") and template.get("kind") != "taught" else None
    if builtin is not None:
        base = read_fields(_learned(builtin), builtin, mail)
        mine = {FIELD_NAMES.get(name.strip().lower(), name.strip().lower()): value for name, value in fields["values"].items()}
        values = base["values"] | mine
        status = "ok" if "ok" in (base["status"], fields["status"]) and values else fields["status"]
        fields = fields | {"values": values, "status": status}
    return template, fields
