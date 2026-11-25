"""Measures courier_fields on real GitHub mail, offline and read-only.

    python3 -I tools/teach_fields_eval.py [--show TEMPLATE] [--sample N]

Reads the notmuch index read-only (notmuch2 MODE.READ_ONLY) and the mail
files; writes nothing anywhere. Prints only counts, rates, field names and
GitHub subject patterns, never an email's text, unless --show is given (for
checking by hand, on your own screen).

For each of six GitHub templates it teaches the first one or two emails
(the "user" selects each field's value, simulated with an oracle), then
reads every other email of the template and compares with the oracle. The
oracles are independent of what the learner reads where GitHub allows: the
author from X-GitHub-Sender, the link from the email's schema.org ld+json,
the PR number from the Message-ID, CI and advisory fields and commit lists
from the text/plain part.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import html
import os
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))

import courier_fields as cf  # noqa: E402


def load(query: str = "from:github.com") -> list[dict]:
    os.environ.setdefault("NOTMUCH_CONFIG", str(Path.home() / ".config/courier/notmuch-config"))
    import notmuch2

    db = notmuch2.Database(mode=notmuch2.Database.MODE.READ_ONLY)
    rows = []
    try:
        for message in db.messages(query, exclude_tags=[]):
            rows.append({"id": message.messageid, "thread": message.threadid, "path": str(message.path), "date": int(message.date),
                         "tags": set(message.tags)})
    finally:
        db.close()
    for row in rows:
        with open(row["path"], "rb") as handle:
            parsed = email.message_from_binary_file(handle, policy=email.policy.default)
        rich, plain = parsed.get_body(("html",)), parsed.get_body(("plain",))
        row.update(subject=str(parsed["Subject"] or ""), sender=str(parsed["From"] or ""),
                   list_id=str(parsed.get("List-ID", "")), x_sender=str(parsed.get("X-GitHub-Sender", "")),
                   reason=str(parsed.get("X-GitHub-Reason", "")),
                   html=_content(rich), text=_content(plain))
    rows.sort(key=lambda row: row["date"])
    return rows


def _content(part) -> str:
    if part is None:
        return ""
    try:
        return part.get_content()
    except (LookupError, ValueError):
        return (part.get_payload(decode=True) or b"").decode("utf-8", "replace")


def kind(row: dict) -> str:
    """GitHub's own event kind, from the Message-ID (for checking templates)."""
    mid = row["id"]
    if "github.com" not in mid:
        return "other:" + cf.sender_of(row["sender"])
    shape = re.sub(r"^[^/]+/[^/]+/", "", mid)
    shape = re.sub(r"[0-9a-f]{40}", "S", shape)
    shape = re.sub(r"CS_[\w-]+", "CS", shape)
    return re.sub(r"\d+", "N", shape)


# ---------------------------------------------------------------------------
# Oracles: what each field truly is, from sources the learner doesn't read


def repo_of(row: dict) -> str | None:
    match = re.match(r"\s*([\w.-]+/[\w.-]+)\s*<", row["list_id"])
    return match.group(1) if match else None


def ld_url(row: dict) -> str | None:
    """The address in GitHub's schema.org block (not a "url" someone pasted
    into a comment, as one email has)."""
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', row["html"], re.S)
    match = re.search(r'"url":\s*"([^"]+)"', block.group(1)) if block else None
    return html.unescape(match.group(1)) if match else None


def number_of(row: dict) -> str | None:
    match = re.search(r"/(?:pull|issues)/(\d+)[/@]", row["id"])
    return match.group(1) if match else None


def title_of(row: dict) -> str | None:
    match = re.match(r"^(?:Re: )?\[[^\]]+\] (.*) \((?:PR|Issue) #\d+\)$", cf.collapse(row["subject"]).strip())
    return match.group(1) if match else None


def comment_truth(row: dict) -> dict:
    repo, number = repo_of(row), number_of(row)
    return {"author": row["x_sender"] or None, "repo": repo, "number": number, "title": title_of(row),
            "ref": f"{repo}#{number}" if repo and number else None, "link": ld_url(row)}


def review_truth(row: dict) -> dict:
    first = row["text"].strip().splitlines()[0] if row["text"].strip() else ""
    match = re.match(r"^@\S+ (.+?) this pull request\.", first)
    return {"author": "@" + row["x_sender"] if row["x_sender"] else None, "action": match.group(1) if match else None,
            "number": number_of(row), "link": ld_url(row)}


