"""``/auth/validate-key`` -- called by the Job Manager on incoming requests."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app import crud
from app.audit import record_event
from app.db import get_db
from app.rate_limit import enforce_rate_limit
from app.models import GpuUsageRecord
from app.schemas import ApiKeyValidateResponse, GpuUsageReportRequest, GpuUsageReportResponse
from app.security import hash_secret_key

router = APIRouter(prefix="/auth", tags=["auth"])


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


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


@router.post("/report-usage", response_model=GpuUsageReportResponse, dependencies=[Depends(enforce_rate_limit)])
def report_usage(request: Request, usage: GpuUsageReportRequest, authorization: str = Header(default=""), db: Session = Depends(get_db)) -> GpuUsageReportResponse:
    """Atomically debit one completed job, idempotently by its job id."""
    client_ip = request.client.host if request.client else None
    if not authorization.startswith("Bearer "):
        return GpuUsageReportResponse(accepted=False, reason="Missing or malformed Authorization header.")
    key = crud.get_api_key_by_hash(db, hash_secret_key(authorization.removeprefix("Bearer ").strip()))
    account = crud.get_account(db, key.account_id) if key else None
    if key is None or key.status != "active" or account is None or account.status != "active":
        return GpuUsageReportResponse(accepted=False, reason="API key or account is not active.")
    existing = db.execute(select(GpuUsageRecord).where(GpuUsageRecord.job_id == usage.job_id)).scalar_one_or_none()
    if existing:
        if existing.account_id != key.account_id:
            return GpuUsageReportResponse(accepted=False, reason="Job usage belongs to another account.")
        remaining = _remaining(db, key)
        return GpuUsageReportResponse(accepted=True, gpu_hours_remaining=remaining)
    remaining = _remaining(db, key)
    if remaining is not None and usage.gpu_hours > remaining + 1e-9:
        record_event(db, "auth.report_usage", "failure", account_id=key.account_id, subject_id=key.id, detail={"reason": "quota_exhausted", "job_id": usage.job_id}, ip_address=client_ip)
        return GpuUsageReportResponse(accepted=False, reason="GPU-hours quota exhausted.", gpu_hours_remaining=remaining)
    db.add(GpuUsageRecord(job_id=usage.job_id, account_id=key.account_id, api_key_id=key.id, gpu_hours=usage.gpu_hours, gpu_count=usage.gpu_count, started_at=usage.started_at, completed_at=usage.completed_at))
    key.last_used_at = datetime.now(timezone.utc)
    db.commit()
    remaining = _remaining(db, key)
    record_event(db, "auth.report_usage", "success", account_id=key.account_id, subject_id=key.id, detail={"job_id": usage.job_id, "gpu_hours": usage.gpu_hours}, ip_address=client_ip)
    return GpuUsageReportResponse(accepted=True, gpu_hours_remaining=remaining)


def _remaining(db: Session, key) -> float | None:
    if key.quota_gpu_hours_per_month is None:
        return None
    used = db.execute(select(func.coalesce(func.sum(GpuUsageRecord.gpu_hours), 0.0)).where(GpuUsageRecord.api_key_id == key.id, GpuUsageRecord.reported_at >= _month_start())).scalar_one()
    return max(0.0, float(key.quota_gpu_hours_per_month) - float(used))
