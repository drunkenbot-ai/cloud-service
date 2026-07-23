"""DrunkenBot cloud service: IDE license validation + training-farm auth.

Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000

Put this behind a TLS-terminating reverse proxy (Caddy/nginx/Cloudflare) in
any real deployment -- this app itself speaks plain HTTP only.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.db import init_db
from app.routers import admin, auth, license

app = FastAPI(
    title="DrunkenBot Cloud Service",
    description="IDE license validation and cloud-training-farm subscription management.",
    version="0.1.0",
)

app.include_router(license.router)
app.include_router(auth.router)
app.include_router(admin.router)


@app.on_event("startup")
def on_startup() -> None:
    """Ensure database tables exist before serving requests."""

    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    """Basic liveness check.

    Returns:
        Status payload.
    """

    return {"status": "ok"}
