import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from house_lights.cli import build_parser, main
from house_lights.settings import UsageError, normalize_ble_address, settings_from_namespace


class CliTests(unittest.TestCase):
    def test_preview_independence_day(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["preview", "--date", "2026-07-04"])
        text = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Independence Day", text)
        self.assertIn("red (255, 0, 0)", text)
        self.assertIn("white (255, 255, 255)", text)
        self.assertIn("blue (0, 0, 255)", text)
        self.assertIn("repeating sequence", text)

    def test_preview_christmas_and_new_year_and_default(self) -> None:
        christmas = _preview(["preview", "--date", "2026-12-25"])
        self.assertIn("Classic Christmas", christmas)
        self.assertIn("orange/yellow", christmas)
        self.assertIn("blue", christmas)
        new_year = _preview(["preview", "--date", "2026-12-31"])
        self.assertIn("New Year's", new_year)
        self.assertIn("gold", new_year)
        self.assertIn("white", new_year)
        plain = _preview(["preview", "--date", "2026-03-03"])
        self.assertIn("Default night", plain)
        self.assertIn("warm white", plain)

    def test_run_requires_coordinates(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main(["run", "--backend", "lan"])
        self.assertEqual(caught.exception.code, 2)

    def test_defaults_and_flag_override(self) -> None:
        args = build_parser().parse_args(["preview", "--date", "2026-07-04"])
        settings = settings_from_namespace(args)
        self.assertEqual(settings.ip, "192.168.0.119")
        self.assertEqual(settings.timezone, "America/Chicago")
        self.assertEqual(settings.sku, "H706C")
        self.assertIsNone(settings.ble_address)
        self.assertEqual(settings.brightness, 70)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lights.json"
            path.write_text(
                json.dumps({"backend": "lan", "ip": "10.1.1.1", "brightness": 15, "lat": 1, "lon": 2}),
                encoding="utf-8",
            )
            flagged = build_parser().parse_args(
                ["status", "--config", str(path), "--ip", "192.168.0.50", "--backend", "bluetooth"]
            )
            merged = settings_from_namespace(flagged)
        self.assertEqual(merged.ip, "192.168.0.50")
        self.assertEqual(merged.backend, "bluetooth")
        self.assertEqual(merged.brightness, 15)
        self.assertEqual(merged.lat, 1.0)
        self.assertEqual(merged.lon, 2.0)

    def test_ble_address_normalizes_dashes(self) -> None:
        self.assertEqual(normalize_ble_address("d4-13-68-b6-d3-92"), "D4:13:68:B6:D3:92")
        with self.assertRaises(UsageError):
            normalize_ble_address("not-a-mac")

    def test_preview_with_coordinates_prints_sun(self) -> None:
        text = _preview(
            ["preview", "--date", "2026-07-04", "--lat", "41.8781", "--lon", "-87.6298"]
        )
        self.assertIn("sunset:", text)
        self.assertIn("sunrise:", text)
        self.assertIn("America/Chicago", text)


def _preview(argv: list[str]) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    if code != 0:
        raise AssertionError(code)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
