"""GitHub, for the notification dock: the whole of an item, read with your own
gh, and the dock's buttons that act on GitHub as you.

Reading (courier_notify.enrich_feed, after a sync):
- a PR or issue comment: its whole body, its author (login, name, picture),
  and the conversation before it, oldest first;
- a review comment: the same, plus its file, line and diff hunk, its
  thread's earlier replies, and the thread's id (to resolve it);
- a review: its body and verdict;
- a failed run: its failing jobs, and the last lines of their failed steps
  (gh run view --log-failed), ANSI codes stripped;
- a review request: the PR's description (its first lines), its size, its
  checks, and its branches.

Only items in the dock are read (never silent mail), each once, a few per
sync, niced and spaced; when gh can't, the item keeps the email's own text.
Pictures are downloaded once into Junco's avatar cache (public https from
GitHub's avatar hosts only, via courier_avatars) and given to the dock as
file:// addresses: the dock never fetches anything.

Acting (courier_notify.dock_action, from the dock's button or send only,
never on its own): reply in the thread, 👍, resolve a review thread, re-run
a run's failed jobs, approve a PR. With COURIER_GH_DRY_RUN=1 a write prints
what it would do and does nothing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time

# A GitHub address as notification mail links it: the thing, and the
# comment, review or thread it's about.
LINK = re.compile(r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/"
                  r"(?:(?P<kind>pull|issues)/(?P<number>\d+)|commit/(?P<sha>[0-9a-f]{7,40})|actions/runs/(?P<run>\d+))"
                  r"(?:/[\w./-]*)?(?:\?[^#\s]*)?(?:#(?P<anchor>[\w-]+))?$")
ANCHORS = [(re.compile(r"issuecomment-(\d+)"), "issue-comment"), (re.compile(r"discussion_r(\d+)"), "review-comment"),
           (re.compile(r"pullrequestreview-(\d+)"), "review")]
# How much of each the dock gets (contract v2: body under ~20 kB, a hunk
# ~30 lines, a log ~20 lines per failing job and ~40 in all).
BODY_MOST = 20000
THREAD_MOST = 6
THREAD_BODY_MOST = 4000
HUNK_LINES = 30
LOG_LINES = 20
LOG_MOST = 40
PR_BODY_LINES = 15
# Between two reads: no bursts.
PAUSE = 1.0
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s?")
AVATAR_HOSTS = (".githubusercontent.com",)


class GitHubError(RuntimeError):
    """gh couldn't (not signed in, offline, no such thing): its first line."""


def parse(link: str) -> dict | None:
    """What a notification's GitHub address points at: {owner, repo, kind
    ("pr", "issue", "commit" or "run"), number|sha|run, and for a comment,
    review or review thread: anchor ("issue-comment", "review-comment",
    "review") and id}; None for anything else."""
    link = (link or "").strip()
    match = LINK.match(link)
    # No "." or ".." segment and no escapes: what a browser opens is what
    # the address says (the item's link is rebuilt from the parts: canonical).
    if not match or "%" in link or "\\" in link or any(part in (".", "..") for part in link.split("#")[0].split("?")[0].split("/")[3:]):
        return None
    found = {"owner": match["owner"], "repo": match["repo"]}
    if match["run"]:
        found |= {"kind": "run", "run": match["run"]}
    elif match["sha"]:
        found |= {"kind": "commit", "sha": match["sha"]}
    else:
        found |= {"kind": "pr" if match["kind"] == "pull" else "issue", "number": match["number"]}
    for pattern, anchor in ANCHORS:
        hit = pattern.fullmatch(match["anchor"] or "")
        if hit:
            found |= {"anchor": anchor, "id": hit.group(1)}
            break
    return found


def canonical(where: dict) -> str:
    """The address of what `where` points at, rebuilt from its parts: the
    page the dock opens is the one its buttons act on."""
    base = f"https://github.com/{where['owner']}/{where['repo']}"
    path = {"pr": f"/pull/{where.get('number')}", "issue": f"/issues/{where.get('number')}", "commit": f"/commit/{where.get('sha')}",
            "run": f"/actions/runs/{where.get('run')}"}[where["kind"]]
    anchor = {"issue-comment": "#issuecomment-", "review-comment": "#discussion_r", "review": "#pullrequestreview-"}.get(where.get("anchor", ""))
    return base + path + (anchor + where["id"] if anchor else "")