def push_truth(row: dict) -> dict:
    text = row["text"]
    match = re.search(r"^@(\S+) pushed (\d+) commits?\.", text, re.M)
    commits = re.findall(r"^([0-9a-f]{40})\s+(.*)$", text, re.M)
    return {"author": "@" + row["x_sender"] if row["x_sender"] else None, "count": match.group(2) if match else None,
            "shas": [sha[:7] for sha, _ in commits] or None, "messages": [cf.collapse(m).strip() for _, m in commits] or None,
            "link": ld_url(row), "_first_sha": commits[0][0] if commits else None}


def ci_truth(row: dict) -> dict:
    text = row["text"]

    def line(name: str) -> str | None:
        match = re.search(rf"^{name}: (.+)$", text, re.M)
        return match.group(1).strip() if match else None

    jobs = re.findall(r"^\s+\* (.+?) (?:failed|cancelled|skipped|succeeded|timed out|action required)\b", text, re.M)
    return {"repo": line("Repository"), "workflow": line("Workflow"), "jobs": jobs or None, "link": line("View results")}


def advisory_truth(row: dict) -> dict:
    lines = [line for line in row["text"].splitlines()]
    first = next((line for line in lines if line.strip()), "")
    package = re.search(r"found in (\S+)\s*$", first)
    titled = next((re.match(r"^(.*) \((\w+) severity\)\s*$", line) for line in lines if re.match(r"^.* \(\w+ severity\)\s*$", line)), None)
    repos = re.findall(r"^\s+- ([\w.-]+/[\w.-]+)\s*$", row["text"], re.M)
    link = re.search(r"security advisory here: (\S+)", row["text"])
    return {"package": package.group(1) if package else None, "title": titled.group(1).strip() if titled else None,
            "severity": titled.group(2).capitalize() if titled else None, "repos": repos or None,
            "link": link.group(1) if link else None}


# ---------------------------------------------------------------------------
# What the "user" teaches on an email, given its true values


def comment_teach(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("author", truth["author"]),
        cf.Taught("ref", truth["ref"]),
        cf.Taught("link", "view it on GitHub", link=True),
        cf.Taught("repo", truth["repo"], subject=True),
        cf.Taught("number", truth["number"], subject=True),
        cf.Taught("title", truth["title"], subject=True),
    ]


def review_teach(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("author", truth["author"]),
        cf.Taught("action", truth["action"], after=truth["author"]),
        cf.Taught("link", "view it on GitHub", link=True),
        cf.Taught("number", truth["number"], subject=True),
    ]


def push_teach(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("author", truth["author"]),
        cf.Taught("count", truth["count"], after="pushed"),
        cf.Taught("shas", truth["shas"][0], many=True),
        cf.Taught("messages", truth["messages"][0], after=truth["shas"][0], many=True),
        cf.Taught("link", "View it on GitHub", link=True),
    ]


def ci_teach(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("repo", truth["repo"]),
        cf.Taught("workflow", truth["workflow"], after=truth["repo"]),
        cf.Taught("jobs", truth["jobs"][0], after="/ ", many=True),
        cf.Taught("link", "View workflow run", link=True),
    ]


def advisory_teach(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("package", truth["package"], subject=True),
        cf.Taught("title", truth["title"]),
        cf.Taught("severity", truth["severity"], after=truth["title"]),
        cf.Taught("repos", truth["repos"][0], after="Affected", many=True),
        cf.Taught("link", "View all alerts", link=True),
    ]


# Plain-text teaching: the same fields, selected in the text part.

def push_teach_text(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("author", truth["author"]),
        cf.Taught("count", truth["count"], after="pushed"),
        # The text part shows the whole hash; that's what one selects there.
        cf.Taught("shas", truth["_first_sha"], many=True),
        cf.Taught("messages", truth["messages"][0], after=truth["_first_sha"], many=True),
        cf.Taught("link", truth["link"], after="View it on GitHub"),
    ]


def review_teach_text(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("author", truth["author"]),
        cf.Taught("action", truth["action"], after=truth["author"]),
        cf.Taught("link", truth["link"], after="view it on GitHub"),
    ]


