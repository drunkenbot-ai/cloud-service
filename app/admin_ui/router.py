"""Server-rendered admin UI for managing accounts, licenses, and API keys.

Deliberately plain HTML + minimal CSS, no JS framework or build step --
this is an internal tool for DrunkenBot staff, not a customer-facing
product yet. See the cloud-service README for the reasoning behind keeping
this lean for v1.

Auth model: a single shared "master password" (the same ADMIN_API_TOKEN
used by the JSON /admin/* API) logs in via a form and sets a signed session
cookie (see SESSION_SECRET_KEY in app/config.py). This is a v1
simplification matching the existing single-shared-credential approach for
the API -- replace with real per-admin accounts before more than a
couple of people need access, so actions can be attributed to a person.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import crud
from app.audit import record_event
from app.notifications import notify_event
from app.db import SessionLocal
from app.models import Account, AdminUser, ApiKey, License
from app.rate_limit import enforce_rate_limit
from app.security import validate_password_strength, verify_password

router = APIRouter(prefix="/admin-ui", tags=["admin-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Roles are ranked so "does this session meet at least role X" is a single
# integer comparison rather than a hardcoded per-role branch everywhere.
_ROLE_RANK = {"readonly": 0, "full": 1, "superadmin": 2}


def _session_role(request: Request) -> str | None:
    """Return the logged-in admin's role for this session, if any.

    Args:
        request: Incoming request.

    Returns:
        Role string, or ``None`` if not logged in.
    """

    return request.session.get("admin_role")


def _require_login(request: Request) -> RedirectResponse | None:
    """Return a redirect to the login page if not authenticated.

    Args:
        request: Incoming request.

    Returns:
        Redirect response if unauthenticated, otherwise ``None``.
    """

    if not _session_role(request):
        return RedirectResponse(f"/admin-ui/login?next={request.url.path}", status_code=303)
    return None


def _require_role(request: Request, minimum_role: str) -> RedirectResponse | None:
    """Return a redirect/error page unless the session meets a minimum role.

    Args:
        request: Incoming request.
        minimum_role: Minimum required role: "readonly", "full", or
            "superadmin".

    Returns:
        A redirect to login (if not authenticated at all) or back to the
        dashboard with an error (if authenticated but under-privileged), or
        ``None`` if the session meets the requirement.
    """

    login_redirect = _require_login(request)
    if login_redirect:
        return login_redirect
    role = _session_role(request)
    if _ROLE_RANK.get(role, -1) < _ROLE_RANK[minimum_role]:
        return RedirectResponse("/admin-ui/?error=insufficient_permissions", status_code=303)
    return None


def _db() -> Session:
    """Open a plain (non-generator-dependency) session for use inside routes.

    Returns:
        New database session; callers are responsible for closing it.
    """

    return SessionLocal()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = "", next: str = "/admin-ui/") -> HTMLResponse:
    """Show the admin login form.

    Args:
        request: Incoming request.
        error: Optional error message to display.
        next: Page to redirect to after a successful login.

    Returns:
        Rendered login page.
    """

    return templates.TemplateResponse(
        request, "login.html", {"error": error, "next": next}
    )


@router.post("/login", dependencies=[Depends(enforce_rate_limit)])
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/admin-ui/"),
) -> RedirectResponse:
    """Handle admin login form submission.

    Rate-limited (shared limiter with the public validation endpoints) --
    unlike the previous single-shared-token login, this is now a real
    email/password surface and needs the same brute-force protection.

    Args:
        request: Incoming request.
        email: Admin's email.
        password: Admin's password.
        next: Page to redirect to after success.

    Returns:
        Redirect to ``next`` on success, back to the login form on failure.
    """

    client_ip = request.client.host if request.client else None
    db = _db()
    try:
        admin = crud.get_admin_user_by_email(db, email)
        if admin is None or admin.status != "active" or not verify_password(password, admin.password_hash):
            record_event(
                db, "admin_login_failed", "failure", detail={"email": email}, ip_address=client_ip
            )
            return RedirectResponse(f"/admin-ui/login?error=Invalid+email+or+password&next={next}", status_code=303)

        request.session["admin_user_id"] = admin.id
        request.session["admin_role"] = admin.role
        request.session["admin_email"] = admin.email
        crud.record_admin_login(db, admin)
        record_event(db, "admin_login", "success", account_id=None, subject_id=admin.id, ip_address=client_ip)
        return RedirectResponse(next or "/admin-ui/", status_code=303)
    finally:
        db.close()


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    """Clear the admin session.

    Args:
        request: Incoming request.

    Returns:
        Redirect to the login page.
    """

    request.session.clear()
    return RedirectResponse("/admin-ui/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Show the admin dashboard: summary counts and recent activity.

    Args:
        request: Incoming request.

    Returns:
        Rendered dashboard, or a redirect to login if unauthenticated.
    """

    redirect = _require_login(request)
    if redirect:
        return redirect
    db = _db()
    try:
        counts = crud.dashboard_counts(db)
        recent_audit = crud.list_audit_log(db, limit=15)
        recent_launches = crud.list_launch_events(db, limit=15)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"counts": counts, "recent_audit": recent_audit, "recent_launches": recent_launches},
        )
    finally:
        db.close()