def gh(args: list[str], *, stdin: str | None = None, write: bool = False, timeout: int = 30) -> str:
    """gh, as you: its output; GitHubError when it fails. A write in dry run
    (COURIER_GH_DRY_RUN=1) does nothing and says what it would have done.
    Reads run niced."""
    if write and os.environ.get("COURIER_GH_DRY_RUN") == "1":
        return f"dry run: gh {' '.join(args)}"
    env = os.environ | {"GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1",
                        "GH_NO_EXTENSION_UPDATE_NOTIFIER": "1", "GH_PAGER": "cat"}
    try:
        result = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, timeout=timeout, env=env,
                                preexec_fn=None if write else (lambda: os.nice(19)))
    except (OSError, subprocess.TimeoutExpired) as problem:
        raise GitHubError(f"gh: {problem}") from None
    if result.returncode != 0:
        first = next((line for line in (result.stderr or result.stdout).splitlines() if line.strip()), "failed")
        raise GitHubError(first.strip()[:200])
    return result.stdout


def api(path: str):
    return json.loads(gh(["api", path]) or "null")


def text(value: str, most: int = BODY_MOST) -> str:
    """GitHub's text for the dock, as written (its lines, code blocks, <T>),
    but for control and direction-changing characters. The dock renders a
    fixed markup subset only (contract v2: paragraphs, lists, inline code,
    code blocks, quotes); HTML, links and images show as typed and nothing
    is fetched."""
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f‪-‮⁦-⁩]", "", (value or "").replace("\r\n", "\n"))
    return value if len(value) <= most else value[: most - 1].rstrip() + "…"


# Pictures -----------------------------------------------------------------------------


def avatar(login: str, url: str) -> str:
    """A person's GitHub picture as a file:// address, downloaded once into
    Junco's avatar cache; "" when there's none to be had."""
    import hashlib
    import urllib.parse

    import courier_avatars

    if not login or not url:
        return ""
    key = f"gh:{login.lower()}"
    path = courier_avatars.cache_dir() / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".png")
    if path.is_file():
        return path.as_uri()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not (parts.hostname or "").lower().endswith(AVATAR_HOSTS):
        return ""
    found = courier_avatars.fetch(url)
    if not found:
        return ""
    data, _ = found
    kind = courier_avatars.image_kind(data)
    name = courier_avatars.store(key, data, kind) if kind else None
    return (courier_avatars.cache_dir() / name).as_uri() if name else ""


_people: dict[str, dict] = {}


def person(user: dict | None) -> dict:
    """{login, name, avatar (file://)} for a GitHub user: their name and
    picture address asked once per login."""
    login = (user or {}).get("login", "")
    if not login:
        return {"login": "", "name": "", "avatar": ""}
    if login not in _people:
        try:
            _people[login] = api(f"users/{login}") or {}
        except GitHubError:
            _people[login] = {}
    found = _people[login]
    return {"login": login, "name": found.get("name") or "",
            "avatar": avatar(login, found.get("avatar_url") or (user or {}).get("avatar_url", ""))}


def entry(comment: dict) -> dict:
    """A thread entry: {who, avatar?, time, body}."""
    who = person(comment.get("user"))
    out = {"who": who["name"] or who["login"], "time": comment.get("created_at", ""), "body": text(comment.get("body", ""), THREAD_BODY_MOST)}
    if who["avatar"]:
        out["avatar"] = who["avatar"]
    return out


def hunk_lines(hunk: str, most: int = HUNK_LINES) -> list[str]:
    """A diff hunk as its lines, the header and the last ones kept (a review
    comment sits under the hunk's end)."""
    lines = [text(line, 400) for line in (hunk or "").replace("\r\n", "\n").split("\n") if line != ""]
    return lines if len(lines) <= most else lines[:1] + lines[-(most - 1):]


# Reading --------------------------------------------------------------------------------


