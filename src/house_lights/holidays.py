"""Still holiday colors. Edit ``TABLE`` to change a look.

Every pattern is a static sequence. On Bluetooth a mixed pattern tiles one
light per color from the plug. The scheduler paints it once and leaves it.
Nothing here blinks, fades, or cycles over time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

RGB = tuple[int, int, int]

RED: RGB = (255, 0, 0)
GREEN: RGB = (0, 255, 0)
BLUE: RGB = (0, 0, 255)
# Orange/yellow for Classic Christmas. Exact triple is the editable swatch.
ORANGE_YELLOW: RGB = (255, 165, 0)
WHITE: RGB = (255, 255, 255)
GOLD: RGB = (255, 215, 0)
PINK: RGB = (255, 105, 180)
PURPLE: RGB = (128, 0, 255)
HALLOWEEN_ORANGE: RGB = (255, 95, 0)
# Approximate warm-white RGB for the default night. LAN sends it as colorwc
# with colorTemInKelvin 0, so the device uses the RGB field.
WARM_WHITE: RGB = (255, 197, 143)


@dataclass(frozen=True)
class Pattern:
    """One still look. ``colors`` repeats one light at a time on Bluetooth."""

    key: str
    name: str
    color_names: tuple[str, ...]
    colors: tuple[RGB, ...]

    @property
    def mixed(self) -> bool:
        return len(set(self.colors)) > 1


@dataclass(frozen=True)
class Holiday:
    """A row in the editable holiday table.

    ``days`` is a set of (month, day). ``span`` is an inclusive (month, day)
    range inside a single year. A date uses the first matching row.
    """

    pattern: Pattern
    days: frozenset[tuple[int, int]] = frozenset()
    span: tuple[tuple[int, int], tuple[int, int]] | None = None

    def matches(self, day: date) -> bool:
        md = (day.month, day.day)
        if md in self.days:
            return True
        if self.span is None:
            return False
        start, end = self.span
        return start <= md <= end


CHRISTMAS = Pattern(
    key="christmas",
    name="Classic Christmas",
    color_names=("red", "green", "blue", "orange/yellow"),
    colors=(RED, GREEN, BLUE, ORANGE_YELLOW),
)
INDEPENDENCE = Pattern(
    key="independence",
    name="Independence Day",
    color_names=("red", "white", "blue"),
    colors=(RED, WHITE, BLUE),
)
NEW_YEAR = Pattern(
    key="new_year",
    name="New Year's",
    color_names=("gold", "white"),
    colors=(GOLD, WHITE),
)
HALLOWEEN = Pattern(
    key="halloween",
    name="Halloween",
    color_names=("orange", "purple"),
    colors=(HALLOWEEN_ORANGE, PURPLE),
)
VALENTINES = Pattern(
    key="valentines",
    name="Valentine's Day",
    color_names=("red", "pink"),
    colors=(RED, PINK),
)
DEFAULT_NIGHT = Pattern(
    key="default",
    name="Default night",
    color_names=("warm white",),
    colors=(WARM_WHITE,),
)

# First match wins. New Year is listed before Christmas so December 31 is
# New Year's, and Christmas stops on December 26.
TABLE: tuple[Holiday, ...] = (
    Holiday(NEW_YEAR, days=frozenset({(12, 31), (1, 1)})),
    Holiday(INDEPENDENCE, days=frozenset({(7, 4)})),
    Holiday(HALLOWEEN, days=frozenset({(10, 31)})),
    Holiday(VALENTINES, days=frozenset({(2, 14)})),
    Holiday(CHRISTMAS, span=((12, 1), (12, 26))),
)


def pattern_for(day: date) -> Pattern:
    """Return the still pattern for a civil date. Other dates use warm white."""
    for row in TABLE:
        if row.matches(day):
            return row.pattern
    return DEFAULT_NIGHT


def segment_groups(colors: tuple[RGB, ...] | list[RGB], count: int) -> list[tuple[RGB, list[int]]]:
    """Repeat ``colors`` across ``count`` segments, grouped for one write per color.

    Segment 0 gets ``colors[0]``, segment 1 gets ``colors[1]``, and so on,
    wrapping. Indices in each group are the positions that share that RGB.
    """
    if count < 1:
        raise ValueError("segment count must be >= 1")
    if not colors:
        raise ValueError("pattern has no colors")
    order: list[RGB] = []
    buckets: dict[RGB, list[int]] = {}
    for index in range(count):
        color = colors[index % len(colors)]
        if color not in buckets:
            buckets[color] = []
            order.append(color)
        buckets[color].append(index)
    return [(color, buckets[color]) for color in order]
