#!/usr/bin/env python3
"""Create config.json in the repo root. Leave an existing file alone."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

IPINFO_URL = "https://ipinfo.io/json"
HELP = """\
Could not create config.json.
ipinfo.io did not return a location. The network may be down, or the response had no loc or timezone.

Write config.json in the repo root yourself. It needs backend, lat, lon, timezone, sku, timeout, retries, and retry_delay.
Use backend "lan" only together with ip set to the light.
Then run make install again.
"""


def fetch_ipinfo(urlopen=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(IPINFO_URL, headers={"User-Agent": "house-lights"})
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ipinfo.io did not return an object")
    return payload


def config_from_ipinfo(info: dict) -> dict:
    loc = str(info.get("loc") or "")
    try:
        lat_text, lon_text = loc.split(",")
        lat = float(lat_text)
        lon = float(lon_text)
    except ValueError as exc:
        raise ValueError("ipinfo.io loc was not latitude,longitude") from exc
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValueError("ipinfo.io loc was out of range")
    timezone = info.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        raise ValueError("ipinfo.io did not return a timezone")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"ipinfo.io timezone is not recognized: {timezone}") from exc
    return {
        "backend": "bluetooth",
        "lat": lat,
        "lon": lon,
        "timezone": timezone,
        "sku": "H706C",
        "timeout": 8,
        "retries": 3,
        "retry_delay": 1.0,
    }


def place_line(info: dict) -> str:
    city = info.get("city") or "unknown city"
    region = info.get("region") or "unknown region"
    country = info.get("country") or "unknown country"
    return f"{city}, {region}, {country}"


def create_config(path: Path, fetch=fetch_ipinfo) -> int:
    if path.exists():
        print(f"config.json already exists: {path}")
        return 0
    try:
        info = fetch()
        data = config_from_ipinfo(info)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError, TimeoutError) as exc:
        print(HELP, file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"Wrote {path}")
    print(place_line(info))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: make_config.py CONFIG.json", file=sys.stderr)
        return 2
    return create_config(Path(args[0]))


if __name__ == "__main__":
    raise SystemExit(main())
