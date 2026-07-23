"""Repository invariants — assertions about the git index, not about program behaviour.

This module is deliberately unusual. `data/jobscout.db` carries the title, company and
full description of every listing JobScout has ever ingested; publishing that from a
public repository is not ours to do. That rule has no code seam — restore the `.gitignore`
whitelist and every other test in the suite still passes — so it needs a mechanical
tripwire instead. Its failure mode is legal, not functional.
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


def test_feedback_file_is_still_tracked():
    """Guards the guard: proves `git ls-files` actually reports tracked paths here.

    Without this, a wrong cwd or a broken git invocation would make the assertion
    above pass for the wrong reason.
    """
    assert _tracked("data/feedback.yaml") == "data/feedback.yaml"
