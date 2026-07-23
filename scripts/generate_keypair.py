"""Generate the Ed25519 signing keypair for this service.

Run once, store the private key output in this service's secrets (as
SIGNING_PRIVATE_KEY_B64) and hand the public key to the LLM-IDE team to
embed in the app for offline signature verification. The private key must
never leave wherever you store secrets for this service -- it is the one
value that, if leaked, lets someone forge valid licenses.

Usage:
    python scripts/generate_keypair.py
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    """Generate and print a new Ed25519 keypair."""

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    print("=" * 70)
    print("PRIVATE KEY -- put this in the service's secrets, never commit it.")
    print("Set as SIGNING_PRIVATE_KEY_B64 in .env:")
    print("=" * 70)
    print(base64.b64encode(private_pem).decode("ascii"))
    print()
    print("=" * 70)
    print("PUBLIC KEY -- safe to embed in the LLM-IDE app for verification.")
    print("=" * 70)
    print(public_pem.decode("ascii"))


if __name__ == "__main__":
    main()
