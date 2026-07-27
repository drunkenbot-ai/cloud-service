"""Shared pytest fixtures.

Sets required environment variables at collection time, before any test
module imports anything from ``app`` -- app/config.py's Settings and
app/db.py's engine are both constructed at import time from the process
environment, so this has to happen before those modules are first
imported anywhere in the test session.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_TEST_DB_PATH = Path(tempfile.mkdtemp()) / "test.sqlite3"

_signing_key = Ed25519PrivateKey.generate()
_signing_key_pem_b64 = __import__("base64").b64encode(
    _signing_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
).decode("ascii")

os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")
os.environ.setdefault("SIGNING_PRIVATE_KEY_B64", _signing_key_pem_b64)
os.environ.setdefault("ADMIN_API_TOKEN", "test-admin-token-for-pytest")
os.environ.setdefault("SESSION_SECRET_KEY", "test-session-secret-for-pytest")
os.environ.setdefault("NOTIFICATION_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "10000")  # effectively unlimited for test runs

import itertools  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_email_counter = itertools.count()


def unique_email(label: str = "user") -> str:
    """Return a unique email address for test data isolation.

    Tests share one SQLite file for the whole session (see ``_TEST_DB_PATH``
    above), so distinct test functions need non-colliding emails rather
    than a fresh database each time.

    Args:
        label: Short label included in the generated address for
            readability in failure output.

    Returns:
        Unique email address.
    """

    return f"{label}-{next(_email_counter)}@example.com"


@pytest.fixture()
def client():
    """Provide a TestClient with the app's startup event already run."""

    with TestClient(app) as test_client:
        yield test_client
