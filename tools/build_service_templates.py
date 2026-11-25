"""Builds Courier's built-in services: the automated senders beyond GitHub
(Google's account alerts, Cloudflare, Hostinger, your bank…) whose mail is
notified by what it says, read-only and offline from your own mail.

    python3 -I tools/build_service_templates.py [--days 90] [--top 10] [--check]

- Picks the services: the verified automated senders with the most mail in
  the last 30 days, and any that sent a security alert, a failed payment, an
  expiry notice or an incident in the last `--days` (rare, and the ones that
  matter).
- Names each one (a known brand, else its display name) and lists its own
  role addresses (no-reply@, alerts@, team@…).
- For a layout it sends often, with a call to action that links back to the
  service ("Check activity", "Renew now"), learns a template whose only
  field is that link, and keeps nothing else: no fixed text, no anchors but
  the button's words.
- Writes mainstream services (BRANDS) to engine/builtin_templates/
  services.json (the repo), and the rest (banks, brokers, funds, the niche
  newsletters and sites you use) to
  ~/.local/share/courier/builtin_templates/private.json (never the repo:
  which bank you use is yours).

What a service's email is (a security alert, a statement) is decided when
it arrives, from its subject (courier_notify.SERVICE_KINDS); nothing here
reads or keeps a subject. --check scans the written files against the mail
for names, addresses, domains and subjects.
"""

from __future__ import annotations

import argparse
import collections
import email.utils
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import courier_fields as cf  # noqa: E402
import courier_notify as cn  # noqa: E402
import courier_sync as sync  # noqa: E402
import courier_templates as ct  # noqa: E402

PUBLIC = ROOT / "engine" / "builtin_templates" / "services.json"
PRIVATE_NAME = "private.json"
# Automated mail: a mailing list, an auto-submitted or bulk message, or a
# role address.
ROLE = re.compile(r"(?:^|[._+-])(?:no-?reply|do-?not-?reply|notifications?|notify|alerts?|mailer|automated|system|security|"
                  r"accounts?|info|updates?|news(?:letter)?|hello|team|support|billing|invoices?|statements?|service|"
                  r"auth|reports?|messages|jobs?|jobalerts|recommendations|store|order|em|marketing|product)(?:$|[._+-]|\d)", re.I)
# Money: kept out of the repo.
PRIVATE = re.compile(r"bank|broker|trad(?:e|ing)|invest|financ|fund|mutual|\bmf\b|insur|crypto|coin|exchange|wallet|pay|tax|loan|"
                     r"credit|stock|demat|capital|wealth|stripe", re.I)
BRANDS = {"google.com": "Google", "linkedin.com": "LinkedIn", "cloudflare.com": "Cloudflare", "hostinger.com": "Hostinger",
          "spotify.com": "Spotify", "indeed.com": "Indeed", "huggingface.co": "Hugging Face", "supabase.com": "Supabase",
          "amazon.in": "Amazon", "medium.com": "Medium", "vercel.com": "Vercel", "linear.app": "Linear",
          "render.com": "Render", "runpod.io": "RunPod", "notion.so": "Notion", "uber.com": "Uber", "udemy.com": "Udemy",
          "pinterest.com": "Pinterest", "instagram.com": "Instagram", "facebookmail.com": "Facebook", "x.com": "X",
          "dropbox.com": "Dropbox", "openai.com": "OpenAI", "x.ai": "xAI", "kaggle.com": "Kaggle", "proton.me": "Proton"}
# A call to action's words: a button back to the service, never a name.
CTA = re.compile(r"^(?:check|review|renew|view|open|manage|validate|verify|update|pay|go to|see|sign in|log in|secure|confirm|"
                 r"get started|download|reset|resolve|fix|restore|reactivate|activate)\b[\w ’'-]{0,40}$", re.I)
NOT_CTA = re.compile(r"unsubscribe|preferences|privacy|terms|help|support|contact|policy|settings|app store|google play|manage|"
                     r"web version|in (?:your )?browser|premium|upgrade|trial|offer|buy|shop|subscribe|plan", re.I)
