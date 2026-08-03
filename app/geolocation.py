"""Small, privacy-conscious IP geolocation adapter."""

from __future__ import annotations

import ipaddress
import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.config import get_settings


def lookup(ip_address: str | None) -> dict[str, str | None]:
    """Resolve a public client IP using the configured provider."""
    if not ip_address:
        return {"city": None, "country": None, "isp": None}
    try:
        address = ipaddress.ip_address(ip_address)
    except ValueError:
        return {"city": None, "country": None, "isp": None}
    if address.is_private or address.is_loopback or address.is_reserved or address.is_unspecified:
        return {"city": None, "country": None, "isp": None}

    settings = get_settings()
    if not settings.geolocation_enabled:
        return {"city": None, "country": None, "isp": None}
    url = settings.geolocation_api_url.format(ip=ip_address)
    request = Request(url, headers={"User-Agent": "DrunkenBot-Cloud-Service/1.0", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=settings.geolocation_timeout_seconds) as response:
            data = json.load(response)
    except (OSError, URLError, TimeoutError, ValueError):
        return {"city": None, "country": None, "isp": None}
    if not isinstance(data, dict) or data.get("error"):
        return {"city": None, "country": None, "isp": None}
    return {
        "city": str(data["city"])[:100] if data.get("city") else None,
        "country": str(data.get("country_name") or data.get("country"))[:100] if data.get("country_name") or data.get("country") else None,
        "isp": str(data["org"])[:200] if data.get("org") else None,
    }
