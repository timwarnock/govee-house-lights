"""Official Govee LAN API, local UDP only.

Documented in https://app-h5.govee.com/user-manual/wlan-guide :

- scan request: UDP multicast 239.255.255.250 port 4001
- scan replies: UDP port 4002
- control: unicast UDP to the device IP port 4003
- commands used here: scan, turn, brightness, devStatus, colorwc

``colorwc`` sets one RGB color or one color temperature on the whole device.
A multi-color pattern therefore sends the first color only and says so.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Protocol, Sequence

from house_lights.backend import ApplyResult, LightStatus
from house_lights.still import RGB
from house_lights.retry import call_with_retry

log = logging.getLogger("house_lights")

MULTICAST_GROUP = "239.255.255.250"
SCAN_PORT = 4001
REPLY_PORT = 4002
CONTROL_PORT = 4003

LAN_MIXED_NOTE = (
    "Official LAN colorwc sets one color or one color temperature for the whole "
    "device (https://app-h5.govee.com/user-manual/wlan-guide). "
    "A mixed color list uses the first color {rgb} on the whole device. "
    "Per-light color uses Bluetooth."
)


class LanError(Exception):
    pass


def scan_payload() -> dict:
    return {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}


def turn_payload(on: bool) -> dict:
    return {"msg": {"cmd": "turn", "data": {"value": 1 if on else 0}}}


def brightness_payload(percent: int) -> dict:
    if isinstance(percent, bool) or not isinstance(percent, int) or not 1 <= percent <= 100:
        raise ValueError("brightness must be an integer from 1 to 100")
    return {"msg": {"cmd": "brightness", "data": {"value": percent}}}


def dev_status_payload() -> dict:
    return {"msg": {"cmd": "devStatus", "data": {}}}


def colorwc_payload(rgb: RGB) -> dict:
    red, green, blue = _check_rgb(rgb)
    # colorTemInKelvin 0 tells the device to use r/g/b. A non-zero Kelvin
    # would replace the RGB, per the LAN guide.
    return {
        "msg": {
            "cmd": "colorwc",
            "data": {
                "color": {"r": red, "g": green, "b": blue},
                "colorTemInKelvin": 0,
            },
        }
    }


def lan_color_plan(colors: Sequence[RGB]) -> tuple[RGB, str | None]:
    """Whole-device color, plus a note when the pattern has more than one color."""
    if not colors:
        raise ValueError("pattern has no colors")
    chosen = _check_rgb(colors[0])
    if len(set(colors)) == 1:
        return chosen, None
    return chosen, LAN_MIXED_NOTE.format(rgb=chosen)


def parse_dev_status(message: dict) -> LightStatus | None:
    msg = message.get("msg") if isinstance(message, dict) else None
    if not isinstance(msg, dict) or msg.get("cmd") != "devStatus":
        return None
    data = msg.get("data")
    if not isinstance(data, dict):
        return None
    # A scan reply also uses cmd "scan"; devStatus replies carry onOff.
    if "onOff" not in data and "brightness" not in data and "color" not in data:
        return None
    color = data.get("color") if isinstance(data.get("color"), dict) else {}
    rgb = None
    if color:
        try:
            rgb = (int(color.get("r", 0)), int(color.get("g", 0)), int(color.get("b", 0)))
        except (TypeError, ValueError):
            rgb = None
    on_off = data.get("onOff")
    brightness = data.get("brightness")
    kelvin = data.get("colorTemInKelvin")
    return LightStatus(
        is_on=None if on_off is None else bool(int(on_off)),
        brightness=None if brightness is None else int(brightness),
        rgb=rgb,
        color_temp_kelvin=None if kelvin is None else int(kelvin),
        detail="devStatus",
    )


def _check_rgb(rgb: RGB) -> RGB:
    if len(rgb) != 3:
        raise ValueError(f"color must be an (r, g, b) triple, got {rgb!r}")
    out = []
    for channel in rgb:
        if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255:
            raise ValueError(f"color channel must be an int 0..255, got {channel!r}")
        out.append(channel)
    return (out[0], out[1], out[2])


class LanTransport(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def send(self, payload: dict) -> None: ...

    def request_status(self) -> dict: ...


class UdpLanTransport:
    """One UDP socket bound to port 4002, as the LAN guide describes for replies."""

    def __init__(self, ip: str, timeout: float) -> None:
        self.ip = ip
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def open(self) -> None:
        if self._sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", REPLY_PORT))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            membership = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton("0.0.0.0")
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            except OSError as exc:
                log.warning("could not join multicast %s: %s", MULTICAST_GROUP, exc)
            sock.settimeout(self.timeout)
        except OSError as exc:
            sock.close()
            raise LanError(f"could not bind UDP port {REPLY_PORT} for LAN replies: {exc}") from exc
        self._sock = sock
        self._log_scan()

    def scan_wait(self) -> float:
        """Best-effort scan wait. A missing reply should not burn the whole status timeout."""
        return min(self.timeout, 2.0)

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            sock.close()

    def send(self, payload: dict) -> None:
        self._sendto(payload, (self.ip, CONTROL_PORT))

    def request_status(self) -> dict:
        self.send(dev_status_payload())
        deadline_sock = self._require()
        deadline_sock.settimeout(self.timeout)
        while True:
            try:
                raw, _addr = deadline_sock.recvfrom(4096)
            except socket.timeout as exc:
                raise LanError(
                    f"no devStatus reply from {self.ip} on UDP port {REPLY_PORT} "
                    f"within {self.timeout:g}s"
                ) from exc
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                log.debug("ignoring non-JSON LAN packet")
                continue
            if parse_dev_status(message) is not None:
                return message
            log.debug("ignoring LAN packet while waiting for devStatus: %s", message)

    def _log_scan(self) -> None:
        try:
            self._sendto(scan_payload(), (MULTICAST_GROUP, SCAN_PORT))
            found = self._collect(self.scan_wait(), stop_ip=self.ip)
        except OSError as exc:
            log.warning("LAN scan failed: %s. Controlling configured IP %s.", exc, self.ip)
            return
        matches = [item for item in found if item.get("ip") == self.ip]
        if matches:
            row = matches[0]
            log.info(
                "LAN scan saw sku %s device %s at %s",
                row.get("sku"),
                row.get("device"),
                self.ip,
            )
            return
        if found:
            log.info(
                "LAN scan saw %s other device(s); controlling configured IP %s",
                len(found),
                self.ip,
            )
            return
        log.info("no LAN scan reply; controlling configured IP %s", self.ip)

    def _collect(self, timeout: float, stop_ip: str | None = None) -> list[dict]:
        sock = self._require()
        sock.settimeout(timeout)
        rows: list[dict] = []
        while True:
            try:
                raw, _addr = sock.recvfrom(4096)
            except socket.timeout:
                return rows
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            msg = message.get("msg") if isinstance(message, dict) else None
            data = msg.get("data") if isinstance(msg, dict) else None
            if isinstance(msg, dict) and msg.get("cmd") == "scan" and isinstance(data, dict) and data.get("ip"):
                rows.append(data)
                if stop_ip and data.get("ip") == stop_ip:
                    return rows

    def _sendto(self, payload: dict, address: tuple[str, int]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._require().sendto(body, address)

    def _require(self) -> socket.socket:
        if self._sock is None:
            raise LanError("LAN socket is not open")
        return self._sock


class LanBackend:
    def __init__(
        self,
        ip: str,
        *,
        timeout: float = 8.0,
        retries: int = 3,
        retry_delay: float = 1.0,
        transport: LanTransport | None = None,
    ) -> None:
        self.ip = ip
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self._transport = transport if transport is not None else UdpLanTransport(ip, timeout)

    async def open(self) -> None:
        await asyncio.to_thread(self._transport.open)

    async def close(self) -> None:
        await asyncio.to_thread(self._transport.close)

    async def turn_on(self) -> None:
        await self._send(turn_payload(True), "LAN turn on")

    async def turn_off(self) -> None:
        await self._send(turn_payload(False), "LAN turn off")

    async def set_brightness(self, percent: int) -> None:
        await self._send(brightness_payload(percent), "LAN brightness")

    async def apply_pattern(self, colors: Sequence[RGB]) -> ApplyResult:
        chosen, note = lan_color_plan(colors)
        await self._send(colorwc_payload(chosen), "LAN colorwc")
        return ApplyResult(mode="lan_colorwc_whole_device", colors_sent=(chosen,), note=note)

    async def status(self) -> LightStatus | None:
        message = await call_with_retry(
            lambda: asyncio.to_thread(self._transport.request_status),
            attempts=self.retries,
            delay=self.retry_delay,
            label="LAN devStatus",
        )
        parsed = parse_dev_status(message)
        if parsed is None:
            raise LanError("devStatus reply was not understood")
        return parsed

    async def _send(self, payload: dict, label: str) -> None:
        await call_with_retry(
            lambda: asyncio.to_thread(self._transport.send, payload),
            attempts=self.retries,
            delay=self.retry_delay,
            label=label,
        )
