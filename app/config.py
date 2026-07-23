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

    model_config = SettingsConfigDict(env_file=r"E:\AI_Projects\cloud-service\.env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    signing_private_key_b64: str
    admin_api_token: str
    grace_receipt_valid_hours: int = 168
    rate_limit_per_minute: int = 30,



@lru_cache
def get_settings() -> Settings:
    """Return cached application settings.

    Returns:
        Loaded settings singleton.
    """

    return Settings()
