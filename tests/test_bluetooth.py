import asyncio
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from bleak.backends.device import BLEDevice
from govee_ble_local import Capability, GoveeBleInvalidValue, create_device, profile_for
from govee_ble_local.wire import build

from house_lights.bluetooth import BluetoothBackend
from house_lights.settings import DEFAULT_BLE_CACHE, Settings
from house_lights.still import STILL_COMM, STILL_SCENE, still_scene_value

RED = (255, 0, 0)
WARM_WHITE = (255, 197, 143)
CHRISTMAS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 165, 0))


class FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def hold_heartbeat(self):
        return nullcontext()

    async def send_unacked(self, frames, unit=None) -> None:
        self.calls.append(("upload", frames, unit))

    async def send(self, frame: bytes) -> bytes:
        self.calls.append(("show", frame))
        return b""


def settings(tmp: Path, **overrides) -> Settings:
    data = dict(
        command="on",
        backend="bluetooth",
        ip="192.168.1.100",
        ble_address="AA:BB:CC:DD:EE:FF",
        sku="H706C",
        lat=None,
        lon=None,
        timezone="America/Chicago",
        brightness=70,
        timeout=0.2,
        retries=1,
        retry_delay=0.0,
        scan=False,
        ble_cache=tmp / "ble.json",
        when=None,
        config_path=None,
    )
    data.update(overrides)
    return Settings(**data)


class FakeDevice:
    def __init__(self, capabilities, count: int = 12) -> None:
        self.capabilities = capabilities
        self.segment_count = count
        self.segment_count_read_at = None
        self.calls: list[tuple] = []
        self._conn = FakeConn()
        self._state = SimpleNamespace(hardware_version=None)

    def set_segment_count(self, count: int) -> None:
        self.calls.append(("set_segment_count", count))
        self.segment_count = count

    async def set_rgb(self, rgb) -> None:
        self.calls.append(("set_rgb", rgb))

    async def set_segment_rgb(self, indices, rgb) -> None:
        self.calls.append(("set_segment_rgb", tuple(indices), rgb))

    async def update(self):
        self.calls.append(("update",))
        self.segment_count_read_at = 1.0
        self.segment_count = 4
        return SimpleNamespace(
            is_on=True,
            brightness=70,
            rgb_color=RED,
            color_temp_kelvin=None,
            segments=[1, 2, 3, 4],
            optimistic=False,
        )

    async def connect(self) -> None:
        self.calls.append(("connect",))

    async def stop(self) -> None:
        self.calls.append(("stop",))

    async def turn_on(self) -> None:
        self.calls.append(("turn_on",))


class BluetoothTests(unittest.TestCase):
    def test_mixed_pattern_uploads_a_still_scene(self) -> None:
        device = FakeDevice(frozenset({Capability.SEGMENTS}))
        backend = BluetoothBackend(settings(Path("/tmp")), device_factory=lambda *a, **k: device)
        backend._device = device

        result = asyncio.run(backend.apply_pattern(CHRISTMAS))

        self.assertEqual(result.mode, "ble_rgbic_still")
        self.assertEqual(result.colors_sent, CHRISTMAS)
        self.assertEqual(device.calls, [])
        upload, frames, unit = device._conn.calls[0]
        self.assertEqual(upload, "upload")
        self.assertEqual(unit.comm, STILL_COMM)
        self.assertEqual(frames, build.scene_upload_a3(still_scene_value(CHRISTMAS), STILL_COMM))
        kind, show = device._conn.calls[1]
        self.assertEqual(kind, "show")
        self.assertEqual(show, build.scene_activate(STILL_SCENE))

    def test_solid_pattern_uses_set_rgb(self) -> None:
        device = FakeDevice(frozenset({Capability.SEGMENTS}))
        backend = BluetoothBackend(settings(Path("/tmp")))
        backend._device = device
        result = asyncio.run(backend.apply_pattern((WARM_WHITE,)))
        self.assertEqual(result.mode, "ble_set_rgb")
        self.assertEqual(device.calls, [("set_rgb", WARM_WHITE)])

    def test_mixed_pattern_does_not_need_segments(self) -> None:
        device = FakeDevice(frozenset({Capability.RGB, Capability.POWER}))
        backend = BluetoothBackend(settings(Path("/tmp")))
        backend._device = device
        result = asyncio.run(backend.apply_pattern(CHRISTMAS))
        self.assertEqual(result.mode, "ble_rgbic_still")
        self.assertEqual(device.calls, [])
        self.assertEqual(device._conn.calls[0][0], "upload")

    def test_known_address_still_scans(self) -> None:
        created: dict = {}
        ble = BLEDevice("AA:BB:CC:DD:EE:FF", "Govee_H706C", {"path": "/org/bluez/hci0/dev_AA"})
        found = SimpleNamespace(
            sku="H706C",
            address="AA:BB:CC:DD:EE:FF",
            ble_device=ble,
            advertisement="adv",
        )

        def factory(ble_device, sku, advertisement, allow_modelled=False):
            created["ble"] = ble_device
            created["sku"] = sku
            created["adv"] = advertisement
            created["allow"] = allow_modelled
            return FakeDevice(frozenset({Capability.SEGMENTS}))

        async def discover(**kwargs):
            created["discover_timeout"] = kwargs.get("timeout")
            return [found]

        cache = Path("/tmp/house-lights-ble-test")
        cache.mkdir(exist_ok=True)
        backend = BluetoothBackend(
            settings(cache, ble_cache=cache / "ble.json", scan=False),
            device_factory=factory,
            discover_func=discover,
        )
        asyncio.run(backend.open())
        self.assertTrue(created["allow"])
        self.assertEqual(created["sku"], "H706C")
        self.assertEqual(created["adv"], "adv")
        self.assertIs(created["ble"], ble)
        self.assertEqual(created["discover_timeout"], 0.2)
        saved = (cache / "ble.json").read_text(encoding="utf-8")
        self.assertIn("AA:BB:CC:DD:EE:FF", saved)
        self.assertIn("H706C", saved)
        asyncio.run(backend.close())
        self.assertIsNone(backend._device)

    def test_default_cache_is_not_the_wifi_mac(self) -> None:
        self.assertEqual(DEFAULT_BLE_CACHE.name, "ble.json")

    def test_h706c_library_row_is_modelled_and_caps_segments(self) -> None:
        self.assertIsNone(profile_for("H706C"))
        profile = profile_for("H706C", allow_modelled=True)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertIn(Capability.SEGMENTS, profile.capabilities)
        self.assertEqual(profile.segments, 12)
        self.assertTrue(profile.special_info_read)
        device = create_device(BLEDevice("AA:BB:CC:DD:EE:FF", None, {}), "H706C", allow_modelled=True)
        self.assertEqual(device.segment_count, 12)
        with self.assertRaises(GoveeBleInvalidValue):
            device.set_segment_count(120)
        device.set_segment_count(8)
        self.assertEqual(device.segment_count, 8)


if __name__ == "__main__":
    unittest.main()
