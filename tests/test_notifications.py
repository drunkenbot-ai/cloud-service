"""Notification settings and dispatch tests, running the real app."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import crud
from app.crypto_secrets import decrypt_secret
from app.db import SessionLocal
from app.main import app

from .conftest import unique_email

ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token-for-pytest"}


def _login_as_superadmin(email: str, password: str = "SuperAdminPass123"):
    db = SessionLocal()
    try:
        crud.create_admin_user(db, email, password, "superadmin", created_by_admin_id=None)
    finally:
        db.close()
    superadmin_client = TestClient(app)
    superadmin_client.post("/admin-ui/login", data={"email": email, "password": password, "next": "/admin-ui/"})
    return superadmin_client


def test_secrets_are_encrypted_at_rest_not_plaintext():
    super_client = _login_as_superadmin(unique_email("settings-super"))
    super_client.post(
        "/admin-ui/settings",
        data={
            "email_enabled": "on",
            "gmail_address": "sender@gmail.com",
            "gmail_app_password": "plaintext-app-password",
            "recipient_email": "alerts@example.com",
            "notify_account_created": "on",
            "notify_account_status_changed": "on",
            "notify_license_created": "on",
            "notify_license_revoked": "on",
            "notify_license_extended": "on",
        },
    )
    db = SessionLocal()
    try:
        settings = crud.get_notification_settings(db)
        assert "plaintext-app-password" not in settings.gmail_app_password_encrypted
        assert decrypt_secret(settings.gmail_app_password_encrypted) == "plaintext-app-password"
    finally:
        db.close()


def test_blank_secret_field_preserves_existing_value_on_resave():
    super_client = _login_as_superadmin(unique_email("settings-super"))
    super_client.post(
        "/admin-ui/settings",
        data={
            "email_enabled": "on",
            "gmail_address": "sender@gmail.com",
            "gmail_app_password": "original-password",
            "recipient_email": "alerts@example.com",
            "notify_account_created": "on",
            "notify_account_status_changed": "on",
            "notify_license_created": "on",
            "notify_license_revoked": "on",
            "notify_license_extended": "on",
        },
    )
    super_client.post(
        "/admin-ui/settings",
        data={
            "email_enabled": "on",
            "gmail_address": "sender@gmail.com",
            "gmail_app_password": "",
            "recipient_email": "different-recipient@example.com",
            "notify_account_created": "on",
            "notify_account_status_changed": "on",
            "notify_license_created": "on",
            "notify_license_revoked": "on",
            "notify_license_extended": "on",
        },
    )
    db = SessionLocal()
    try:
        settings = crud.get_notification_settings(db)
        assert decrypt_secret(settings.gmail_app_password_encrypted) == "original-password"
        assert settings.recipient_email == "different-recipient@example.com"
    finally:
        db.close()


def test_settings_page_is_superadmin_only():
    full_email = unique_email("full-not-super")
    db = SessionLocal()
    try:
        crud.create_admin_user(db, full_email, "FullAccessPass123", "full", created_by_admin_id=None)
    finally:
        db.close()
    full_client = TestClient(app)
    full_client.post("/admin-ui/login", data={"email": full_email, "password": "FullAccessPass123", "next": "/admin-ui/"})

    r = full_client.get("/admin-ui/settings")
    assert "insufficient_permissions" in str(r.url)
    r = full_client.post("/admin-ui/settings/test/email")
    assert "insufficient_permissions" in str(r.url)


def test_account_creation_dispatches_to_all_enabled_channels():
    super_client = _login_as_superadmin(unique_email("settings-super"))
    super_client.post(
        "/admin-ui/settings",
        data={
            "email_enabled": "on",
            "gmail_address": "sender@gmail.com",
            "gmail_app_password": "app-pass",
            "recipient_email": "alerts@example.com",
            "telegram_enabled": "on",
            "telegram_bot_token": "123:TOKEN",
            "telegram_chat_id": "555",
            "discord_enabled": "on",
            "discord_webhook_url": "https://discord.com/api/webhooks/1/x",
            "notify_account_created": "on",
            "notify_account_status_changed": "on",
            "notify_license_created": "on",
            "notify_license_revoked": "on",
            "notify_license_extended": "on",
        },
    )

    mock_smtp_instance = MagicMock()
    mock_smtp_ssl = MagicMock()
    mock_smtp_ssl.return_value.__enter__.return_value = mock_smtp_instance

    with patch("smtplib.SMTP_SSL", mock_smtp_ssl), patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = MagicMock()
        new_customer = unique_email("notif-customer")
        super_client.post("/admin-ui/accounts", data={"email": new_customer, "company_name": "Acme"})

        assert mock_smtp_instance.login.call_args[0] == ("sender@gmail.com", "app-pass")
        sent_message = mock_smtp_instance.send_message.call_args[0][0]
        assert sent_message["To"] == "alerts@example.com"
        assert new_customer in str(sent_message)

        assert mock_urlopen.call_count == 2
        telegram_request = mock_urlopen.call_args_list[0][0][0]
        assert "bot123:TOKEN" in telegram_request.full_url
        assert json.loads(telegram_request.data)["chat_id"] == "555"

        discord_request = mock_urlopen.call_args_list[1][0][0]
        assert discord_request.full_url == "https://discord.com/api/webhooks/1/x"


def test_disabling_one_event_toggle_suppresses_only_that_category():
    super_client = _login_as_superadmin(unique_email("settings-super"))
    super_client.post(
        "/admin-ui/settings",
        data={
            "email_enabled": "on",
            "gmail_address": "sender@gmail.com",
            "gmail_app_password": "app-pass",
            "recipient_email": "alerts@example.com",
            "notify_account_created": "on",
            "notify_account_status_changed": "on",
            "notify_license_created": "",
            "notify_license_revoked": "on",
            "notify_license_extended": "on",
        },
    )
    account_email = unique_email("toggle-customer")
    super_client.post("/admin-ui/accounts", data={"email": account_email, "company_name": "Co"})
    import re

    account_id = re.search(
        r'/admin-ui/accounts/([a-f0-9-]+)"[^>]*>Manage', super_client.get("/admin-ui/accounts").text
    ).group(1)

    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        mock_instance = MagicMock()
        mock_smtp_ssl.return_value.__enter__.return_value = mock_instance

        super_client.post(f"/admin-ui/accounts/{account_id}/licenses", data={"version_ceiling": "2.0.0"})
        assert not mock_instance.send_message.called

        super_client.post(f"/admin-ui/accounts/{account_id}/status", data={"status": "suspended"})
        assert mock_instance.send_message.called


def test_notification_failure_never_breaks_the_admin_action():
    super_client = _login_as_superadmin(unique_email("settings-super"))
    super_client.post(
        "/admin-ui/settings",
        data={
            "email_enabled": "on",
            "gmail_address": "sender@gmail.com",
            "gmail_app_password": "wrong-password",
            "recipient_email": "alerts@example.com",
            "notify_account_created": "on",
            "notify_account_status_changed": "on",
            "notify_license_created": "on",
            "notify_license_revoked": "on",
            "notify_license_extended": "on",
        },
    )
    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        mock_smtp_ssl.side_effect = Exception("SMTP auth failed")
        resilience_email = unique_email("resilience")
        super_client.post("/admin-ui/accounts", data={"email": resilience_email, "company_name": "X"})

    r = super_client.get("/admin-ui/accounts")
    assert resilience_email in r.text
