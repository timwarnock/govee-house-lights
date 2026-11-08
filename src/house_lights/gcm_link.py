"""Teach ``govee-ble-local`` 1.10.0 the AES-GCM session it detects and refuses.

The library still builds every command. This only wraps the link: the
handshake, then seal on the way out and unseal on the way in.
"""

from __future__ import annotations

import asyncio
import logging

from govee_ble_local.exceptions import (
    GoveeBleHandshakeConnectionError,
    GoveeBleHandshakeTimeout,
    GoveeBleNotSupported,
)
from govee_ble_local.models import Encryption
from govee_ble_local.transport.connection import GoveeConnection, _LinkLost

from house_lights.aes_gcm import TAG_LENGTHS, GcmSession, build_handshake, parse_handshake

log = logging.getLogger("house_lights")

_ATTEMPT_SECONDS = 4.0


def install_gcm_link() -> None:
    if getattr(GoveeConnection, "_hl_gcm_installed", False):
        return
    orig_prepare = GoveeConnection._prepare_session
    orig_ensure = GoveeConnection._ensure_connected_locked
    orig_notify = GoveeConnection._handle_notify
    orig_encrypt = GoveeConnection._encrypt
    orig_reset = GoveeConnection._reset_session

    async def _prepare_session(self: GoveeConnection) -> None:
        try:
            await orig_prepare(self)
        except GoveeBleNotSupported as exc:
            if "AES-GCM" not in str(exc):
                raise
            await _handshake(self)
            await _finish_session(self)

    async def _ensure_connected_locked(self: GoveeConnection, budget=None) -> None:
        # The library skips the link once it has seen version 2. Clear that so
        # the next command connects and handshakes again.
        if self._bgc_checked and self._session_mode() is Encryption.AES_GCM:
            self._bgc_checked = False
        await orig_ensure(self, budget)

    def _handle_notify(self: GoveeConnection, char, data: bytearray) -> None:
        session = getattr(self, "_hl_gcm", None)
        raw = bytes(data)
        if self._encryption is Encryption.AES_GCM or session is not None:
            if not self._ready:
                if len(raw) >= 3 and raw[0] == 0xE7 and raw[1] == 0x11:
                    self._enqueue(raw)
                return
            if session is not None and len(raw) != 20:
                try:
                    plain = session.unseal(raw)
                except Exception as exc:
                    log.debug("%s: dropped a GCM notify: %s", self.address, exc)
                    return
                data = bytearray(plain)
        orig_notify(self, char, data)

    def _encrypt(self: GoveeConnection, frame_plaintext: bytes) -> bytes:
        session = getattr(self, "_hl_gcm", None)
        if session is not None and self._encryption is Encryption.AES_GCM:
            return session.seal(frame_plaintext)
        return orig_encrypt(self, frame_plaintext)

    def _reset_session(self: GoveeConnection) -> None:
        self._hl_gcm = None
        orig_reset(self)

    GoveeConnection._prepare_session = _prepare_session  # type: ignore[method-assign]
    GoveeConnection._ensure_connected_locked = _ensure_connected_locked  # type: ignore[method-assign]
    GoveeConnection._handle_notify = _handle_notify  # type: ignore[method-assign]
    GoveeConnection._encrypt = _encrypt  # type: ignore[method-assign]
    GoveeConnection._reset_session = _reset_session  # type: ignore[method-assign]
    GoveeConnection._hl_gcm_installed = True  # type: ignore[attr-defined]


async def _handshake(conn: GoveeConnection) -> None:
    payload = conn.write_payload_size
    log.info("%s: AES-GCM handshake, write payload %s bytes", conn.address, payload)
    loop = asyncio.get_running_loop()
    for tag_len in TAG_LENGTHS:
        frame, tx_iv = build_handshake(tag_len)
        await conn._raw_write(frame)
        deadline = loop.time() + _ATTEMPT_SECONDS
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                log.info("%s: no AES-GCM reply for a %s-byte tag", conn.address, tag_len)
                break
            try:
                raw = await conn._next_rx(remaining)
            except TimeoutError:
                log.info("%s: no AES-GCM reply for a %s-byte tag", conn.address, tag_len)
                break
            except _LinkLost as exc:
                raise GoveeBleHandshakeConnectionError(
                    f"{conn.address}: link lost during AES-GCM handshake"
                ) from exc
            try:
                opened = parse_handshake(raw, tag_len)
            except Exception as exc:
                log.debug("%s: ignoring a notify during handshake: %s", conn.address, exc)
                continue
            conn._hl_gcm = GcmSession(tx_iv, opened.rx_iv, opened.device_key, tag_len)
            log.info(
                "%s: AES-GCM session ready, tag %s bytes, device %s",
                conn.address,
                tag_len,
                opened.sku,
            )
            return
    raise GoveeBleHandshakeTimeout(f"{conn.address}: AES-GCM handshake got no reply")


async def _finish_session(conn: GoveeConnection) -> None:
    """The library returns before this once it refuses AES-GCM. Run that tail."""
    conn._ready = True
    conn._drain()
    log.debug("%s: session ready (%s)", conn.address, conn._encryption.value)
    if conn._unlock_frames is not None:
        for frame in conn._unlock_frames():
            conn._setup_wrote = True
            await conn._send_write_verified(frame, conn._write_copies)
    if conn._session_frames is not None:
        await conn._send_session_frames(conn._session_frames())
