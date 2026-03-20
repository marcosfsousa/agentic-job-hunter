from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


def write_digest(content: str, digests_dir: Path, run_date: date | None = None) -> Path:
    """Write a markdown digest to digests_dir/YYYY-MM-DD.md.

    Creates the directory if it does not exist. Overwrites any existing file
    for the same date (pipeline is idempotent — same day = same result).

    Args:
        content: Markdown string produced by format_digest().
        digests_dir: Directory to write into (from AppConfig.digests_dir).
        run_date: Date used for the filename. Defaults to today.

    Returns:
        Path of the written file.
    """
    run_date = run_date or date.today()
    digests_dir.mkdir(parents=True, exist_ok=True)

    path = digests_dir / f"{run_date.isoformat()}.md"
    path.write_text(content, encoding="utf-8")

    logger.info("Digest written to %s", path)
    return path
