"""Remember the last Bluetooth address and SKU between process runs.

``govee-ble-local`` 1.10.0 connects, reuses the link, idle-disconnects, and
sends keep-alives by itself. It does not document saving an address to disk.
This file is that small persistence layer.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SavedBle:
    address: str
    sku: str


def load(path: Path) -> SavedBle | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    address = raw.get("address") if isinstance(raw, dict) else None
    sku = raw.get("sku") if isinstance(raw, dict) else None
    if not isinstance(address, str) or not isinstance(sku, str):
        return None
    if not address or not sku:
        return None
    return SavedBle(address=address, sku=sku)


def save(path: Path, address: str, sku: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"address": address, "sku": sku}, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
