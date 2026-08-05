from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from jobscout.models import UserProfile

logger = logging.getLogger(__name__)

# Project root: src/jobscout/config.py → src/jobscout/ → src/ → project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# How long to wait on the `git rev-parse` below before giving up. Generous: the point is
# to bound a hung git, not to time a fast one.
_GIT_TIMEOUT_SECONDS = 10

# Standalone default for the re-evaluation floor. Deliberately independent of
# profile.email_min_score (the digest gate): the digest wants quality (~5 on the
# current compressed distribution) while re-eval cost wants a lower floor (~4), so
# raising one must not move the other. See issue #45 — this replaces the previous
# fallback-to-email_min_score coupling.
DEFAULT_REEVAL_BELOW = 4


class AppConfig(BaseModel):
    # User preferences loaded from profile.yaml
    profile: UserProfile

    # Required API keys — validated non-empty at load time
    anthropic_api_key: str

    # LLM model used for evaluation — change here to swap models pipeline-wide
    llm_model: str = "claude-haiku-4-5-20251001"

    # Sampling temperature for evaluation. NOT previously set at all, which meant the
    # API default of 1.0 applied — to the daily digest as much as to the test harness.
    # Two consequences, and the second is the one that made this visible:
    #   - CLAUDE.md requires "same day = same digest". A pipeline sampling at 1.0
    #     cannot honour that, and nothing in the repo said so.
    #   - The #96 corpus compares which rules fired before and after a prompt edit.
    #     Two runs of #3018325 an hour apart, same prompt SHA, reported six fired
    #     rules and then four — so the instrument was measuring the sampler as much
    #     as the rubric (2026-08-04).
    # 0 is NOT a determinism guarantee — Anthropic's own guidance is that temperature 0
    # never produced identical outputs on the models that accept the parameter, and
    # batching and routing still move results. It collapses most of the spread; it does
    # not remove it, and no test here should assert exact reproduction.
    # Settable because the harness may want to measure the spread deliberately.
    llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0)

    # Optional email delivery via Resend — all three must be set to enable sending
    resend_api_key: str | None = None
    email_to: str | None = None      # Recipient address
    email_from: str | None = None    # Verified sender address

    # Ranking — blend weight for feedback centroid (0 = profile only, 1 = feedback only)
    feedback_weight: float = 0.2

    # Size of the LLM-evaluation pool: the top-N ranked jobs are evaluated, the rest
    # dropped. This is the sole constant carrying CLAUDE.md's "top 20–30 jobs only"
    # — a rank cut, not an absolute-score floor, so it survives an embedding-model
    # swap that rescales cosine. Lives here rather than as an evaluate_jobs signature
    # default because "all config via config.py".
    top_n: int = Field(default=25, ge=1)

    # --- freelancermap operational thresholds -----------------------------
    # Operational, not preferences: these describe how hard we may lean on the
    # source and when to call it broken. Job preferences live in profile.yaml.

    # Hard ceiling on outgoing requests per run, enforced in code rather than by
    # convention, so a looping bug cannot turn a personal tool into a crawler.
    # This is one of the three binding constraints under which ingesting
    # freelancermap was accepted at all (issue #11) — it is a legal commitment,
    # not a tuning knob. Above the five seeded queries with headroom to add more.
    #
    # Deliberately NOT reachable from an environment variable, unlike every other
    # value below: a cap an operator can raise at runtime is a convention, which is
    # the thing this exists instead of. Widening it is a code change and a review.
    freelancermap_max_requests: int = Field(default=10, ge=1)

    # Floor on DISTINCT project ids across the whole run, below which the source
    # is treated as broken and the run fails loudly. With one source, silence in
    # the inbox would otherwise be indistinguishable from a quiet market.
    #
    # Must stay above 22: the anonymous view returns at most 22 rows per query, so
    # a floor at or below that cannot tell "every query collapsed onto the same
    # page" from "one query answered normally" — which is the failure this exists
    # to catch. The standing German inventory is ~115 and eight distinct queries
    # measured 128 distinct projects, so a healthy union across the seeded queries
    # lands far above 30.
    freelancermap_min_raw_ingest: int = Field(default=30, gt=22)

    # Jobs scoring below this threshold on the first LLM pass are re-evaluated once;
    # the higher of the two scores is kept. Independent of profile.email_min_score
    # (the digest gate) — re-eval cost and digest quality are tuned separately (#45).
    # 0 disables re-evaluation (no score can be below 0); overridable via REEVAL_BELOW.
    reeval_below: int = Field(default=DEFAULT_REEVAL_BELOW, ge=0)

    # Paths — default to project-root-relative locations
    db_path: Path = _PROJECT_ROOT / "data" / "jobscout.db"
    digests_dir: Path = _PROJECT_ROOT / "digests"

    model_config = {"arbitrary_types_allowed": True}

    @property
    def feedback_path(self) -> Path:
        return self.db_path.parent / "feedback.yaml"

    @field_validator("anthropic_api_key")
    @classmethod
    def must_be_non_empty(cls, v: str, info) -> str:
        if not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v

    @field_validator("feedback_weight")
    @classmethod
    def feedback_weight_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"feedback_weight must be between 0 and 1, got {v}")
        return v


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_config: AppConfig | None = None


