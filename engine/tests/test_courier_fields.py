"""Fields taught by example (courier_fields.py), on made-up emails shaped
like GitHub's notifications. No real mail here."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import courier_fields as cf  # noqa: E402

FOOTER_PUSH = (
    '<p style="font-size:small;-webkit-text-size-adjust:none;color:#666;">&mdash;<br />'
    '<a href="{link}">View it on GitHub</a> or <a href="https://github.com/notifications/unsubscribe-auth/X">unsubscribe</a>.'
    '<br />You are receiving this because you are subscribed to this thread.'
    '<img src="https://github.com/notifications/beacon/X.gif" height="1" width="1" alt="" />'
    '<span style="color: transparent; display: none; visibility: hidden">Message ID: <span>&lt;x@github.com&gt;</span></span></p>'
    '<script type="application/ld+json">[{{"@type": "EmailMessage"}}]</script>'
)
FOOTER_REPLY = (
    '<p style="font-size:small;-webkit-text-size-adjust:none;color:#666;">&mdash;<br />Reply to this email directly, '
    '<a href="{link}">view it on GitHub</a>, or <a href="https://github.com/notifications/unsubscribe-auth/X">unsubscribe</a>.'
    '<br />You are receiving this because {why}.</p>'
)


def push(author: str, commits: list[tuple[str, str]], link: str, mention_class: str = "user-mention",
         verb: str = "pushed", sha_class: str = "commit-link") -> str:
    rows = "".join(f'<li><a class="{sha_class}" href="https://github.com/o/r/commit/{sha}">{sha[:7]}</a>  {message}</li>\n'
                   for sha, message in commits)
    noun = "commit" if len(commits) == 1 else "commits"
    return (f'<p><a href="https://github.com/{author}" class="{mention_class}">@{author}</a> {verb} {len(commits)} {noun}.</p>\n'
            f"<ul>\n{rows}</ul>\n" + FOOTER_PUSH.format(link=link))


def review(author: str, action: str, body: str, link: str) -> str:
    return (f"<p></p>\n<p><b>@{author}</b> {action} this pull request.</p>\n{body}\n"
            + FOOTER_REPLY.format(link=link, why="you authored the thread"))


def comment(author: str, repo: str, number: int, body: str, link: str) -> str:
    return (f'<div style="display: flex; align-items: center;"><img height="20" width="20" style="border-radius:50%" '
            f'src="https://avatars.githubusercontent.com/u/1?s=20&amp;v=4" /><strong>{author}</strong> left a comment '
            f'<a href="{link}">({repo}#{number})</a></div>\n{body}\n'
            + FOOTER_REPLY.format(link=link, why="you were mentioned"))


def sha(n: int) -> str:
    return f"{n:07x}" + "a" * 33


def page(markup: str) -> cf.Page:
    return cf.Page(cf.sanitize(markup))


class PageTest(unittest.TestCase):
    def test_text_pieces_know_their_place(self) -> None:
        p = page(push("alice", [(sha(1), "Fix the parser"), (sha(2), "Add tests")], "https://github.com/o/r/pull/1"))
        texts = [leaf.text for leaf in p.leaves]
        self.assertIn("@alice", texts)
        self.assertIn(" pushed 2 commits.", texts)
        self.assertIn("@alice pushed 2 commits.", p.text)
        mention = next(leaf for leaf in p.leaves if leaf.text == "@alice")
        self.assertEqual(mention.path, (("p", 0), ("a.user-mention", 0)))
        self.assertEqual(mention.href, "https://github.com/alice")
        second = [leaf for leaf in p.leaves if leaf.path[-1][0] == "a.commit-link"][1]
        self.assertEqual(second.path, (("ul", 0), ("li", 1), ("a.commit-link", 0)))
        self.assertIs(p.leaf_at(p.text.index("Add tests") + 2).text.strip() == "Add tests", True)

    def test_what_the_reader_hides_is_not_text(self) -> None:
        p = page(push("alice", [(sha(1), "Fix")], "https://github.com/o/r/pull/1"))
        self.assertNotIn("Message ID", p.text)
        self.assertNotIn("EmailMessage", p.text)


class TemplateTest(unittest.TestCase):
    def test_one_row_or_many_is_one_template(self) -> None:
        one = page(push("alice", [(sha(1), "Fix")], "https://x/1"))
        many = page(push("bob", [(sha(n), f"Change {n}") for n in range(5)], "https://x/2"))
        self.assertEqual(cf.fingerprint("GitHub <notifications@github.com>", "Re: [o/r] A (PR #1)", one),
                         cf.fingerprint("Bob <notifications@github.com>", "Re: [o/r] B c d (PR #22)", many))

    def test_what_people_wrote_does_not_change_the_template(self) -> None:
        short = page(comment("alice", "o/r", 1, "<p>Thanks!</p>", "https://x/1"))
        long = page(comment("bob", "o/r", 2, "<h2>Plan</h2><ul><li>one</li><li>two</li></ul><pre><code>x = 1</code></pre>", "https://x/2"))
        pushed = page(push("alice", [(sha(1), "Fix")], "https://x/3"))
        subject = "Re: [o/r] Title (PR #1)"
        self.assertEqual(cf.fingerprint("notifications@github.com", subject, short),
                         cf.fingerprint("notifications@github.com", subject, long))
        self.assertNotEqual(cf.fingerprint("notifications@github.com", subject, short),
                            cf.fingerprint("notifications@github.com", subject, pushed))

    def test_one_failed_job_or_six_is_one_template(self) -> None:
        def run(jobs: int) -> cf.Page:
            rows = "".join(f'<table class="border-bottom width-full"><tr><td class="p-3"><p class="mb-0"><b>CI</b> / job {n}<br>Failed</p></td>'
                           f'{"<td class=pr-3><a href=https://x>2</a></td>" if n % 2 else "<td class=pr-3></td>"}</tr></table>'
                           for n in range(jobs))
            return page(f'<table class="container"><tr><td><h2>[o/r] CI workflow run</h2>{rows}<p>Manage notifications</p></td></tr></table>')

        key = cf.fingerprint("notifications@github.com", "[o/r] Run failed: CI - main (abc1234)", run(1))
        self.assertEqual(key, cf.fingerprint("notifications@github.com", "[o/r] Run failed: CI - main (abc1234)", run(6)))

    def test_subject_frame(self) -> None:
        self.assertEqual(cf.subject_frame("Re: [o/r] Fix (draft) parser (PR #12)"), "[*] … (PR #0)")
        self.assertEqual(cf.subject_frame("[o/r] Run failed: CI - main (a1b2c3d)"), "[*] … (h)")
        self.assertEqual(cf.subject_frame("Your receipt"), "…")

    def test_a_generic_layout_is_split_by_what_its_subjects_say(self) -> None:
        subjects = (["[GitHub] A third-party OAuth application has been added to your account"] * 4
                    + ["[GitHub] Payment receipt for acme"] * 3 + ["[GitHub] Please read this once"])
        threads = [f"t{n}" for n in range(len(subjects))]
        labels = cf.subject_labels(subjects, threads)
        self.assertEqual(len(set(labels[:4])), 1)
        self.assertEqual(len(set(labels[4:7])), 1)
        self.assertNotEqual(labels[0], labels[4])
        # Titles of one PR repeated in its own thread aren't a template.
        titles = ["[o/r] Fix the parser (PR #1)"] * 5
        self.assertEqual(set(cf.subject_labels(titles, ["t1"] * 5)), {"*"})


def pushes() -> list[tuple[cf.Page, str]]:
    out = []
    for n in range(12):
        commits = [(sha(10 * n + k), f"Change {n}.{k}: tidy (part {k})") for k in range(1 + n % 4)]
        out.append((page(push(f"user{n}", commits, f"https://github.com/o/r/pull/{n}/files/{n}")), f"Re: [o/r] Work {n} (PR #{n})"))
    return out


class LearnTest(unittest.TestCase):
    def test_one_taught_email_reads_a_list_of_five(self) -> None:
        corpus = pushes()
        taught_page = page(push("alice", [(sha(1), "Fix the parser")], "https://github.com/o/r/pull/7/files/1"))
        template = cf.Template.learn([(taught_page, "Re: [o/r] Fix (PR #7)", [
            cf.Taught("author", "@alice"),
            cf.Taught("count", "1", after="pushed"),
            cf.Taught("shas", sha(1)[:7], many=True),
            cf.Taught("messages", "Fix the parser", many=True),
            cf.Taught("link", "View it on GitHub", link=True),
            cf.Taught("number", "7", subject=True),
        ])], corpus)
        commits = [(sha(100 + k), f"Step {k} (of 5)") for k in range(5)]
        result = template.extract(page(push("bob", commits, "https://github.com/o/r/pull/9/files/2")), "Re: [o/r] Five (PR #9)")
        self.assertEqual(result.status, "ok", result.reason)
        self.assertEqual(result.values["author"], "@bob")
        self.assertEqual(result.values["count"], "5")
        self.assertEqual(result.values["shas"], [s[:7] for s, _ in commits])
        self.assertEqual(result.values["messages"], [m for _, m in commits])
        self.assertEqual(result.values["link"], "https://github.com/o/r/pull/9/files/2")
        self.assertEqual(result.values["number"], "9")

    def test_the_corpus_says_how_wide_a_value_may_be(self) -> None:
        actions = ["approved", "commented on", "requested changes on", "dismissed", "commented on"] * 3
        corpus = [(page(review(f"u{n}", action, f"<p>Note {n}</p>", f"https://x/{n}")), "Re: [o/r] T (PR #1)")
                  for n, action in enumerate(actions)]
        examples = [(page(review(name, "approved", "<p>LGTM</p>", "https://x/a")), "Re: [o/r] T (PR #1)",
                     [cf.Taught("author", f"@{name}"), cf.Taught("action", "approved", after=f"@{name}")])
                    for name in ("ann", "ben")]
        template = cf.Template.learn(examples, corpus)
        result = template.extract(page(review("cy", "requested changes on", "<p>See inline.</p>", "https://x/c")))
        self.assertEqual(result.values["action"], "requested changes on")
        self.assertEqual(result.values["author"], "@cy")

    def test_subject_fields_around_a_title_with_brackets(self) -> None:
        corpus = [(page(review("u", "approved", "", "https://x")), f"Re: [org{n}/repo] Fix ({n}) things (PR #{n})") for n in range(10)]
        template = cf.Template.learn([(corpus[0][0], "Re: [acme/tool] Fix (draft) parser (PR #12)", [
            cf.Taught("repo", "acme/tool", subject=True),
            cf.Taught("title", "Fix (draft) parser", subject=True),
            cf.Taught("number", "12", subject=True),
        ])], corpus)
        result = template.extract(corpus[3][0], "Re: [some/where] Make (it) work (again) (PR #345)")
        self.assertEqual(result.values, {"repo": "some/where", "title": "Make (it) work (again)", "number": "345"})

    def test_a_link_after_text_of_any_length(self) -> None:
        bodies = ["<p>ok</p>", "<p>a</p><p>b</p><ul><li>c</li></ul>", "<p>x</p>" * 6]
        corpus = [(page(comment(f"u{n}", "o/r", n, bodies[n % 3], f"https://github.com/o/r/pull/{n}#c{n}")), "Re: [o/r] T (PR #1)")
                  for n in range(9)]
        template = cf.Template.learn([(corpus[0][0], "", [cf.Taught("link", "view it on GitHub", link=True),
                                                          cf.Taught("ref", "o/r#0")])], corpus)
        for n in (4, 8):
            values = template.extract(corpus[n][0]).values
            self.assertEqual(values["link"], f"https://github.com/o/r/pull/{n}#c{n}")
            self.assertEqual(values["ref"], f"o/r#{n}")

    def test_a_value_ends_at_the_first_closing_anchor(self) -> None:
        def sentence(app: str) -> cf.TextPage:
            return cf.TextPage(f"A third-party OAuth application ({app}) with access to public information (read-only) was authorized.")

        corpus = [(sentence(name), "") for name in ("Big Tool", "X", "Some Other App", "Q Q")]
        template = cf.Template.learn([(sentence("Git Beacon"), "", [cf.Taught("app", "Git Beacon")])], corpus)
        self.assertEqual(template.unlearned, [])
        self.assertEqual(template.extract(sentence("My Cool App")).values["app"], "My Cool App")

    def test_a_field_that_cannot_be_learned_is_named(self) -> None:
        taught_page = page(push("alice", [(sha(1), "Fix")], "https://x/1"))
        template = cf.Template.learn([(taught_page, "", [cf.Taught("ghost", "not in this email")])], pushes())
        self.assertEqual((template.extractors, template.unlearned), ([], ["ghost"]))

    def test_a_class_that_says_the_value_does_not_count(self) -> None:
        def advisory(level: str, colour: str) -> cf.Page:
            return page(f'<h3 class="lh-condensed">Bad bug</h3><span class="Label Label--{colour}">{level} severity</span>'
                        '<p>Affected Repositories</p>')

        corpus = [(advisory("High", "orange"), "")] * 5
        template = cf.Template.learn([(advisory("High", "orange"), "", [cf.Taught("severity", "High")])], corpus)
        self.assertEqual(template.extract(advisory("Critical", "danger")).values["severity"], "Critical")

    def test_a_selection_by_offsets_teaches_the_same(self) -> None:
        taught_page = page(push("alice", [(sha(1), "Fix the parser")], "https://x/1"))
        start = taught_page.text.index("Fix the parser")
        by_value = cf.Template.learn([(taught_page, "", [cf.Taught("message", "Fix the parser")])], pushes())
        by_offsets = cf.Template.learn([(taught_page, "", [cf.Taught("message", start=start, end=start + 14)])], pushes())
        self.assertEqual(cf.dataclasses.asdict(by_value.extractors[0]) | {"name": ""},
                         cf.dataclasses.asdict(by_offsets.extractors[0]) | {"name": ""})


class DriftTest(unittest.TestCase):
    def setUp(self) -> None:
        taught_page = page(push("alice", [(sha(1), "Fix the parser")], "https://github.com/o/r/pull/7/files/1"))
        self.template = cf.Template.learn([(taught_page, "", [
            cf.Taught("author", "@alice"),
            cf.Taught("count", "1", after="pushed"),
            cf.Taught("shas", sha(1)[:7], many=True),
            cf.Taught("link", "View it on GitHub", link=True),
        ])], pushes())

    def test_a_redesigned_template_is_flagged_not_guessed(self) -> None:
        redesigned = page(push("bob", [(sha(5), "Change")], "https://x/2", mention_class="actor", verb="added",
                               sha_class="sha"))
        result = self.template.extract(redesigned)
        self.assertEqual(result.status, "reteach")
        self.assertIn("count", result.missing)

    def test_another_template_is_flagged(self) -> None:
        result = self.template.extract(page(comment("bob", "o/r", 3, "<p>Hello</p>", "https://x/3")))
        self.assertEqual(result.status, "reteach")

    def test_the_same_template_is_read(self) -> None:
        self.assertEqual(self.template.extract(pushes()[5][0]).status, "ok")


CI_TEXT = """[{repo}] {workflow} workflow run