def details(where: dict) -> dict:
    """The item's whole story, from GitHub: some of {body, who, image,
    context: {file, line, hunk}, thread: [{who, avatar?, time, body}] (oldest
    first), log: [lines], meta: {files, additions, deletions, ci, commits,
    base, head}, github: {Junco's own ids}}. Raises GitHubError when gh
    can't."""
    repo = f"repos/{where['owner']}/{where['repo']}"
    anchor = where.get("anchor")
    if anchor == "issue-comment":
        comment = api(f"{repo}/issues/comments/{where['id']}")
        earlier = [c for c in api(f"{repo}/issues/{where['number']}/comments?per_page=100") or [] if c.get("id", 0) < int(where["id"])]
        author = person(comment.get("user"))
        return {"body": text(comment.get("body", "")), "who": author["name"] or author["login"], "image": author["avatar"],
                "thread": [entry(c) for c in earlier[-THREAD_MOST:]],
                "github": {"login": author["login"], "comment_id": str(comment.get("id", where["id"]))}}
    if anchor == "review-comment":
        comment = api(f"{repo}/pulls/comments/{where['id']}")
        root = comment.get("in_reply_to_id") or comment.get("id")
        everything = api(f"{repo}/pulls/{where['number']}/comments?per_page=100") or []
        earlier = [c for c in everything if (c.get("id") == root or c.get("in_reply_to_id") == root) and c.get("id", 0) < comment.get("id", 0)]
        author = person(comment.get("user"))
        own = {"login": author["login"], "comment_id": str(comment.get("id", where["id"])), "thread_root": str(root)}
        thread = review_thread(where, int(root))
        if thread:
            own |= {"thread_id": thread["id"], "thread_resolved": thread["resolved"]}
        return {"body": text(comment.get("body", "")), "who": author["name"] or author["login"], "image": author["avatar"],
                "context": {"file": comment.get("path", ""), "line": int(comment.get("line") or comment.get("original_line") or 0),
                            "hunk": hunk_lines(comment.get("diff_hunk", ""))},
                "thread": [entry(c) for c in earlier[-THREAD_MOST:]], "github": own}
    if anchor == "review":
        review = api(f"{repo}/pulls/{where['number']}/reviews/{where['id']}")
        author = person(review.get("user"))
        return {"body": text(review.get("body", "")), "who": author["name"] or author["login"], "image": author["avatar"],
                "github": {"login": author["login"], "review_id": str(review.get("id", where["id"])),
                           "verdict": (review.get("state") or "").lower().replace("_", " ")}}
    if where["kind"] == "run":
        return run_details(where)
    if where["kind"] == "pr":
        return pr_details(where)
    return {}


