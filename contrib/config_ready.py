#!/usr/bin/env python3
"""Exit 0 when a config file has what the daemon needs to start."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def ready(data: object) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Config must be a JSON object."
    backend = data.get("backend")
    if backend not in {"lan", "bluetooth"}:
        return False, "Config needs backend set to bluetooth or lan."
    if data.get("lat") is None or data.get("lon") is None:
        return False, "Config needs lat and lon for local sunrise and sunset."
    if backend == "lan" and not data.get("ip"):
        return False, "LAN backend needs ip."
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
