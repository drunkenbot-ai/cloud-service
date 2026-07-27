"""Alert notifications for account/license lifecycle events.

Every send function here is deliberately best-effort: a bad Gmail app
password, an unreachable Telegram API, or a revoked Discord webhook must
never turn into a failed account/license operation for the admin who
triggered it. Failures are logged (not raised) and swallowed at the
call site.

v1 scope note: sends happen synchronously, inline in the request that
triggered them. Fine at this scale/volume; if this ever needs to not add
Gmail/Telegram/Discord round-trip latency to admin actions, move dispatch
to a background task queue -- not built now since it would be premature
complexity for the current volume of admin actions.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any, Optional

from sqlalchemy.orm import Session

from app import crud
from app.crypto_secrets import decrypt_secret

LOGGER = logging.getLogger(__name__)

# Maps event type -> which NotificationSettings toggle column controls it.
_EVENT_TOGGLE_ATTR = {
    "account_created": "notify_account_created",
    "account_status_changed": "notify_account_status_changed",
    "license_created": "notify_license_created",
    "license_revoked": "notify_license_revoked",
    "license_extended": "notify_license_extended",
}


def notify_event(db: Session, event_type: str, summary: str, detail: Optional[dict[str, Any]] = None) -> None:
    """Send an alert for a lifecycle event across every enabled channel.

    Args:
        db: Active database session (used to load current settings).
        event_type: One of the keys in ``_EVENT_TOGGLE_ATTR``.
        summary: One-line human-readable summary, e.g. "License revoked for
            customer@example.com".
        detail: Optional extra context appended to the message body.
    """

    settings = crud.get_notification_settings(db)
    toggle_attr = _EVENT_TOGGLE_ATTR.get(event_type)
    if toggle_attr is not None and not getattr(settings, toggle_attr, True):
        return

    body_lines = [summary]
    if detail:
        body_lines.append("")
        body_lines.extend(f"{key}: {value}" for key, value in detail.items())
    body = "\n".join(body_lines)

    if settings.email_enabled:
        _send_email_safe(settings, summary, body)
    if settings.telegram_enabled:
        _send_telegram_safe(settings, body)
    if settings.discord_enabled:
        _send_discord_safe(settings, body)


def _send_email_safe(settings: Any, subject: str, body: str) -> None:
    """Send an email alert, swallowing any failure.

    Args:
        settings: Current notification settings row.
        subject: Email subject line.
        body: Email body text.
    """

    try:
        gmail_password = decrypt_secret(settings.gmail_app_password_encrypted)
        if not settings.gmail_address or not gmail_password or not settings.recipient_email:
            return
        message = EmailMessage()
        message["From"] = settings.gmail_address
        message["To"] = settings.recipient_email
        message["Subject"] = f"[DrunkenBot] {subject}"
        message.set_content(body)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(settings.gmail_address, gmail_password)
            smtp.send_message(message)
    except Exception:
        LOGGER.exception("Failed to send email notification")


def _send_telegram_safe(settings: Any, text: str) -> None:
    """Send a Telegram alert, swallowing any failure.

    Args:
        settings: Current notification settings row.
        text: Message text.
    """

    try:
        bot_token = decrypt_secret(settings.telegram_bot_token_encrypted)
        if not bot_token or not settings.telegram_chat_id:
            return
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        body = json.dumps({"chat_id": settings.telegram_chat_id, "text": f"[DrunkenBot] {text}"}).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (urllib.error.URLError, TimeoutError, OSError):
        LOGGER.exception("Failed to send Telegram notification")
    except Exception:
        LOGGER.exception("Failed to send Telegram notification")


def _send_discord_safe(settings: Any, content: str) -> None:
    """Send a Discord webhook alert, swallowing any failure.

    Args:
        settings: Current notification settings row.
        content: Message content.
    """

    try:
        webhook_url = decrypt_secret(settings.discord_webhook_url_encrypted)
        if not webhook_url:
            return
        body = json.dumps({"content": f"**[DrunkenBot]** {content}"}).encode("utf-8")
        request = urllib.request.Request(
            webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (urllib.error.URLError, TimeoutError, OSError):
        LOGGER.exception("Failed to send Discord notification")
    except Exception:
        LOGGER.exception("Failed to send Discord notification")