def ci_teach_text(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("repo", truth["repo"], after="Repository:"),
        cf.Taught("workflow", truth["workflow"], after="Workflow:"),
        cf.Taught("jobs", truth["jobs"][0], after="Jobs:", many=True),
        cf.Taught("link", truth["link"], after="View results:"),
    ]


def advisory_teach_text(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("package", truth["package"], subject=True),
        cf.Taught("title", truth["title"]),
        cf.Taught("severity", truth["severity"].lower(), after=truth["title"]),
        cf.Taught("repos", truth["repos"][0], after="used in", many=True),
        cf.Taught("link", truth["link"], after="advisory here:"),
    ]


def oauth_truth(row: dict) -> dict:
    """GitHub's text-only notice that an OAuth app was authorised. Its lines
    wrap at about 72 characters, so where a sentence breaks depends on the
    app's name: a hard case for reading by lines."""
    text = re.sub(r"\s+", " ", row["text"])
    sentence = re.search(r"A third-party OAuth application \((.+?)\) with (.+?) was recently authorized", text)
    link = re.search(r"Visit (https://\S+)", text)
    return {"app": sentence.group(1) if sentence else None, "access": sentence.group(2) if sentence else None,
            "link": link.group(1) if link else None}


def oauth_teach_text(truth: dict) -> list[cf.Taught]:
    return [
        cf.Taught("app", truth["app"]),
        cf.Taught("access", truth["access"], after=truth["app"]),
        cf.Taught("link", truth["link"], after="Visit"),
    ]


def strip_query(url: str | None) -> str | None:
    """A link without GitHub's ?email_source=…&email_token=… (the footer's
    links carry it, the ld+json address doesn't); the #fragment stays."""
    if not url:
        return url
    base, _, rest = url.partition("?")
    return base + ("#" + rest.split("#", 1)[1] if "#" in rest else "")


# name: (Message-ID kind or subject test that picks the template, oracle, teach (html), teach (text), comparers)
SPECS = {
    "PR comment": (lambda row: kind(row) == "pull/N/cN@github.com", comment_truth, comment_teach, None, {"link": strip_query}),
    "PR review": (lambda row: kind(row) == "pull/N/review/N@github.com", review_truth, review_teach, review_teach_text, {"link": strip_query}),
    "PR push": (lambda row: kind(row).startswith("pull/N/before"), push_truth, push_teach, push_teach_text,
                {"link": strip_query, "shas": lambda v: v[:7] if isinstance(v, str) else v}),
    "CI run failed": (lambda row: kind(row) == "check-suites/CS/N@github.com", ci_truth, ci_teach, ci_teach_text, {"link": strip_query}),
    "Issue comment": (lambda row: kind(row) == "issues/N/N@github.com", comment_truth, comment_teach, None, {"link": strip_query}),
    "Security advisory": (lambda row: "security advisory on" in row["subject"], advisory_truth, advisory_teach, advisory_teach_text,
                          {"link": strip_query, "severity": lambda v: v.capitalize() if isinstance(v, str) else v}),
    # Text only: no HTML part at all.
    "OAuth app added (text only)": (lambda row: not row["html"] and "OAuth application has been added" in row["subject"],
                                    oauth_truth, None, oauth_teach_text, {}),
}