TWO = {"co.in", "co.uk", "com.au", "net.in", "org.in", "ac.in", "gov.in", "bank.in"}
LEAST = 4
POPUP_KINDS = {"security-alert", "payment-failed", "domain-expiring", "incident"}
# Senders that carry other people's words in their subjects (a LinkedIn
# message, a comment, a mention): never alert senders, whatever they say.
RELAY = re.compile(r"messag|messenger|comment|mention|discussion|digest|community|forum|social|invit|connect|recommend", re.I)
# An address dedicated to alerts, by its mailbox or its host
# (security-noreply@, alerts@, auth@, payments-update@, no-reply@accounts.…).
DEDICATED = re.compile(r"(?:^|[._+-])(?:security|alerts?|auth|accounts?|payments?|billing|verify|verification|login|signin)"
                       r"(?:$|[._+-])", re.I)
# Generic senders reviewed by hand: they send only the service's own words
# (Hostinger's renewals, Cloudflare's domain and billing notices, Spotify's
# login alerts), never anyone else's.
REVIEWED_ALERTS = {"team@info.hostinger.com", "team@updates.hostinger.com", "noreply@notify.cloudflare.com", "no-reply@spotify.com"}


def alert_sender(address: str, kinds: collections.Counter) -> bool:
    """May this address raise an alert? Only if dedicated to alerts by name
    or reviewed, never a relay. (A generic notify@ that happened to send
    only login alerts lately may still carry someone's page or file name.)"""
    local, _, host = address.partition("@")
    if RELAY.search(local):
        return False
    return bool(DEDICATED.search(local) or DEDICATED.search(host.split(".")[0]) or address in REVIEWED_ALERTS)


def org(domain: str) -> str:
    parts = domain.lower().split(".")
    return ".".join(parts[-3:]) if ".".join(parts[-2:]) in TWO else ".".join(parts[-2:])


def brand_for(domain: str, names: collections.Counter) -> str:
    if domain in BRANDS:
        return BRANDS[domain]
    for name, _ in names.most_common():
        name = re.sub(r"\b(?:insta ?alerts?|alerts?|notifications?|no-?reply|team|updates?|mailer|support|info|service)\b", "",
                      name, flags=re.I)
        name = re.sub(r"[^\w& .-]", "", name).strip(" .-")
        if name and len(name) <= 30:
            return name
    return domain.split(".")[0].capitalize()


def load(days: int) -> list[dict]:
    """Verified automated mail of the last `days`, read-only: headers, and
    each email's page and subject (kept in memory only)."""
    os.environ.setdefault("NOTMUCH_CONFIG", str(Path.home() / ".config/courier/notmuch-config"))
    import notmuch2

    since = int(time.time() - days * 86400)
    rows = []
    with notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY) as db:
        for message in db.messages(f"date:@{since}.. and {sync.HIDDEN} and not tag:sent and not from:github.com", exclude_tags=[]):
            headers = {k.lower(): v for k, v in sync.read_headers([str(p) for p in message.filenames()]).items()}
            name, address = email.utils.parseaddr(headers.get("from", ""))
            address = address.lower()
            if "@" not in address:
                continue
            automated = (headers.get("list-id") or headers.get("auto-submitted", "no").lower() not in ("", "no")
                         or headers.get("precedence", "").lower() in ("bulk", "list", "junk") or ROLE.search(address.split("@")[0]))
            if not automated:
                continue
            try:
                mail = ct.Mail(message)
            except ct.TemplateError:
                continue
            domain = org(address.split("@")[1])
            if not ct.vouched(mail, domain):
                continue
            rows.append({"mail": mail, "address": address, "name": name, "domain": domain, "at": float(message.date),
                         "kind": cn.service_kind(mail.subject)[0], "role": bool(ROLE.search(address.split("@")[0]))})
    return rows


