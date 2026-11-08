"""AES-GCM session for newer Govee BLE lights.

govee-ble-local 1.10.0 detects this mode (BGC encrypt version 2, handshake
opcode 0x11) and refuses it. The wire format below is the one those lights
use: a public handshake key, then per-frame AES-GCM around the same 20-byte
commands the library already builds.

Tag length is part of the request. Some lights use 16 and ignore a 12-byte
tag, so the link tries 16 and then 12.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY_HANDSHAKE = bytes.fromhex("fc03783c7c42cb83e202a1643648aff6")
KEY_DEVICE = bytes.fromhex("ae028b630bae6ecc4bff1b249e22f955")
TAG_LENGTHS = (16, 12)
FRAME_LEN = 20


class GcmFormatError(ValueError):
    pass


def _seal(key: bytes, nonce: bytes, aad: bytes, plain: bytes, tag_len: int) -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    body = encryptor.update(plain) + encryptor.finalize()
    return body + encryptor.tag[:tag_len]


def _aes_ecb(key: bytes, block: bytes) -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()  # nosec B305
    return encryptor.update(block) + encryptor.finalize()


def _gmul(x: int, y: int) -> int:
    """GF(2^128) multiply, the GHASH polynomial."""
    r = 0xE1000000000000000000000000000000
    z = 0
    v = x
    for i in range(128):
        if (y >> (127 - i)) & 1:
            z ^= v
        v = (v >> 1) ^ r if v & 1 else v >> 1
    return z


def _ghash(h: bytes, data: bytes) -> bytes:
    hv = int.from_bytes(h, "big")
    y = 0
    for offset in range(0, len(data), 16):
        block = data[offset : offset + 16].ljust(16, b"\0")
        y = _gmul(y ^ int.from_bytes(block, "big"), hv)
    return y.to_bytes(16, "big")


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right, strict=True))


def _inc32(block: bytes) -> bytes:
    n = int.from_bytes(block[12:], "big")
    return block[:12] + ((n + 1) & 0xFFFFFFFF).to_bytes(4, "big")


def _open(key: bytes, nonce: bytes, blob: bytes, aad: bytes, tag_len: int) -> bytes:
    """Open a GCM blob. Tag lengths under 16 are the leading bytes of the full tag.

    cryptography 50 rejects a tag shorter than 16, and some of these lights send 12.
    """
    if len(nonce) != 12:
        raise GcmFormatError("GCM nonce must be 12 bytes")
    if len(blob) < tag_len:
        raise GcmFormatError("sealed blob is shorter than the tag")
    body, tag = blob[:-tag_len], blob[-tag_len:]
    hash_key = _aes_ecb(key, b"\0" * 16)
    padded_aad = aad + b"\0" * ((-len(aad)) % 16)
    padded_body = body + b"\0" * ((-len(body)) % 16)
    lengths = (len(aad) * 8).to_bytes(8, "big") + (len(body) * 8).to_bytes(8, "big")
    digest = _ghash(hash_key, padded_aad + padded_body + lengths)
    j0 = nonce + b"\x00\x00\x00\x01"
    full_tag = _xor(_aes_ecb(key, j0), digest)
    if full_tag[:tag_len] != tag:
        raise GcmFormatError("GCM tag did not verify")
    counter = _inc32(j0)
    plain = bytearray()
    for offset in range(0, len(body), 16):
        stream = _aes_ecb(key, counter)
        chunk = body[offset : offset + 16]
        plain += _xor(chunk, stream[: len(chunk)])
        counter = _inc32(counter)
    return bytes(plain)


def build_handshake(
    tag_len: int,
    *,
    tx_iv: bytes | None = None,
    nonce: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Return ``(frame, tx_iv)`` for an ``e7 11 01`` handshake request."""
    if tag_len not in TAG_LENGTHS:
        raise GcmFormatError(f"tag length must be one of {TAG_LENGTHS}")
    tx_iv = os.urandom(8) if tx_iv is None else tx_iv
    nonce = os.urandom(12) if nonce is None else nonce
    if len(tx_iv) != 8 or len(nonce) != 12:
        raise GcmFormatError("handshake needs an 8-byte iv and a 12-byte nonce")
    header = bytes((0xE7, 0x11, 0x01)) + nonce + bytes((tag_len,))
    return header + _seal(KEY_HANDSHAKE, nonce, header, tx_iv, tag_len), tx_iv


@dataclass(frozen=True)
class HandshakeResult:
    rx_iv: bytes
    dev_info: bytes
    device_key: bytes
    sku: str


def parse_handshake(frame: bytes, tag_len: int) -> HandshakeResult:
    """Open an ``e7 11 00`` reply and derive the per-device frame key."""
    if tag_len not in TAG_LENGTHS:
        raise GcmFormatError(f"tag length must be one of {TAG_LENGTHS}")
    if len(frame) < 15 or frame[0] != 0xE7 or frame[1] != 0x11:
        raise GcmFormatError("not an e7 11 handshake reply")
    if frame[2] != 0x00:
        raise GcmFormatError(f"handshake status 0x{frame[2]:02x}")
    nonce = frame[3:15]
    plain = _open(KEY_HANDSHAKE, nonce, frame[15:], frame[:15], tag_len)
    if len(plain) != 19:
        raise GcmFormatError(f"handshake plaintext is {len(plain)} bytes")
    rx_iv, dev_info = plain[:8], plain[8:19]
    block = dev_info.ljust(16, b"\0")
    encryptor = Cipher(algorithms.AES(KEY_DEVICE), modes.ECB()).encryptor()  # nosec B305
    device_key = encryptor.update(block) + encryptor.finalize()
    sku = dev_info[:5].decode("ascii", errors="replace")
    return HandshakeResult(rx_iv=rx_iv, dev_info=dev_info, device_key=device_key, sku=sku)


class GcmSession:
    """Wraps each 20-byte command. Counters start at 1 and reset per link."""

    def __init__(self, tx_iv: bytes, rx_iv: bytes, device_key: bytes, tag_len: int) -> None:
        self.tx_iv = tx_iv
        self.rx_iv = rx_iv
        self.device_key = device_key
        self.tag_len = tag_len
        self._tx_counter = 1

    def seal(self, frame20: bytes) -> bytes:
        if len(frame20) != FRAME_LEN:
            raise GcmFormatError(f"command frame must be {FRAME_LEN} bytes")
        counter = self._tx_counter
        self._tx_counter += 1
        ctr = counter.to_bytes(4, "big")
        body = _seal(self.device_key, self.tx_iv + ctr, ctr, frame20, self.tag_len)
        return ctr + body

    def unseal(self, frame: bytes) -> bytes:
        if len(frame) < 4 + self.tag_len:
            raise GcmFormatError("data frame is too short")
        ctr = frame[:4]
        plain = _open(self.device_key, self.rx_iv + ctr, frame[4:], ctr, self.tag_len)
        if len(plain) != FRAME_LEN:
            raise GcmFormatError(f"opened frame is {len(plain)} bytes")
        return plain
