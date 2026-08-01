"""DrunkenBot cloud service: IDE license validation + training-farm auth.

Run with: uvicorn app.main:app --host 0.0.0.0 --port 8000

Put this behind a TLS-terminating reverse proxy (Caddy/nginx/Cloudflare) in
any real deployment -- this app itself speaks plain HTTP only.
"""

from __future__ import annotations

from pathlib import Path
import json

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
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
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ORGANIZATION_JSON = json.dumps({"@context": "https://schema.org", "@type": "Organization", "name": "DrunkenBot AI", "url": "https://drunkenbot.ai"})
app.add_middleware(SessionMiddleware, secret_key=get_settings().session_secret_key, same_site="lax")

app.include_router(license.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_ui_router)


@app.on_event("startup")
def on_startup() -> None:
    """Ensure database tables exist before serving requests."""

    init_db()


@app.get("/")
def root(request: Request) -> object:
    """Render the public service landing page."""

    return templates.TemplateResponse(request, "home.html", {"meta_description": "DrunkenBot AI builds practical tools for private AI data preparation, model training, and deployment.", "organization_json": ORGANIZATION_JSON})


@app.get("/mission")
def mission(request: Request) -> object:
    return templates.TemplateResponse(request, "mission.html", {"meta_description": "Learn how DrunkenBot AI helps teams build practical, private AI systems.", "organization_json": ORGANIZATION_JSON})


@app.get("/products/{slug}")
def product(request: Request, slug: str) -> object:
    products = {
        "llm-ide": ("DrunkenBot LLM-IDE", "A complete local AI workshop for building, training, testing, and exporting language models.", "One-time purchase"),
        "gpu-farm": ("GPU Training Farm", "Rent ready-to-use GPU capacity by the hour and run demanding training jobs without buying hardware.", "Pay as you go"),
        "gpu-farm-management": ("GPU Training Farm Management", "Server and client applications for coordinating your own distributed GPU workers and training jobs.", "One-time purchase"),
        "ebook-scout": ("eBook Scout", "A free research utility for discovering, downloading, and organizing public-domain books into clean dataset sources.", "Free"),
        "wikipedia-scout": ("Wikipedia Scout", "Search Wikipedia by topic, filter pages by size and word count, and build focused datasets from selected articles.", "Free"),
    }
    if slug not in products:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Product not found")
    title, description, pricing = products[slug]
    product_data = {"slug": slug, "title": title, "description": description, "pricing": pricing}
    structured = {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": title, "description": description, "applicationCategory": "DeveloperApplication", "operatingSystem": "Windows, macOS, Linux"}
    return templates.TemplateResponse(request, "product.html", {"product": product_data, "meta_description": description, "organization_json": json.dumps(structured)})


@app.get("/robots.txt")
def robots() -> object:
    return Response("User-agent: *\nAllow: /\nDisallow: /admin-ui/\nDisallow: /admin/\nSitemap: https://drunkenbot.ai/sitemap.xml\n", media_type="text/plain")


@app.get("/sitemap.xml")
def sitemap() -> object:
    urls = ["", "mission", "products/llm-ide", "products/gpu-farm", "products/gpu-farm-management", "products/ebook-scout", "products/wikipedia-scout"]
    return Response("<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">" + "".join(f"<url><loc>https://drunkenbot.ai/{path}</loc></url>" for path in urls) + "</urlset>", media_type="application/xml")


@app.get("/health")
def health() -> dict[str, str]:
    """Basic liveness check.

    Returns:
        Status payload.
    """

    return {"status": "ok"}