@router.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request, search: str = "", created: str = ""):
    """List accounts, with an inline create-account form.

    Args:
        request: Incoming request.
        search: Optional search filter.
        created: Set to a license/api-key plaintext value right after
            creation, so it can be shown exactly once (see the note on
            those routes below).

    Returns:
        Rendered accounts page, or a redirect to login if unauthenticated.
    """

    redirect = _require_login(request)
    if redirect:
        return redirect
    db = _db()
    try:
        accounts = crud.list_accounts(db, search=search or None)
        return templates.TemplateResponse(
            request, "accounts.html", {"accounts": accounts, "search": search, "created": created}
        )
    finally:
        db.close()


@router.post("/accounts")
def create_account_submit(request: Request, email: str = Form(...), company_name: str = Form("")):
    """Create a new account from the admin UI form.

    Args:
        request: Incoming request.
        email: Account email.
        company_name: Optional company name.

    Returns:
        Redirect back to the accounts list, or to login/error if not
        authorized.
    """

    redirect = _require_role(request, "full")
    if redirect:
        return redirect
    db = _db()
    try:
        account = crud.create_account(db, email, company_name or None, None)
        record_event(db, "admin_ui.account.create", "success", account_id=account.id)
        notify_event(db, "account_created", f"Account created: {account.email}", {"company": company_name or "-"})
        return RedirectResponse("/admin-ui/accounts", status_code=303)
    finally:
        db.close()


@router.get("/accounts/{account_id}", response_class=HTMLResponse)
def account_detail(request: Request, account_id: str, created_license_key: str = "", created_api_key: str = ""):
    """Show one account's details, licenses, and API keys.

    Args:
        request: Incoming request.
        account_id: Account to display.
        created_license_key: Plaintext license key just created, shown once.
        created_api_key: Plaintext API key just created, shown once.

    Returns:
        Rendered account detail page, or a redirect if unauthenticated or
        the account does not exist.
    """

    redirect = _require_login(request)
    if redirect:
        return redirect
    db = _db()
    try:
        account = db.get(Account, account_id)
        if account is None:
            return RedirectResponse("/admin-ui/accounts", status_code=303)
        licenses = crud.list_licenses_for_account(db, account_id)
        api_keys = crud.list_api_keys_for_account(db, account_id)
        launches = crud.list_launch_events(db, account_id=account_id, limit=20)
        return templates.TemplateResponse(
            request,
            "account_detail.html",
            {
                "account": account,
                "licenses": licenses,
                "api_keys": api_keys,
                "launches": launches,
                "created_license_key": created_license_key,
                "created_api_key": created_api_key,
            },
        )
    finally:
        db.close()


