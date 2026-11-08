import unittest

from house_lights.aes_gcm import (
    KEY_HANDSHAKE,
    GcmSession,
    build_handshake,
    parse_handshake,
)
from house_lights.aes_gcm import _open as open_gcm
from house_lights.gcm_link import install_gcm_link


class AesGcmTests(unittest.TestCase):
    def test_handshake_request_seals_the_tx_iv(self) -> None:
        tx_iv = b"12345678"
        nonce = b"abcdefghijkl"
        frame, returned = build_handshake(16, tx_iv=tx_iv, nonce=nonce)
        self.assertEqual(returned, tx_iv)
        self.assertEqual(frame[:3], b"\xe7\x11\x01")
        self.assertEqual(frame[3:15], nonce)
        self.assertEqual(frame[15], 16)
        self.assertEqual(len(frame), 16 + 8 + 16)
        self.assertEqual(open_gcm(KEY_HANDSHAKE, nonce, frame[16:], frame[:16], 16), tx_iv)

    def test_handshake_reply_derives_a_device_key(self) -> None:
        rx_iv = b"abcdefgH"
        dev_info = b"H706C" + bytes.fromhex("1f488ab6eac0")
        plain = rx_iv + dev_info
        nonce = b"nonce-12-byt"
        header = bytes((0xE7, 0x11, 0x00)) + nonce
        from house_lights.aes_gcm import _seal

        frame = header + _seal(KEY_HANDSHAKE, nonce, header, plain, 16)
        opened = parse_handshake(frame, 16)
        self.assertEqual(opened.rx_iv, rx_iv)
        self.assertEqual(opened.sku, "H706C")
        self.assertEqual(len(opened.device_key), 16)

    def test_data_frame_round_trip(self) -> None:
        frame = bytes(range(20))
        for tag_len in (16, 12):
            sender = GcmSession(b"tx-iv-88", b"rx-iv-88", b"device-key-16byt", tag_len)
            receiver = GcmSession(b"rx-iv-88", b"tx-iv-88", b"device-key-16byt", tag_len)
            wire = sender.seal(frame)
            self.assertEqual(wire[:4], (1).to_bytes(4, "big"))
            self.assertEqual(len(wire), 4 + len(frame) + tag_len)
            self.assertEqual(receiver.unseal(wire), frame)

    def test_install_is_idempotent(self) -> None:
        from govee_ble_local.transport.connection import GoveeConnection

        install_gcm_link()
        first = GoveeConnection._prepare_session
        install_gcm_link()
        self.assertIs(GoveeConnection._prepare_session, first)


if __name__ == "__main__":
    unittest.main()
