# DrunkenBot Cloud Service

FastAPI backend serving three purposes for the DrunkenBot product line:

1. **`/license/validate`** — called by LLM-IDE at launch to validate a
   permanent, per-version IDE license. Online-first with a signed offline
   grace receipt the IDE caches locally, so a temporary connectivity issue
   doesn't block launch. Also accepts optional, privacy-conscious launch
   telemetry (see below).
2. **`/auth/validate-key`** — called by the DrunkenBot-JobManager to
   validate cloud-training-farm API keys and check subscription tier/quota.
3. **`/admin-ui/*`** — a server-rendered web admin panel (login, dashboard,
   account/license/API-key management, audit log, telemetry viewer). The
   underlying **`/admin/*`** JSON API still exists for scripting/curl.

## Notifications (email / Telegram / Discord)

Configurable at `/admin-ui/settings` — **superadmin only**. Alerts fire on:
account created, account suspended/reactivated, license generated, license
revoked, and grace period/free upgrade granted — each individually
toggleable. This fires from both the admin web UI *and* the JSON `/admin/*`
API, so a scripted action notifies just as much as a click in the UI does.

- **Email**: via Gmail SMTP. Use a Gmail
  [app password](https://myaccount.google.com/apppasswords), not your real
  account password.
- **Telegram**: a bot token (from [@BotFather](https://t.me/BotFather)) and
  a chat ID.
- **Discord**: a channel webhook URL.

Secrets (Gmail app password, Telegram bot token, Discord webhook URL) are
**encrypted at rest** via `NOTIFICATION_ENCRYPTION_KEY` (see `.env.example`)
— genuine symmetric encryption, not hashing, since the service has to
retrieve the plaintext later to actually send messages. The settings page
never redisplays a saved secret; leave a secret field blank when saving to
keep the existing value, only fill it in to replace it.

All sends are best-effort: a bad password, an expired webhook, or a
network hiccup is logged and swallowed, never allowed to fail the
account/license action that triggered it. "Send test message" buttons on
the settings page let you verify a channel works without waiting for a
real event.

## Admin web UI

Visit `/admin-ui/` and log in with a personal admin account (see
Bootstrapping below to create the first one). Three roles:

- **Read-only** — view accounts, licenses, telemetry, audit log. Can't
  create/edit/revoke anything.
- **Full** — everything read-only can do, plus manage customer accounts,
  licenses, and API keys.
- **Superadmin** — everything full can do, plus create/disable other admin
  users and change their roles.

Read-only vs. full is a data-access distinction; full vs. superadmin is a
*trust* distinction — someone trusted to manage customer accounts day-to-day
isn't automatically trusted to grant other people admin access. Every login
(success and failure) and every admin action is written to the audit log,
viewable at `/admin-ui/audit-log`.

The JSON `/admin/*` API still uses the single shared `ADMIN_API_TOKEN`
bearer token, unchanged — this is a deliberate v1 scoping choice (per-person
accounts for the web UI where people actually log in and take actions;
simple shared-token auth for scripting/curl access is a lower-stakes,
lower-frequency surface for now).

### Bootstrapping the first admin

Nobody can create the first admin through the UI itself (every
admin-creation path requires already being a superadmin). Run once:

```bash
python scripts/create_first_admin.py you@drunkenbot.ai
```

You'll be prompted for a password. After that, log in at `/admin-ui/login`
and create further admin accounts (of any role) from `/admin-ui/admins`.

## Launch telemetry

`POST /license/validate` accepts an optional `telemetry` object:

```json
{"machine_id": "...", "os": "Windows", "os_version": "10.0.19045"}
```

Deliberately excludes anything directly identifying:

- **No OS username, no hostname, no hardware identifiers.** `machine_id` is
  a random value the IDE generates once and persists locally — it
  distinguishes installs without fingerprinting a real person or device.
- **ISP/geolocation is not self-reported by the client.** It's meant to be
  derived server-side from the request's source IP. The validation endpoint
  itself does *not* do this synchronously (see `LaunchEvent` in
  `app/models.py`) — adding a third-party geolocation API call to the
  single most latency- and reliability-sensitive endpoint in the service
  would be a bad tradeoff. Enrich `ip_country`/`isp` later via a batch job
  reading the raw `ip_address` column instead.

Stored in a separate `launch_events` table, not mixed into `audit_log` —
different purpose (usage analytics vs. security audit) and very different
volume (every launch of every install, vs. discrete admin/validation
events).

## Deploying this for real

Everything above has only been run locally. See **[DEPLOYMENT.md](DEPLOYMENT.md)**
for the checklist (Postgres, TLS, process management, real secrets, and
updating the IDE side) before pointing any real LLM-IDE install at this
service.

## Security hardening notes

- **License keys are hashed at rest**, the same as API keys and admin
  passwords -- only `license_key_hash` (SHA-256) and a short
  `license_key_prefix` (for display) are stored; the plaintext key is shown
  to the admin exactly once, at creation, and is not retrievable again.
  If you have an existing local database from before this change, it used
  a different schema (`license_key` stored directly) -- since there's no
  migration tooling yet (see deferred items below), drop and recreate your
  local dev database rather than trying to migrate old rows.
- **Admin passwords have a minimum strength check** (`app/security.py`'s
  `validate_password_strength`), enforced both by the bootstrap script and
  the `/admin-ui/admins` creation form -- length-based rather than a
  composition policy (requiring specific character classes tends to push
  people toward predictable patterns more than it improves real security).

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
# ADMIN_API_TOKEN, and SESSION_SECRET_KEY (both via
# `python -c "import secrets; print(secrets.token_hex(32))"` -- use two
# DIFFERENT values, not the same one for both).
```

Requires a running Postgres instance matching `DATABASE_URL` (SQLite also
works for local dev without Postgres installed — see `app/db.py`).

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Tables are created automatically on startup (see `app/db.py` — this is a v1
simplification; add Alembic migrations before making breaking schema
changes against a database holding real customer data).

Interactive API docs: `http://localhost:8000/docs`
Admin web UI: `http://localhost:8000/admin-ui/`

**Never expose this directly to the internet without TLS.** Put it behind a
reverse proxy (Caddy, nginx, Cloudflare Tunnel, etc.) that terminates TLS —
this app speaks plain HTTP only.

## Typical admin workflow

Easiest via the web UI at `/admin-ui/`. Equivalent curl-based flow, useful
for scripting:

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

Note: `/license/validate` and `/auth/validate-key` are POST-only by design
(they validate, they don't fetch a resource) — visiting them directly in a
browser or a bare `curl` GET will correctly 405. Use `/docs`'s "Try it out"
or `curl -X POST` with a JSON body to test them.

## Deliberately deferred to a later pass

- Self-serve signup, Stripe/billing integration, automated subscription
  lifecycle
- Forced password reset on first login for newly created admin accounts
- Per-admin tokens for the JSON `/admin/*` API (currently one shared
  `ADMIN_API_TOKEN`; the web UI now has real per-person accounts, the JSON
  API does not yet)
- IP-based ISP/geolocation enrichment (raw IP is captured; resolving it is
  deferred to an async/batch job, not the validation hot path)
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
