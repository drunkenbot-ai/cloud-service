"""Database read/write operations, kept separate from route handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, ApiKey, License
from app.security import generate_api_key, generate_license_key, hash_api_key


def get_account(db: Session, account_id: str) -> Optional[Account]:
    """Fetch an account by ID.

    Args:
        db: Active database session.
        account_id: Account primary key.

    Returns:
        Matching account, or ``None``.
    """

    return db.get(Account, account_id)


def create_account(db: Session, email: str, company_name: Optional[str], notes: Optional[str]) -> Account:
    """Create a new account.

    Args:
        db: Active database session.
        email: Account email, used as the unique identifier for lookups.
        company_name: Optional company name.
        notes: Optional free-form admin notes.

    Returns:
        Newly created account.
    """

    account = Account(email=email, company_name=company_name, notes=notes)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def get_license_by_key(db: Session, license_key: str) -> Optional[License]:
    """Fetch a license by its customer-facing key.

    Args:
        db: Active database session.
        license_key: Plaintext license key as entered by the customer.

    Returns:
        Matching license, or ``None``.
    """

    return db.execute(select(License).where(License.license_key == license_key)).scalar_one_or_none()


def create_license(
    db: Session,
    account_id: str,
    version_ceiling: str,
    grace_period_until: Optional[datetime],
) -> License:
    """Issue a new IDE license for an account.

    Args:
        db: Active database session.
        account_id: Owning account ID.
        version_ceiling: Highest app version this license covers.
        grace_period_until: Optional temporary extension past the ceiling.

    Returns:
        Newly created license, with its plaintext ``license_key`` populated
        (this is the only time the plaintext key is available).
    """

    license_row = License(
        account_id=account_id,
        license_key=generate_license_key(),
        version_ceiling=version_ceiling,
        grace_period_until=grace_period_until,
    )
    db.add(license_row)
    db.commit()
    db.refresh(license_row)
    return license_row


def extend_license(
    db: Session,
    license_row: License,
    version_ceiling: Optional[str],
    grace_period_until: Optional[datetime],
) -> License:
    """Apply a free upgrade and/or grace period to an existing license.

    Args:
        db: Active database session.
        license_row: License to modify.
        version_ceiling: New version ceiling, or ``None`` to leave unchanged.
        grace_period_until: New grace period end, or ``None`` to leave
            unchanged.

    Returns:
        Updated license.
    """

    if version_ceiling is not None:
        license_row.version_ceiling = version_ceiling
    if grace_period_until is not None:
        license_row.grace_period_until = grace_period_until
    db.commit()
    db.refresh(license_row)
    return license_row


def revoke_license(db: Session, license_row: License) -> License:
    """Mark a license as revoked.

    Args:
        db: Active database session.
        license_row: License to revoke.

    Returns:
        Updated license.
    """

    license_row.status = "revoked"
    db.commit()
    db.refresh(license_row)
    return license_row


def get_api_key_by_hash(db: Session, key_hash: str) -> Optional[ApiKey]:
    """Fetch an API key row by its stored hash.

    Args:
        db: Active database session.
        key_hash: SHA-256 hash of the plaintext key presented by the caller.

    Returns:
        Matching API key row, or ``None``.
    """

    return db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash)).scalar_one_or_none()


def create_api_key(
    db: Session,
    account_id: str,
    tier: str,
    quota_gpu_hours_per_month: Optional[float],
) -> tuple[ApiKey, str]:
    """Issue a new cloud-training API key for an account.

    Args:
        db: Active database session.
        account_id: Owning account ID.
        tier: Subscription tier label.
        quota_gpu_hours_per_month: Optional monthly GPU-hour quota.

    Returns:
        Tuple of the created row and the plaintext key -- the plaintext
        value is never stored and cannot be retrieved again.
    """

    plaintext_key = generate_api_key()
    row = ApiKey(
        account_id=account_id,
        key_hash=hash_api_key(plaintext_key),
        key_prefix=plaintext_key[:16],
        tier=tier,
        quota_gpu_hours_per_month=quota_gpu_hours_per_month,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plaintext_key


def revoke_api_key(db: Session, api_key_row: ApiKey) -> ApiKey:
    """Mark an API key as revoked.

    Args:
        db: Active database session.
        api_key_row: API key row to revoke.

    Returns:
        Updated API key row.
    """

    api_key_row.status = "revoked"
    db.commit()
    db.refresh(api_key_row)
    return api_key_row