def recipients_tokens(rows: list[dict]) -> tuple[set[str], set[str]]:
    """What a shipped file must never hold: the names and addresses the mail
    was to, the hosts its links go to other than the services' own, and its
    subjects."""
    words: set[str] = set()
    phrases: set[str] = set()
    services = {row["domain"] for row in rows}
    for row in rows:
        parsed = row["mail"].parsed
        for name, address in email.utils.getaddresses([str(parsed.get(h, "")) for h in ("To", "Cc", "Delivered-To")]):
            for word in re.findall(r"[\w.+-]{3,}", f"{name} {address}"):
                words |= {part.lower() for part in re.split(r"[._+@-]", word) if len(part) >= 3}
                words.add(word.lower())
        text = row["mail"].html + " " + row["mail"].text
        for host in set(re.findall(r"https?://([\w.-]+)", text)):
            if org(host) not in services:
                words.add(host.lower())
        subject = cf.collapse(row["mail"].subject).strip().lower()
        if len(subject) >= 12:
            phrases.add(subject)
        for match in re.findall(r"\b[\w.-]+\.(?:dev|app|io|in|com|co|ai|me|xyz|net|org)\b", subject):
            if org(match) not in services:
                words.add(match.lower())
    # Role words (info@, team@user.…) are every service's, not a name.
    generic = {"com", "www", "mail", "gmail", "google", "http", "https", "email", "the", "and", "you", "your", "for", "info",
               "user", "users", "team", "support", "hello", "noreply", "no-reply", "reply", "notifications", "notification",
               "alerts", "alert", "updates", "update", "news", "account", "accounts", "security", "billing", "mailer", "emails"}
    return words - generic - {s.split(".")[0] for s in services}, phrases


def cta_template(service: dict, rows: list[dict]) -> dict | None:
    """A layout's template, its only field the call to action's link, or
    None when the layout has no such button back to the service."""
    pages = [row["mail"].page for row in rows]
    counts: collections.Counter = collections.Counter()
    for page in pages:
        counts.update({cf.text_shape(leaf.text) for leaf in page.leaves if leaf.href and re.match(r"https?://", leaf.href)})
    subjects = {cf.collapse(row["mail"].subject) for row in rows}
    labels = [label for label, n in counts.most_common() if n / len(pages) >= 0.9 and CTA.match(label) and not NOT_CTA.search(label)]
    if not labels or len(subjects) < 2:
        return None
    label = labels[0]
    learned = cf.Template.learn([(pages[0], rows[0]["mail"].subject, [cf.Taught("link", label, link=True)])],
                                [(page, row["mail"].subject) for page, row in zip(pages, rows)])
    if learned.unlearned or not learned.extractors:
        return None
    learned.fixed = {}
    for extractor in learned.extractors:
        extractor.landmark = ""
    shipped = cf.Template.from_json(learned.to_json())
    ok = 0
    for page, row in zip(pages, rows):
        link = shipped.extract(page, row["mail"].subject).values.get("link") or ""
        host = re.match(r"https?://([^/:?#]+)", link)
        ok += bool(host) and (host.group(1).lower() == service["domain"] or host.group(1).lower().endswith("." + service["domain"]))
    if ok / len(rows) < 0.9:
        return None
    return {"kind": "service", "service": service["id"], "surface": "html", "fields": [{"name": "link", "list": False,
            "link": True, "subject": False}], "learned": learned.to_json(), "_label": label, "_read": f"{ok}/{len(rows)}"}


