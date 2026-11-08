"""A 120-light color grid and the Finger Sketch picture that carries it.

The picture layout is the Govee app's Finger Sketch (DiyGraffitiV2). On a
120-light string every index fits in one byte, so the group count and each
bulb count are one byte. The two-byte form is only for a bulb past 255. Effect
0x0f (Gradient) at speed 0 holds still. Effects 0x00, 0x01, 0x02, 0x10, 0x11,
0x12, and 0x15 turn the light off, so this module does not expose an effect
field.

Bulbs count from 0 at the plug. A listed bulb is that group's color. The
header still carries a background color because a picture with zero groups
does not show on the H70C5. Every bulb is listed anyway, background included.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from govee_ble_local.wire.build import scene_activate, scene_upload_a3

from house_lights.holidays import (
    BLUE,
    GOLD,
    GREEN,
    PINK,
    PURPLE,
    RED,
    RGB,
    WARM_WHITE,
    WHITE,
)

LIGHT_COUNT = 120
SKETCH_EFFECT = 0x0F
SKETCH_SPEED = 0x00
SKETCH_COMM = 0x03
SKETCH_CODE = 0x0320

_NAMES: dict[str, RGB] = {
    "red": RED,
    "green": GREEN,
    "blue": BLUE,
    "white": WHITE,
    "black": (0, 0, 0),
    "gold": GOLD,
    "pink": PINK,
    "purple": PURPLE,
    "orange": (255, 165, 0),
    "warm white": WARM_WHITE,
    "warm-white": WARM_WHITE,
}


class GridError(ValueError):
    pass


def load_grid(path: Path) -> tuple[tuple[RGB, ...], int]:
    """Read a grid file and expand it to ``LIGHT_COUNT`` colors.

    Returns ``(colors, source_count)``. ``source_count`` is how many entries
    the file held before a shorter list was repeated.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GridError(f"grid file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GridError(f"grid file is not JSON: {path}: {exc}") from exc
    raw = _lights_field(data, path)
    colors = tuple(_parse_color(item, index) for index, item in enumerate(raw))
    return expand_lights(colors), len(colors)


def expand_lights(colors: Sequence[RGB], count: int = LIGHT_COUNT) -> tuple[RGB, ...]:
    """Repeat ``colors`` until there are ``count`` lights.

    A list of ``count`` is kept. A shorter list is repeated only when its
    length divides ``count``.
    """
    if count < 1:
        raise GridError("light count must be >= 1")
    if not colors:
        raise GridError("grid has no lights")
    if len(colors) > count:
        raise GridError(f"grid has {len(colors)} lights; this string has {count}")
    if count % len(colors) != 0:
        raise GridError(
            f"grid has {len(colors)} lights; use {count}, "
            f"or a length that divides {count} so it can repeat"
        )
    return tuple(colors) * (count // len(colors))


def group_colors(colors: Sequence[RGB]) -> tuple[RGB, ...]:
    """Distinct colors in first-seen order, which is the picture's group order."""
    return tuple(rgb for rgb, _ in _groups(colors))


def finger_sketch_value(colors: Sequence[RGB], *, brightness: int) -> bytes:
    """The kind-0x03 picture body for these lights, one color per index.

    A string whose indexes all fit in one byte uses DiyGraffitiV2's small form:
    the group count and each bulb count are one byte. The wide form (counts as
    u16, for bulbs past 255) was acked by this H706C and the string showed only
    the background color.
    """
    if not colors:
        raise GridError("grid has no lights")
    if not 1 <= brightness <= 100:
        raise GridError("brightness must be an integer from 1 to 100")
    groups = _groups(colors)
    background = _background(groups)
    if _fits_one_byte(groups):
        body = bytearray((SKETCH_EFFECT, SKETCH_SPEED, brightness, *background, len(groups)))
        for rgb, indices in groups:
            body.append(len(indices))
            body += bytes(rgb)
            body += bytes(indices)
        return bytes(body)
    body = bytearray((SKETCH_EFFECT, SKETCH_SPEED, brightness, *background))
    body += len(groups).to_bytes(2, "little")
    for rgb, indices in groups:
        body += _group_bytes(rgb, indices)
    return bytes(body)


def sketch_frames(colors: Sequence[RGB], *, brightness: int) -> tuple[list[bytes], bytes]:
    """0xA3 upload frames of kind 0x03, then the ``33 05 0a 20 03`` show frame.

    The show frame is separate so the upload can be accepted before it is sent.
    """
    value = finger_sketch_value(colors, brightness=brightness)
    frames = scene_upload_a3(value, SKETCH_COMM)
    show = scene_activate(SKETCH_CODE, diy=True)
    return frames, show


def _lights_field(data: object, path: Path) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "lights" not in data:
            raise GridError(f"{path}: grid JSON needs a lights array")
        unknown = sorted(set(data) - {"lights"})
        if unknown:
            raise GridError(f"{path}: unknown grid keys: {', '.join(unknown)}")
        lights = data["lights"]
        if not isinstance(lights, list):
            raise GridError(f"{path}: lights must be an array")
        return lights
    raise GridError(f"{path}: grid JSON must be an object or an array")


def _parse_color(item: object, index: int) -> RGB:
    if isinstance(item, str):
        return _parse_name(item, index)
    if isinstance(item, (list, tuple)) and len(item) == 3 and all(_byte(part) for part in item):
        return (int(item[0]), int(item[1]), int(item[2]))
    raise GridError(
        f"light {index} must be [r, g, b], #rrggbb, or a color name (got {item!r})"
    )


def _byte(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255


def _parse_name(value: str, index: int) -> RGB:
    text = value.strip().lower()
    if text in _NAMES:
        return _NAMES[text]
    hex_text = text[1:] if text.startswith("#") else ""
    if len(hex_text) == 6 and all(ch in "0123456789abcdef" for ch in hex_text):
        return (int(hex_text[0:2], 16), int(hex_text[2:4], 16), int(hex_text[4:6], 16))
    raise GridError(f"light {index} is not a known color or #rrggbb (got {value!r})")


def _fits_one_byte(groups: Sequence[tuple[RGB, list[int]]]) -> bool:
    if len(groups) > 255:
        return False
    for _, indices in groups:
        if len(indices) > 255 or any(index > 255 for index in indices):
            return False
    return True


def _groups(colors: Sequence[RGB]) -> list[tuple[RGB, list[int]]]:
    order: list[RGB] = []
    buckets: dict[RGB, list[int]] = {}
    for index, rgb in enumerate(colors):
        if rgb not in buckets:
            order.append(rgb)
            buckets[rgb] = []
        buckets[rgb].append(index)
    return [(rgb, buckets[rgb]) for rgb in order]


def _background(groups: Sequence[tuple[RGB, list[int]]]) -> RGB:
    most = max(len(indices) for _, indices in groups)
    for rgb, indices in groups:
        if len(indices) == most:
            return rgb
    raise GridError("grid has no lights")


def _group_bytes(rgb: RGB, indices: Sequence[int]) -> bytes:
    low = [index for index in indices if index < 256]
    high = [index for index in indices if index >= 256]
    if any(index > 0xFFFF for index in high):
        raise GridError("a light index must fit in 16 bits")
    out = bytearray()
    out += len(indices).to_bytes(2, "little")
    out += bytes(rgb)
    out += len(high).to_bytes(2, "little")
    out += bytes(low)
    for index in high:
        out += index.to_bytes(2, "little")
    return bytes(out)
