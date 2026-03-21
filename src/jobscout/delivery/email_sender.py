from __future__ import annotations

import asyncio
import logging
from datetime import date

import markdown as md
import resend
import resend.exceptions

from jobscout.config import AppConfig

logger = logging.getLogger(__name__)


async def send_digest(content: str, config: AppConfig, run_date: date | None = None) -> bool:
    """Send the markdown digest as an HTML email via Resend.

    Skips silently if any required credential is missing.

    Args:
        content: Markdown string produced by format_digest().
        config: AppConfig with Resend credentials.
        run_date: Date shown in the subject line. Defaults to today.

    Returns:
        True if the email was sent, False if skipped or failed.
    """
    run_date = run_date or date.today()

    if not _is_configured(config):
        logger.info("Email delivery not configured — skipping")
        return False

    resend.api_key = config.resend_api_key

    params: resend.Emails.SendParams = {
        "from": config.email_from,
        "to": [config.email_to],
        "subject": f"JobScout Digest — {run_date.isoformat()}",
        "html": md.markdown(content, extensions=["tables"]),
        "text": content,
    }

    try:
        response = await asyncio.to_thread(resend.Emails.send, params)
        logger.info("Digest emailed to %s (id=%s)", config.email_to, response["id"])
        return True
    except resend.exceptions.ResendError as exc:
        logger.warning("Failed to send digest email: %s", exc.message)
        return False
    except Exception as exc:
        logger.warning("Failed to send digest email: %s", exc)
        return False


def _is_configured(config: AppConfig) -> bool:
    return all([
        config.resend_api_key,
        config.email_to,
        config.email_from,
    ])