def build(rows: list[dict], top: int) -> tuple[dict, dict, list[str]]:
    month = time.time() - 30 * 86400
    by_domain: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_domain[row["domain"]].append(row)
    volume = collections.Counter({d: sum(1 for r in rs if r["at"] >= month) for d, rs in by_domain.items()})
    urgent = {d for d, rs in by_domain.items() if any(r["kind"] in POPUP_KINDS and r["role"] for r in rs)}
    chosen = [d for d, _ in volume.most_common(top)] + sorted(urgent - {d for d, _ in volume.most_common(top)})
    public = {"about": "Courier's built-in services: automated senders whose mail is notified by what it says (a security "
                       "alert, a failed payment, an expiring domain, an incident), made by build_service_templates.py. Each "
                       "has its role addresses and, for layouts with a call to action, a template whose only field is that "
                       "link. Nothing from any email is kept.", "services": [], "templates": []}
    private = {"about": "Your own services Courier won't put in its repo (banks, brokers, funds), made by "
                        "build_service_templates.py from your mail.", "services": [], "templates": []}
    report = []
    for domain in chosen:
        mine = [r for r in by_domain[domain] if r["role"]]
        if not mine:
            continue
        senders = sorted({r["address"] for r in mine})
        # The addresses that sent this service's alerts, and only those, may
        # raise one: a security alert in a relayed message's subject is
        # someone's words, not the service's.
        by_sender = collections.defaultdict(collections.Counter)
        for r in mine:
            by_sender[r["address"]][r["kind"]] += 1
        alerts = sorted(a for a, kinds in by_sender.items() if any(k in POPUP_KINDS for k in kinds) and alert_sender(a, kinds))
        service = {"id": re.sub(r"[^a-z0-9]+", "-", domain).strip("-"), "brand": brand_for(domain, collections.Counter(r["name"] for r in mine)),
                   "domain": domain, "senders": senders, "alerts": alerts}
        # The repo carries only mainstream brands; money, and the niche
        # newsletters and sites you happen to use, stay yours.
        target = public if domain in BRANDS and not PRIVATE.search(domain) else private
        target["services"].append(service)
        kinds = collections.Counter(r["kind"] for r in by_domain[domain])
        made = []
        layouts: dict[str, list[dict]] = collections.defaultdict(list)
        for r in mine:
            layouts[r["mail"].fingerprint].append(r)
        for fingerprint, members in layouts.items():
            if len(members) < LEAST:
                continue
            template = cta_template(service, members)
            if template is None:
                continue
            label, read = template.pop("_label"), template.pop("_read")
            template = {"id": f"{service['id']}.{len(made) + 1}", **template, "fingerprints": [fingerprint]}
            target["templates"].append(template)
            made.append(f"{label!r} {read}")
        report.append(f"{'private' if target is private else 'public '} {service['brand']:16} {domain:22} {len(by_domain[domain]):4} emails "
                      f"({volume[domain]} in 30 days), {len(senders)} senders, kinds {dict(kinds)}, templates {made}")
    return public, private, report


def scan(data: dict, words: set[str], phrases: set[str]) -> list[str]:
    """Names, addresses, hosts and subjects from the mail found in a file
    (its fingerprints and ids aside: hashes of markup and its own names)."""
    copy = json.loads(json.dumps(data))
    copy.pop("about", None)  # this tool's own words
    for template in copy.get("templates", []):
        template.pop("fingerprints", None)
        template.pop("id", None)
    body = json.dumps(copy, ensure_ascii=False).lower()
    found = [w for w in words if re.search(rf"(?<![\w.-]){re.escape(w)}(?![\w-])", body)]
    found += [p for p in phrases if p in body]
    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--check", action="store_true", help="only scan the written files against the mail")
    parser.add_argument("--private-out", type=Path, help="where the private services go (default: Courier's own folder)")
    args = parser.parse_args()
    rows = load(args.days)
    words, phrases = recipients_tokens(rows)
    private_path = args.private_out or ct.private_builtin_dir() / PRIVATE_NAME
    if args.check:
        leaks = []
        for path in (PUBLIC, private_path):
            if path.exists():
                found = scan(json.loads(path.read_text()), words, phrases)
                leaks += [f"{path}: {leak}" for leak in found]
        if PUBLIC.exists() and any(PRIVATE.search(s["domain"]) for s in json.loads(PUBLIC.read_text())["services"]):
            leaks.append(f"{PUBLIC}: a money service in the repo")
        print(f"scanned against {len(rows)} emails ({len(words)} names and hosts, {len(phrases)} subjects): "
              f"{'no' if not leaks else len(leaks)} matches")
        for leak in leaks:
            print("LEAK:", leak)
        return 1 if leaks else 0
    public, private, report = build(rows, args.top)
    print(f"{len(rows)} verified automated emails in {args.days} days")
    for line in report:
        print(line)
    leaks = [f"public: {x}" for x in scan(public, words, phrases)] + [f"private: {x}" for x in scan(private, words, phrases)]
    if leaks:
        for leak in leaks:
            print("PROBLEM:", leak)
        print("not written")
        return 1
    PUBLIC.write_text(json.dumps(public, ensure_ascii=False, indent=1) + "\n")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    sync.write_private(private_path, json.dumps(private, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {PUBLIC.relative_to(ROOT)} ({len(public['services'])} services, {len(public['templates'])} templates) and "
          f"{private_path} ({len(private['services'])} services, {len(private['templates'])} templates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
