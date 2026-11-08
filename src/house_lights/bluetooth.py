"""Bluetooth backend wrapping published ``govee-ble-local`` 1.10.0.

Method names used here are the ones that package documents: ``discover``,
``create_device``, ``Device.connect``, ``turn_on``, ``turn_off``,
``set_brightness``, ``set_rgb``, ``set_segment_count``,
``update``, ``release`` is available but this backend leaves idle disconnect
to the library, and ``stop`` on process shutdown.

H706C is a modelled SKU. ``discover`` and ``create_device`` are called with
``allow_modelled=True``. The GitHub repository named on PyPI
(https://github.com/Brady-Woods/govee-ble-local) returned HTTP 404 when this
project was written, so this wrapper follows the 1.10.0 wheel and its PyPI
long description: https://pypi.org/project/govee-ble-local/1.10.0/

That wheel refuses an AES-GCM session. This string advertises one, so
``install_gcm_link`` adds the handshake around the library's own frames.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from bleak.backends.device import BLEDevice

from govee_ble_local import (
    create_device,
    discover,
    profile_for,
)
from govee_ble_local.devices._fold import upload_interval
from govee_ble_local.transport.connection import UploadUnit
from govee_ble_local.wire import build
from govee_ble_local.wire.build import PRO_MULTI_A3

from house_lights.backend import ApplyResult, GridResult, LightStatus
from house_lights.ble_store import load as load_ble
from house_lights.ble_store import save as save_ble
from house_lights.gcm_link import install_gcm_link
from house_lights.grid import LIGHT_COUNT, SKETCH_COMM, group_colors, sketch_frames
from house_lights.holidays import RGB
from house_lights.retry import call_with_retry
from house_lights.settings import Settings
from house_lights.still import STILL_COMM, STILL_SCENE, still_scene_value

install_gcm_link()

log = logging.getLogger("house_lights")


class BluetoothError(Exception):
    pass


class BluetoothBackend:
    def __init__(
        self,
        settings: Settings,
        *,
        device_factory: Callable[..., Any] | None = None,
        discover_func: Callable[..., Awaitable[list]] | None = None,
    ) -> None:
        self.settings = settings
        self._device_factory = device_factory or create_device
        self._discover = discover_func or discover
        self._device: Any = None

    async def open(self) -> None:
        if self._device is not None:
            return
        ble_device, advertisement, address = await self._resolve()
        sku = self.settings.sku
        modelled = profile_for(sku) is None and profile_for(sku, allow_modelled=True) is not None
        if modelled:
            log.warning(
                "%s is modelled in govee-ble-local and is created with allow_modelled=True. "
                "The 1.10.0 library marks H706A/H706B/H706C modelled, not hardware-verified.",
                sku,
            )
        self._device = self._device_factory(
            ble_device,
            sku,
            advertisement,
            allow_modelled=True,
        )
        save_ble(self.settings.ble_cache, address, sku)
        log.info("saved BLE address %s sku %s to %s", address, sku, self.settings.ble_cache)
        await self._retry(self._device.connect, "BLE connect")

    async def close(self) -> None:
        device = self._device
        self._device = None
        if device is None:
            return
        try:
            await device.stop()
        except Exception as exc:
            log.warning("BLE stop raised: %s", exc)

    async def turn_on(self) -> None:
        await self._retry(self._require().turn_on, "BLE turn_on")

    async def turn_off(self) -> None:
        await self._retry(self._require().turn_off, "BLE turn_off")

    async def set_brightness(self, percent: int) -> None:
        if not 1 <= percent <= 100:
            raise ValueError("brightness must be an integer from 1 to 100")

        async def action() -> None:
            await self._require().set_brightness(percent)

        await self._retry(action, "BLE set_brightness")

    async def apply_pattern(self, colors: Sequence[RGB]) -> ApplyResult:
        palette = tuple(colors)
        if not palette:
            raise ValueError("pattern has no colors")
        device = self._require()
        if len(set(palette)) == 1:
            await self._retry(lambda: device.set_rgb(palette[0]), "BLE set_rgb")
            return ApplyResult(mode="ble_set_rgb", colors_sent=(palette[0],), note=None)
        frames = build.scene_upload_a3(still_scene_value(palette), STILL_COMM)
        show = build.scene_activate(STILL_SCENE)

        async def action() -> None:
            await self._send_still(device, frames, show)

        await self._retry(action, "BLE still scene")
        return ApplyResult(
            mode="ble_rgbic_still",
            colors_sent=palette,
            note="One light per color, repeating from the plug.",
        )

    async def apply_grid(self, colors: Sequence[RGB], *, brightness: int) -> GridResult:
        palette = tuple(colors)
        if len(palette) != LIGHT_COUNT:
            raise BluetoothError(f"grid has {len(palette)} lights; this string has {LIGHT_COUNT}")
        frames, show = sketch_frames(palette, brightness=brightness)
        device = self._require()

        async def action() -> None:
            await self._send_sketch(device, frames, show)

        await self._retry(action, "BLE finger sketch")
        colors_in_order = group_colors(palette)
        return GridResult(
            mode="ble_finger_sketch",
            light_count=len(palette),
            group_count=len(colors_in_order),
            upload_packets=len(frames),
            colors=colors_in_order,
            note=(
                "The controller acked the Finger Sketch upload and the show packet. "
                "Effect 0x0f at speed 0 is the still picture traced on an H70C5. "
                "Look at the house to see whether each light changed. "
                "A status read cannot show per-light color. "
                "The phone app on Bluetooth can overwrite it."
            ),
        )

    async def _send_sketch(self, device: Any, frames: list[bytes], show: bytes) -> None:
        # The modelled H706C profile has no scenes capability, so Device.set_scene
        # will not send this. The upload is the app's kind-0x03 DIY picture and
        # the show packet is scene code 0x0320 under sub-mode 0x0a. Kind 0x03 is
        # a scene compose unit: its ack status is byte 2, and the show packet
        # goes out only after that ack.
        conn = device._conn
        state = getattr(device, "_state", None)
        hard = getattr(state, "hardware_version", None)
        if not isinstance(hard, str):
            hard = None
        interval = upload_interval(hard, "compose")
        unit = UploadUnit(PRO_MULTI_A3, SKETCH_COMM, 2, interval)
        log.info(
            "finger sketch: %s upload packets, then show, %.0f ms between packets",
            len(frames),
            interval * 1000,
        )
        with conn.hold_heartbeat():
            await conn.send_unacked(frames, unit=unit)
            await conn.send(show)

    async def _send_still(self, device: Any, frames: list[bytes], show: bytes) -> None:
        # Same compose unit as a library rgbic scene: ack status at byte 2,
        # show packet only after that ack. Scene 11183 is the Bright slot.
        conn = device._conn
        state = getattr(device, "_state", None)
        hard = getattr(state, "hardware_version", None)
        if not isinstance(hard, str):
            hard = None
        interval = upload_interval(hard, "compose")
        unit = UploadUnit(PRO_MULTI_A3, STILL_COMM, 2, interval)
        log.info(
            "still scene %s: %s upload packets, %.0f ms between packets",
            STILL_SCENE,
            len(frames),
            interval * 1000,
        )
        with conn.hold_heartbeat():
            await conn.send_unacked(frames, unit=unit)
            await conn.send(show)

    async def status(self) -> LightStatus | None:
        state = await self._retry(self._require().update, "BLE update")
        segments = getattr(state, "segments", ()) or ()
        return LightStatus(
            is_on=getattr(state, "is_on", None),
            brightness=getattr(state, "brightness", None),
            rgb=getattr(state, "rgb_color", None),
            color_temp_kelvin=getattr(state, "color_temp_kelvin", None),
            detail=f"segments={len(segments)} optimistic={getattr(state, 'optimistic', None)}",
        )

    async def _resolve(self) -> tuple[BLEDevice, Any, str]:
        cached = load_ble(self.settings.ble_cache)
        address = self.settings.ble_address
        if address is None and cached is not None and cached.sku.upper() == self.settings.sku:
            address = cached.address
            log.info("using saved BLE address %s for %s", address, cached.sku)
        # A BLEDevice built from the address alone has no fresh advertisement.
        # BlueZ then sits in Connect until the library's 45s operation limit.
        # Scan first so the connect uses a device BlueZ has just heard.
        if address:
            log.info("scanning for %s at %s", self.settings.sku, address)
        found = await self._retry(
            lambda: self._discover(
                timeout=self.settings.timeout,
                supported_only=True,
                allow_modelled=True,
            ),
            "BLE discover",
        )
        wanted = self.settings.sku.upper()
        rows = [item for item in found if str(getattr(item, "sku", "")).upper() == wanted]
        if address:
            rows = [item for item in rows if _same_address(item.address, address)]
            if not rows:
                raise BluetoothError(
                    f"no {wanted} advertisement from {address} during a "
                    f"{self.settings.timeout:g}s scan. The light has to be advertising."
                )
        if not rows:
            raise BluetoothError(
                f"no {wanted} advertisement during a {self.settings.timeout:g}s scan. "
                "Pass --ble-address, or rerun after a light has been saved to the BLE cache."
            )
        if len(rows) > 1 and not address:
            listed = ", ".join(item.address for item in rows)
            raise BluetoothError(f"several {wanted} devices in scan ({listed}). Pass --ble-address.")
        chosen = rows[0]
        log.info("discovered %s at %s", chosen.sku, chosen.address)
        return chosen.ble_device, chosen.advertisement, chosen.address

    async def _retry(self, action: Callable[[], Awaitable], label: str):
        return await call_with_retry(
            action,
            attempts=self.settings.retries,
            delay=self.settings.retry_delay,
            label=label,
        )

    def _require(self) -> Any:
        if self._device is None:
            raise BluetoothError("Bluetooth backend is not open")
        return self._device


def _same_address(left: str, right: str) -> bool:
    return left.strip().replace("-", ":").upper() == right.strip().replace("-", ":").upper()
