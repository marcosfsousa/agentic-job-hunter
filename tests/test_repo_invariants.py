"""Repository invariants — assertions about the checkout, not about program behaviour.

This module is deliberately unusual. `data/jobscout.db` carries the title, company and
full description of every listing JobScout has ever ingested; publishing that from a
public repository is not ours to do. That rule has no code seam — restore the `.gitignore`
whitelist and every other test in the suite still passes — so it needs a mechanical
tripwire instead. Its failure mode is legal, not functional.

`tests/fixtures/scored_postings/` (#96) is the second instance of exactly that rule, which
is why the guard below is written as a second case rather than as a variation.

The import invariant below is here for a related reason: it is the only test that fails
*reliably* when the suite imports the wrong tree's source. Other tests may or may not
notice, depending entirely on how the two trees happen to differ at that moment — which
is not a property you can depend on, and is precisely what makes the bug dangerous.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _tracked(relative_path: str) -> str:
    """Return git's index entry for a path, or "" if it is untracked."""
    result = subprocess.run(
        ["git", "ls-files", "--", relative_path],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"git unavailable or not a repository: {result.stderr.strip()}")
    return result.stdout.strip()


def test_database_is_not_tracked():
    assert _tracked("data/jobscout.db") == "", (
        "data/jobscout.db is tracked by git. It must never be committed — it contains "
        "the full description of every ingested listing. Untrack it with "
        "`git rm --cached data/jobscout.db` (--cached, or you delete the local dedup "
        "state) and check that .gitignore does not whitelist it out of the `data/*` rule."
    )


def test_no_scored_posting_text_is_tracked():
    """The A2 corpus's posting text (#96) must stay local, like the database above.

    Same class of rule, one degree worse: these are third-party copyrighted postings
    naming real contact persons, in a public repo linked from a CV. The committed half
    is `tests/fixtures/scored_postings.yaml` — scores, bands and the rule each case
    exercises, no posting text — and it deliberately sits *outside* the ignored
    directory so no `!` negation is needed to keep it visible.
    """
    tracked = _tracked("tests/fixtures/scored_postings")
    assert tracked == "", (
        "posting text under tests/fixtures/scored_postings/ is tracked by git:\n"
        f"{tracked}\n"
        "It must never be committed. Untrack it with `git rm --cached -r "
        "tests/fixtures/scored_postings` and check that .gitignore still carries the "
        "whole-directory rule for that path. The manifest lives at "
        "tests/fixtures/scored_postings.yaml and is unaffected."
    )


def test_no_agent_brief_is_tracked():
    """Per-issue agent briefs carry posting text too, and they sit in a tracked directory.

    `docs/issue_96_agent_brief.md` holds verbatim excerpts from five postings. It lives
    in `docs/` for convenience, which means it is one `git add docs/` from being
    published — a likelier accident than the database, which at least sits behind its own
    ignore rule in a directory nobody stages by hand.
    """
    tracked = _tracked("docs/*_agent_brief.md")
    assert tracked == "", (
        f"an agent brief is tracked by git:\n{tracked}\n"
        "Briefs carry third-party posting text and must stay local. Untrack it with "
        "`git rm --cached <path>` and check the `docs/*_agent_brief.md` rule in "
        ".gitignore."
    )


def test_feedback_file_is_still_tracked():
    """Guards the guard: proves `git ls-files` actually reports tracked paths here.

    Without this, a wrong cwd or a broken git invocation would make the assertion
    above pass for the wrong reason.
    """
    assert _tracked("data/feedback.yaml") == "data/feedback.yaml"


def test_suite_imports_src_from_this_tree():
    """The suite must import the `src/` sitting next to it, not another checkout's.

    The editable install (`__editable__.jobscout-0.1.0.pth`) is a plain path entry
    pointing at the main checkout. A run started from `.claude/worktrees/<name>/`
    therefore collects the worktree's `tests/` and — without the `pythonpath = ["src"]`
    setting in pyproject.toml — imports the main checkout's `jobscout`. Two trees in
    one run, with nothing in pytest's output naming either. That fails *open*: every
    assertion still executes, just against source you are not editing, so the suite
    goes green on a change it never saw.

    Delete `pythonpath` and this is the only test guaranteed to notice. Others may —
    with the main checkout on an older branch, `test_evaluation.py` fails too — but only
    by luck of how the trees differ that day, and that is not something to rely on.

    The `import jobscout` is function-local on purpose. At module level it would give the
    `data/jobscout.db` guards above a dependency on the package being importable at all:
    an import error would fail collection for the whole module and take the legal
    tripwire down with it. Nothing else in this file imports project code, and that is
    the property worth keeping.
    """
    import jobscout

    imported = Path(jobscout.__file__).resolve()
    expected_root = (_REPO_ROOT / "src").resolve()
    assert imported.is_relative_to(expected_root), (
        f"the suite imported jobscout from {imported}, but these tests live in "
        f"{_REPO_ROOT}. Tests and source are coming from different checkouts, so "
        "every result in this run is about the wrong tree. Fix: check that "
        "`pythonpath = [\"src\"]` is still present under [tool.pytest.ini_options] "
        "in pyproject.toml. Note that PYTHONPATH is *not* a suspect — pytest inserts "
        "the ini entry at sys.path[0], ahead of it."
    )
