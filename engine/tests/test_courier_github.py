"""GitHub for the notification dock (courier_github.py): the links mail
carries, the whole story read per kind, and the buttons that act as you.

Nothing here reaches GitHub: gh is a stand-in that answers from fixtures and
records each command, and the module's subprocess is one that fails the test
if anything tries to run. No real post, reaction, re-run or approval."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import courier_github as g  # noqa: E402


def no_process(*args, **kwargs):
    raise AssertionError(f"a test tried to run {args[0] if args else kwargs.get('args')!r}")


NO_PROCESS = types.SimpleNamespace(run=no_process, TimeoutExpired=TimeoutError)
_guard = unittest.mock.patch.object(g, "subprocess", NO_PROCESS)


def setUpModule() -> None:
    _guard.start()


def tearDownModule() -> None:
    _guard.stop()


class FakeGh:
    """gh, answering from fixtures: {"api path or gh words": output}. Each
    call is kept as (args, stdin, write)."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.calls: list[tuple[list[str], str | None, bool]] = []

    def __call__(self, args, *, stdin=None, write=False, timeout=30):
        self.calls.append((list(args), stdin, write))
        if write:
            return ""
        if args[:2] == ["api", "graphql"]:
            key = "graphql"
        elif args[0] == "api":
            key = args[-1]
        else:
            key = " ".join(a for a in args if a not in ("--repo", "--json") and "," not in a and "/" not in a)
        if key not in self.answers:
            raise g.GitHubError(f"HTTP 404: Not Found ({key})")
        answer = self.answers[key]
        return answer if isinstance(answer, str) else json.dumps(answer)

    def writes(self):
        return [(args, stdin) for args, stdin, write in self.calls if write]


def user(login: str) -> dict:
    return {"login": login, "avatar_url": f"https://avatars.githubusercontent.com/u/{len(login)}?v=4"}


PEOPLE = {"users/tomas-r": {"login": "tomas-r", "name": "Tomas Ruiz", "avatar_url": "https://avatars.githubusercontent.com/u/7?v=4"},
          "users/priya-n": {"login": "priya-n", "name": "Priya Natarajan", "avatar_url": "https://avatars.githubusercontent.com/u/8?v=4"},
          "users/sam-o": {"login": "sam-o", "name": "", "avatar_url": "https://avatars.githubusercontent.com/u/9?v=4"}}
LONG_BODY = ("Could we batch these?\n\n- one query per team\n- retry on 429\n\n```ts\nawait sendInvites(team.members)\n```\n\n"
             "> quoted\n\n<img src=\"https://example.com/x.png\"> stays as typed‮")
HUNK = "@@ -38,6 +38,40 @@ export async function send()\n" + "\n".join(f"+line {n}" for n in range(1, 41))


def where(link: str) -> dict:
    found = g.parse(link)
    assert found is not None, link
    return found


