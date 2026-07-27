"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the DrunkenBot cloud service.

    Attributes:
        database_url: SQLAlchemy connection string for Postgres.
        signing_private_key_b64: Base64-encoded PEM Ed25519 private key used
            to sign licenses and grace receipts.
        admin_api_token: Shared bearer token protecting ``/admin/*`` routes.
        grace_receipt_valid_hours: How long an online-issued grace receipt
            remains valid before the IDE must re-check with the server.
        rate_limit_per_minute: Requests allowed per client IP per minute on
            the public validation endpoints.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    signing_private_key_b64: str
    admin_api_token: str
    # Separate from admin_api_token on purpose: this signs browser session
    # cookies for the admin UI, a different purpose than the API bearer
    # token. Keeping them independent means a leak of one doesn't also
    # compromise the other.
    session_secret_key: str
    # Encrypts notification secrets at rest (Gmail app password, Telegram
    # bot token, Discord webhook URL) in the database. Unlike API keys
    # (hashed, one-way, never need the original back), these need to be
    # retrieved in plaintext to actually send notifications -- so this is
    # genuine encryption, not hashing. A separate key from every other
    # secret in this service, same reasoning as session_secret_key: a leak
    # of one should not compromise the others.
    notification_encryption_key: str
    grace_receipt_valid_hours: int = 168
    rate_limit_per_minute: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings.

    Returns:
        Loaded settings singleton.
    """

    return Settings()
