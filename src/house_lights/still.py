"""Still per-light scene for the H706C.

A short palette tiles one light per color from the plug. On 2026-11-07 the
outdoor string showed red, white, blue that way: upload comm 0x02, then
scene 11183 (the Bright slot). The record is the catalog Bright scene with
``color_ic`` 1 and the pattern's colors.
"""

from __future__ import annotations

from collections.abc import Sequence

RGB = tuple[int, int, int]

# Bright's scene code. Each upload replaces that slot until the app sends it again.
STILL_SCENE = 11183
STILL_COMM = 0x02

# style, mode, mode_param, algo, brightness count, the six-byte brightness block,
# color_ic, speed, duration, color count, then 3 bytes in-area and 4 bytes area.
_RECORD_OVERHEAD = 23
_MAX_COLORS = (255 - _RECORD_OVERHEAD) // 3


def still_scene_value(colors: Sequence[RGB]) -> bytes:
    """Rgbic scene blob: one effect, held still, one light per palette color."""
    palette = tuple(colors)
    if not palette:
        raise ValueError("pattern has no colors")
    if len(palette) > _MAX_COLORS:
        raise ValueError(
            f"a still scene holds at most {_MAX_COLORS} colors, got {len(palette)}"
        )
    record = bytearray()
    record.append(0)  # style
    record.append(0)  # mode
    record.extend((0, 1))  # mode_param, big-endian 1, copied from Bright
    record.append(0)  # bright_algo
    record.append(1)  # one brightness effect
    record.extend(bytes.fromhex("ffff01003201"))
    record.append(1)  # color_ic: one light per color
    record.append(0)  # speed
    record.append(0x32)  # duration, copied from Bright
    record.append(len(palette))
    for rgb in palette:
        if len(rgb) != 3 or any(not isinstance(channel, int) or channel < 0 or channel > 255 for channel in rgb):
            raise ValueError(f"color must be three bytes 0-255, got {rgb}")
        record.extend(rgb)
    record.extend(bytes(7))
    if len(record) != _RECORD_OVERHEAD + 3 * len(palette):
        raise ValueError("still scene record length does not match the palette")
    return bytes((1, len(record))) + bytes(record)