class Links(unittest.TestCase):
    """The GitHub addresses notification mail links, and what each points at."""

    def test_each_link_type(self) -> None:
        base = "https://github.com/lumenlabs/lumen-app"
        self.assertEqual(g.parse(f"{base}/pull/274#issuecomment-123"),
                         {"owner": "lumenlabs", "repo": "lumen-app", "kind": "pr", "number": "274", "anchor": "issue-comment", "id": "123"})
        self.assertEqual(g.parse(f"{base}/pull/268#discussion_r1520"),
                         {"owner": "lumenlabs", "repo": "lumen-app", "kind": "pr", "number": "268", "anchor": "review-comment", "id": "1520"})
        self.assertEqual(g.parse(f"{base}/pull/268/files#discussion_r1520")["anchor"], "review-comment")
        self.assertEqual(g.parse(f"{base}/pull/268#pullrequestreview-99"),
                         {"owner": "lumenlabs", "repo": "lumen-app", "kind": "pr", "number": "268", "anchor": "review", "id": "99"})
        self.assertEqual(g.parse(f"{base}/issues/12#issuecomment-5"),
                         {"owner": "lumenlabs", "repo": "lumen-app", "kind": "issue", "number": "12", "anchor": "issue-comment", "id": "5"})
        self.assertEqual(g.parse(f"{base}/pull/274"), {"owner": "lumenlabs", "repo": "lumen-app", "kind": "pr", "number": "274"})
        self.assertEqual(g.parse(f"{base}/actions/runs/9182736450"),
                         {"owner": "lumenlabs", "repo": "lumen-app", "kind": "run", "run": "9182736450"})
        self.assertEqual(g.parse(f"{base}/actions/runs/91/job/7?pr=3")["run"], "91")
        self.assertEqual(g.parse(f"{base}/commit/4f2a9c1e#commitcomment-8"),
                         {"owner": "lumenlabs", "repo": "lumen-app", "kind": "commit", "sha": "4f2a9c1e"})
        self.assertEqual(g.parse("https://github.com/lumenlabs/.github/pull/1")["repo"], ".github")

    def test_the_link_is_rebuilt_from_its_parts(self) -> None:
        # What the dock opens is what its buttons act on: no "..", no escapes.
        for link in ("https://github.com/o/r/pull/1/../../../evil/x/pull/2#discussion_r5",
                     "https://github.com/o/r/pull/1/./files#discussion_r5", "https://github.com/o/r/pull/1/%2e%2e/%2e%2e/x/y/pull/2",
                     "https://github.com/o/r/pull/1/files\\..\\x#discussion_r5"):
            self.assertIsNone(g.parse(link), link)
        for link, made in (("https://github.com/o/r/pull/268/files?w=1#discussion_r1520", "https://github.com/o/r/pull/268#discussion_r1520"),
                           ("https://github.com/o/r/pull/274#issuecomment-8", "https://github.com/o/r/pull/274#issuecomment-8"),
                           ("https://github.com/o/r/pull/268#pullrequestreview-99", "https://github.com/o/r/pull/268#pullrequestreview-99"),
                           ("https://github.com/o/r/issues/12", "https://github.com/o/r/issues/12"),
                           ("https://github.com/o/r/actions/runs/91/job/7?pr=3", "https://github.com/o/r/actions/runs/91"),
                           ("https://github.com/o/r/commit/4f2a9c1e", "https://github.com/o/r/commit/4f2a9c1e")):
            self.assertEqual(g.canonical(where(link)), made)
            self.assertEqual(g.parse(made), where(link))  # the same thing

    def test_what_isnt_a_github_item(self) -> None:
        for link in ("", "https://example.com/a/b/pull/1", "http://github.com/a/b/pull/1", "https://github.com/a/b",
                     "https://github.com/a/b/pull/x", "https://github.com.evil.example/a/b/pull/1", "https://github.com/../x/pull/1",
                     "https://github.com/a/../pull/1", "https://github.com/a/b/pull/1 extra", "javascript:alert(1)"):
            self.assertIsNone(g.parse(link), link)


