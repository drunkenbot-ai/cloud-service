# DrunkenBot Cloud Service

FastAPI backend serving two purposes for the DrunkenBot product line:

1. **`/license/validate`** — called by LLM-IDE at launch to validate a
   permanent, per-version IDE license. Online-first with a signed offline
   grace receipt the IDE caches locally, so a temporary connectivity issue
   doesn't block launch.
2. **`/auth/validate-key`** — called by the DrunkenBot-JobManager to
   validate cloud-training-farm API keys and check subscription tier/quota.

Plus **`/admin/*`** for DrunkenBot staff to create/revoke/extend accounts,
licenses, and API keys by hand — deliberately bare-bones for v1 (no web UI,
no self-serve signup/billing yet). See the architecture plan for the full
reasoning behind this scope.

## Why this exists / design notes

- **Signing, not encryption.** License validity is proven with an Ed25519
  signature the IDE verifies using an embedded public key. The private
  signing key never leaves this service. See `app/security.py`.
- **`version_ceiling` + `grace_period_until`** on each license is what makes
  "permanent per version, repurchase to upgrade, but we can always grant
  free upgrades or grace periods" work — extending either field is the
  entire mechanism, no app update required.
- **This is the highest-stakes component in the whole DrunkenBot
  infrastructure.** A bug here can give the product away for free or lock
  out every paying customer. Treat changes to `app/security.py`,
  `app/routers/license.py`, and `app/routers/auth.py` with more scrutiny
  than anything else in this repo.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Generate the signing keypair (do this once, store the private key securely)
python scripts/generate_keypair.py

cp .env.example .env
# Fill in DATABASE_URL, SIGNING_PRIVATE_KEY_B64 (from the script above),
# and ADMIN_API_TOKEN (e.g. `openssl rand -hex 32`).
```

Requires a running Postgres instance matching `DATABASE_URL`.

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Tables are created automatically on startup (see `app/db.py` — this is a v1
simplification; add Alembic migrations before making breaking schema
changes against a database holding real customer data).

Interactive API docs: `http://localhost:8000/docs`

**Never expose this directly to the internet without TLS.** Put it behind a
reverse proxy (Caddy, nginx, Cloudflare Tunnel, etc.) that terminates TLS —
this app speaks plain HTTP only.

## Typical admin workflow (until a web UI exists)

```bash
# Create an account
curl -X POST http://localhost:8000/admin/accounts \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"email": "customer@example.com", "company_name": "Example Inc"}'

# Issue an IDE license (use the account id returned above)
curl -X POST http://localhost:8000/admin/licenses \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"account_id": "<account_id>", "version_ceiling": "2.0.0"}'

# Grant a free upgrade later
curl -X POST http://localhost:8000/admin/licenses/<license_id>/extend \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"version_ceiling": "3.0.0"}'

# Issue a cloud-training API key
curl -X POST http://localhost:8000/admin/api-keys \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"account_id": "<account_id>", "tier": "pro", "quota_gpu_hours_per_month": 100}'
```

## Deliberately deferred to a later pass

- Self-serve signup, Stripe/billing integration, automated subscription
  lifecycle
- Per-admin accounts (currently one shared `ADMIN_API_TOKEN`)
- Alembic migrations
- Distributed rate limiting (current limiter is in-process memory; fine for
  one instance, needs a shared store like Redis if this is ever
  horizontally scaled)

## Tests

```bash
pip install pytest
pytest
```

Current tests cover signing/verification and version-ceiling logic without
needing a live Postgres instance. Add integration tests against a real (or
test-container) Postgres before relying on this in production.
