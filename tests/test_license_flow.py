"""End-to-end license lifecycle tests, running the real app via TestClient."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_public_key,
)

from app import crud
from app.db import SessionLocal
from app.security import _load_private_key

from .conftest import unique_email

ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token-for-pytest"}


def _create_account_and_license(client, version_ceiling: str = "2.0.0") -> tuple[str, str]:
    """Create an account and a license via the JSON admin API.

    Returns:
        Tuple of (account_id, plaintext_license_key).
    """

    email = unique_email("license-test")
    r = client.post("/admin/accounts", json={"email": email}, headers=ADMIN_HEADERS)
    account_id = r.json()["id"]
    r = client.post(
        "/admin/licenses",
        json={"account_id": account_id, "version_ceiling": version_ceiling},
        headers=ADMIN_HEADERS,
    )
    return account_id, r.json()["license_key"]


def test_valid_license_within_ceiling_validates(client):
    _, license_key = _create_account_and_license(client, version_ceiling="2.0.0")
    r = client.post("/license/validate", json={"license_key": license_key, "app_version": "1.5.0"})
    body = r.json()
    assert body["valid"] is True
    assert body["receipt"] is not None
    assert body["signature"] is not None


def test_signature_verifies_with_the_public_key_alone(client):
    """The whole point of signing: verify using ONLY the public key, no DB access."""

    _, license_key = _create_account_and_license(client, version_ceiling="2.0.0")
    r = client.post("/license/validate", json={"license_key": license_key, "app_version": "1.0.0"})
    body = r.json()

    public_pem = _load_private_key().public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
    )
    public_key = load_pem_public_key(public_pem)
    public_key.verify(base64.b64decode(body["signature"]), body["receipt"].encode("utf-8"))  # raises if invalid


def test_version_above_ceiling_is_rejected(client):
    _, license_key = _create_account_and_license(client, version_ceiling="2.0.0")
    r = client.post("/license/validate", json={"license_key": license_key, "app_version": "3.0.0"})
    assert r.json()["valid"] is False


def test_unknown_license_key_is_rejected(client):
    r = client.post("/license/validate", json={"license_key": "DBIDE-0000-0000-0000-0000", "app_version": "1.0.0"})
    assert r.json()["valid"] is False
    assert r.json()["reason"] == "License key not found."


def test_license_key_is_never_stored_in_plaintext(client):
    """The core hardening fix: license keys must be hashed at rest, like API keys/passwords."""

    account_id, license_key = _create_account_and_license(client, version_ceiling="2.0.0")
    db = SessionLocal()
    try:
        licenses = crud.list_licenses_for_account(db, account_id)
        assert len(licenses) == 1
        stored_row = licenses[0]
        assert not hasattr(stored_row, "license_key")  # attribute removed entirely, not just empty
        assert license_key not in stored_row.license_key_hash
        assert stored_row.license_key_prefix == license_key[:14]
    finally:
        db.close()


def test_extend_license_grants_free_upgrade(client):
    account_id, license_key = _create_account_and_license(client, version_ceiling="2.0.0")
    db = SessionLocal()
    try:
        license_id = crud.list_licenses_for_account(db, account_id)[0].id
    finally:
        db.close()

    r = client.post(
        f"/admin/licenses/{license_id}/extend", json={"version_ceiling": "3.5.0"}, headers=ADMIN_HEADERS
    )
    assert r.status_code == 200

    r = client.post("/license/validate", json={"license_key": license_key, "app_version": "3.0.0"})
    assert r.json()["valid"] is True


def test_revoked_license_is_rejected(client):
    account_id, license_key = _create_account_and_license(client, version_ceiling="2.0.0")
    db = SessionLocal()
    try:
        license_id = crud.list_licenses_for_account(db, account_id)[0].id
    finally:
        db.close()

    r = client.post(f"/admin/licenses/{license_id}/revoke", headers=ADMIN_HEADERS)
    assert r.status_code == 200

    r = client.post("/license/validate", json={"license_key": license_key, "app_version": "1.0.0"})
    assert r.json()["valid"] is False
    assert "revoked" in r.json()["reason"].lower()


def test_suspended_account_blocks_its_licenses(client):
    account_id, license_key = _create_account_and_license(client, version_ceiling="2.0.0")
    db = SessionLocal()
    try:
        account = crud.get_account(db, account_id)
        crud.set_account_status(db, account, "suspended")
    finally:
        db.close()

    r = client.post("/license/validate", json={"license_key": license_key, "app_version": "1.0.0"})
    assert r.json()["valid"] is False


def test_admin_routes_require_valid_token(client):
    r = client.post("/admin/accounts", json={"email": unique_email()}, headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 401
    r = client.post("/admin/accounts", json={"email": unique_email()})
    assert r.status_code == 401