class Reading(unittest.TestCase):
    """The whole story per kind, from stand-in gh answers."""

    def setUp(self) -> None:
        g._people.clear()
        self.avatars = unittest.mock.patch.object(g, "avatar", side_effect=lambda login, url: f"file:///cache/{login}.png")
        self.avatars.start()

    def tearDown(self) -> None:
        self.avatars.stop()

    def read(self, link: str, answers: dict) -> tuple[dict, FakeGh]:
        fake = FakeGh(PEOPLE | answers)
        with unittest.mock.patch.object(g, "gh", fake):
            return g.details(where(link)), fake

    def test_a_pr_comment_and_the_conversation_before_it(self) -> None:
        repo = "repos/lumenlabs/lumen-app"
        comments = [{"id": n, "user": user(who), "created_at": f"2026-11-25T0{n}:00:00Z", "body": f"comment {n}"}
                    for n, who in ((1, "priya-n"), (2, "sam-o"), (3, "priya-n"), (4, "sam-o"), (5, "priya-n"), (6, "sam-o"), (7, "priya-n"),
                                   (9, "sam-o"))]
        found, fake = self.read("https://github.com/lumenlabs/lumen-app/pull/274#issuecomment-8", {
            f"{repo}/issues/comments/8": {"id": 8, "user": user("tomas-r"), "body": LONG_BODY, "created_at": "2026-11-25T08:00:00Z"},
            f"{repo}/issues/274/comments?per_page=100": comments})
        self.assertEqual(found["who"], "Tomas Ruiz")
        self.assertEqual(found["image"], "file:///cache/tomas-r.png")
        self.assertIn("```ts\nawait sendInvites(team.members)\n```", found["body"])  # the markup subset, as written
        self.assertIn('<img src="https://example.com/x.png"> stays as typed', found["body"])  # literal: the dock fetches nothing
        self.assertNotIn("‮", found["body"])  # no direction tricks
        # The 6 comments just before it, oldest first; none after it.
        self.assertEqual([t["body"] for t in found["thread"]], [f"comment {n}" for n in (2, 3, 4, 5, 6, 7)])
        self.assertEqual(found["thread"][0], {"who": "sam-o", "time": "2026-11-25T02:00:00Z", "body": "comment 2",
                                              "avatar": "file:///cache/sam-o.png"})  # no name: the login
        self.assertEqual(found["github"], {"login": "tomas-r", "comment_id": "8"})
        self.assertFalse(fake.writes())
        self.assertEqual(sum(1 for args, _, _ in fake.calls if args[-1] == "users/priya-n"), 1)  # each person asked once

    def test_a_review_comment_with_its_hunk_and_thread(self) -> None:
        repo = "repos/lumenlabs/lumen-app"
        root = {"id": 1518, "user": user("priya-n"), "body": "Why a loop?", "created_at": "2026-11-25T07:00:00Z", "path": "src/x.ts",
                "line": 42, "diff_hunk": HUNK}
        reply = {"id": 1520, "in_reply_to_id": 1518, "user": user("tomas-r"), "body": LONG_BODY, "created_at": "2026-11-25T08:00:00Z",
                 "path": "src/invites/send.ts", "line": None, "original_line": 42, "diff_hunk": HUNK}
        other = {"id": 1519, "user": user("sam-o"), "body": "elsewhere", "created_at": "2026-11-25T07:30:00Z"}
        graphql = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [
            {"id": "PRRT_other", "isResolved": True, "comments": {"nodes": [{"databaseId": 1519}]}},
            {"id": "PRRT_this", "isResolved": False, "comments": {"nodes": [{"databaseId": 1518}]}}]}}}}}
        found, fake = self.read("https://github.com/lumenlabs/lumen-app/pull/268#discussion_r1520", {
            f"{repo}/pulls/comments/1520": reply, f"{repo}/pulls/268/comments?per_page=100": [root, other, reply], "graphql": graphql})
        self.assertEqual(found["context"]["file"], "src/invites/send.ts")
        self.assertEqual(found["context"]["line"], 42)  # outdated: its original line
        hunk = found["context"]["hunk"]
        self.assertEqual(len(hunk), 30)  # at most ~30: the header and the last lines (the comment sits under the end)
        self.assertTrue(hunk[0].startswith("@@ -38,6"))
        self.assertEqual(hunk[-1], "+line 40")
        self.assertEqual([t["who"] for t in found["thread"]], ["Priya Natarajan"])  # its own thread only
        self.assertEqual(found["github"], {"login": "tomas-r", "comment_id": "1520", "thread_root": "1518", "thread_id": "PRRT_this",
                                           "thread_resolved": False})
        graphql_call = next(args for args, _, _ in fake.calls if args[:2] == ["api", "graphql"])
        self.assertIn("owner=lumenlabs", graphql_call)
        self.assertEqual(graphql_call[graphql_call.index("owner=lumenlabs") - 1], "-f")  # names stay strings
        self.assertFalse(fake.writes())

    def test_a_review(self) -> None:
        found, _ = self.read("https://github.com/lumenlabs/lumen-app/pull/268#pullrequestreview-99", {
            "repos/lumenlabs/lumen-app/pulls/268/reviews/99": {"id": 99, "user": user("priya-n"), "state": "CHANGES_REQUESTED",
                                                              "body": "A few things."}})
        self.assertEqual((found["who"], found["body"], found["github"]["verdict"]), ("Priya Natarajan", "A few things.",
                                                                                   "changes requested"))

    def test_a_failed_run_and_its_logs(self) -> None:
        run = {"databaseId": 91, "headBranch": "main", "headSha": "4f2a9c1", "conclusion": "failure", "workflowName": "CI",
               "jobs": [{"name": "build", "conclusion": "success"}, {"name": "test (22.x)", "conclusion": "failure"},
                        {"name": "lint", "conclusion": "failure"}]}
        lines = [f"test (22.x)\tRun tests\t2026-11-25T08:00:{n:02d}.1234567Z \x1b[31mline {n}\x1b[0m" for n in range(30)]
        lines += ["lint\tLint\t2026-11-25T08:01:00.0000000Z error  'retries' is never used", "lint\tLint\t2026-11-25T08:01:01Z ✖ 1 problem"]
        found, fake = self.read("https://github.com/lumenlabs/lumen-app/actions/runs/91", {
            "run view 91": run, "run view 91 --log-failed": "\n".join(lines)})
        self.assertEqual(found["log"][0], "── test (22.x): failure")
        self.assertEqual(found["log"][1:21], [f"line {n}" for n in range(10, 30)])  # the last 20, ANSI and timestamps gone
        self.assertEqual(found["log"][21:], ["── lint: failure", "error  'retries' is never used", "✖ 1 problem"])
        self.assertLessEqual(len(found["log"]), g.LOG_MOST)
        self.assertEqual(found["meta"], {"ci": "failing", "head": "main"})
        self.assertEqual(found["github"], {"run_id": "91", "failing": ["test (22.x)", "lint"]})
        self.assertFalse(fake.writes())

    def test_a_pr_to_review(self) -> None:
        pr = {"title": "Team invites", "body": "\r\n".join(f"line {n}" for n in range(1, 30)), "changedFiles": 7, "additions": 214,
              "deletions": 38, "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"status": "IN_PROGRESS", "conclusion": ""}],
              "author": {"login": "priya-n"}, "commits": [{}] * 5, "baseRefName": "main", "headRefName": "feature/team-invites"}
        found, _ = self.read("https://github.com/lumenlabs/lumen-app/pull/274", {"pr view 274": pr})
        self.assertEqual(found["body"].split("\n"), [f"line {n}" for n in range(1, 16)])  # its first ~15 lines
        self.assertEqual(found["meta"], {"files": "7", "additions": "214", "deletions": "38", "ci": "running", "commits": "5",
                                         "base": "main", "head": "feature/team-invites"})
        self.assertEqual((found["who"], found["image"]), ("Priya Natarajan", "file:///cache/priya-n.png"))

    def test_checks_read_as_one_state(self) -> None:
        for checks, state in (([], "none"), ([{"conclusion": "SUCCESS"}], "passing"), ([{"conclusion": "FAILURE"}, {"status": "QUEUED"}],
                                                                                       "failing"), ([{"state": "PENDING"}], "running")):
            pr = {"title": "t", "body": "", "statusCheckRollup": checks, "author": {"login": "priya-n"}, "commits": []}
            found, _ = self.read("https://github.com/lumenlabs/lumen-app/pull/1", {"pr view 1": pr})
            self.assertEqual(found["meta"]["ci"], state, checks)

    def test_gh_failing_says_why(self) -> None:
        with self.assertRaises(g.GitHubError):
            self.read("https://github.com/lumenlabs/lumen-app/pull/274#issuecomment-404", {})


