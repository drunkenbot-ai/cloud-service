"""ORM models: accounts, IDE licenses, cloud-training API keys, audit log."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_str() -> str:
    """Return a new UUID4 as a string, used as a primary key default.

    Returns:
        UUID4 hex string.
    """

    return str(uuid.uuid4())


def _utc_now() -> datetime:
    """Return the current UTC time.

    Returns:
        Timezone-aware current UTC datetime.
    """

    return datetime.now(timezone.utc)


class Account(Base):
    """A DrunkenBot customer account.

    One account can hold both an IDE license and cloud-training API keys --
    they are the same customer, tracked once.
    """

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # "active" or "suspended". A suspended account fails every validation
    # check regardless of individual license/key status -- this is the
    # single fastest way to cut off a customer entirely (e.g. chargeback,
    # abuse, non-payment) without hunting down every license/key they hold.
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    licenses: Mapped[list["License"]] = relationship(back_populates="account")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="account")


class License(Base):
    """A permanent, per-version IDE license.

    Attributes:
        license_key_hash: SHA-256 hash of the plaintext license key used for
            lookup at validation time. The plaintext itself is never
            stored -- shown to the admin exactly once, at creation, the
            same principle as ApiKey.key_hash.
        license_key_prefix: First few characters of the plaintext key, kept
            only for display in the admin UI/logs so a license can be
            recognized without ever storing or logging the full value.
        version_ceiling: Highest app version this license entitles the
            holder to run, compared against the running app's version at
            validation time.
        grace_period_until: Optional temporary extension past
            version_ceiling, without changing the permanent entitlement --
            the mechanism for "free upgrade" or time-limited grace access.
    """

    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    license_key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    license_key_prefix: Mapped[str] = mapped_column(String(20))
    product: Mapped[str] = mapped_column(String(50), default="LLM-IDE")
    version_ceiling: Mapped[str] = mapped_column(String(50))
    grace_period_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # "active" or "revoked".
    status: Mapped[str] = mapped_column(String(20), default="active")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped["Account"] = relationship(back_populates="licenses")


class ApiKey(Base):
    """A cloud-training-farm API key used by the Job Manager.

    The plaintext key is shown to the customer exactly once at creation and
    never stored -- only its hash is kept, the same principle as a password.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # First few characters of the plaintext key, kept only for display in
    # the admin UI/logs (e.g. "dbk_live_ab12...") so a key can be recognized
    # without ever storing or logging the full secret.
    key_prefix: Mapped[str] = mapped_column(String(20))
    tier: Mapped[str] = mapped_column(String(30), default="free")
    quota_gpu_hours_per_month: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # "active" or "revoked".
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped["Account"] = relationship(back_populates="api_keys")


class GpuUsageRecord(Base):
    """Idempotent cloud-farm GPU-hour debit reported by a Farm Manager."""

    __tablename__ = "gpu_usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    # The manager's globally unique job id is the idempotency key: retries do
    # not double-charge after a timeout or lost response.
    job_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    api_key_id: Mapped[str] = mapped_column(ForeignKey("api_keys.id"), index=True)
    gpu_hours: Mapped[float] = mapped_column(Float)
    gpu_count: Mapped[int] = mapped_column(default=1)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True)


class NotificationSettings(Base):
    """Singleton row holding alert-channel configuration.

    Superadmin-only to view or edit (see app/admin_ui/router.py). Secret
    fields (*_encrypted) are encrypted at rest via app/crypto_secrets.py --
    genuine encryption, not hashing, since these need to be retrieved in
    plaintext to actually send notifications later.

    A single fixed row (id="singleton") rather than a general key-value
    settings table: there is exactly one global notification
    configuration for now, and a dedicated table with named columns is
    simpler to reason about and migrate than a generic settings blob.
    """

    __tablename__ = "notification_settings"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=lambda: "singleton")

    email_enabled: Mapped[bool] = mapped_column(default=False)
    gmail_address: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    gmail_app_password_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recipient_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    telegram_enabled: Mapped[bool] = mapped_column(default=False)
    telegram_bot_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    discord_enabled: Mapped[bool] = mapped_column(default=False)
    discord_webhook_url_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Per-event-category toggles, so noisy categories can be silenced
    # without disabling every channel entirely.
    notify_account_created: Mapped[bool] = mapped_column(default=True)
    notify_account_status_changed: Mapped[bool] = mapped_column(default=True)
    notify_license_created: Mapped[bool] = mapped_column(default=True)
    notify_license_revoked: Mapped[bool] = mapped_column(default=True)
    notify_license_extended: Mapped[bool] = mapped_column(default=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)
    updated_by_admin_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class AdminUser(Base):
    """A person with login access to the admin web UI.

    Attributes:
        role: One of "readonly", "full", or "superadmin". Ranked in that
            order -- see app/admin_ui/router.py's _ROLE_RANK. "full" covers
            everything today's single-shared-token admin could do (manage
            customer accounts/licenses/API keys); "superadmin" additionally
            covers managing OTHER admin users. Deliberately split: being
            trusted to manage customers is not the same as being trusted to
            grant other people admin access.
        created_by_admin_id: Which admin created this one, for
            accountability. Null for the first (bootstrap) superadmin.
    """

    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="readonly")
    # "active" or "disabled".
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    created_by_admin_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class LaunchEvent(Base):
    """One IDE launch's telemetry, recorded alongside license validation.

    Kept separate from ``AuditLog`` deliberately: this is usage-analytics
    volume (every launch, of every install), not security-audit volume
    (validation attempts and admin actions). Mixing them would make the
    audit log noisy and slow to query for its actual purpose.

    Geolocation fields are nullable because local/private addresses and
    provider outages cannot be resolved.
    """

    __tablename__ = "launch_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    account_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    license_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    machine_id: Mapped[str] = mapped_column(String(100), index=True)
    os: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    os_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    app_version: Mapped[str] = mapped_column(String(50))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    ip_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ip_country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    isp: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True)


class AuditLog(Base):
    """Append-only record of every validation and admin action.

    Every row here should be enough, on its own, to answer "who did what,
    to what, when, and did it succeed" without needing to cross-reference
    application logs.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    subject_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    result: Mapped[str] = mapped_column(String(20))
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True)