@router.post("/accounts/{account_id}/status")
def set_account_status_submit(request: Request, account_id: str, status: str = Form(...)):
    """Suspend or reactivate an account.

    Args:
        request: Incoming request.
        account_id: Account to update.
        status: New status, ``"active"`` or ``"suspended"``.

    Returns:
        Redirect back to the account detail page, or to login if
        unauthenticated.
    """

    redirect = _require_role(request, "full")
    if redirect:
        return redirect
    db = _db()
    try:
        account = db.get(Account, account_id)
        if account is not None and status in {"active", "suspended"}:
            crud.set_account_status(db, account, status)
            record_event(db, "admin_ui.account.set_status", "success", account_id=account_id, detail={"status": status})
            notify_event(db, "account_status_changed", f"Account {status}: {account.email}", {"status": status})
        return RedirectResponse(f"/admin-ui/accounts/{account_id}", status_code=303)
    finally:
        db.close()


@router.post("/accounts/{account_id}/licenses")
def create_license_submit(request: Request, account_id: str, version_ceiling: str = Form(...)):
    """Issue a new license for an account.

    Args:
        request: Incoming request.
        account_id: Owning account.
        version_ceiling: Version ceiling for the new license.

    Returns:
        Redirect to the account detail page with the new plaintext license
        key shown once, or to login if unauthenticated.
    """

    redirect = _require_role(request, "full")
    if redirect:
        return redirect
    db = _db()
    try:
        license_row, plaintext_key = crud.create_license(db, account_id, version_ceiling, None)
        record_event(db, "admin_ui.license.create", "success", account_id=account_id, subject_id=license_row.id)
        account = crud.get_account(db, account_id)
        notify_event(
            db,
            "license_created",
            f"License issued for {account.email if account else account_id}",
            {"version_ceiling": version_ceiling, "license_key": license_row.license_key_prefix + "..."},
        )
        return RedirectResponse(
            f"/admin-ui/accounts/{account_id}?created_license_key={plaintext_key}", status_code=303
        )
    finally:
        db.close()


@router.post("/licenses/{license_id}/revoke")
def revoke_license_submit(request: Request, license_id: str, account_id: str = Form(...)):
    """Revoke a license.

    Args:
        request: Incoming request.
        license_id: License to revoke.
        account_id: Owning account, used to redirect back to its page.

    Returns:
        Redirect back to the account detail page, or to login if
        unauthenticated.
    """

    redirect = _require_role(request, "full")
    if redirect:
        return redirect
    db = _db()
    try:
        license_row = db.get(License, license_id)
        if license_row is not None:
            crud.revoke_license(db, license_row)
            record_event(db, "admin_ui.license.revoke", "success", account_id=account_id, subject_id=license_id)
            account = crud.get_account(db, account_id)
            notify_event(
                db,
                "license_revoked",
                f"License revoked for {account.email if account else account_id}",
                {"license_key": license_row.license_key_prefix + "..."},
            )
        return RedirectResponse(f"/admin-ui/accounts/{account_id}", status_code=303)
    finally:
        db.close()


@router.post("/licenses/{license_id}/extend")
def extend_license_submit(
    request: Request,
    license_id: str,
    account_id: str = Form(...),
    version_ceiling: str = Form(""),
):
    """Grant a free upgrade by raising a license's version ceiling.

    Args:
        request: Incoming request.
        license_id: License to extend.
        account_id: Owning account, used to redirect back to its page.
        version_ceiling: New version ceiling; ignored if blank.

    Returns:
        Redirect back to the account detail page, or to login if
        unauthenticated.
    """

    redirect = _require_role(request, "full")
    if redirect:
        return redirect
    db = _db()
    try:
        license_row = db.get(License, license_id)
        if license_row is not None and version_ceiling.strip():
            crud.extend_license(db, license_row, version_ceiling.strip(), None)
            record_event(
                db,
                "admin_ui.license.extend",
                "success",
                account_id=account_id,
                subject_id=license_id,
                detail={"version_ceiling": version_ceiling.strip()},
            )
            account = crud.get_account(db, account_id)
            notify_event(
                db,
                "license_extended",
                f"License extended (grace/upgrade) for {account.email if account else account_id}",
                {"new_version_ceiling": version_ceiling.strip(), "license_key": license_row.license_key_prefix + "..."},
            )
        return RedirectResponse(f"/admin-ui/accounts/{account_id}", status_code=303)
    finally:
        db.close()


