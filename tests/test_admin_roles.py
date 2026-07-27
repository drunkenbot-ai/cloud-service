"""Admin login and role-based access control tests, running the real app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import crud
from app.db import SessionLocal
from app.main import app

from .conftest import unique_email


def _bootstrap_admin(email: str, password: str, role: str) -> str:
    """Create an admin user directly (bypassing the UI, like the real bootstrap script).

    Returns:
        Created admin's ID.
    """

    db = SessionLocal()
    try:
        admin = crud.create_admin_user(db, email, password, role, created_by_admin_id=None)
        return admin.id
    finally:
        db.close()


def test_login_with_correct_password_succeeds(client):
    email = unique_email("admin")
    _bootstrap_admin(email, "CorrectHorseBattery1", "superadmin")
    r = client.post("/admin-ui/login", data={"email": email, "password": "CorrectHorseBattery1", "next": "/admin-ui/"})
    assert r.url.path.rstrip("/") == "/admin-ui"


def test_login_with_wrong_password_fails(client):
    email = unique_email("admin")
    _bootstrap_admin(email, "CorrectHorseBattery1", "superadmin")
    r = client.post("/admin-ui/login", data={"email": email, "password": "wrong-password", "next": "/admin-ui/"})
    assert "error" in str(r.url)


def test_dashboard_redirects_to_login_when_unauthenticated(client):
    r = client.get("/admin-ui/")
    assert "/admin-ui/login" in str(r.url)


def test_readonly_can_view_but_not_create_accounts(client):
    ro_email = unique_email("readonly")
    _bootstrap_admin(ro_email, "ReadOnlyPass123", "readonly")
    ro_client = TestClient(app)
    ro_client.post("/admin-ui/login", data={"email": ro_email, "password": "ReadOnlyPass123", "next": "/admin-ui/"})

    r = ro_client.get("/admin-ui/accounts")
    assert r.status_code == 200

    sneaky_email = unique_email("sneaky")
    ro_client.post("/admin-ui/accounts", data={"email": sneaky_email, "company_name": "X"})
    r = ro_client.get("/admin-ui/accounts")
    assert sneaky_email not in r.text


def test_full_role_can_manage_accounts_but_not_admins(client):
    full_email = unique_email("fulladmin")
    _bootstrap_admin(full_email, "FullAccessPass123", "full")
    full_client = TestClient(app)
    full_client.post("/admin-ui/login", data={"email": full_email, "password": "FullAccessPass123", "next": "/admin-ui/"})

    new_customer_email = unique_email("customer")
    r = full_client.post("/admin-ui/accounts", data={"email": new_customer_email, "company_name": "Co"})
    r = full_client.get("/admin-ui/accounts")
    assert new_customer_email in r.text

    r = full_client.get("/admin-ui/admins")
    assert "insufficient_permissions" in str(r.url)

    sneaky_admin_email = unique_email("sneakyadmin")
    full_client.post("/admin-ui/admins", data={"email": sneaky_admin_email, "password": "x", "role": "superadmin"})
    db = SessionLocal()
    try:
        assert crud.get_admin_user_by_email(db, sneaky_admin_email) is None
    finally:
        db.close()


def test_superadmin_can_create_and_disable_other_admins(client):
    super_email = unique_email("superadmin")
    _bootstrap_admin(super_email, "SuperAdminPass123", "superadmin")
    super_client = TestClient(app)
    super_client.post("/admin-ui/login", data={"email": super_email, "password": "SuperAdminPass123", "next": "/admin-ui/"})

    new_admin_email = unique_email("newadmin")
    r = super_client.post(
        "/admin-ui/admins", data={"email": new_admin_email, "password": "NewAdminPass123", "role": "full"}
    )
    db = SessionLocal()
    try:
        new_admin = crud.get_admin_user_by_email(db, new_admin_email)
        assert new_admin is not None
        assert new_admin.role == "full"
        new_admin_id = new_admin.id
    finally:
        db.close()

    # New admin can log in
    new_admin_client = TestClient(app)
    r = new_admin_client.post(
        "/admin-ui/login", data={"email": new_admin_email, "password": "NewAdminPass123", "next": "/admin-ui/"}
    )
    assert r.url.path.rstrip("/") == "/admin-ui"

    # Superadmin disables them
    super_client.post(f"/admin-ui/admins/{new_admin_id}/status", data={"status": "disabled"})

    # Disabled admin can no longer log in
    disabled_client = TestClient(app)
    r = disabled_client.post(
        "/admin-ui/login", data={"email": new_admin_email, "password": "NewAdminPass123", "next": "/admin-ui/"}
    )
    assert "error" in str(r.url)


def test_weak_password_rejected_when_creating_admin(client):
    super_email = unique_email("superadmin")
    _bootstrap_admin(super_email, "SuperAdminPass123", "superadmin")
    super_client = TestClient(app)
    super_client.post("/admin-ui/login", data={"email": super_email, "password": "SuperAdminPass123", "next": "/admin-ui/"})

    weak_email = unique_email("weakpass")
    super_client.post("/admin-ui/admins", data={"email": weak_email, "password": "short", "role": "readonly"})
    db = SessionLocal()
    try:
        assert crud.get_admin_user_by_email(db, weak_email) is None
    finally:
        db.close()


def test_login_events_are_audited(client):
    email = unique_email("audited")
    _bootstrap_admin(email, "AuditMePass123", "superadmin")
    client.post("/admin-ui/login", data={"email": email, "password": "wrong", "next": "/admin-ui/"})
    client.post("/admin-ui/login", data={"email": email, "password": "AuditMePass123", "next": "/admin-ui/"})

    r = client.get("/admin-ui/audit-log")
    assert "admin_login_failed" in r.text
    assert "admin_login" in r.text
