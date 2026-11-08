import asyncio
import json
import socket
import threading
import unittest

RED = (255, 0, 0)
WARM_WHITE = (255, 197, 143)
CHRISTMAS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 165, 0))
from house_lights.lan import (
    CONTROL_PORT,
    LAN_MIXED_NOTE,
    LanBackend,
    UdpLanTransport,
    brightness_payload,
    colorwc_payload,
    lan_color_plan,
    parse_dev_status,
    turn_payload,
)


class RecordingTransport:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def send(self, payload: dict) -> None:
        self.sent.append(payload)

    def request_status(self) -> dict:
        raise AssertionError("status was not requested")


class LanPlanTests(unittest.TestCase):
    def test_single_color_has_no_fallback_note(self) -> None:
        chosen, note = lan_color_plan((WARM_WHITE,))
        self.assertEqual(chosen, WARM_WHITE)
        self.assertIsNone(note)

    def test_mixed_pattern_keeps_only_the_first_color(self) -> None:
        chosen, note = lan_color_plan(CHRISTMAS)
        self.assertEqual(chosen, RED)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("colorwc", note)
        self.assertIn("https://app-h5.govee.com/user-manual/wlan-guide", note)
        self.assertIn(str(RED), note)
        self.assertNotIn("set_segment_rgb", note)

    def test_colorwc_json_matches_the_lan_guide(self) -> None:
        self.assertEqual(
            colorwc_payload((0, 12, 8)),
            {
                "msg": {
                    "cmd": "colorwc",
                    "data": {"color": {"r": 0, "g": 12, "b": 8}, "colorTemInKelvin": 0},
                }
            },
        )
        self.assertEqual(turn_payload(True), {"msg": {"cmd": "turn", "data": {"value": 1}}})
        self.assertEqual(turn_payload(False), {"msg": {"cmd": "turn", "data": {"value": 0}}})
        self.assertEqual(brightness_payload(20), {"msg": {"cmd": "brightness", "data": {"value": 20}}})

    def test_brightness_rejects_zero(self) -> None:
        with self.assertRaises(ValueError):
            brightness_payload(0)

    def test_backend_sends_first_color_for_christmas(self) -> None:
        transport = RecordingTransport()
        backend = LanBackend("192.168.1.100", transport=transport, retries=1, retry_delay=0)

        async def run() -> None:
            result = await backend.apply_pattern(CHRISTMAS)

            self.assertEqual(result.colors_sent, (RED,))
            self.assertEqual(result.mode, "lan_colorwc_whole_device")
            self.assertEqual(transport.sent, [colorwc_payload(RED)])
            self.assertIn(LAN_MIXED_NOTE.split("{")[0], result.note or "")

        import asyncio

        asyncio.run(run())

    def test_parse_dev_status(self) -> None:
        status = parse_dev_status(
            {
                "msg": {
                    "cmd": "devStatus",
                    "data": {
                        "onOff": 1,
                        "brightness": 100,
                        "color": {"r": 255, "g": 0, "b": 0},
                        "colorTemInKelvin": 0,
                    },
                }
            }
        )
        self.assertIsNotNone(status)
        assert status is not None
        self.assertTrue(status.is_on)
        self.assertEqual(status.brightness, 100)
        self.assertEqual(status.rgb, (255, 0, 0))
        self.assertIsNone(parse_dev_status({"msg": {"cmd": "scan", "data": {"ip": "192.168.1.100"}}}))


class UdpTests(unittest.TestCase):
    def test_unicast_control_and_status_reply(self) -> None:
        seen: list[dict] = []
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            server.bind(("127.0.0.1", CONTROL_PORT))
        except OSError as exc:
            server.close()
            self.skipTest(f"UDP port {CONTROL_PORT} is unavailable: {exc}")
        server.settimeout(3)

        def serve() -> None:
            try:
                while True:
                    raw, addr = server.recvfrom(4096)
                    message = json.loads(raw.decode("utf-8"))
                    seen.append(message)
                    if message["msg"]["cmd"] == "devStatus":
                        reply = {
                            "msg": {
                                "cmd": "devStatus",
                                "data": {
                                    "onOff": 0,
                                    "brightness": 40,
                                    "color": {"r": 9, "g": 8, "b": 7},
                                    "colorTemInKelvin": 2700,
                                },
                            }
                        }
                        server.sendto(json.dumps(reply).encode("utf-8"), addr)
                        return
            except socket.timeout:
                return
            finally:
                server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        transport = UdpLanTransport("127.0.0.1", timeout=0.4)
        try:
            transport.open()
        except Exception as exc:
            thread.join(timeout=3)
            self.skipTest(f"could not open LAN socket: {exc}")
        try:
            transport.send(turn_payload(True))
            message = transport.request_status()
        finally:
            transport.close()
            thread.join(timeout=3)
        self.assertEqual(seen[0]["msg"]["cmd"], "turn")
        self.assertEqual(seen[0]["msg"]["data"]["value"], 1)
        parsed = parse_dev_status(message)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertFalse(parsed.is_on)
        self.assertEqual(parsed.brightness, 40)
        self.assertEqual(parsed.color_temp_kelvin, 2700)


if __name__ == "__main__":
    unittest.main()
