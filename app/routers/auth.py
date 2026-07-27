"""``/auth/validate-key`` -- called by the Job Manager on incoming requests."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app import crud
from app.audit import record_event
from app.db import get_db
from app.rate_limit import enforce_rate_limit
from app.schemas import ApiKeyValidateResponse
from app.security import hash_secret_key

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/validate-key", response_model=ApiKeyValidateResponse, dependencies=[Depends(enforce_rate_limit)])
def validate_api_key(
    request: Request,
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> ApiKeyValidateResponse:
    """Validate a cloud-training API key presented as a bearer token.

    Intended to be called by the Job Manager for each incoming worker/IDE
    request (or cached briefly on its side -- see the architecture plan for
    the caching tradeoff). Expects ``Authorization: Bearer <api_key>``.

    Args:
        request: Incoming request, used to record the client IP.
        authorization: Raw ``Authorization`` header value.
        db: Database session.

    Returns:
        Validation result with account/tier/quota info when valid.
    """

    client_ip = request.client.host if request.client else None
    if not authorization.startswith("Bearer "):
        return ApiKeyValidateResponse(valid=False, reason="Missing or malformed Authorization header.")

    plaintext_key = authorization.removeprefix("Bearer ").strip()
    key_row = crud.get_api_key_by_hash(db, hash_secret_key(plaintext_key))

    if key_row is None:
        record_event(db, "auth.validate_key", "failure", detail={"reason": "not_found"}, ip_address=client_ip)
        return ApiKeyValidateResponse(valid=False, reason="API key not found.")

    if key_row.status != "active":
        record_event(
            db,
            "auth.validate_key",
            "failure",
            account_id=key_row.account_id,
            subject_id=key_row.id,
            detail={"reason": "key_revoked"},
            ip_address=client_ip,
        )
        return ApiKeyValidateResponse(valid=False, reason="API key has been revoked.")

    account = crud.get_account(db, key_row.account_id)
    if account is None or account.status != "active":
        record_event(
            db,
            "auth.validate_key",
            "failure",
            account_id=key_row.account_id,
            subject_id=key_row.id,
            detail={"reason": "account_inactive"},
            ip_address=client_ip,
        )
        return ApiKeyValidateResponse(valid=False, reason="Account is not active.")

    key_row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    record_event(
        db,
        "auth.validate_key",
        "success",
        account_id=key_row.account_id,
        subject_id=key_row.id,
        ip_address=client_ip,
    )
    return ApiKeyValidateResponse(
        valid=True,
        account_id=key_row.account_id,
        tier=key_row.tier,
        quota_gpu_hours_per_month=key_row.quota_gpu_hours_per_month,
    )
