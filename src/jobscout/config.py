from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

from jobscout.models import UserProfile

logger = logging.getLogger(__name__)

# Project root: src/jobscout/config.py → src/jobscout/ → src/ → project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class AppConfig(BaseModel):
    # User preferences loaded from profile.yaml
    profile: UserProfile

    # Required API keys — validated non-empty at load time
    adzuna_app_id: str
    adzuna_app_key: str
    openai_api_key: str

    # LLM model used for evaluation — change here to swap models pipeline-wide
    llm_model: str = "gpt-4o-mini"

    # Optional email delivery via Resend — all three must be set to enable sending
    resend_api_key: str | None = None
    email_to: str | None = None      # Recipient address
    email_from: str | None = None    # Verified sender address

    # Paths — default to project-root-relative locations
    db_path: Path = _PROJECT_ROOT / "data" / "jobscout.db"
    digests_dir: Path = _PROJECT_ROOT / "digests"

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("adzuna_app_id", "adzuna_app_key", "openai_api_key")
    @classmethod
    def must_be_non_empty(cls, v: str, info) -> str:
        if not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
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
# Internal loader
# ---------------------------------------------------------------------------

def _load_config(profile_path: Path | None = None) -> AppConfig:
    # Shell env vars take precedence over .env (override=False is the default,
    # but explicit is better than implicit — GitHub Actions secrets are shell
    # env vars and must not be overridden by a stale .env file)
    load_dotenv(override=False)

    resolved_profile_path = profile_path or (_PROJECT_ROOT / "profile.yaml")

    if not resolved_profile_path.exists():
        raise FileNotFoundError(
            f"profile.yaml not found at {resolved_profile_path}. "
            "Create one based on profile.yaml in the project root."
        )

    with resolved_profile_path.open() as f:
        yaml_data = yaml.safe_load(f)

    profile = UserProfile.model_validate(yaml_data)

    cfg = AppConfig(
        profile=profile,
        adzuna_app_id=os.environ.get("ADZUNA_APP_ID", ""),
        adzuna_app_key=os.environ.get("ADZUNA_APP_KEY", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        resend_api_key=os.environ.get("RESEND_API_KEY") or None,
        email_to=os.environ.get("EMAIL_TO") or None,
        email_from=os.environ.get("EMAIL_FROM") or None,
    )

    logger.debug(
        "Config loaded — profile: %s, db: %s, digests: %s",
        cfg.profile.name,
        cfg.db_path,
        cfg.digests_dir,
    )

    return cfg
