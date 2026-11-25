"""Builds Courier's built-in GitHub templates (engine/builtin_templates/
github.json) from real GitHub notifications, read-only and offline.

    python3 -I tools/build_builtin_templates.py [--check]

For each kind of GitHub email (PR comment, CI run failed, review, push…) it
picks the layouts (fingerprints) that kind comes in, teaches one email of
each the way a person would (the values found by a hand-written oracle),
learns the template with courier_fields from all that layout's emails, and
then keeps only GitHub's own boilerplate:

- fixed text: only what at least 90% of the layout's emails say, across
  3 or more repos and 3 or more threads, and that contains no name from the
  mail (repos, owners, logins, people, addresses);
- anchors, landmarks and link labels: checked word by word against the same
  names; one that holds any is an error, never shipped.

What it writes holds no value from the mail it learned from: no repo,
person, hash, number or subject (engine/tests/test_builtin_templates.py
checks the shapes; --check also scans it against the mail itself). It
prints, per template, how many of the layout's emails it reads with every
field right.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "tools"))

import courier_fields as cf  # noqa: E402
import teach_fields_eval as ev  # noqa: E402

OUT = ROOT / "engine" / "builtin_templates" / "github.json"
NOTIFICATIONS = "notifications@github.com"
# Service names GitHub's own boilerplate says ("view it on GitHub"); never
# counted as names from the mail.
SERVICE_WORDS = {"github", "dependabot", "actions", "copilot", "support", "noreply", "notifications", "the", "and"}


# What each field truly is, from the email itself (text part, subject,
# headers); the "user" selects these values when the builder teaches.

def subject_of(row: dict) -> str:
    return cf.collapse(row["subject"]).strip()


def first_line(row: dict) -> str:
    return next((line.strip() for line in row["text"].splitlines() if line.strip()), "")


def footer_link(row: dict) -> str | None:
    match = re.search(r"view it on GitHub:\s*\n\s*(https://\S+)", row["text"], re.I)
    return match.group(1) if match else ev.ld_url(row)


def comment_truth(row: dict) -> dict:
    truth = ev.comment_truth(row)
    return truth


def review_requested_truth(row: dict) -> dict:
    match = re.match(r"^@(\S+) requested your review on: ([\w.-]+/[\w.-]+)#(\d+) (.+)$", first_line(row))
    subject = re.match(r"^(?:Re: )?\[([^\]]+)\] (.*) \((?:PR|Issue) #(\d+)\)$", subject_of(row))
    return {"author": "@" + match.group(1) if match else None, "ref": f"{match.group(2)}#{match.group(3)}" if match else None,
            "repo": subject.group(1) if subject else None, "number": subject.group(3) if subject else None,
            "title": subject.group(2) if subject else None, "link": footer_link(row)}


def state_truth(row: dict) -> dict:
    match = re.match(r"^(Merged|Closed|Reopened) #(\d+)", first_line(row))
    subject = re.match(r"^(?:Re: )?\[([^\]]+)\] (.*) \((?:PR|Issue) #(\d+)\)$", subject_of(row))
    return {"action": match.group(1) if match else None, "number": match.group(2) if match else None,
            "repo": subject.group(1) if subject else None, "title": subject.group(2) if subject else None,
            "link": footer_link(row)}


def review_truth(row: dict) -> dict:
    truth = ev.review_truth(row)
    subject = re.match(r"^(?:Re: )?\[([^\]]+)\] (.*) \(PR #(\d+)\)$", subject_of(row))
    truth.update(repo=subject.group(1) if subject else None, title=subject.group(2) if subject else None)
    return truth


def push_truth(row: dict) -> dict:
    truth = ev.push_truth(row)
    subject = re.match(r"^(?:Re: )?\[([^\]]+)\] (.*) \(PR #(\d+)\)$", subject_of(row))
    truth.update(repo=subject.group(1) if subject else None, number=subject.group(3) if subject else None,
                 title=subject.group(2) if subject else None)
    truth["hashes"] = truth.pop("shas")
    truth.pop("_first_sha", None)
    return truth


CI_SUBJECT = re.compile(r"^\[[^\]]+\] ((?:PR )?[Rr]un [^:]+): (.+?) - (.+) \(([0-9a-f]{7,})\)$")


def ci_truth(row: dict) -> dict:
    truth = ev.ci_truth(row)
    subject = CI_SUBJECT.match(subject_of(row))
    # Each job's result as the designed version says it ("Failed in 3
    # seconds"), checked against the text part's word for it ("failed").
    results = [cf.collapse(text).strip() for text in
               re.findall(r">\s*((?:Failed|Cancelled|Timed out|Succeeded|Skipped|Action required)\b[^<]*?)\s*<", row["html"])]
    truth.update(status=subject.group(1) if subject else None, branch=subject.group(3) if subject else None,
                 commit=subject.group(4) if subject else None, results=results or None,
                 _states=re.findall(r"^\s+\* .+? (failed|cancelled|skipped|succeeded|timed out|action required)\b", row["text"], re.M))
    return truth


def commit_comment_truth(row: dict) -> dict:
    subject = re.match(r"^(?:Re: )?\[([^\]]+)\] (.*) \(([0-9a-f]{7,})\)$", subject_of(row))
    return {"repo": subject.group(1) if subject else None, "title": subject.group(2) if subject else None,
            "commit": subject.group(3) if subject else None, "link": footer_link(row)}


def digest_truth(row: dict) -> dict:
    match = re.search(r"for the week of (.+)$", subject_of(row))
    return {"week": match.group(1) if match else None}


def notice_truth(row: dict) -> dict:
    subject = subject_of(row)
    match = re.match(r"^\[GitHub\] (.+)$", subject)
    return {"notice": match.group(1) if match else subject}


# How the "user" teaches each kind: which text they select for each field.

def teach_comment(truth: dict) -> list:
    return [cf.Taught("author", truth["author"]), cf.Taught("ref", truth["ref"]),
            cf.Taught("link", "view it on GitHub", link=True),
            cf.Taught("repo", truth["repo"], subject=True), cf.Taught("number", truth["number"], subject=True),
            cf.Taught("title", truth["title"], subject=True)]


def teach_review(truth: dict) -> list:
    return [cf.Taught("author", truth["author"]), cf.Taught("action", truth["action"], after=truth["author"]),
            cf.Taught("link", "view it on GitHub", link=True),
            cf.Taught("repo", truth["repo"], subject=True), cf.Taught("number", truth["number"], subject=True),
            cf.Taught("title", truth["title"], subject=True)]


def teach_review_requested(truth: dict) -> list:
    return [cf.Taught("author", truth["author"]), cf.Taught("ref", truth["ref"]),
            cf.Taught("link", "view it on GitHub", link=True),
            cf.Taught("repo", truth["repo"], subject=True), cf.Taught("number", truth["number"], subject=True),
            cf.Taught("title", truth["title"], subject=True)]


def teach_state(truth: dict) -> list:
    return [cf.Taught("action", truth["action"]), cf.Taught("number", truth["number"], after=truth["action"]),
            cf.Taught("link", "view it on GitHub", link=True),
            cf.Taught("repo", truth["repo"], subject=True), cf.Taught("title", truth["title"], subject=True)]


def teach_push(truth: dict) -> list:
    return [cf.Taught("author", truth["author"]), cf.Taught("count", truth["count"], after="pushed"),
            cf.Taught("hashes", truth["hashes"][0], many=True),
            cf.Taught("messages", truth["messages"][0], after=truth["hashes"][0], many=True),
            cf.Taught("link", "View it on GitHub", link=True),
            cf.Taught("repo", truth["repo"], subject=True), cf.Taught("number", truth["number"], subject=True),
            cf.Taught("title", truth["title"], subject=True)]


def teach_ci(truth: dict) -> list:
    return [cf.Taught("repo", truth["repo"]), cf.Taught("workflow", truth["workflow"], after=truth["repo"]),
            cf.Taught("jobs", truth["jobs"][0], after="/ ", many=True),
            cf.Taught("results", truth["results"][0], after=truth["jobs"][0], many=True),
            cf.Taught("link", "View workflow run", link=True),
            cf.Taught("status", truth["status"], subject=True),
            cf.Taught("branch", truth["branch"], subject=True), cf.Taught("commit", truth["commit"], subject=True)]


def teach_advisory(truth: dict) -> list:
    return ev.advisory_teach(truth)


def teach_commit_comment(truth: dict) -> list:
    return [cf.Taught("link", "view it on GitHub", link=True), cf.Taught("repo", truth["repo"], subject=True),
            cf.Taught("commit", truth["commit"], subject=True), cf.Taught("title", truth["title"], subject=True)]


def teach_digest(truth: dict) -> list:
    return [cf.Taught("week", truth["week"], subject=True)]


def teach_notice(truth: dict) -> list:
    return [cf.Taught("notice", truth["notice"], subject=True)]


def kind_is(*shapes: str):
    return lambda row: ev.kind(row) in shapes


# id, kind (what notifications key on), name, which emails, the oracle, how
# it's taught, the surface, compare functions, and the most layouts kept.
SPECS = [
    ("github.pr-comment", "comment", "PR comment", kind_is("pull/N/cN@github.com"), comment_truth, teach_comment, "html"),
    ("github.issue-comment", "issue-comment", "Issue comment", kind_is("issues/N/N@github.com"), comment_truth, teach_comment, "html"),
    ("github.pr-review", "review", "PR review", kind_is("pull/N/review/N@github.com"), review_truth, teach_review, "html"),
    ("github.review-requested", "review-requested", "Review requested",
     lambda row: ev.kind(row) == "pull/N/issue_event/N@github.com" and first_line(row).startswith("@") and "requested your review" in first_line(row),
     review_requested_truth, teach_review_requested, "html"),
    ("github.pr-state", "state", "PR or issue closed, merged or reopened",
     lambda row: ev.kind(row) in ("pull/N/issue_event/N@github.com", "issue/N/issue_event/N@github.com", "issues/N/issue_event/N@github.com")
     and re.match(r"^(Merged|Closed|Reopened) #\d+", first_line(row)) is not None, state_truth, teach_state, "html"),
    ("github.pr-push", "push", "PR push", lambda row: ev.kind(row).startswith("pull/N/before"), push_truth, teach_push, "html"),
    ("github.ci-failed", "ci-failed", "Actions run failed", kind_is("check-suites/CS/N@github.com"), ci_truth, teach_ci, "html"),
    ("github.security-advisory", "security-advisory", "Security advisory", lambda row: "security advisory on" in row["subject"],
     ev.advisory_truth, teach_advisory, "html"),
    ("github.commit-comment", "commit-comment", "Commit comment", kind_is("commit/S/N@github.com"), commit_comment_truth,
     teach_commit_comment, "html"),
    ("github.dependabot-digest", "dependabot-digest", "Dependabot weekly digest",
     lambda row: "Your Dependabot alerts for the week of" in row["subject"], digest_truth, teach_digest, "html"),
    ("github.account-notice", "account-notice", "Account and security notice",
     lambda row: cf.sender_of(row["sender"]) in ("noreply@github.com", "support@github.com") and "Dependabot alerts" not in row["subject"],
     notice_truth, teach_notice, "html"),
]
# Layouts with fewer emails than this aren't learned on their own.
LEAST = 4


# The engine's own value shapes (courier_fields.SHAPES and the link's):
# its vocabulary, not the mail's ("[bot]" is in one).
ENGINE_SHAPES = {*cf.SHAPES, r"[\s\S]+", r"https?://\S+|mailto:\S+"}


# First steps of github.com addresses that are GitHub's own pages, not an
# owner: what follows /users/ or /orgs/ still is a name.
GITHUB_ROUTES = {"settings", "notifications", "orgs", "users", "sponsors", "features", "marketplace", "site", "security",
                 "about", "pricing", "login", "contact", "apps", "account", "customer-stories", "enterprise", "github",
                 "readme", "topics", "explore", "codespaces", "copilot", "advisories", "dependabot", "collections",
                 "logout", "join", "password_reset", "sessions", "team", "new", "organizations", "support", "mobile",
                 "trending", "events", "home", "dashboard", "issues", "pulls", "search", "invitations", "email",
                 "repositories", "enterprises", "user-attachments", "customer-terms"}


def recipients(row: dict) -> list[str]:
    """Who an email was to (names and addresses), from its file's headers."""
    import email
    import email.policy
    import email.utils

    try:
        with open(row["path"], "rb") as handle:
            head = email.message_from_binary_file(handle, policy=email.policy.default)
    except OSError:
        return []
    out = []
    for name, address in email.utils.getaddresses([str(head.get(h, "")) for h in ("To", "Cc", "Delivered-To")]):
        # GitHub's own reason addresses ("State change
        # <state_change@noreply.github.com>") say nothing of anyone.
        if not address.lower().endswith("github.com"):
            out += [name, address.split("@")[0]]
    return [item for item in out if item]


