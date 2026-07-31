"""DrunkenBot cloud service: IDE license validation + training-farm auth.

Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000

Put this behind a TLS-terminating reverse proxy (Caddy/nginx/Cloudflare) in
any real deployment -- this app itself speaks plain HTTP only.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.admin_ui.router import router as admin_ui_router
from app.config import get_settings
from app.db import init_db
from app.routers import admin, auth, license

app = FastAPI(
    title="DrunkenBot Cloud Service",
    description="IDE license validation and cloud-training-farm subscription management.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.add_middleware(SessionMiddleware, secret_key=get_settings().session_secret_key, same_site="lax")

app.include_router(license.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_ui_router)


@app.on_event("startup")
def on_startup() -> None:
    """Ensure database tables exist before serving requests."""

    init_db()


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    """Render the public service landing page."""

    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DrunkenBot AI | Cloud Service</title>
  <meta name="description" content="DrunkenBot AI licensing and cloud service backend.">
  <style>
    :root { color-scheme: dark; --cyan: #19ddff; --purple: #9b6cff; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; color: #f5f7fb; background: #050608;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif; }
    body:before { content: ""; position: fixed; inset: 0; pointer-events: none;
      background: radial-gradient(circle at 50% 15%, #12213a 0, transparent 42%); opacity: .8; }
    header, main, footer { position: relative; max-width: 1120px; margin: auto; padding: 24px; }
    header { display: flex; justify-content: space-between; align-items: center; }
    .wordmark { color: #fff; font-size: 1.15rem; font-weight: 800; letter-spacing: .08em; }
    .status { color: #9ca8b9; font-size: .85rem; }
    .status span { display: inline-block; width: 8px; height: 8px; margin-right: 7px;
      border-radius: 50%; background: #38e68b; box-shadow: 0 0 12px #38e68b; }
    .hero { display: grid; grid-template-columns: 1.1fr .9fr; gap: 54px; align-items: center;
      min-height: 620px; }
    .eyebrow { color: var(--cyan); font-size: .8rem; font-weight: 800; letter-spacing: .18em;
      text-transform: uppercase; }
    h1 { max-width: 650px; margin: 18px 0; font-size: clamp(3rem, 7vw, 6rem); line-height: .96;
      letter-spacing: -.07em; }
    h1 em { color: var(--cyan); font-style: normal; }
    .lead { max-width: 570px; color: #aeb8c8; font-size: 1.15rem; line-height: 1.7; }
    .actions { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 32px; }
    a.button { padding: 13px 20px; border: 1px solid #26374c; border-radius: 10px;
      color: #eafcff; text-decoration: none; font-weight: 700; transition: transform .2s, border-color .2s; }
    a.button.primary { border-color: var(--cyan); color: #031015;
      background: var(--cyan); box-shadow: 0 0 24px #19ddff40; }
    a.button:hover { transform: translateY(-3px); border-color: var(--cyan); }
    .logo-wrap { display: grid; place-items: center; }
    .logo-wrap img { width: min(100%, 410px); border-radius: 50%; filter: drop-shadow(0 0 28px #13dfff55);
      animation: float 5s ease-in-out infinite; }
    .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; padding-bottom: 54px; }
    .card { padding: 24px; border: 1px solid #1c293b; border-radius: 14px; background: #0b1018cc; }
    .card h2 { margin: 0 0 9px; font-size: 1.05rem; }
    .card p { margin: 0; color: #94a1b3; line-height: 1.6; font-size: .92rem; }
    footer { border-top: 1px solid #182231; color: #8390a2; font-size: .9rem; }
    footer a { color: var(--cyan); }
    @keyframes float { 50% { transform: translateY(-10px); } }
    @media (max-width: 760px) { .hero { grid-template-columns: 1fr; min-height: auto; padding: 55px 24px; }
      .logo-wrap { grid-row: 1; } .logo-wrap img { width: 270px; } .cards { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header><div class="wordmark">DRUNKENBOT AI</div><div class="status"><span></span>Systems operational</div></header>
  <main>
    <section class="hero">
      <div><div class="eyebrow">Intelligent tools. Reliable infrastructure.</div>
        <h1>Powering the next wave of <em>AI.</em></h1>
        <p class="lead">DrunkenBot AI's secure cloud backend handles licensing, authentication, and subscription services for our intelligent developer tools.</p>
        <div class="actions"><a class="button primary" href="/admin-ui/login">Visit admin login</a>
          <a class="button" href="/docs">API documentation</a></div>
      </div>
      <div class="logo-wrap"><img src="/static/drunken_bot_logo.png" alt="DrunkenBot AI robot logo"></div>
    </section>
    <section class="cards">
      <article class="card"><h2>License validation</h2><p>Fast, signed license verification with offline grace support for DrunkenBot IDE tools.</p></article>
      <article class="card"><h2>Secure authentication</h2><p>Protected account and API-key validation for cloud training and automation workflows.</p></article>
      <article class="card"><h2>Built for reliability</h2><p>Observable service health, audit trails, rate limits, and a focused admin control panel.</p></article>
    </section>
  </main>
  <footer>© 2026 DrunkenBot AI · Founded by Nilesh Jadhav · <a href="mailto:drunken.bot.contact@gmail.com">drunken.bot.contact@gmail.com</a></footer>
</body>
</html>"""


@app.get("/health")
def health() -> dict[str, str]:
    """Basic liveness check.

    Returns:
        Status payload.
    """

    return {"status": "ok"}
