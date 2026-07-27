"""Encrypt/decrypt helpers for secrets that must be retrievable in plaintext.

Distinct from app/security.py's hashing functions on purpose: API keys and
passwords are hashed one-way because we only ever need to *verify* them
again, never see the original. Notification secrets (Gmail app password,
Telegram bot token, Discord webhook URL) are different -- the service has
to actually use the plaintext value later to send a message, so hashing
would not work here. This uses genuine symmetric encryption instead.
"""

from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    """Return a Fernet instance built from the configured encryption key.

    Returns:
        Fernet cipher.
    """

    return Fernet(get_settings().notification_encryption_key.encode("utf-8"))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage.

    Args:
        plaintext: Secret value to encrypt.

    Returns:
        Encrypted token, safe to store as a string column.
    """

    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: Optional[str]) -> Optional[str]:
    """Decrypt a stored secret.

    Args:
        token: Encrypted token as stored, or ``None``.

    Returns:
        Decrypted plaintext, or ``None`` if ``token`` was ``None`` or could
        not be decrypted (e.g. the encryption key changed since it was
        saved).
    """

    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None