@router.post("/accounts/{account_id}/api-keys")
def create_api_key_submit(
    request: Request,
    account_id: str,
    tier: str = Form("free"),
    quota_gpu_hours_per_month: str = Form(""),
):
    """Issue a new cloud-training API key for an account.

    Args:
        request: Incoming request.
        account_id: Owning account.
        tier: Subscription tier label.
        quota_gpu_hours_per_month: Optional quota, blank for unlimited.

    Returns:
        Redirect to the account detail page with the new plaintext API key
        shown once, or to login if unauthenticated.
    """

    redirect = _require_role(request, "full")
    if redirect:
        return redirect
    db = _db()
    try:
        quota = float(quota_gpu_hours_per_month) if quota_gpu_hours_per_month.strip() else None
        key_row, plaintext_key = crud.create_api_key(db, account_id, tier, quota)
        record_event(db, "admin_ui.api_key.create", "success", account_id=account_id, subject_id=key_row.id)
        return RedirectResponse(
            f"/admin-ui/accounts/{account_id}?created_api_key={plaintext_key}", status_code=303
        )
    finally:
        db.close()


@router.post("/api-keys/{api_key_id}/revoke")
def revoke_api_key_submit(request: Request, api_key_id: str, account_id: str = Form(...)):
    """Revoke an API key.

    Args:
        request: Incoming request.
        api_key_id: API key to revoke.
        account_id: Owning account, used to redirect back to its page.

    Returns:
        Redirect back to the account detail page, or to login if
        unauthenticated.
    """

    redirect = _require_role(request, "full")
    if redirect:
        return redirect
    db = _db()
    try:
        key_row = db.get(ApiKey, api_key_id)
        if key_row is not None:
            crud.revoke_api_key(db, key_row)
            record_event(db, "admin_ui.api_key.revoke", "success", account_id=account_id, subject_id=api_key_id)
        return RedirectResponse(f"/admin-ui/accounts/{account_id}", status_code=303)
    finally:
        db.close()


@router.get("/audit-log", response_class=HTMLResponse)
def audit_log_page(request: Request, event_type: str = ""):
    """Show the audit log, optionally filtered by event type.

    Args:
        request: Incoming request.
        event_type: Optional exact event-type filter.

    Returns:
        Rendered audit log page, or a redirect to login if unauthenticated.
    """

    redirect = _require_login(request)
    if redirect:
        return redirect
    db = _db()
    try:
        entries = crud.list_audit_log(db, event_type=event_type or None, limit=200)
        return templates.TemplateResponse(
            request, "audit_log.html", {"entries": entries, "event_type": event_type}
        )
    finally:
        db.close()


@router.get("/telemetry", response_class=HTMLResponse)
def telemetry_page(request: Request):
    """Show recent launch telemetry across all accounts.

    Args:
        request: Incoming request.

    Returns:
        Rendered telemetry page, or a redirect to login if unauthenticated.
    """

    redirect = _require_login(request)
    if redirect:
        return redirect
    db = _db()
    try:
        launches = crud.list_launch_events(db, limit=200)
        return templates.TemplateResponse(request, "telemetry.html", {"launches": launches})
    finally:
        db.close()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = "", test_result: str = ""):
    """Show the notification settings page. Superadmin only.

    Args:
        request: Incoming request.
        saved: Set to "1" right after a successful save, to show a
            confirmation banner.
        test_result: Result message from a test-send action, if any.

    Returns:
        Rendered settings page, or a redirect if not authorized.
    """

    redirect = _require_role(request, "superadmin")
    if redirect:
        return redirect
    db = _db()
    try:
        settings = crud.get_notification_settings(db)
        return templates.TemplateResponse(
            request, "settings.html", {"settings": settings, "saved": saved, "test_result": test_result}
        )
    finally:
        db.close()