Repository: {repo}
Workflow: {workflow}
Duration: 1 minute and {n}.0 seconds
Finished: 2026-01-0{n} 10:00:00 UTC

View results: https://github.com/{repo}/actions/runs/{n}{n}{n}

Jobs:
{jobs}

--
You are receiving this because you are subscribed to this thread.
Manage your GitHub Actions notifications: https://github.com/settings/notifications
"""


def ci_text(n: int, jobs: list[str], workflow: str = "CI") -> str:
    # Most jobs fail; some are cancelled or skipped beside them.
    states = ["failed", "failed", "cancelled", "failed", "skipped"]
    lines = "\n".join(f"  * {job} {states[k % 5] if k else 'failed'} ({n} annotations)" for k, job in enumerate(jobs))
    return CI_TEXT.format(repo=f"own{n}/repo{n}", workflow=workflow, n=n, jobs=lines)


class PlainTextTest(unittest.TestCase):
    def test_key_value_lines_and_a_list(self) -> None:
        corpus = [(cf.TextPage(ci_text(n, [f"Build {k} (linux)" for k in range(1 + n % 3)], f"Flow {n}")), "") for n in range(1, 9)]
        first = corpus[0][0]
        template = cf.Template.learn([(first, "", [
            cf.Taught("repo", "own1/repo1", after="Repository:"),
            cf.Taught("workflow", "Flow 1", after="Workflow:"),
            cf.Taught("jobs", "Build 0 (linux)", after="Jobs:", many=True),
            cf.Taught("link", "https://github.com/own1/repo1/actions/runs/111", after="View results:"),
        ])], corpus)
        result = template.extract(cf.TextPage(ci_text(7, ["Lint", "Unit tests (py3)", "Deploy"], "Release train")))
        self.assertEqual(result.status, "ok", result.reason)
        self.assertEqual(result.values["repo"], "own7/repo7")
        self.assertEqual(result.values["workflow"], "Release train")
        self.assertEqual(result.values["jobs"], ["Lint", "Unit tests (py3)", "Deploy"])
        self.assertEqual(result.values["link"], "https://github.com/own7/repo7/actions/runs/777")


def notice(app: str, access: str) -> str:
    """A text-only notice wrapped at 72 characters, as GitHub sends it."""
    import textwrap

    sentence = f"A third-party OAuth application ({app}) with {access} was recently authorized to access your account."
    return ("Hey you!\n\n" + textwrap.fill(sentence, 72) + "\nVisit https://github.com/settings/connections/applications/"
            + app.replace(" ", "") + " for more information.\n\nThanks,\nThe GitHub Team\n")


class WrappedTextTest(unittest.TestCase):
    def test_a_value_the_wrap_splits_is_read_whole(self) -> None:
        apps = [("Tiny", "read:user scope"), ("A Much Longer Application Name", "read:user and user:email scopes"),
                ("Mid App", "repo, read:org and workflow scopes"), ("X", "gist scope"), ("Some Tool", "user:email scope")]
        corpus = [(cf.TextPage(notice(app, access)), "") for app, access in apps]
        template = cf.Template.learn([(corpus[0][0], "", [cf.Taught("app", "Tiny"),
                                                          cf.Taught("access", "read:user scope", after="Tiny")])], corpus)
        for app, access in apps[1:]:
            values = template.extract(cf.TextPage(notice(app, access))).values
            self.assertEqual((values["app"], values["access"]), (app, access))

    def test_list_rows_are_not_joined(self) -> None:
        text = "@a pushed 2 commits.\n\n" + "\n".join(f"{n:07x}{'b' * 33}  " + "word " * 7 for n in range(2)) + "\n"
        self.assertEqual(len([leaf for leaf in cf.TextPage(text).leaves if re.match(r"[0-9a-f]{40}", leaf.text)]), 2)


class SelectionTest(unittest.TestCase):
    def test_a_selection_in_qts_text_maps_to_the_page(self) -> None:
        p = page(comment("alice", "o/r", 4, "<p>Looks   good</p>", "https://x/4"))
        # Qt's text for the same HTML: its own whitespace, a paragraph mark
        # between blocks and an object mark for the avatar.
        shown = "\ufffcalice left a comment (o/r#4)\u2029Looks good\u2029—\u2029Reply to this email directly, view it on GitHub, or unsubscribe.\u2029You are receiving this because you were mentioned."
        start = shown.index("alice")
        mapped = cf.map_selection(p, shown, start, start + 5)
        self.assertIsNotNone(mapped)
        self.assertEqual(p.text[mapped[0]:mapped[1]], "alice")
        start = shown.index("o/r#4")
        mapped = cf.map_selection(p, shown, start, start + 5)
        self.assertEqual(p.text[mapped[0]:mapped[1]], "o/r#4")

    def test_qts_table_marks_are_not_text(self) -> None:
        p = page('<table><tr><td>Job</td><td>Status</td></tr><tr><td>build</td><td>Failed</td></tr></table>')
        # TextEdit.getText() keeps U+FDD0 and U+FDD1 where a table's frame
        # begins and ends.
        shown = "\ufdd0Job\u2029Status\u2029build\u2029Failed\ufdd1"
        start = shown.index("build")
        mapped = cf.map_selection(p, shown, start, start + 5)
        self.assertEqual(p.text[mapped[0]:mapped[1]], "build")
        self.assertEqual(cf._visible(shown)[0], cf._visible(p.text)[0])

    def test_an_image_description_does_not_throw_it_off(self) -> None:
        p = page(comment("alice", "o/r", 4, "<p>Looks good</p>", "https://x/4"))
        shown = "avatar alice left a comment (o/r#4)\nLooks good\n—\nReply to this email directly, view it on GitHub, or unsubscribe.\nYou are receiving this because you were mentioned."
        start = shown.index("Looks")
        mapped = cf.map_selection(p, shown, start, start + 10)
        self.assertEqual(p.text[mapped[0]:mapped[1]], "Looks good")


if __name__ == "__main__":
    unittest.main()
