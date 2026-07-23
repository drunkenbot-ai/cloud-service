"""Signing round-trip tests.

Deliberately uses the cryptography primitives directly rather than
app.security, so these tests don't require full app configuration
(DATABASE_URL, SIGNING_PRIVATE_KEY_B64, etc.) via environment variables --
this exercises the same signing approach the service uses, in isolation.
"""

import json

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_valid_signature_verifies() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    payload = _canonical({"account_id": "abc", "valid_until": "2026-08-01T00:00:00+00:00"})

    signature = private_key.sign(payload)

    public_key.verify(signature, payload)  # raises if invalid


def test_tampered_payload_fails_verification() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    payload = _canonical({"account_id": "abc", "valid_until": "2026-08-01T00:00:00+00:00"})
    signature = private_key.sign(payload)

    tampered_payload = _canonical({"account_id": "abc", "valid_until": "2099-01-01T00:00:00+00:00"})

    with pytest.raises(InvalidSignature):
        public_key.verify(signature, tampered_payload)


def test_wrong_public_key_fails_verification() -> None:
    private_key = Ed25519PrivateKey.generate()
    payload = _canonical({"account_id": "abc"})
    signature = private_key.sign(payload)

    other_public_key = Ed25519PrivateKey.generate().public_key()

    with pytest.raises(InvalidSignature):
        other_public_key.verify(signature, payload)


def test_canonical_json_is_order_independent() -> None:
    payload_a = {"b": 2, "a": 1}
    payload_b = {"a": 1, "b": 2}
    assert _canonical(payload_a) == _canonical(payload_b)