def value_tokens(rows: list[dict]) -> tuple[dict[str, str], set[str]]:
    """What a built-in template must never hold, from the mail it's learned
    from: names, as lowercased words with where each came from (repos and
    owners, logins and people, split into their parts too; workflows, jobs,
    branches and packages whole), and phrases (titles, commit messages)."""
    words: dict[str, str] = {}
    phrases: set[str] = set()

    def name(text: str | None, source: str) -> None:
        """A name and its parts ("lumenlabs/lumen-app": lumenlabs, lumen, app)."""
        for word in re.findall(r"[\w.-]{2,}", text or ""):
            for part in {word, *re.split(r"[._-]", word)}:
                if (len(part) >= 3 or part == word) and not part.isdigit() and part.lower() not in SERVICE_WORDS:
                    words.setdefault(part.lower(), source)

    def whole(text: str | None, source: str) -> None:
        """A value as a whole ("CI", "lint", "main")."""
        text = cf.collapse(text or "").strip().lower()
        if len(text) >= 2 and not text.isdigit() and text not in SERVICE_WORDS:
            words.setdefault(text, source)

    def phrase(text: str | None) -> None:
        text = cf.collapse(text or "").strip().lower()
        if len(text) >= 12:
            phrases.add(text)

    for row in rows:
        name(ev.repo_of(row), "repo")
        # Every repo, org and person a github.com link names (a digest lists
        # repos with no List-ID of their own), GitHub's own pages aside.
        for first, second in re.findall(r"https://github\.com/([\w.-]+)(?:/([\w.-]+))?", row["html"] + row["text"]):
            if first.lower() not in GITHUB_ROUTES:
                name(first, "link")
                name(second, "link")
            elif first.lower() in ("users", "orgs", "sponsors", "apps"):
                name(second, "link")
        for header in recipients(row):
            name(header, "recipient")
        name(row.get("x_sender", ""), "login")
        name(re.sub(r"<[^>]*>", "", row["sender"]), "sender name")
        bracket = re.match(r"^(?:Re: )?\[([^\]]+)\]", subject_of(row))
        if bracket and bracket.group(1) != "GitHub":
            name(bracket.group(1), "repo")
        phrase(cf.subject_parts(row["subject"])[1])
        for login in re.findall(r"(?<![\w.])@([\w-]{2,})", row["text"][:600]):
            name(login, "login")
        ci = ev.ci_truth(row)
        whole(ci["workflow"], "workflow")
        for job in ci["jobs"] or []:
            whole(job, "job")
        subject = CI_SUBJECT.match(subject_of(row))
        if subject:
            whole(subject.group(2), "workflow")
            whole(subject.group(3), "branch")
            phrase(subject.group(3))
        for message in re.findall(r"^[0-9a-f]{40}\s+(.*)$", row["text"], re.M):
            phrase(message)
        package = re.search(r"found in (\S+)\s*$", row["text"].strip().splitlines()[0] if row["text"].strip() else "")
        if package:
            whole(package.group(1), "package")
    return words, phrases