@router.post("/settings")
def settings_submit(
    request: Request,
    email_enabled: str = Form(""),
    gmail_address: str = Form(""),
    gmail_app_password: str = Form(""),
    recipient_email: str = Form(""),
    telegram_enabled: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    discord_enabled: str = Form(""),
    discord_webhook_url: str = Form(""),
    notify_account_created: str = Form(""),
    notify_account_status_changed: str = Form(""),
    notify_license_created: str = Form(""),
    notify_license_revoked: str = Form(""),
    notify_license_extended: str = Form(""),
):
    """Save notification settings. Superadmin only.

    Checkbox fields arrive as "on" when checked and are simply absent
    (empty string default) when unchecked -- standard HTML form behavior.

    Args:
        request: Incoming request.
        (form fields, see NotificationSettings for meaning)

    Returns:
        Redirect back to the settings page, or a redirect if not authorized.
    """

    redirect = _require_role(request, "superadmin")
    if redirect:
        return redirect
    db = _db()
    try:
        crud.update_notification_settings(
            db,
            updated_by_admin_id=request.session.get("admin_user_id"),
            email_enabled=bool(email_enabled),
            gmail_address=gmail_address.strip() or None,
            gmail_app_password=gmail_app_password.strip() or None,
            recipient_email=recipient_email.strip() or None,
            telegram_enabled=bool(telegram_enabled),
            telegram_bot_token=telegram_bot_token.strip() or None,
            telegram_chat_id=telegram_chat_id.strip() or None,
            discord_enabled=bool(discord_enabled),
            discord_webhook_url=discord_webhook_url.strip() or None,
            notify_account_created=bool(notify_account_created),
            notify_account_status_changed=bool(notify_account_status_changed),
            notify_license_created=bool(notify_license_created),
            notify_license_revoked=bool(notify_license_revoked),
            notify_license_extended=bool(notify_license_extended),
        )
        record_event(db, "admin_ui.settings.update", "success", subject_id=request.session.get("admin_user_id"))
        return RedirectResponse("/admin-ui/settings?saved=1", status_code=303)
    finally:
        db.close()


@router.post("/settings/test/{channel}")
def settings_test_submit(request: Request, channel: str):
    """Send a test notification through one channel. Superadmin only.

    Args:
        request: Incoming request.
        channel: "email", "telegram", or "discord".

    Returns:
        Redirect back to the settings page with a result message, or a
        redirect if not authorized.
    """

    redirect = _require_role(request, "superadmin")
    if redirect:
        return redirect
    if channel not in {"email", "telegram", "discord"}:
        return RedirectResponse("/admin-ui/settings", status_code=303)
    db = _db()
    try:
        settings = crud.get_notification_settings(db)
        if channel == "email" and settings.email_enabled:
            from app.notifications import _send_email_safe

            _send_email_safe(settings, "Test notification", "This is a test alert from DrunkenBot Cloud Service.")
        elif channel == "telegram" and settings.telegram_enabled:
            from app.notifications import _send_telegram_safe

            _send_telegram_safe(settings, "Test notification from DrunkenBot Cloud Service.")
        elif channel == "discord" and settings.discord_enabled:
            from app.notifications import _send_discord_safe

            _send_discord_safe(settings, "Test notification from DrunkenBot Cloud Service.")
        else:
            return RedirectResponse(f"/admin-ui/settings?test_result=Enable+{channel}+first", status_code=303)
        return RedirectResponse(
            f"/admin-ui/settings?test_result=Test+{channel}+message+sent+%28check+delivery%2C+failures+are+logged+server-side%29",
            status_code=303,
        )
    finally:
        db.close()


