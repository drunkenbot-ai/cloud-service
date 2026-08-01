"""Database read/write operations, kept separate from route handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, AdminUser, ApiKey, AuditLog, LaunchEvent, License, NotificationSettings
from app.security import generate_api_key, generate_license_key, hash_secret_key, hash_password
from app.crypto_secrets import encrypt_secret


def get_notification_settings(db: Session) -> NotificationSettings:
    """Fetch the singleton notification settings row, creating it if needed.

    Args:
        db: Active database session.

    Returns:
        Notification settings row (always exactly one).
    """

    settings = db.get(NotificationSettings, "singleton")
    if settings is None:
        settings = NotificationSettings(id="singleton")
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_notification_settings(
    db: Session,
    updated_by_admin_id: str,
    email_enabled: bool,
    gmail_address: Optional[str],
    gmail_app_password: Optional[str],
    recipient_email: Optional[str],
    telegram_enabled: bool,
    telegram_bot_token: Optional[str],
    telegram_chat_id: Optional[str],
    discord_enabled: bool,
    discord_webhook_url: Optional[str],
    notify_account_created: bool,
    notify_account_status_changed: bool,
    notify_license_created: bool,
    notify_license_revoked: bool,
    notify_license_extended: bool,
) -> NotificationSettings:
    """Update notification settings.

    Secret fields (``gmail_app_password``, ``telegram_bot_token``,
    ``discord_webhook_url``) are only re-encrypted and overwritten when a
    non-blank value is provided -- the settings page never redisplays a
    saved secret, so "leave blank to keep the current value" is the only
    sane way for a superadmin to edit non-secret fields (like the
    recipient email) without being forced to re-enter secrets that are
    already saved.

    Args:
        db: Active database session.
        updated_by_admin_id: Admin making this change.
        email_enabled: Whether email alerts are enabled.
        gmail_address: Gmail account used to send alerts.
        gmail_app_password: New Gmail app password, or blank to keep the
            existing one.
        recipient_email: Where alerts are sent.
        telegram_enabled: Whether Telegram alerts are enabled.
        telegram_bot_token: New bot token, or blank to keep the existing one.
        telegram_chat_id: Telegram chat ID to send alerts to.
        discord_enabled: Whether Discord alerts are enabled.
        discord_webhook_url: New webhook URL, or blank to keep the existing
            one.
        notify_account_created: Whether to alert on account creation.
        notify_account_status_changed: Whether to alert on suspend/reactivate.
        notify_license_created: Whether to alert on license issuance.
        notify_license_revoked: Whether to alert on license revocation.
        notify_license_extended: Whether to alert on grace/upgrade grants.

    Returns:
        Updated notification settings row.
    """

    settings = get_notification_settings(db)
    settings.email_enabled = email_enabled
    settings.gmail_address = gmail_address or None
    if gmail_app_password:
        settings.gmail_app_password_encrypted = encrypt_secret(gmail_app_password)
    settings.recipient_email = recipient_email or None

    settings.telegram_enabled = telegram_enabled
    if telegram_bot_token:
        settings.telegram_bot_token_encrypted = encrypt_secret(telegram_bot_token)
    settings.telegram_chat_id = telegram_chat_id or None

    settings.discord_enabled = discord_enabled
    if discord_webhook_url:
        settings.discord_webhook_url_encrypted = encrypt_secret(discord_webhook_url)

    settings.notify_account_created = notify_account_created
    settings.notify_account_status_changed = notify_account_status_changed
    settings.notify_license_created = notify_license_created
    settings.notify_license_revoked = notify_license_revoked
    settings.notify_license_extended = notify_license_extended
    settings.updated_by_admin_id = updated_by_admin_id

    db.commit()
    db.refresh(settings)
    return settings


def get_admin_user_by_email(db: Session, email: str) -> Optional[AdminUser]:
    """Fetch an admin user by email.

    Args:
        db: Active database session.
        email: Admin user's email.

    Returns:
        Matching admin user, or ``None``.
    """

    return db.execute(select(AdminUser).where(AdminUser.email == email)).scalar_one_or_none()


def create_admin_user(
    db: Session,
    email: str,
    password: str,
    role: str,
    created_by_admin_id: Optional[str],
) -> AdminUser:
    """Create a new admin user.

    Args:
        db: Active database session.
        email: New admin's email, used to log in.
        password: Plaintext password, hashed before storage.
        role: One of "readonly", "full", "superadmin".
        created_by_admin_id: ID of the admin creating this one, for
            accountability. ``None`` only for the bootstrap first admin.

    Returns:
        Newly created admin user.
    """

    admin = AdminUser(
        email=email,
        password_hash=hash_password(password),
        role=role,
        created_by_admin_id=created_by_admin_id,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def list_admin_users(db: Session) -> list[AdminUser]:
    """List every admin user.

    Args:
        db: Active database session.

    Returns:
        Admin users, most recently created first.
    """

    return list(db.execute(select(AdminUser).order_by(AdminUser.created_at.desc())).scalars().all())


def set_admin_user_status(db: Session, admin: AdminUser, status: str) -> AdminUser:
    """Enable or disable an admin user's login access.

    Args:
        db: Active database session.
        admin: Admin user to update.
        status: "active" or "disabled".

    Returns:
        Updated admin user.
    """

    admin.status = status
    db.commit()
    db.refresh(admin)
    return admin


def set_admin_user_role(db: Session, admin: AdminUser, role: str) -> AdminUser:
    """Change an admin user's role.

    Args:
        db: Active database session.
        admin: Admin user to update.
        role: New role: "readonly", "full", or "superadmin".

    Returns:
        Updated admin user.
    """

    admin.role = role
    db.commit()
    db.refresh(admin)
    return admin


def record_admin_login(db: Session, admin: AdminUser) -> None:
    """Update an admin user's last-login timestamp.

    Args:
        db: Active database session.
        admin: Admin user who just logged in.
    """

    admin.last_login_at = _utc_now_for_crud()
    db.commit()


def _utc_now_for_crud():
    """Return the current UTC time (mirrors models._utc_now for crud use)."""

    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def list_accounts(db: Session, search: Optional[str] = None, limit: int = 200) -> list[Account]:
    """List accounts, optionally filtered by email/company substring.

    Args:
        db: Active database session.
        search: Optional case-insensitive substring to match against email
            or company name.
        limit: Maximum rows to return.

    Returns:
        Matching accounts, most recently created first.
    """

    query = select(Account).order_by(Account.created_at.desc()).limit(limit)
    if search:
        pattern = f"%{search.lower()}%"
        query = select(Account).where(
            (Account.email.ilike(pattern)) | (Account.company_name.ilike(pattern))
        ).order_by(Account.created_at.desc()).limit(limit)
    return list(db.execute(query).scalars().all())


def set_account_status(db: Session, account: Account, status: str) -> Account:
    """Set an account's status (e.g. suspend or reactivate).

    Args:
        db: Active database session.
        account: Account to update.
        status: New status, ``"active"`` or ``"suspended"``.

    Returns:
        Updated account.
    """

    account.status = status
    db.commit()
    db.refresh(account)
    return account


def list_licenses_for_account(db: Session, account_id: str) -> list[License]:
    """List every license belonging to an account.

    Args:
        db: Active database session.
        account_id: Owning account ID.

    Returns:
        Licenses, most recently issued first.
    """

    return list(
        db.execute(
            select(License).where(License.account_id == account_id).order_by(License.issued_at.desc())
        ).scalars().all()
    )


def list_api_keys_for_account(db: Session, account_id: str) -> list[ApiKey]:
    """List every API key belonging to an account.

    Args:
        db: Active database session.
        account_id: Owning account ID.

    Returns:
        API keys, most recently created first.
    """

    return list(
        db.execute(
            select(ApiKey).where(ApiKey.account_id == account_id).order_by(ApiKey.created_at.desc())
        ).scalars().all()
    )


def list_audit_log(
    db: Session,
    account_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> list[AuditLog]:
    """List recent audit log entries, optionally filtered.

    Args:
        db: Active database session.
        account_id: Optional account filter.
        event_type: Optional exact event-type filter.
        limit: Maximum rows to return.

    Returns:
        Matching entries, most recent first.
    """

    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if account_id:
        query = query.where(AuditLog.account_id == account_id)
    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    return list(db.execute(query).scalars().all())


def list_launch_events(db: Session, account_id: Optional[str] = None, limit: int = 100) -> list[LaunchEvent]:
    """List recent launch telemetry events, optionally filtered by account.

    Args:
        db: Active database session.
        account_id: Optional account filter.
        limit: Maximum rows to return.

    Returns:
        Matching events, most recent first.
    """

    query = select(LaunchEvent).order_by(LaunchEvent.created_at.desc()).limit(limit)
    if account_id:
        query = query.where(LaunchEvent.account_id == account_id)
    return list(db.execute(query).scalars().all())


def dashboard_counts(db: Session) -> dict[str, int]:
    """Return summary counts for the admin dashboard.

    Args:
        db: Active database session.

    Returns:
        Dict of count labels to values.
    """

    from sqlalchemy import func

    return {
        "accounts": db.execute(select(func.count()).select_from(Account)).scalar_one(),
        "active_licenses": db.execute(
            select(func.count()).select_from(License).where(License.status == "active")
        ).scalar_one(),
        "active_api_keys": db.execute(
            select(func.count()).select_from(ApiKey).where(ApiKey.status == "active")
        ).scalar_one(),
        "launches_recorded": db.execute(select(func.count()).select_from(LaunchEvent)).scalar_one(),
    }


def record_launch_event(
    db: Session,
    machine_id: str,
    app_version: str,
    account_id: Optional[str] = None,
    license_id: Optional[str] = None,
    os: Optional[str] = None,
    os_version: Optional[str] = None,
    ip_address: Optional[str] = None,
    ip_city: Optional[str] = None,
    ip_country: Optional[str] = None,
    isp: Optional[str] = None,
) -> None:
    """Record one launch telemetry event.

    Args:
        db: Active database session.
        machine_id: Client-generated pseudonymous machine identifier.
        app_version: Running app version.
        account_id: Associated account, if the license resolved to one.
        license_id: Associated license, if it resolved.
        os: Operating system name, if reported.
        os_version: Operating system version, if reported.
        ip_address: Request source IP.
    """

    db.add(
        LaunchEvent(
            account_id=account_id,
            license_id=license_id,
            machine_id=machine_id,
            os=os,
            os_version=os_version,
            app_version=app_version,
            ip_address=ip_address,
            ip_city=ip_city,
            ip_country=ip_country,
            isp=isp,
        )
    )
    db.commit()


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

    key_hash = hash_secret_key(license_key)
    return db.execute(select(License).where(License.license_key_hash == key_hash)).scalar_one_or_none()


def create_license(
    db: Session,
    account_id: str,
    version_ceiling: str,
    grace_period_until: Optional[datetime],
) -> tuple[License, str]:
    """Issue a new IDE license for an account.

    Args:
        db: Active database session.
        account_id: Owning account ID.
        version_ceiling: Highest app version this license covers.
        grace_period_until: Optional temporary extension past the ceiling.

    Returns:
        Tuple of the created row and the plaintext license key -- the
        plaintext value is never stored and cannot be retrieved again
        (mirrors ``create_api_key``).
    """

    plaintext_key = generate_license_key()
    license_row = License(
        account_id=account_id,
        license_key_hash=hash_secret_key(plaintext_key),
        license_key_prefix=plaintext_key[:14],
        version_ceiling=version_ceiling,
        grace_period_until=grace_period_until,
    )
    db.add(license_row)
    db.commit()
    db.refresh(license_row)
    return license_row, plaintext_key


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
        key_hash=hash_secret_key(plaintext_key),
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