def words_in(text: str) -> set[str]:
    """The literal words of an anchor (a regular expression) or a text."""
    plain = re.sub(r"\\[a-zA-Z]|\[[^\]]*\]|[(){}?*+|^$\\]", " ", text or "")
    return {word.lower() for word in re.findall(r"[^\W\d_]{2,}", plain)}


def value_like(shape: str) -> bool:
    """A fixed text that is really a value: a masked number, hash or version
    ("#0", "h", "<= 0.0.0", "CVE-0-0") or a file's name ("package-lock.json")."""
    if re.fullmatch(r"[\w./-]+\.[a-z]{2,8}", shape):
        return True
    return bool(re.search(r"\b[0h]\b", shape)) and not re.search(r"[^\W\d_]{3,}", shape)


def sanitize(template: cf.Template, pages: list, subjects: list[str], repos: list[str], tokens: set[str]) -> tuple[dict, list[str]]:
    """The template with only boilerplate kept; problems found (anchors that
    hold a name from the mail)."""
    problems: list[str] = []
    seen: dict[str, tuple[set, set, int]] = {}
    for page, subject, repo in zip(pages, subjects, repos):
        for shape in {cf.text_shape(leaf.text) for leaf in page.leaves}:
            entry = seen.setdefault(shape, (set(), set(), 0))
            seen[shape] = (entry[0] | {repo}, entry[1] | {subject}, entry[2] + 1)
    total = len(pages)
    has_repos = any(repos)
    fixed = {}
    for shape in template.fixed:
        found_repos, found_subjects, count = seen.get(shape, (set(), set(), 0))
        if (count / total >= 0.9 and len(found_subjects) >= 3 and (not has_repos or len({r for r in found_repos if r}) >= 3)
                and not (words_in(shape) & set(tokens)) and len(shape) <= 160 and not re.search(r"https?://|@\w", shape)
                and not value_like(shape)):
            fixed[shape] = round(count / total, 3)
    template.fixed = fixed
    # Fields that couldn't be learned on this layout (no header to read an
    # author from) are simply not in it.
    template.unlearned = []
    for extractor in template.extractors:
        if extractor.landmark and extractor.landmark not in fixed:
            extractor.landmark = ""
        if extractor.label and fixed.get(extractor.label, 0) < 0.9:
            extractor.label = ""
        if extractor.shape not in ENGINE_SHAPES:
            problems.append(f"{extractor.name}: shape {extractor.shape!r} isn't one of the engine's")
        for side in (extractor.left, extractor.right):
            leaked = words_in(side) & set(tokens)
            if leaked:
                problems.append(f"{extractor.name}: anchor {side!r} holds {sorted(leaked)}")
    return template.to_json(), problems


