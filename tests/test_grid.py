import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from govee_ble_local.wire.parse import multi_unit_comm

from house_lights.backend import ApplyResult, GridResult
from house_lights.bluetooth import BluetoothBackend
from house_lights.cli import _paint, main
from house_lights.grid import (
    LIGHT_COUNT,
    expand_lights,
    finger_sketch_value,
    load_grid,
    sketch_frames,
)
from house_lights.holidays import BLUE, RED, WHITE
from house_lights.settings import Settings


RWB = (RED, WHITE, BLUE)


class GridFileTests(unittest.TestCase):
    def test_example_repeats_red_white_blue(self) -> None:
        path = Path(__file__).resolve().parents[1] / "grids" / "rwb.json"
        colors, source_count = load_grid(path)
        self.assertEqual(source_count, 3)
        self.assertEqual(len(colors), LIGHT_COUNT)
        self.assertEqual(colors[:6], RWB + RWB)
        self.assertEqual(colors[0::3], (RED,) * 40)

    def test_full_list_names_and_hex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            lights = ["#ff0000", "white", [0, 0, 255]] * 40
            path.write_text(json.dumps(lights), encoding="utf-8")
            colors, source_count = load_grid(path)
        self.assertEqual(source_count, LIGHT_COUNT)
        self.assertEqual(colors[:3], RWB)

    def test_length_must_divide_120(self) -> None:
        with self.assertRaises(ValueError):
            expand_lights([(0, 0, 0)] * 7)
        with self.assertRaises(ValueError):
            expand_lights([(0, 0, 0)] * 121)

    def test_bad_json_names_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                load_grid(path)
        self.assertIn("grid.json", str(caught.exception))


class FingerSketchTests(unittest.TestCase):
    def test_rwb_picture_lists_every_bulb(self) -> None:
        colors = expand_lights(RWB)
        value = finger_sketch_value(colors, brightness=100)
        self.assertEqual(value[:7], bytes((0x0F, 0x00, 100, 255, 0, 0, 3)))
        self.assertEqual(len(value), 7 + 3 * (1 + 3 + 40))
        red, white, blue = _groups_from(value)
        self.assertEqual(red[0], RED)
        self.assertEqual(red[1], list(range(0, 120, 3)))
        self.assertEqual(white[0], WHITE)
        self.assertEqual(white[1], list(range(1, 120, 3)))
        self.assertEqual(blue[0], BLUE)
        self.assertEqual(blue[1], list(range(2, 120, 3)))

    def test_background_is_the_most_common_color_and_its_bulbs_stay_listed(self) -> None:
        colors = expand_lights((WHITE, WHITE, RED))
        value = finger_sketch_value(colors, brightness=100)
        self.assertEqual(value[3:6], bytes(WHITE))
        self.assertEqual(value[6], 2)
        white, red = _groups_from(value)
        self.assertEqual(len(white[1]), 80)
        self.assertEqual(white[1][0], 0)
        self.assertEqual(len(red[1]), 40)

    def test_one_color_lists_bulb_zero(self) -> None:
        value = finger_sketch_value((RED,) * LIGHT_COUNT, brightness=70)
        groups = _groups_from(value)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], RED)
        self.assertIn(0, groups[0][1])
        self.assertEqual(len(groups[0][1]), LIGHT_COUNT)

    def test_index_at_or_above_256_is_a_little_endian_short(self) -> None:
        colors = [(0, 0, 0)] * 256 + [(1, 2, 3)]
        value = finger_sketch_value(colors, brightness=1)
        tail = (1).to_bytes(2, "little") + bytes((1, 2, 3)) + (1).to_bytes(2, "little")
        tail += (256).to_bytes(2, "little")
        self.assertTrue(value.endswith(tail))

    def test_upload_frames_and_show_packet(self) -> None:
        frames, show = sketch_frames(expand_lights(RWB), brightness=100)
        self.assertEqual(len(frames), 9)
        self.assertTrue(all(len(frame) == 20 for frame in frames))
        self.assertEqual(frames[0][0], 0xA3)
        self.assertEqual(frames[0][1], 0x00)
        self.assertEqual(frames[-1][1], 0xFF)
        self.assertEqual(multi_unit_comm(frames[0]), 0x03)
        self.assertEqual(show[:5], bytes.fromhex("33050a2003"))
        self.assertEqual(len(show), 20)


