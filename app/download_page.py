"""Public DrunkenBot-IDE download page."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

RELEASES_URL = "https://github.com/drunkenbot-ai/LLM-IDE/releases/latest"
DOWNLOADS = [
    {
        "name": "Windows",
        "label": "Windows 10/11 (64-bit)",
        "icon": "windows",
        "url": f"{RELEASES_URL}/download/DrunkenBot-IDE-x64-Setup.exe",
        "format": "EXE installer",
    },
    {
        "name": "macOS",
        "label": "macOS (Intel / Apple Silicon)",
        "icon": "apple",
        "url": f"{RELEASES_URL}/download/DrunkenBot-IDE-macos-x64.zip",
        "format": "ZIP archive",
    },
    {
        "name": "Linux",
        "label": "Linux (64-bit)",
        "icon": "linux",
        "url": f"{RELEASES_URL}/download/DrunkenBot-IDE-linux-x64.tar.gz",
        "format": "TAR.GZ archive",
    },
]


@router.get("/download")
def download_page(request: Request):
    """Render the public installer download page."""
    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={"downloads": DOWNLOADS, "releases_url": RELEASES_URL},
    )
