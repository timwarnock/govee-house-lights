"""CLI settings. Flags override an optional JSON config. Flags alone are enough."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("house_lights")

DEFAULT_TIMEZONE = "America/Chicago"
DEFAULT_SKU = "H706C"
DEFAULT_TIMEOUT = 8.0
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_BLE_CACHE = Path.home() / ".local" / "state" / "house-lights" / "ble.json"

CONFIG_KEYS = frozenset({
    "backend",
    "ip",
    "ble_address",
    "sku",
    "lat",
    "lon",
    "timezone",
    "timeout",
    "retries",
    "retry_delay",
    "scan",
    "ble_cache",
    "enforce_minutes",
})


class UsageError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    command: str
    backend: str | None
    ip: str | None
    ble_address: str | None
    sku: str
    lat: float | None
    lon: float | None
    timezone: str
    timeout: float
    retries: int
    retry_delay: float
    scan: bool
    ble_cache: Path
    when: date | None
    config_path: Path | None
    desired_state_dir: Path | None = None
    state_path: Path | None = None
    enforce_minutes: int | None = None


def normalize_ble_address(value: str) -> str:
    raw = value.strip().replace("-", ":").upper()
    parts = raw.split(":")
    if len(parts) != 6 or any(len(part) != 2 or any(ch not in "0123456789ABCDEF" for ch in part) for part in parts):
        raise UsageError(
            f"BLE address must look like AA:BB:CC:DD:EE:FF (got {value!r}). "
            "The Wi-Fi MAC is not assumed to be the Bluetooth address."
        )
    return ":".join(parts)


def _load_config(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UsageError(f"config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise UsageError(f"config file is not JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError("config file must be a JSON object")
    unknown = sorted(set(data) - CONFIG_KEYS)
    if unknown:
        log.warning("ignoring unknown config keys: %s", ", ".join(unknown))
    return data


def _pick(args_value, file_data: dict, key: str, default):
    if args_value is not None:
        return args_value
    if key in file_data and file_data[key] is not None:
        return file_data[key]
    return default


def settings_from_namespace(args, *, file_data: dict | None = None) -> Settings:
    data = file_data if file_data is not None else {}
    if file_data is None and getattr(args, "config", None):
        data = _load_config(Path(args.config))

    backend = _pick(args.backend, data, "backend", None)
    if backend is not None:
        backend = str(backend).lower()
        if backend not in {"lan", "bluetooth"}:
            raise UsageError("--backend must be lan or bluetooth")

    ip_raw = _pick(args.ip, data, "ip", None)
    ip = str(ip_raw) if ip_raw else None
    sku = str(_pick(args.sku, data, "sku", DEFAULT_SKU)).upper()
    timezone = str(_pick(args.timezone, data, "timezone", DEFAULT_TIMEZONE))
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise UsageError(f"unknown timezone {timezone!r}") from exc

    ble_raw = _pick(args.ble_address, data, "ble_address", None)
    ble_address = normalize_ble_address(str(ble_raw)) if ble_raw else None

    lat = _pick(args.lat, data, "lat", None)
    lon = _pick(args.lon, data, "lon", None)
    lat_f = float(lat) if lat is not None else None
    lon_f = float(lon) if lon is not None else None
    if lat_f is not None and not -90.0 <= lat_f <= 90.0:
        raise UsageError("--lat must be between -90 and 90")
    if lon_f is not None and not -180.0 <= lon_f <= 180.0:
        raise UsageError("--lon must be between -180 and 180")
    if (lat_f is None) ^ (lon_f is None):
        raise UsageError("pass both --lat and --lon")

    timeout = float(_pick(args.timeout, data, "timeout", DEFAULT_TIMEOUT))
    retries = int(_pick(args.retries, data, "retries", DEFAULT_RETRIES))
    retry_delay = float(_pick(args.retry_delay, data, "retry_delay", DEFAULT_RETRY_DELAY))
    if timeout <= 0:
        raise UsageError("--timeout must be > 0")
    if retries < 1:
        raise UsageError("--retries must be >= 1")
    if retry_delay < 0:
        raise UsageError("--retry-delay must be >= 0")

    scan = bool(args.scan or data.get("scan", False))
    cache_raw = _pick(getattr(args, "ble_cache", None), data, "ble_cache", str(DEFAULT_BLE_CACHE))
    when = _parse_date(args.date, timezone) if getattr(args, "date", None) else None
    desired_raw = getattr(args, "desired_state_dir", None)
    desired_state_dir = Path(str(desired_raw)).expanduser() if desired_raw else None
    state_raw = getattr(args, "state_path", None)
    state_path = Path(str(state_raw)).expanduser() if state_raw else None
    enforce_raw = _pick(getattr(args, "enforce_minutes", None), data, "enforce_minutes", None)
    if enforce_raw is None:
        enforce_minutes = None
    elif isinstance(enforce_raw, bool):
        raise UsageError("--enforce-minutes must be an integer >= 1")
    else:
        enforce_minutes = int(enforce_raw)
        if enforce_minutes < 1:
            raise UsageError("--enforce-minutes must be an integer >= 1")

    hardware = {"on", "off", "status", "daemon"}
    if args.command == "daemon" and (lat_f is None or lon_f is None):
        raise UsageError("daemon needs --lat and --lon (or both keys in --config) for local sunset and sunrise")
    if args.command in hardware and backend is None:
        raise UsageError("pass --backend lan or --backend bluetooth")
    if args.command in hardware and backend == "lan" and not ip:
        raise UsageError("LAN needs --ip or an ip key in --config")

    return Settings(
        command=args.command,
        backend=backend,
        ip=ip,
        ble_address=ble_address,
        sku=sku,
        lat=lat_f,
        lon=lon_f,
        timezone=timezone,
        timeout=timeout,
        retries=retries,
        retry_delay=retry_delay,
        scan=scan,
        ble_cache=Path(cache_raw).expanduser(),
        when=when,
        config_path=Path(args.config) if getattr(args, "config", None) else None,
        desired_state_dir=desired_state_dir,
        state_path=state_path,
        enforce_minutes=enforce_minutes,
    )


def _parse_date(value: str, timezone: str) -> date:
    if value == "today":
        return datetime.now(ZoneInfo(timezone)).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise UsageError("--date must be YYYY-MM-DD") from exc