class PaintSendTests(unittest.TestCase):
    def test_bluetooth_sends_upload_then_show_under_one_hold(self) -> None:
        device = _SketchDevice()
        backend = BluetoothBackend(_settings(), device_factory=lambda *a, **k: device)
        backend._device = device
        result = asyncio.run(backend.apply_grid(expand_lights(RWB), brightness=100))
        self.assertEqual(result.mode, "ble_finger_sketch")
        self.assertEqual(result.light_count, 120)
        self.assertEqual(result.group_count, 3)
        self.assertEqual(result.upload_packets, 9)
        self.assertEqual([call[0] for call in device.conn.calls], ["upload", "show"])
        upload, show = device.conn.calls
        self.assertEqual(upload[2].comm, 0x03)
        self.assertEqual(upload[2].status_at, 2)
        self.assertEqual(show[1][:5], bytes.fromhex("33050a2003"))
        self.assertEqual(device.conn.held_during, [1, 1])
        self.assertEqual(device.conn.held, 0)

    def test_failed_sketch_restores_segment_pattern(self) -> None:
        backend = _FakePaint(fail=True)
        code = asyncio.run(_paint(backend, _settings(brightness=100), expand_lights(RWB), 3))
        self.assertEqual(code, 1)
        self.assertEqual(backend.calls[0], "on")
        self.assertEqual(backend.calls[1], ("bri", 100))
        self.assertEqual(backend.calls[2][0], "grid")
        self.assertEqual(backend.calls[3][0], "pattern")
        self.assertEqual(backend.calls[3][1], RWB)


def _groups_from(value: bytes) -> list[tuple[tuple[int, int, int], list[int]]]:
    """Parse the one-byte DiyGraffitiV2 form used for this 120-light string."""
    count = value[6]
    groups = []
    offset = 7
    for _ in range(count):
        bulbs = value[offset]
        rgb = (value[offset + 1], value[offset + 2], value[offset + 3])
        start = offset + 4
        groups.append((rgb, list(value[start:start + bulbs])))
        offset = start + bulbs
    return groups


class _Hold:
    def __init__(self, conn: "_Conn") -> None:
        self.conn = conn

    def __enter__(self) -> None:
        self.conn.held += 1

    def __exit__(self, *args: object) -> None:
        self.conn.held -= 1


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.held = 0
        self.held_during: list[int] = []

    def hold_heartbeat(self) -> _Hold:
        return _Hold(self)

    async def send_unacked(self, frames: list[bytes], unit: object = None) -> None:
        self.held_during.append(self.held)
        self.calls.append(("upload", list(frames), unit))

    async def send(self, frame: bytes, **kwargs: object) -> bytes:
        self.held_during.append(self.held)
        self.calls.append(("show", frame))
        return frame


class _SketchDevice:
    def __init__(self) -> None:
        self.conn = _Conn()
        self._conn = self.conn
        self._state = type("State", (), {"hardware_version": None})()


class _FakePaint:
    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.calls: list[object] = []

    async def turn_on(self) -> None:
        self.calls.append("on")

    async def set_brightness(self, percent: int) -> None:
        self.calls.append(("bri", percent))

    async def apply_grid(self, colors: tuple, *, brightness: int) -> GridResult:
        self.calls.append(("grid", len(colors), brightness))
        if self.fail:
            raise RuntimeError("no ack")
        return GridResult(
            mode="ble_finger_sketch",
            light_count=len(colors),
            group_count=3,
            upload_packets=9,
            colors=RWB,
            note="sent",
        )

    async def apply_pattern(self, colors: tuple) -> ApplyResult:
        self.calls.append(("pattern", tuple(colors)))
        return ApplyResult(mode="ble_set_segment_rgb", colors_sent=tuple(colors))


def _settings(**overrides: object) -> Settings:
    data: dict[str, object] = dict(
        command="paint",
        backend="bluetooth",
        ip="192.168.0.119",
        ble_address=None,
        sku="H706C",
        lat=None,
        lon=None,
        timezone="America/Chicago",
        brightness=70,
        segments=None,
        timeout=0.2,
        retries=1,
        retry_delay=0.0,
        poll_interval=60.0,
        scan=False,
        ble_cache=Path("/tmp/house-lights-grid-ble.json"),
        when=None,
        config_path=None,
        grid=Path("/tmp/house-lights-grid.json"),
    )
    data.update(overrides)
    return Settings(**data)  # type: ignore[arg-type]


class CliGridTests(unittest.TestCase):
    def test_paint_requires_a_grid_file(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main(["paint", "--backend", "bluetooth"])
        self.assertEqual(caught.exception.code, 2)
        with self.assertRaises(SystemExit) as missing:
            main(["paint", "--grid", "/tmp/house-lights-no-such-grid.json"])
        self.assertEqual(missing.exception.code, 2)

    def test_bad_grid_does_not_open_a_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            path.write_text(json.dumps({"lights": [[0, 0, 0]] * 7}), encoding="utf-8")
            code = main(["paint", "--backend", "bluetooth", "--grid", str(path), "--retries", "1"])
        self.assertEqual(code, 1)