def same(a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return [cf.collapse(str(x)).strip() for x in a or []] == [cf.collapse(str(x)).strip() for x in b or []]
    return (cf.collapse(str(a)).strip() if a is not None else None) == (cf.collapse(str(b)).strip() if b is not None else None)


def compare(name: str, got, want) -> bool:
    if name == "link":
        return ev.strip_query(got) == ev.strip_query(want)
    if name == "hashes":
        return same([g[:7] for g in got or []], want)
    if name == "severity":
        return same(got.capitalize() if isinstance(got, str) else got, want)
    if name in ("jobs", "results"):
        # The designed version lists the first 10 jobs; the text part, all.
        return same(got, (want or [])[:10])
    return same(got, want)


def differs(a: dict, b: dict) -> int:
    """How unlike two emails' values are: a second example most unlike the
    first teaches the most (another workflow, a branch with a slash)."""
    score = 0
    for key, value in a.items():
        other = b.get(key)
        one = value[0] if isinstance(value, list) and value else value
        two = other[0] if isinstance(other, list) and other else other
        if one != two:
            score += 1
            if isinstance(one, str) and isinstance(two, str):
                if cf.value_shape([one]) != cf.value_shape([two]):
                    score += 2
                # Punctuation the first hasn't ("(MOM-94)" in a title) says
                # where a value really ends.
                score += len(set(re.findall(r"[^\w\s]", two)) - set(re.findall(r"[^\w\s]", one)))
    return score


def novel_punctuation(a: dict, b: dict) -> int:
    """Punctuation in b's values that a's lack, most of all after a space
    (" (" in "Fix login (MOM-94)"): where a lazy anchor would end a value."""
    def marks(truth: dict) -> set[str]:
        return {mark for key, value in truth.items() if isinstance(value, str) and key != "link"
                for mark in re.findall(r"\s?[^\w\s]", value)}

    return sum(2 if mark[0].isspace() else 1 for mark in marks(b) - marks(a))


def evaluate(shipped: cf.Template, pages: list, rows: list[dict], members: list[int], truths: dict) -> tuple[int, Counter]:
    right: Counter = Counter()
    read = 0
    for index, n in enumerate(members):
        result = shipped.extract(pages[index], rows[n]["subject"])
        if result.status == "reteach":
            continue
        read += 1
        for field, want in truths[n].items():
            if not field.startswith("_") and want not in (None, [], ""):
                right[field] += compare(field, result.values.get(field), want)
    return read, right


def boilerplate_only(tokens) -> None:
    """Have the learner choose only among anchors that hold no name from
    the mail: "CI - " before a branch is a workflow's name, not GitHub's, so
    " - " is learned instead (courier_fields.anchor_variants, filtered)."""
    original = getattr(cf.anchor_variants, "original", cf.anchor_variants)

    def variants(contexts, side, most=4):
        return [(regex, score) for regex, score in original(contexts, side, most) if not (words_in(regex) & tokens)]

    variants.original = original
    cf.anchor_variants = variants


def build(rows: list[dict]) -> tuple[dict, list[str], list[str]]:
    tokens, phrases = value_tokens(rows)
    boilerplate_only(tokens.keys())
    emails = [cf.Email(r["sender"], r["subject"], r["html"], r["text"], r["thread"]) for r in rows]
    prints = [cf.fingerprint(e.sender, e.subject, e.page) for e in emails]
    everywhere = Counter(prints)
    templates, report, problems = [], [], []
    subject_fields: dict[str, dict] = {}
    for tid, kind, name, pick, truth_of, teach, _surface in SPECS:
        chosen = [n for n, row in enumerate(rows) if pick(row)]
        layouts = Counter(prints[n] for n in chosen)
        for fingerprint, count in layouts.most_common():
            if count < LEAST:
                continue
            members = [n for n in chosen if prints[n] == fingerprint]
            truths = {n: truth_of(rows[n]) for n in members}
            teachable = [n for n in members if all(v not in (None, [], "") for k, v in truths[n].items() if not k.startswith("_"))]
            if not teachable:
                report.append(f"{tid} {fingerprint}: {count} emails, none teachable; skipped")
                continue
            # The page every email of a template is read from: the designed
            # version, or the text when there's none (courier_templates'
            # Mail.page, the "html" surface).
            pages = [emails[n].page for n in members]
            corpus = list(zip(pages, [rows[n]["subject"] for n in members]))
            first = teachable[0]
            options = [[first]]
            if len(teachable) > 1:
                # A second example most unlike the first; and one whose
                # values hold punctuation the first's don't ("(MOM-94)" at
                # a title's end). Whichever reads the layout best is kept.
                for unlike in (differs, novel_punctuation):
                    second = max(teachable[1:], key=lambda n: unlike(truths[first], truths[n]))
                    if [first, second] not in options:
                        options.append([first, second])
            best = None
            for examples in options:
                learned = cf.Template.learn([(pages[members.index(n)], rows[n]["subject"], teach(truths[n])) for n in examples], corpus)
                data, found = sanitize(learned, pages, [cf.subject_parts(rows[n]["subject"])[1] for n in members],
                                       [ev.repo_of(rows[n]) or "" for n in members], tokens)
                shipped = cf.Template.from_json(data)
                read, right = evaluate(shipped, pages, rows, members, truths)
                # No names first, then the most fields right; two examples
                # when they do as well (they generalise more).
                rank = (not found, sum(right.values()), len(examples))
                if best is None or rank > best[0]:
                    best = (rank, examples, data, found, shipped, read, right)
            _, examples, data, found, shipped, read, right = best
            # The subject says the same thing whatever the layout: a kind's
            # subject fields learned on its biggest layout may read this
            # one's better than its own few emails taught.
            if kind in subject_fields and not found:
                swapped = dict(data, fields=[subject_fields[kind].get(item["name"], item) if item["subject"] else item
                                             for item in data["fields"]])
                other = cf.Template.from_json(swapped)
                other_read, other_right = evaluate(other, pages, rows, members, truths)
                if sum(other_right.values()) > sum(right.values()):
                    data, shipped, read, right = swapped, other, other_read, other_right
            subject_fields.setdefault(kind, {item["name"]: item for item in data["fields"] if item["subject"]})
            problems += [f"{tid} {fingerprint}: {p}" for p in found]
            accuracy = {e.name: f"{right[e.name]}/{count}" for e in shipped.extractors}
            share = count / everywhere[fingerprint]
            report.append(f"{tid} {fingerprint}: {count} emails ({share:.0%} of this layout's), taught on {len(examples)}, "
                          f"read {read}, right per field {accuracy}")
            templates.append({
                "id": f"{tid}.{len([t for t in templates if t['kind'] == kind]) + 1}",
                "kind": kind,
                "name": name,
                "surface": "html",
                "fingerprints": [fingerprint],
                "fields": [{"name": e.name, "list": e.many, "link": e.link, "subject": e.subject} for e in shipped.extractors],
                "learned": data,
            })
    out = {
        "about": "Courier's built-in GitHub templates, learned from GitHub's notification emails by "
                 "build_builtin_templates.py and kept to GitHub's own boilerplate: no repo, person, "
                 "hash, number or subject from any mail. Templates you teach override these.",
        "templates": templates,
    }
    leaks = scan(json.dumps(out), tokens.keys(), phrases)
    problems += [f"leak: {leak} ({tokens.get(leak, 'phrase')})" for leak in leaks]
    return out, report, problems


def scan(text: str, tokens: set[str], phrases: set[str]) -> list[str]:
    """Names and phrases from the mail found in a built-in file's text. Not
    read: fingerprints and ids (hashes of the markup, and GitHub's own
    sender) and the engine's own value shapes."""
    data = json.loads(text)
    for template in data.get("templates", []):
        template.pop("fingerprints", None)
        template.pop("id", None)
        for item in template.get("learned", {}).get("fields", []):
            if item.get("shape") in ENGINE_SHAPES:
                item.pop("shape")
    body = json.dumps(data, ensure_ascii=False).lower()
    found = [token for token in tokens if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", body)]
    found += [phrase for phrase in phrases if phrase in body]
    return sorted(set(found))


def load_rows(cache: Path | None) -> list[dict]:
    """GitHub's emails, read-only from the index (or from the cache an
    earlier run wrote: plain JSON, so reading it runs no code)."""
    if cache and cache.is_file():
        return json.loads(cache.read_text())
    rows = ev.load("from:github.com")
    for row in rows:
        row["tags"] = sorted(row["tags"])
    if cache:
        cache.write_text(json.dumps(rows))
        cache.chmod(0o600)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only scan the shipped file against the mail")
    parser.add_argument("--cache", help="a JSON file to keep the emails read in between runs (never in the repo)")
    args = parser.parse_args()
    rows = load_rows(Path(args.cache) if args.cache else None)
    if args.check:
        tokens, phrases = value_tokens(rows)
        leaks = scan(OUT.read_text(), tokens.keys(), phrases)
        print(f"scanned {OUT.relative_to(ROOT)} against {len(rows)} emails: {len(tokens)} names, {len(phrases)} phrases; "
              f"{'no' if not leaks else len(leaks)} matches")
        for leak in leaks:
            print("LEAK:", leak)
        return 1 if leaks else 0
    out, report, problems = build(rows)
    for line in report:
        print(line)
    for problem in problems:
        print("PROBLEM:", problem)
    if problems:
        print("not written: fix the problems first")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out['templates'])} templates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
