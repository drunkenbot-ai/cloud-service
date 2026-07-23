"""Audit log writer, used by every validation and admin route."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog


def record_event(
    db: Session,
    event_type: str,
    result: str,
    account_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Append one audit log entry and commit it immediately.

    Committed independently of the caller's own transaction so an audit
    record is never lost because a later step in the same request rolled
    back.

    Args:
        db: Active database session.
        event_type: Short event name, e.g. ``"license.validate"``.
        result: ``"success"`` or ``"failure"``.
        account_id: Account the event relates to, if known.
        subject_id: License/API key/other subject ID, if applicable.
        detail: Extra JSON-serializable context.
        ip_address: Client IP address, if available.
    """

    entry = AuditLog(
        event_type=event_type,
        account_id=account_id,
        subject_id=subject_id,
        result=result,
        detail=detail,
        ip_address=ip_address,
    )
    db.add(entry)
    db.commit()
