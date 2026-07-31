# Deployment Checklist

This service has only ever been run locally (SQLite, `uvicorn --reload`, no
TLS) during development. Nothing here is optional before it serves a real
LLM-IDE install anywhere outside your own machine.

## Netlify build settings

The repository includes `netlify.toml` and `runtime.txt`, which pin supported
build environments to Python 3.12. This is required because the pinned
`pydantic-core` dependency does not provide a wheel for Python 3.14; without
the pin, hosting platforms try to compile it and fail because Rust/Cargo is
not installed.

Netlify is suitable for building and hosting a frontend, but this repository
is a stateful FastAPI service. Do not deploy the API as a static Netlify site:
it requires a continuously running ASGI process and a persistent Postgres
database. Use a service that supports Python web processes (for example,
Render, Railway, Fly.io, or a VM) and configure its start command as:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## 1. Database: switch to Postgres

SQLite is fine for local dev, not for a real deployment (single-writer,
no real concurrent access). Provision a Postgres instance and point
`DATABASE_URL` at it:

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/drunkenbot
```

Tables are still created via `init_db()` (`create_all`, no migrations yet
-- see the README's deferred-items list). Run the app once against the new
database to create the schema, then run `scripts/create_first_admin.py`
against it to bootstrap your first admin.

## 2. TLS: put a reverse proxy in front

This app speaks plain HTTP only, on purpose (TLS termination doesn't belong
in application code). Easiest path: [Caddy](https://caddyserver.com/),
which gets you automatic HTTPS with a two-line config:

```
license.yourdomain.com {
    reverse_proxy localhost:8000
}
```

nginx + certbot or a platform's built-in TLS (Cloudflare Tunnel, a PaaS's
managed HTTPS, etc.) work equally well -- the requirement is just: nothing
reaches this service over plain HTTP from outside the host it runs on.

## 3. Process management

Don't run `uvicorn --reload` in production (that's a dev-only flag). Run it
under a real process manager so it restarts on crash and starts on boot.
Two straightforward options:

**systemd** (if deploying to a plain VM):
```ini
[Unit]
Description=DrunkenBot Cloud Service
After=network.target

[Service]
WorkingDirectory=/opt/cloud-service
ExecStart=/opt/cloud-service/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
EnvironmentFile=/opt/cloud-service/.env
Restart=always
User=drunkenbot

[Install]
WantedBy=multi-user.target
```

**Docker**, if you'd rather containerize:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
(Feed secrets via environment variables / your platform's secret manager,
not baked into the image.)

## 4. Generate real production secrets

Every secret in `.env.example` needs a **fresh, real** value for
production -- do not reuse anything generated during local development or
testing:

```bash
python -c "import secrets; print(secrets.token_hex(32))"   # ADMIN_API_TOKEN, SESSION_SECRET_KEY (run twice, different values)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # NOTIFICATION_ENCRYPTION_KEY
python scripts/generate_keypair.py   # SIGNING_PRIVATE_KEY_B64 + the public key for the IDE
```

## 5. Update the IDE side

Two things in the LLM-IDE codebase currently hold placeholder values that
only work for local testing:

- **`license_client.py`**: `LICENSE_PUBLIC_KEY_PEM` is a throwaway key
  generated during scaffolding. Replace it with the **public** key printed
  by `scripts/generate_keypair.py` in step 4 above (never the private key
  -- that stays only in this service's `.env`).
- **`app.py`**: `LICENSE_SERVER_URL` defaults to a placeholder domain. It's
  overridable via the `DRUNKENBOT_LICENSE_SERVER_URL` environment variable,
  so you can point different builds at different environments
  (dev/staging/prod) without a rebuild -- set that to your real deployed
  URL (e.g. `https://license.yourdomain.com`).

## 6. Bootstrap the first admin

```bash
python scripts/create_first_admin.py you@yourdomain.com
```

Then log into `/admin-ui/login` and create accounts for the rest of your
team from `/admin-ui/admins`.

## 7. Sanity-check before pointing real IDE installs at it

- [ ] `curl https://license.yourdomain.com/health` returns `{"status":"ok"}` over HTTPS
- [ ] `/admin-ui/login` loads over HTTPS, not HTTP
- [ ] A test account/license created via `/admin-ui/` validates successfully
      against a build of the IDE configured with `DRUNKENBOT_LICENSE_SERVER_URL`
      pointed at this deployment and the matching public key
- [ ] `pytest` passes against this environment (or at minimum was run
      against the same codebase before deploying)
- [ ] You have a real backup plan for the Postgres database -- it now holds
      customer accounts, license records, and (if configured) encrypted
      notification credentials