def review_thread(where: dict, root: int) -> dict | None:
    """The review thread (its GraphQL id, and whether it's resolved) whose
    first comment is `root`."""
    query = ("query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$number)"
             "{reviewThreads(first:100){nodes{id isResolved comments(first:1){nodes{databaseId}}}}}}}")
    try:
        data = json.loads(gh(["api", "graphql", "-f", f"query={query}", "-f", f"owner={where['owner']}", "-f", f"repo={where['repo']}",
                              "-F", f"number={int(where['number'])}"]))
    except (GitHubError, ValueError):
        return None
    nodes = (((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {}).get("reviewThreads", {}).get("nodes", [])
    for node in nodes:
        first = (node.get("comments") or {}).get("nodes") or [{}]
        if first[0].get("databaseId") == root:
            return {"id": node.get("id", ""), "resolved": bool(node.get("isResolved"))}
    return None


def run_details(where: dict) -> dict:
    """A failed run: the last LOG_LINES of each failing job's failed steps
    (LOG_MOST in all), and its run id for a re-run."""
    repo = f"{where['owner']}/{where['repo']}"
    run = json.loads(gh(["run", "view", where["run"], "--repo", repo, "--json",
                         "databaseId,headBranch,headSha,conclusion,workflowName,jobs"]))
    failing = [job for job in run.get("jobs", []) if job.get("conclusion") not in ("success", "skipped", "neutral", None)]
    try:
        raw = gh(["run", "view", where["run"], "--repo", repo, "--log-failed"], timeout=60)
    except GitHubError:
        raw = ""
    by_job: dict[str, list[str]] = {}
    for line in raw.splitlines():
        job, _, rest = line.partition("\t")
        _, _, message = rest.partition("\t")
        message = TIMESTAMP.sub("", ANSI.sub("", message)).rstrip()
        if job:
            by_job.setdefault(job, []).append(text(message, 300))
    log: list[str] = []
    for job in failing or [{"name": name} for name in by_job]:
        log.append(f"── {job.get('name', '')}: {job.get('conclusion') or 'failed'}")
        log += by_job.get(job.get("name", ""), [])[-LOG_LINES:]
    jobs = [{"name": text(job.get("name", ""), 80), "state": "passed" if job.get("conclusion") == "success" else
             "running" if job.get("conclusion") in (None, "") else "failed"}
            for job in run.get("jobs", []) if job.get("conclusion") not in ("skipped", "neutral")]
    return {"log": log[-LOG_MOST:], "meta": {"ci": "failing", "head": run.get("headBranch", "")}, "jobs": jobs[:20],
            "github": {"run_id": str(run.get("databaseId", where["run"])), "failing": [job.get("name", "") for job in failing]}}


def pr_details(where: dict) -> dict:
    """A PR you're asked to review: its description's first lines, its size,
    its checks and its branches."""
    pr = json.loads(gh(["pr", "view", where["number"], "--repo", f"{where['owner']}/{where['repo']}", "--json",
                        "title,body,changedFiles,additions,deletions,statusCheckRollup,author,commits,baseRefName,headRefName,files"]))
    checks = [c.get("conclusion") or c.get("state") or c.get("status") or "" for c in pr.get("statusCheckRollup") or []]
    state = ("failing" if any(c in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED") for c in checks)
             else "running" if any(c in ("PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", "WAITING", "") for c in checks)
             else "passing" if checks else "none")
    author = person({"login": (pr.get("author") or {}).get("login", "")})
    body = "\n".join((pr.get("body") or "").replace("\r\n", "\n").split("\n")[:PR_BODY_LINES])
    return {"body": text(body), "who": author["name"] or author["login"], "image": author["avatar"],
            "meta": {"files": str(pr.get("changedFiles", "")), "additions": str(pr.get("additions", "")),
                     "deletions": str(pr.get("deletions", "")), "ci": state, "commits": str(len(pr.get("commits") or [])),
                     "base": pr.get("baseRefName", ""), "head": pr.get("headRefName", "")},
            # Its biggest changes first (the card shows three, then "+N more").
            "files": sorted(({"path": text(f.get("path", ""), 200), "additions": int(f.get("additions") or 0),
                              "deletions": int(f.get("deletions") or 0)} for f in pr.get("files") or [] if f.get("path")),
                            key=lambda f: -(f["additions"] + f["deletions"]))[:50],
            "github": {"title": pr.get("title", "")}}


# Acting (only from the dock's own button or send) ----------------------------------------


def done(output: str, result: str) -> str:
    """The one line the dock shows: the result, or in a dry run the command
    that would have run."""
    return output.strip() if output.startswith("dry run:") else result


def thread_root(where: dict, own: dict) -> str:
    """A review thread's first comment (GitHub replies only to it): read
    from GitHub, or asked now if the item wasn't read yet."""
    if own.get("thread_root"):
        return str(own["thread_root"])
    comment = api(f"repos/{where['owner']}/{where['repo']}/pulls/comments/{where['id']}") or {}
    return str(comment.get("in_reply_to_id") or comment.get("id") or where["id"])


def reply(where: dict, own: dict, body: str = "") -> str:
    """Your text as a reply: in a review comment's thread, else on the PR's
    or issue's conversation."""
    if not (body or "").strip():
        raise GitHubError("Nothing to send")
    repo = f"repos/{where['owner']}/{where['repo']}"
    if where.get("anchor") == "review-comment":
        root = thread_root(where, own)
        output = gh(["api", "--method", "POST", f"{repo}/pulls/{where['number']}/comments/{root}/replies", "-F", "body=@-"],
                    stdin=body, write=True)
    elif where.get("number"):
        output = gh(["api", "--method", "POST", f"{repo}/issues/{where['number']}/comments", "-F", "body=@-"], stdin=body, write=True)
    else:
        raise GitHubError("There's no conversation to reply in")
    return done(output, "Sent")


def react(where: dict, own: dict, body: str = "") -> str:
    repo = f"repos/{where['owner']}/{where['repo']}"
    comment = own.get("comment_id") or where.get("id")
    if where.get("anchor") == "review-comment":
        path = f"{repo}/pulls/comments/{comment}/reactions"
    elif where.get("anchor") == "issue-comment":
        path = f"{repo}/issues/comments/{comment}/reactions"
    else:
        raise GitHubError("Only a comment takes a reaction")
    return done(gh(["api", "--method", "POST", path, "-f", "content=+1"], write=True), "👍 added")


def resolve(where: dict, own: dict, body: str = "") -> str:
    if where.get("anchor") != "review-comment":
        raise GitHubError("Only a review thread can be resolved")
    thread = own.get("thread_id") or (review_thread(where, int(thread_root(where, own))) or {}).get("id")
    if not thread:
        raise GitHubError("Couldn't find the review thread")
    mutation = "mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}"
    return done(gh(["api", "graphql", "-f", f"query={mutation}", "-f", f"id={thread}"], write=True), "Thread resolved")


def rerun_failed(where: dict, own: dict, body: str = "") -> str:
    run = own.get("run_id") or where.get("run")
    if not run:
        raise GitHubError("No run to re-run")
    return done(gh(["run", "rerun", str(run), "--failed", "--repo", f"{where['owner']}/{where['repo']}"], write=True), "Re-run started")


def approve(where: dict, own: dict, body: str = "") -> str:
    if where.get("kind") != "pr" or not where.get("number"):
        raise GitHubError("Only a PR can be approved")
    return done(gh(["pr", "review", str(where["number"]), "--approve", "--repo", f"{where['owner']}/{where['repo']}"], write=True),
                "Approved")


# The dock's action ids (contract v2), and the names first used for two.
ACTIONS = {"reply": reply, "react-plus1": react, "react-+1": react, "resolve-thread": resolve, "resolve": resolve,
           "rerun-failed": rerun_failed, "approve": approve}


def pause() -> None:
    time.sleep(PAUSE)