class Pictures(unittest.TestCase):
    """A person's picture, downloaded once, from GitHub's avatar hosts only."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.env = unittest.mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.folder.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.folder.cleanup()

    def test_only_github_hosts_over_https_and_once(self) -> None:
        import courier_avatars

        png = b"\x89PNG\r\n\x1a\n" + b"0" * 32

        def store(key, data, kind):
            name = __import__("hashlib").sha1(key.encode()).hexdigest()[:16] + ".png"
            courier_avatars.cache_dir().mkdir(parents=True, exist_ok=True)
            (courier_avatars.cache_dir() / name).write_bytes(data)
            return name

        with unittest.mock.patch.object(courier_avatars, "fetch", return_value=(png, "image/png")) as fetched, \
                unittest.mock.patch.object(courier_avatars, "store", side_effect=store):
            self.assertEqual(g.avatar("evil", "https://example.com/a.png"), "")
            self.assertEqual(g.avatar("evil", "http://avatars.githubusercontent.com/u/1"), "")
            self.assertEqual(g.avatar("evil", "https://avatars.githubusercontent.com.evil.example/u/1"), "")
            fetched.assert_not_called()
            first = g.avatar("Tomas-R", "https://avatars.githubusercontent.com/u/7?v=4")
            again = g.avatar("tomas-r", "https://avatars.githubusercontent.com/u/7?v=4")
        self.assertTrue(first.startswith("file://") and first.endswith(".png"))
        self.assertEqual(first, again)
        self.assertEqual(fetched.call_count, 1)  # downloaded once; the dock gets the file


class Acting(unittest.TestCase):
    """The dock's GitHub buttons: the exact gh command, nothing else."""

    def act(self, action: str, link: str, own: dict | None = None, text: str = "", answers: dict | None = None):
        fake = FakeGh(answers or {})
        with unittest.mock.patch.object(g, "gh", fake):
            return g.ACTIONS[action](where(link), own or {}, text), fake

    def test_replies(self) -> None:
        said = "Thanks, done in 9c1e0b2.\n\n```ts\nfoo()\n```"
        result, fake = self.act("reply", "https://github.com/o/r/pull/268#discussion_r1520", {"thread_root": "1518"}, said)
        self.assertEqual(result, "Sent")
        self.assertEqual(fake.writes(), [(["api", "--method", "POST", "repos/o/r/pulls/268/comments/1518/replies", "-F", "body=@-"], said)])
        result, fake = self.act("reply", "https://github.com/o/r/pull/274#issuecomment-8", {}, "Sounds good")
        self.assertEqual(fake.writes(), [(["api", "--method", "POST", "repos/o/r/issues/274/comments", "-F", "body=@-"], "Sounds good")])
        # A review comment not read yet: its thread's first comment is asked for (GitHub replies only to that).
        result, fake = self.act("reply", "https://github.com/o/r/pull/268#discussion_r1520", {}, "ok",
                                {"repos/o/r/pulls/comments/1520": {"id": 1520, "in_reply_to_id": 1518}})
        self.assertEqual(fake.writes()[0][0][3], "repos/o/r/pulls/268/comments/1518/replies")

    def test_an_empty_reply_is_never_sent(self) -> None:
        for text in ("", "   ", "\n\t\n"):
            with self.assertRaises(g.GitHubError):
                self.act("reply", "https://github.com/o/r/pull/274#issuecomment-8", {}, text)

    def test_reactions_resolve_rerun_and_approve(self) -> None:
        result, fake = self.act("react-plus1", "https://github.com/o/r/pull/268#discussion_r1520", {"comment_id": "1520"})
        self.assertEqual((result, fake.writes()[0][0]), ("👍 added", ["api", "--method", "POST", "repos/o/r/pulls/comments/1520/reactions",
                                                                      "-f", "content=+1"]))
        _, fake = self.act("react-plus1", "https://github.com/o/r/issues/12#issuecomment-5")
        self.assertEqual(fake.writes()[0][0][3], "repos/o/r/issues/comments/5/reactions")
        result, fake = self.act("resolve-thread", "https://github.com/o/r/pull/268#discussion_r1520", {"thread_id": "PRRT_this"})
        args = fake.writes()[0][0]
        self.assertEqual((result, args[:2], args[-2:]), ("Thread resolved", ["api", "graphql"], ["-f", "id=PRRT_this"]))
        self.assertIn("resolveReviewThread", args[3])
        result, fake = self.act("rerun-failed", "https://github.com/o/r/actions/runs/91", {"run_id": "91"})
        self.assertEqual((result, fake.writes()[0][0]), ("Re-run started", ["run", "rerun", "91", "--failed", "--repo", "o/r"]))
        result, fake = self.act("approve", "https://github.com/o/r/pull/274")
        self.assertEqual((result, fake.writes()[0][0]), ("Approved", ["pr", "review", "274", "--approve", "--repo", "o/r"]))

    def test_what_an_action_cant_do(self) -> None:
        for action, link in (("react-plus1", "https://github.com/o/r/pull/268#pullrequestreview-9"),
                             ("resolve-thread", "https://github.com/o/r/pull/274#issuecomment-8"),
                             ("approve", "https://github.com/o/r/actions/runs/91"),
                             ("approve", "https://github.com/o/r/issues/12")):
            with self.assertRaises(g.GitHubError, msg=action):
                self.act(action, link)

    def test_dry_run_says_the_command_and_runs_nothing(self) -> None:
        # The real gh(), with no stand-in: the guard fails the test if it runs anything.
        with unittest.mock.patch.dict(os.environ, {"COURIER_GH_DRY_RUN": "1"}):
            self.assertEqual(g.ACTIONS["rerun-failed"](where("https://github.com/o/r/actions/runs/91"), {}, ""),
                             "dry run: gh run rerun 91 --failed --repo o/r")
            self.assertEqual(g.ACTIONS["approve"](where("https://github.com/o/r/pull/274"), {}, ""),
                             "dry run: gh pr review 274 --approve --repo o/r")
            self.assertTrue(g.ACTIONS["reply"](where("https://github.com/o/r/pull/268#discussion_r1520"), {"thread_root": "1518"}, "hi")
                            .startswith("dry run: gh api --method POST repos/o/r/pulls/268/comments/1518/replies"))
        with self.assertRaises(AssertionError):  # and without it, the guard holds
            g.gh(["pr", "review", "1", "--approve"], write=True)

    def test_gh_failure_is_one_line(self) -> None:
        failed = types.SimpleNamespace(returncode=1, stdout="", stderr="\nHTTP 403: Resource not accessible\nmore\n")
        with unittest.mock.patch.object(g, "subprocess", types.SimpleNamespace(run=lambda *a, **k: failed, TimeoutExpired=TimeoutError)):
            with self.assertRaises(g.GitHubError) as caught:
                g.gh(["api", "x"])
        self.assertEqual(str(caught.exception), "HTTP 403: Resource not accessible")


if __name__ == "__main__":
    unittest.main()
