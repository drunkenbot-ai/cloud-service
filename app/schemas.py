"""Pydantic request/response models for every route."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LaunchTelemetry(BaseModel):
    """Optional, privacy-conscious launch telemetry sent with a license check.

    Deliberately excludes anything directly identifying (no OS username, no
    email beyond what the license key already implies, no hostname). ISP/
    geo information is derived server-side from the request's source IP,
    not self-reported by the client -- both more reliable and one less
    thing the client needs to detect about itself.
    """

    machine_id: str = Field(description="Stable, locally-generated pseudonymous ID -- not a hardware serial.")
    os: Optional[str] = Field(default=None, description="e.g. 'Windows', 'macOS', 'Linux'.")
    os_version: Optional[str] = None


class LicenseValidateRequest(BaseModel):
    """Request body for ``POST /license/validate``."""

    license_key: str
    app_version: str = Field(description="Semantic version of the running IDE build, e.g. '2.1.0'.")
    telemetry: Optional[LaunchTelemetry] = None


class LicenseValidateResponse(BaseModel):
    """Response body for ``POST /license/validate``.

    ``receipt`` and ``signature`` together form the offline grace receipt
    the IDE caches locally: ``receipt`` is the exact JSON string that was
    signed (verify against this exact string, not a re-serialized copy),
    and ``signature`` is the base64 Ed25519 signature over it.
    """

    valid: bool
    reason: Optional[str] = None
    version_ceiling: Optional[str] = None
    grace_period_until: Optional[datetime] = None
    receipt: Optional[str] = None
    signature: Optional[str] = None


class ApiKeyValidateResponse(BaseModel):
    """Response body for ``POST /auth/validate-key``."""

    valid: bool
    reason: Optional[str] = None
    account_id: Optional[str] = None
    tier: Optional[str] = None
    quota_gpu_hours_per_month: Optional[float] = None


class AccountCreateRequest(BaseModel):
    """Admin request to create a new account."""

    email: EmailStr
    company_name: Optional[str] = None
    notes: Optional[str] = None


class AccountResponse(BaseModel):
    """Admin-facing account representation."""

    id: str
    email: str
    company_name: Optional[str]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LicenseCreateRequest(BaseModel):
    """Admin request to issue a new IDE license."""

    account_id: str
    version_ceiling: str
    grace_period_until: Optional[datetime] = None


class LicenseCreateResponse(BaseModel):
    """Admin response after issuing a license, including the plaintext key.

    The plaintext ``license_key`` is only ever returned here, at creation
    time -- send it to the customer immediately, it is not retrievable
    again through any other endpoint.
    """

    id: str
    license_key: str
    version_ceiling: str
    grace_period_until: Optional[datetime]


class LicenseExtendRequest(BaseModel):
    """Admin request to grant a free upgrade or grace period.

    Both fields are optional and independent: raise ``version_ceiling`` for
    a permanent entitlement bump, or set ``grace_period_until`` for a
    temporary extension without changing the permanent ceiling. Omit a
    field to leave it unchanged.
    """

    version_ceiling: Optional[str] = None
    grace_period_until: Optional[datetime] = None


class ApiKeyCreateRequest(BaseModel):
    """Admin request to issue a new cloud-training API key."""

    account_id: str
    tier: str = "free"
    quota_gpu_hours_per_month: Optional[float] = None


class ApiKeyCreateResponse(BaseModel):
    """Admin response after issuing an API key, including the plaintext key.

    The plaintext ``api_key`` is only ever returned here, at creation time.
    """

    id: str
    api_key: str
    tier: str
    quota_gpu_hours_per_month: Optional[float]
