"""Backend interface shared by the LAN and Bluetooth implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from house_lights.still import RGB


@dataclass(frozen=True)
class LightStatus:
    is_on: bool | None
    brightness: int | None
    rgb: RGB | None
    color_temp_kelvin: int | None
    detail: str = ""


@dataclass(frozen=True)
class ApplyResult:
    """What a backend actually sent for a still pattern."""

    mode: str
    colors_sent: tuple[RGB, ...]
    note: str | None = None


class LightsBackend(Protocol):
    """The daemon and CLI depend only on this surface."""

    async def open(self) -> None:
        """Prepare the transport. Bluetooth may connect; LAN opens a UDP socket."""

    async def close(self) -> None:
        """Release the transport. Bluetooth calls ``Device.stop()``."""

    async def turn_on(self) -> None:
        ...

    async def turn_off(self) -> None:
        ...

    async def set_brightness(self, percent: int) -> None:
        """Brightness percent, 1 through 100."""

    async def apply_pattern(self, colors: Sequence[RGB]) -> ApplyResult:
        """Send a still color list. A mixed list over LAN uses the first color."""

    async def status(self) -> LightStatus | None:
        """Read device status, or None when this backend cannot."""
