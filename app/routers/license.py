"""``/license/validate`` -- called by LLM-IDE at launch."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import crud
from app.audit import record_event
from app.config import get_settings
from app.db import get_db
from app.rate_limit import enforce_rate_limit
from app.schemas import LicenseValidateRequest, LicenseValidateResponse
from app.security import sign_payload
from app.versioning import is_version_within_ceiling
from app.geolocation import lookup

router = APIRouter(prefix="/license", tags=["license"])


@router.post("/validate", response_model=LicenseValidateResponse, dependencies=[Depends(enforce_rate_limit)])
def validate_license(
    payload: LicenseValidateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LicenseValidateResponse:
    """Validate an IDE license and, if valid, issue a signed grace receipt.

    The IDE caches the returned ``receipt``/``signature`` pair locally and
    can use it to launch offline for a limited window (see
    ``GRACE_RECEIPT_VALID_HOURS``) if this endpoint is unreachable next time,
    re-validating opportunistically whenever it can reach the server again.

    Args:
        payload: License key and the running app's version.
        request: Incoming request, used to record the client IP.
        db: Database session.

    Returns:
        Validation result, with a signed grace receipt when valid.
    """

    client_ip = request.headers.get("CF-Connecting-IP")
    if not client_ip:
        forwarded_for = request.headers.get("X-Forwarded-For")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else None
    if not client_ip:
        client_ip = request.client.host if request.client else None
    location = lookup(client_ip)
    license_row = crud.get_license_by_key(db, payload.license_key)

    if payload.telemetry is not None:
        crud.record_launch_event(
            db,
            machine_id=payload.telemetry.machine_id,
            app_version=payload.app_version,
            account_id=license_row.account_id if license_row else None,
            license_id=license_row.id if license_row else None,
            os=payload.telemetry.os,
            os_version=payload.telemetry.os_version,
            ip_address=client_ip,
            ip_city=location["city"],
            ip_country=location["country"],
            isp=location["isp"],
        )

    if license_row is None:
        record_event(db, "license.validate", "failure", detail={"reason": "not_found"}, ip_address=client_ip)
        return LicenseValidateResponse(valid=False, reason="License key not found.")

    account = crud.get_account(db, license_row.account_id)
    if account is None or account.status != "active":
        record_event(
            db,
            "license.validate",
            "failure",
            account_id=license_row.account_id,
            subject_id=license_row.id,
            detail={"reason": "account_inactive"},
            ip_address=client_ip,
        )
        return LicenseValidateResponse(valid=False, reason="Account is not active.")

    if license_row.status != "active":
        record_event(
            db,
            "license.validate",
            "failure",
            account_id=license_row.account_id,
            subject_id=license_row.id,
            detail={"reason": "license_revoked"},
            ip_address=client_ip,
        )
        return LicenseValidateResponse(valid=False, reason="License has been revoked.")

    now = datetime.now(timezone.utc)
    within_ceiling = is_version_within_ceiling(payload.app_version, license_row.version_ceiling)
    within_grace = bool(license_row.grace_period_until and now <= license_row.grace_period_until)

    if not within_ceiling and not within_grace:
        record_event(
            db,
            "license.validate",
            "failure",
            account_id=license_row.account_id,
            subject_id=license_row.id,
            detail={
                "reason": "version_not_covered",
                "app_version": payload.app_version,
                "version_ceiling": license_row.version_ceiling,
            },
            ip_address=client_ip,
        )
        return LicenseValidateResponse(
            valid=False,
            reason=(
                f"This license covers up to version {license_row.version_ceiling}. "
                "Please purchase an upgrade license to run this version."
            ),
            version_ceiling=license_row.version_ceiling,
            grace_period_until=license_row.grace_period_until,
        )

    settings = get_settings()
    valid_until = now + timedelta(hours=settings.grace_receipt_valid_hours)
    receipt = {
        "account_id": license_row.account_id,
        "license_id": license_row.id,
        "version_ceiling": license_row.version_ceiling,
        "valid_until": valid_until.isoformat(),
        "issued_at": now.isoformat(),
    }
    # sort_keys + compact separators: must be canonical so the exact same
    # receipt dict always produces the exact same bytes to sign/verify.
    canonical_receipt = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    signature = sign_payload(canonical_receipt.encode("utf-8"))

    license_row.last_validated_at = now
    db.commit()
    record_event(
        db,
        "license.validate",
        "success",
        account_id=license_row.account_id,
        subject_id=license_row.id,
        ip_address=client_ip,
    )
    return LicenseValidateResponse(
        valid=True,
        version_ceiling=license_row.version_ceiling,
        grace_period_until=license_row.grace_period_until,
        receipt=canonical_receipt,
        signature=signature,
    )
