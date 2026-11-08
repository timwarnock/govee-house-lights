#!/usr/bin/env python3
"""Exit 0 when a config file exists and has everything the daemon needs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def ready(data: object) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Config must be a JSON object."
    backend = data.get("backend")
    if backend not in {"lan", "bluetooth"}:
        return False, "Config needs backend set to bluetooth or lan."
    lat_ok, lat_message = _number(data.get("lat"), "lat", -90.0, 90.0)
    if not lat_ok:
        return False, lat_message
    lon_ok, lon_message = _number(data.get("lon"), "lon", -180.0, 180.0)
    if not lon_ok:
        return False, lon_message
    timezone = data.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        return False, "Config needs timezone set to an IANA name, such as America/Chicago."
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return False, f"Config timezone is not recognized: {timezone}."
    sku = data.get("sku")
    if not isinstance(sku, str) or not sku.strip():
        return False, "Config needs sku, such as H706C."
    timeout_ok, timeout_message = _number(data.get("timeout"), "timeout", above=0)
    if not timeout_ok:
        return False, timeout_message
    retries = data.get("retries")
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 1:
        return False, "Config needs retries set to an integer >= 1."
    delay_ok, delay_message = _number(data.get("retry_delay"), "retry_delay", minimum=0)
    if not delay_ok:
        return False, delay_message
    if backend == "lan" and not data.get("ip"):
        return False, "LAN backend needs ip."
    ble = data.get("ble_address")
    if ble is not None and (not isinstance(ble, str) or not ble.strip()):
        return False, "Config ble_address must be a Bluetooth address string."
    enforce = data.get("enforce_minutes")
    if enforce is not None and (isinstance(enforce, bool) or not isinstance(enforce, int) or enforce < 1):
        return False, "Config enforce_minutes must be an integer >= 1."
    return True, ""


def _number(
    value: object,
    name: str,
    low: float | None = None,
    high: float | None = None,
    *,
    above: float | None = None,
    minimum: float | None = None,
) -> tuple[bool, str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False, f"Config needs {name} set to a number."
    number = float(value)
    if low is not None and not low <= number <= high:
        return False, f"Config {name} must be between {low:g} and {high:g}."
    if above is not None and not number > above:
        return False, f"Config {name} must be > {above:g}."
    if minimum is not None and number < minimum:
        return False, f"Config {name} must be >= {minimum:g}."
    return True, ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: config_ready.py CONFIG.json", file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Config not found: {path}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Config could not be read: {exc}", file=sys.stderr)
        return 1
    ok, message = ready(data)
    if not ok:
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