@router.get("/admins", response_class=HTMLResponse)
def admins_page(request: Request, error: str = ""):
    """List admin users and offer a create-admin form.

    Superadmin only -- being trusted to manage customer accounts (the
    "full" role) is a different, lesser level of trust than being able to
    grant other people admin access at all.

    Args:
        request: Incoming request.
        error: Optional error message to display (e.g. weak password).

    Returns:
        Rendered admin-users page, or a redirect if not authorized.
    """

    redirect = _require_role(request, "superadmin")
    if redirect:
        return redirect
    db = _db()
    try:
        admins = crud.list_admin_users(db)
        return templates.TemplateResponse(
            request,
            "admins.html",
            {"admins": admins, "current_admin_id": request.session.get("admin_user_id"), "error": error},
        )
    finally:
        db.close()


@router.post("/admins")
def create_admin_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("readonly"),
):
    """Create a new admin user.

    Args:
        request: Incoming request.
        email: New admin's login email.
        password: New admin's initial password (they can be told to change
            it -- there is no forced-reset-on-first-login flow yet, a
            reasonable v1 gap given this is created directly by another
            trusted admin, not self-served).
        role: Initial role: "readonly", "full", or "superadmin".

    Returns:
        Redirect back to the admin-users list, or a redirect if not
        authorized.
    """

    redirect = _require_role(request, "superadmin")
    if redirect:
        return redirect
    if role not in _ROLE_RANK:
        role = "readonly"
    weakness = validate_password_strength(password)
    if weakness:
        return RedirectResponse(f"/admin-ui/admins?error={weakness}", status_code=303)
    db = _db()
    try:
        creator_id = request.session.get("admin_user_id")
        new_admin = crud.create_admin_user(db, email, password, role, creator_id)
        record_event(
            db, "admin_ui.admin_user.create", "success", subject_id=new_admin.id, detail={"role": role, "created_by": creator_id}
        )
        return RedirectResponse("/admin-ui/admins", status_code=303)
    finally:
        db.close()


@router.post("/admins/{admin_id}/status")
def set_admin_status_submit(request: Request, admin_id: str, status: str = Form(...)):
    """Enable or disable an admin user's login access.

    Args:
        request: Incoming request.
        admin_id: Admin user to update.
        status: "active" or "disabled".

    Returns:
        Redirect back to the admin-users list, or a redirect if not
        authorized.
    """

    redirect = _require_role(request, "superadmin")
    if redirect:
        return redirect
    db = _db()
    try:
        admin = db.get(AdminUser, admin_id)
        if admin is not None and status in {"active", "disabled"}:
            crud.set_admin_user_status(db, admin, status)
            record_event(
                db,
                "admin_ui.admin_user.set_status",
                "success",
                subject_id=admin_id,
                detail={"status": status, "changed_by": request.session.get("admin_user_id")},
            )
        return RedirectResponse("/admin-ui/admins", status_code=303)
    finally:
        db.close()


@router.post("/admins/{admin_id}/role")
def set_admin_role_submit(request: Request, admin_id: str, role: str = Form(...)):
    """Change an admin user's role.

    Args:
        request: Incoming request.
        admin_id: Admin user to update.
        role: New role: "readonly", "full", or "superadmin".

    Returns:
        Redirect back to the admin-users list, or a redirect if not
        authorized.
    """

    redirect = _require_role(request, "superadmin")
    if redirect:
        return redirect
    if role not in _ROLE_RANK:
        return RedirectResponse("/admin-ui/admins", status_code=303)
    db = _db()
    try:
        admin = db.get(AdminUser, admin_id)
        if admin is not None:
            crud.set_admin_user_role(db, admin, role)
            record_event(
                db,
                "admin_ui.admin_user.set_role",
                "success",
                subject_id=admin_id,
                detail={"role": role, "changed_by": request.session.get("admin_user_id")},
            )
        return RedirectResponse("/admin-ui/admins", status_code=303)
    finally:
        db.close()
