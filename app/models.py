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
        license_key: Short customer-facing identifier (what they actually
            type/paste into the IDE's activation dialog). Distinct from the
            signed payload issued after validation.
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
    license_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
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
