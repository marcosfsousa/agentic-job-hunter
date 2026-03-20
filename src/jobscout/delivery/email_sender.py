from __future__ import annotations

import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown as md

from jobscout.config import AppConfig

logger = logging.getLogger(__name__)


def send_digest(content: str, config: AppConfig, run_date: date | None = None) -> bool:
    """Send the markdown digest as an HTML email.

    Skips silently if any required SMTP credential is missing.

    Args:
        content: Markdown string produced by format_digest().
        config: AppConfig with SMTP credentials.
        run_date: Date shown in the subject line. Defaults to today.

    Returns:
        True if the email was sent, False if skipped or failed.
    """
    run_date = run_date or date.today()

    if not _is_configured(config):
        logger.info("Email delivery not configured — skipping")
        return False

    sender = config.email_from or config.smtp_user
    subject = f"JobScout Digest — {run_date.isoformat()}"
    html_body = md.markdown(content, extensions=["tables"])

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = config.email_to
    msg.attach(MIMEText(content, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls()
            server.login(config.smtp_user, config.smtp_password)
            server.sendmail(sender, config.email_to, msg.as_string())
        logger.info("Digest emailed to %s", config.email_to)
        return True
    except Exception as exc:
        logger.warning("Failed to send digest email: %s", exc)
        return False


def _is_configured(config: AppConfig) -> bool:
    return all([
        config.smtp_host,
        config.smtp_user,
        config.smtp_password,
        config.email_to,
    ])