def same(a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return [cf.collapse(x).strip() for x in a or []] == [cf.collapse(x).strip() for x in b or []]
    return (cf.collapse(a).strip() if a else a) == (cf.collapse(b).strip() if b else b)


def score(results: list[tuple[dict, cf.Result]], compare: dict) -> dict:
    """Per field: precision and recall (a list field item by item), and
    how many emails were flagged for teaching again."""
    out: dict[str, dict] = {}
    names = [name for name in results[0][0] if not name.startswith("_")] if results else []
    for name in names:
        tp = fp = fn = 0
        fix = compare.get(name, lambda v: v)
        for truth, result in results:
            want = truth.get(name)
            got = None if result.status == "reteach" else result.values.get(name)
            if name not in result.values:
                continue
            if isinstance(want, list) or isinstance(got, list):
                want_items = Counter(cf.collapse(x).strip() for x in (want or []))
                got_items = Counter(cf.collapse(fix(x)).strip() for x in (got or []))
                hit = sum((want_items & got_items).values())
                tp += hit
                fp += sum(got_items.values()) - hit
                fn += sum(want_items.values()) - hit
                continue
            want, got = fix(want), fix(got)
            if got and want and same(got, want):
                tp += 1
            else:
                fp += 1 if got else 0
                fn += 1 if want else 0
        if tp + fp + fn:
            out[name] = {"precision": tp / (tp + fp) if tp + fp else 1.0, "recall": tp / (tp + fn) if tp + fn else 1.0,
                         "tp": tp, "fp": fp, "fn": fn}
    return out


def run(rows: list[dict], examples: int, text: bool, show: str | None, sample: int) -> None:
    emails = [cf.Email(row["sender"], row["subject"], row["html"], row["text"], row["thread"]) for row in rows]
    groups = cf.templates(emails)
    template_of = {n: key for key, members in groups.items() for n in members}
    for name, (pick, oracle, teach_html, teach_text, compare) in SPECS.items():
        teach = teach_text if text else teach_html
        if teach is None:
            continue
        # The template: the biggest fingerprint group of this kind of email.
        chosen = Counter(template_of[n] for n, row in enumerate(rows) if pick(row) and (row["html"] or text)).most_common(1)
        if not chosen:
            continue
        key = chosen[0][0]
        members = groups[key]
        truths = {n: oracle(rows[n]) for n in members}
        teachable = [n for n in members if all(v for v in truths[n].values())]
        taught = teachable[:examples]
        view = (lambda n: cf.TextPage(rows[n]["text"])) if text else (lambda n: emails[n].page)
        corpus = [(view(n), rows[n]["subject"]) for n in members]
        template = cf.Template.learn([(view(n), rows[n]["subject"], teach(truths[n])) for n in taught], corpus)
        results = []
        for n in members:
            if n in taught:
                continue
            results.append((n, truths[n], template.extract(view(n), rows[n]["subject"])))
        scores = score([(t, r) for _, t, r in results], compare)
        flagged = sum(1 for _, _, r in results if r.status == "reteach")
        print(f"\n== {name} [{'text' if text else 'html'}, taught {len(taught)}]: {len(members)} emails, "
              f"read {len(results)}, flagged for reteach {flagged}")
        print("   subject pattern:", cf.words_pattern([cf.mask(cf.subject_parts(rows[n]['subject'])[1]) for n in members], 0.6))
        for field_name, s in scores.items():
            print(f"   {field_name:10s} P={s['precision']:.3f} R={s['recall']:.3f}  (tp {s['tp']}, fp {s['fp']}, fn {s['fn']})")
        for extractor in template.extractors:
            print(f"   · {extractor.name}: {'subject' if extractor.subject else 'body'} left={extractor.left!r} right={extractor.right!r} "
                  f"shape={extractor.shape!r} many={extractor.many} landmark={extractor.landmark[:30]!r} "
                  f"path={'/'.join(s + ('' if n is None else f'[{n}]') for s, n in extractor.path)[-70:]!r}")
        # Drift: the same template's extractors on emails of other GitHub
        # templates. They should be flagged, not read.
        others = [n for n, row in enumerate(rows) if template_of[n] != key and cf.sender_of(row["sender"]) == cf.sender_of(rows[members[0]]["sender"])
                  and (row["html"] or text)]
        outcome: Counter[str] = Counter()
        for n in others:
            result = template.extract(view(n), rows[n]["subject"])
            if result.status == "reteach":
                outcome["flagged"] += 1
                continue
            # Read: right or wrong? Only emails of the same kind have a truth.
            same_kind = pick(rows[n])
            truth = oracle(rows[n]) if same_kind else {}
            right = same_kind and all(same(compare.get(f, lambda v: v)(result.values.get(f)), compare.get(f, lambda v: v)(truth.get(f)))
                                      for f in truth if not f.startswith("_") and f in result.values)
            outcome["read, same kind, all right" if right else "read, same kind, some wrong" if same_kind else "read, other kind"] += 1
        print(f"   other templates of the sender ({len(others)}): {dict(outcome)}")
        if not text and examples == 1:
            print(f"   simulated redesigns of this template's emails: {drift(template, [(n, truths[n]) for n in members if n not in taught], rows, compare)}")
        if show == name:
            random.seed(7)
            for n, truth, result in random.sample(results, min(sample, len(results))):
                print("\n   ---", rows[n]["subject"][:90], "|", result.status, result.reason)
                for field_name in (k for k in truth if not k.startswith("_")):
                    got = result.values.get(field_name)
                    mark = "ok " if same(compare.get(field_name, lambda v: v)(got), compare.get(field_name, lambda v: v)(truth[field_name])) else "XX "
                    print(f"     {mark}{field_name}: truth={str(truth[field_name])[:90]!r} got={str(got)[:90]!r}")


# How a sender might change a template: what Courier must notice.
REDESIGNS = {
    # Every class renamed (a new design system).
    "classes renamed": lambda markup: re.sub(r'class="([^"]*)"', lambda m: 'class="' + " ".join(c + "-v2" for c in m.group(1).split()) + '"', markup),
    # A banner block added above everything (the header moves down).
    "banner added on top": lambda markup: '<p class="banner">GitHub is changing how notifications look.</p>' + markup,
    # The fixed words reworded.
    "wording changed": lambda markup: (markup.replace(" pushed ", " added ").replace("left a comment", "commented")
                                       .replace("this pull request", "this PR").replace("view it on GitHub", "open on GitHub")
                                       .replace("View it on GitHub", "Open on GitHub").replace("workflow run", "run")
                                       .replace("View workflow run", "Open run").replace(" severity", " risk")
                                       .replace("View all alerts", "See alerts").replace("Affected Repositories", "Repositories")),
}


def drift(template: cf.Template, emails: list[tuple[int, dict]], rows: list[dict], compare: dict) -> dict:
    """Per redesign: how many emails are flagged for teaching again, read
    right, or read wrong without a flag (the failure that matters)."""
    out = {}
    for name, change in REDESIGNS.items():
        counts: Counter[str] = Counter()
        for n, truth in emails:
            changed = change(rows[n]["html"])
            if changed == rows[n]["html"]:
                counts["unchanged"] += 1
                continue
            result = template.extract(cf.Page(cf.sanitize(changed)), rows[n]["subject"])
            if result.status == "reteach":
                counts["flagged"] += 1
                continue
            right = all(same(compare.get(f, lambda v: v)(result.values.get(f)), compare.get(f, lambda v: v)(truth.get(f)))
                        for f in truth if not f.startswith("_") and f in result.values)
            counts["read right" if right else "READ WRONG"] += 1
        out[name] = dict(counts)
    return out


def survey(rows: list[dict]) -> None:
    emails = [cf.Email(row["sender"], row["subject"], row["html"], row["text"], row["thread"]) for row in rows]
    groups = cf.templates(emails)
    sizes = sorted((len(m) for m in groups.values()), reverse=True)
    accounts = Counter(next((t.split("/", 1)[1] for t in row["tags"] if t.startswith("account/")), "?") for row in rows)
    print(f"emails {len(rows)} (by account: {dict(accounts)}), with HTML {sum(1 for r in rows if r['html'])}, text only {sum(1 for r in rows if not r['html'])}")
    print(f"senders: {dict(Counter(cf.sender_of(r['sender']) for r in rows))}")
    print(f"templates {len(groups)}; with >=5 emails {sum(1 for s in sizes if s >= 5)} holding {sum(s for s in sizes if s >= 5)} emails; singletons {sum(1 for s in sizes if s == 1)}")
    kinds = defaultdict(Counter)
    for key, members in groups.items():
        for n in members:
            kinds[key][kind(rows[n])] += 1
    purity = sum(c.most_common(1)[0][1] for c in kinds.values()) / len(rows)
    print(f"purity against GitHub's own event kind (Message-ID): {purity:.3f}")
    for extra in ("reason", "list_id"):
        split = Counter((template_of_key, rows[n][extra]) for template_of_key, members in groups.items() for n in members)
        print(f"  adding {extra} to the fingerprint would make {len(split)} templates")
    print("\nbiggest templates:")
    for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:15]:
        sender, frame, _, label = key.split("|")
        print(f"  {len(members):4d}  {sender:28s} {frame:16s} {label[:55]:55s} e.g. {rows[members[0]]['subject'][:70]!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", help="print a sample of one template's emails, truth and values, for checking by hand")
    parser.add_argument("--sample", type=int, default=12)
    args = parser.parse_args()
    rows = load()
    survey(rows)
    for text in (False, True):
        for examples in (1, 2):
            print(f"\n######## {'plain text' if text else 'HTML'}, {examples} taught example(s)")
            run(rows, examples, text, args.show, args.sample)


if __name__ == "__main__":
    main()