def get_config(profile_path: Path | None = None) -> AppConfig:
    """Return the loaded AppConfig, initialising it on first call.

    Args:
        profile_path: Override the default profile.yaml location.
            Useful in tests to point at a fixture profile.
    """
    global _config
    if _config is None:
        _config = _load_config(profile_path)
    return _config


def reset_config() -> None:
    """Clear the cached config. Intended for use in tests only."""
    global _config
    _config = None


# ---------------------------------------------------------------------------
# Environment resolution
# ---------------------------------------------------------------------------

def _git_common_root(start: Path) -> Path | None:
    """Root of the checkout that owns the shared `.git`, or None if there isn't one.

    `git rev-parse --git-common-dir` reports the *shared* git directory: `<main>/.git`
    seen from a linked worktree, and a plain `.git` seen from the main checkout itself.
    Its parent is therefore the one root that holds the gitignored files a worktree
    cannot inherit — `.env` among them (#146).

    Returns None when git is unavailable or this is not a repository (an installed
    package, a tarball). Both are ordinary, so neither is an error here.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = start / common_dir  # git answers relatively from the main checkout
    return common_dir.resolve().parent


def _env_candidates(start: Path) -> list[Path]:
    """The `.env` files to load, nearest first — the order is the precedence.

    Two entries at most:

    1. the nearest `.env` at or above `start`, which is what python-dotenv's
       `find_dotenv()` used to locate on its own;
    2. the main checkout's `.env`, when `start` is a linked worktree.

    The second is the point of this function. `.env` holds a secret, so it is gitignored,
    and gitignored untracked files do not follow a `git worktree` — so every worktree
    started life with no key at all and the root copy had to be hand-copied (#146). Note
    the walk-up in (1) does *not* reliably cover this: it finds the main checkout only
    when the worktree happens to sit inside it (as `.claude/worktrees/<name>/` does), and
    that is a property of where worktrees are parked, not something to depend on.
    """
    candidates: list[Path] = []

    for directory in (start, *start.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            candidates.append(candidate.resolve())
            break  # nearest wins, as find_dotenv did

    common_root = _git_common_root(start)
    if common_root is not None:
        candidate = (common_root / ".env").resolve()
        if candidate.is_file() and candidate not in candidates:
            candidates.append(candidate)

    return candidates


def load_env(start: Path | None = None) -> None:
    """Populate `os.environ` from `.env`, worktrees included.

    Shell env vars take precedence over every `.env` (`override=False` is the default,
    but explicit is better than implicit — GitHub Actions secrets are shell env vars and
    must not be overridden by a stale `.env` file). For the same reason a nearer `.env`
    beats the main checkout's: the first value loaded wins.

    Public because the live-evaluation harness needs it. That gate reads
    `ANTHROPIC_API_KEY` off `os.environ` to decide whether to skip, which it can only do
    honestly after the `.env` files have been loaded.

    `start` defaults to the project root. Passing it explicitly is for tests, and makes
    the search deterministic rather than dependent on the calling frame the way bare
    `load_dotenv()` was.
    """
    for path in _env_candidates(Path(start) if start is not None else _PROJECT_ROOT):
        load_dotenv(path, override=False)


# ---------------------------------------------------------------------------
# Internal loader
# ---------------------------------------------------------------------------

def _load_config(profile_path: Path | None = None) -> AppConfig:
    load_env()

    resolved_profile_path = profile_path or (_PROJECT_ROOT / "profile.yaml")

    if not resolved_profile_path.exists():
        raise FileNotFoundError(
            f"profile.yaml not found at {resolved_profile_path}. "
            "Create one based on profile.yaml in the project root."
        )

    # Explicit utf-8: profile.yaml holds em dashes and German text, and a bare open()
    # picks up the platform default (cp1252 on Windows), which decodes them to mojibake
    # silently and ships that to Haiku. Linux CI never sees it (#55).
    with resolved_profile_path.open(encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)

    profile = UserProfile.model_validate(yaml_data)

    cfg = AppConfig(
        profile=profile,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        reeval_below=int(os.environ.get("REEVAL_BELOW", str(DEFAULT_REEVAL_BELOW))),
        llm_temperature=float(os.environ.get("LLM_TEMPERATURE", "0.0")),
        resend_api_key=os.environ.get("RESEND_API_KEY") or None,
        email_to=os.environ.get("EMAIL_TO") or None,
        email_from=os.environ.get("EMAIL_FROM") or None,
        feedback_weight=float(os.environ.get("FEEDBACK_WEIGHT", "0.2")),
        freelancermap_min_raw_ingest=int(os.environ.get("FREELANCERMAP_MIN_RAW_INGEST", "30")),
    )

    logger.debug(
        "Config loaded - profile: %s, db: %s, digests: %s",
        cfg.profile.name,
        cfg.db_path,
        cfg.digests_dir,
    )

    return cfg
