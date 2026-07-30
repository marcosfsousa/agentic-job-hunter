"""Repository invariants — assertions about the checkout, not about program behaviour.

This module is deliberately unusual. `data/jobscout.db` carries the title, company and
full description of every listing JobScout has ever ingested; publishing that from a
public repository is not ours to do. That rule has no code seam — restore the `.gitignore`
whitelist and every other test in the suite still passes — so it needs a mechanical
tripwire instead. Its failure mode is legal, not functional.

The import invariant below is here for the same reason: it guards a property that no
other test can fail on, because every other test passes just as happily against the
wrong copy of the source.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import jobscout
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

    Delete `pythonpath` and this is the only test that notices.
    """
    imported = Path(jobscout.__file__).resolve()
    expected_root = (_REPO_ROOT / "src").resolve()
    assert imported.is_relative_to(expected_root), (
        f"the suite imported jobscout from {imported}, but these tests live in "
        f"{_REPO_ROOT}. Tests and source are coming from different checkouts, so "
        "every result in this run is about the wrong tree. Check that "
        "`pythonpath = [\"src\"]` is still present under [tool.pytest.ini_options] "
        "in pyproject.toml, and that PYTHONPATH is not pointing elsewhere."
    )
