"""Signing, hashing, and admin-authentication primitives.

This module holds the one piece of the whole service that matters most to
get right: signature verification is what lets the IDE and Job Manager
trust a response without a bug here being able to forge trust cheaply.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import Header, HTTPException, status

from app.config import get_settings


def _load_private_key() -> Ed25519PrivateKey:
    """Load the Ed25519 signing key from configuration.

    Returns:
        Loaded private key object.

    Raises:
        ValueError: If the configured key is missing, malformed, or not an
            Ed25519 key.
    """

    settings = get_settings()
    if not settings.signing_private_key_b64:
        raise ValueError("SIGNING_PRIVATE_KEY_B64 is not configured.")
    pem_bytes = base64.b64decode(settings.signing_private_key_b64)
    key = load_pem_private_key(pem_bytes, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Configured signing key is not an Ed25519 private key.")
    return key


def sign_payload(canonical_payload: bytes) -> str:
    """Sign a canonical payload with the service's Ed25519 private key.

    Args:
        canonical_payload: Exact bytes to sign. Callers are responsible for
            producing a canonical, deterministic encoding (e.g. JSON with
            sorted keys and no extraneous whitespace) so the same logical
            payload always signs identically and verifies identically.

    Returns:
        Base64-encoded signature.
    """

    private_key = _load_private_key()
    signature = private_key.sign(canonical_payload)
    return base64.b64encode(signature).decode("ascii")


def hash_api_key(plaintext_key: str) -> str:
    """Hash an API key for storage, the same way a password would be hashed.

    Args:
        plaintext_key: Raw API key as issued to the customer.

    Returns:
        Hex-encoded SHA-256 hash. The plaintext key is never stored.
    """

    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    """Generate a new, high-entropy plaintext API key.

    Returns:
        A key of the form ``dbk_live_<43 random URL-safe characters>``, only
        ever shown to the customer once at creation time.
    """

    return f"dbk_live_{secrets.token_urlsafe(32)}"


def generate_license_key() -> str:
    """Generate a new, customer-facing license key.

    Returns:
        A key of the form ``DBIDE-XXXX-XXXX-XXXX-XXXX`` (uppercase,
        hyphenated, easy to read and type by hand).
    """

    groups = [secrets.token_hex(2).upper() for _ in range(4)]
    return "DBIDE-" + "-".join(groups)


def require_admin_token(x_admin_token: str = Header(default="")) -> None:
    """FastAPI dependency enforcing the shared admin bearer token.

    This is a deliberate v1 simplification -- one shared credential for all
    admin actions rather than per-admin accounts with their own audit
    identity. Fine while DrunkenBot has a small internal team issuing
    licenses by hand; revisit before more than a couple of people need
    admin access, so individual actions can be attributed to a person.

    Args:
        x_admin_token: Value of the ``X-Admin-Token`` request header.

    Raises:
        HTTPException: If the token is missing or does not match.
    """

    settings = get_settings()
    if not settings.admin_api_token or not secrets.compare_digest(x_admin_token, settings.admin_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing admin token.")
