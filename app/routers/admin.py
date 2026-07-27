"""``/admin/*`` -- protected by a shared admin bearer token (see README).

Deliberately bare-bones for v1: no web UI, just endpoints DrunkenBot staff
call directly (via curl, a small internal script, or FastAPI's auto-generated
``/docs``) to issue and manage licenses/keys by hand.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud
from app.audit import record_event
from app.notifications import notify_event
from app.db import get_db
from app.models import Account, ApiKey, License
from app.schemas import (
    AccountCreateRequest,
    AccountResponse,
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    LicenseCreateRequest,
    LicenseCreateResponse,
    LicenseExtendRequest,
)
from app.security import require_admin_token

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])


def _get_account_or_404(db: Session, account_id: str) -> Account:
    """Fetch an account or raise a 404.

    Args:
        db: Active database session.
        account_id: Account primary key.

    Returns:
        Matching account.

    Raises:
        HTTPException: 404 if no account matches.
    """

    account = crud.get_account(db, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    return account


@router.post("/accounts", response_model=AccountResponse)
def create_account(payload: AccountCreateRequest, db: Session = Depends(get_db)) -> Account:
    """Create a new customer account.

    Args:
        payload: Account details.
        db: Database session.

    Returns:
        Newly created account.
    """

    account = crud.create_account(db, str(payload.email), payload.company_name, payload.notes)
    record_event(db, "admin.account.create", "success", account_id=account.id)
    notify_event(db, "account_created", f"Account created: {account.email}", {"company": payload.company_name or "-"})
    return account


@router.post("/licenses", response_model=LicenseCreateResponse)
def create_license(payload: LicenseCreateRequest, db: Session = Depends(get_db)) -> LicenseCreateResponse:
    """Issue a new IDE license for an account.

    Args:
        payload: License details.
        db: Database session.

    Returns:
        Newly created license, including its plaintext key -- shown only
        this once.
    """

    account = _get_account_or_404(db, payload.account_id)
    license_row, plaintext_key = crud.create_license(
        db, payload.account_id, payload.version_ceiling, payload.grace_period_until
    )
    record_event(db, "admin.license.create", "success", account_id=payload.account_id, subject_id=license_row.id)
    notify_event(
        db,
        "license_created",
        f"License issued for {account.email}",
        {"version_ceiling": payload.version_ceiling, "license_key": license_row.license_key_prefix + "..."},
    )
    return LicenseCreateResponse(
        id=license_row.id,
        license_key=plaintext_key,
        version_ceiling=license_row.version_ceiling,
        grace_period_until=license_row.grace_period_until,
    )


@router.post("/licenses/{license_id}/extend", response_model=LicenseCreateResponse)
def extend_license(
    license_id: str,
    payload: LicenseExtendRequest,
    db: Session = Depends(get_db),
) -> LicenseCreateResponse:
    """Grant a free upgrade and/or grace period on an existing license.

    Args:
        license_id: License to modify.
        payload: New version ceiling and/or grace period end.
        db: Database session.

    Returns:
        Updated license. ``license_key`` in the response is the masked
        prefix, not the full key -- the plaintext is never retrievable
        after creation (see ``License.license_key_hash``).

    Raises:
        HTTPException: 404 if the license does not exist.
    """

    license_row = db.get(License, license_id)
    if license_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found.")
    license_row = crud.extend_license(db, license_row, payload.version_ceiling, payload.grace_period_until)
    record_event(
        db,
        "admin.license.extend",
        "success",
        account_id=license_row.account_id,
        subject_id=license_row.id,
        detail=payload.model_dump(mode="json"),
    )
    extended_account = crud.get_account(db, license_row.account_id)
    notify_event(
        db,
        "license_extended",
        f"License extended (grace/upgrade) for {extended_account.email if extended_account else license_row.account_id}",
        {"new_version_ceiling": license_row.version_ceiling, "license_key": license_row.license_key_prefix + "..."},
    )
    return LicenseCreateResponse(
        id=license_row.id,
        license_key=license_row.license_key_prefix + "...",
        version_ceiling=license_row.version_ceiling,
        grace_period_until=license_row.grace_period_until,
    )


@router.post("/licenses/{license_id}/revoke")
def revoke_license(license_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    """Revoke an IDE license.

    Args:
        license_id: License to revoke.
        db: Database session.

    Returns:
        Confirmation payload.

    Raises:
        HTTPException: 404 if the license does not exist.
    """

    license_row = db.get(License, license_id)
    if license_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found.")
    crud.revoke_license(db, license_row)
    record_event(db, "admin.license.revoke", "success", account_id=license_row.account_id, subject_id=license_id)
    revoked_account = crud.get_account(db, license_row.account_id)
    notify_event(
        db,
        "license_revoked",
        f"License revoked for {revoked_account.email if revoked_account else license_row.account_id}",
        {"license_key": license_row.license_key_prefix + "..."},
    )
    return {"status": "revoked", "license_id": license_id}


@router.post("/api-keys", response_model=ApiKeyCreateResponse)
def create_api_key(payload: ApiKeyCreateRequest, db: Session = Depends(get_db)) -> ApiKeyCreateResponse:
    """Issue a new cloud-training API key for an account.

    Args:
        payload: API key details.
        db: Database session.

    Returns:
        Newly created key, including its plaintext value -- shown only this
        once.
    """

    _get_account_or_404(db, payload.account_id)
    key_row, plaintext_key = crud.create_api_key(
        db, payload.account_id, payload.tier, payload.quota_gpu_hours_per_month
    )
    record_event(db, "admin.api_key.create", "success", account_id=payload.account_id, subject_id=key_row.id)
    return ApiKeyCreateResponse(
        id=key_row.id,
        api_key=plaintext_key,
        tier=key_row.tier,
        quota_gpu_hours_per_month=key_row.quota_gpu_hours_per_month,
    )


@router.post("/api-keys/{api_key_id}/revoke")
def revoke_api_key(api_key_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    """Revoke a cloud-training API key.

    Args:
        api_key_id: API key to revoke.
        db: Database session.

    Returns:
        Confirmation payload.

    Raises:
        HTTPException: 404 if the key does not exist.
    """

    key_row = db.get(ApiKey, api_key_id)
    if key_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    crud.revoke_api_key(db, key_row)
    record_event(db, "admin.api_key.revoke", "success", account_id=key_row.account_id, subject_id=api_key_id)
    return {"status": "revoked", "api_key_id": api_key_id}
