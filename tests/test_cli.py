import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from house_lights.cli import build_parser, main
from house_lights.settings import UsageError, normalize_ble_address, settings_from_namespace


class CliTests(unittest.TestCase):
    def test_preview_reads_a_desired_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "holidays.yaml").write_text(
                "\n".join([
                    "- name: Fixture Day",
                    "  month: 7",
                    "  day: 4",
                    "  colors:",
                    "    - [255, 0, 0]",
                    "    - [255, 255, 255]",
                    "    - [0, 0, 255]",
                    "",
                ]),
                encoding="utf-8",
            )
            text = _preview(["preview", "--desired-state", str(root), "--date", "2026-07-04"])
        self.assertIn("Fixture Day", text)
        self.assertIn("red (255, 0, 0)", text)
        self.assertIn("white (255, 255, 255)", text)
        self.assertIn("blue (0, 0, 255)", text)
        self.assertIn("repeating sequence", text)

    def test_repo_desired_state_preview(self) -> None:
        text = _preview(["preview", "--date", "2026-03-03"])
        self.assertIn("pattern:", text)
        self.assertIn("colors:", text)

    def test_daemon_requires_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "backend": "lan",
                        "ip": "192.168.1.100",
                        "timezone": "America/Chicago",
                        "sku": "H706C",
                        "timeout": 8,
                        "retries": 3,
                        "retry_delay": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as caught:
                main(["daemon", "--config", str(path)])
            self.assertEqual(caught.exception.code, 2)

    def test_lan_requires_an_address(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            main(["status", "--backend", "lan"])
        self.assertEqual(caught.exception.code, 2)

    def test_defaults_and_flag_override(self) -> None:
        args = build_parser().parse_args(["preview", "--date", "2026-07-04"])
        settings = settings_from_namespace(args)
        self.assertIsNone(settings.ip)
        self.assertEqual(settings.timezone, "America/Chicago")
        self.assertEqual(settings.sku, "H706C")
        self.assertIsNone(settings.ble_address)
        self.assertIsNone(settings.brightness)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lights.json"
            path.write_text(
                json.dumps({"backend": "lan", "ip": "10.1.1.1", "lat": 1, "lon": 2}),
                encoding="utf-8",
            )
            flagged = build_parser().parse_args(
                ["status", "--config", str(path), "--ip", "10.2.2.2", "--backend", "bluetooth", "--brightness", "40"]
            )
            merged = settings_from_namespace(flagged)
        self.assertEqual(merged.ip, "10.2.2.2")
        self.assertEqual(merged.backend, "bluetooth")
        self.assertEqual(merged.brightness, 40)
        self.assertEqual(merged.lat, 1.0)
        self.assertEqual(merged.lon, 2.0)

    def test_desired_state_flag_selects_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chosen = Path(tmp) / "lights"
            flagged = settings_from_namespace(
                build_parser().parse_args(["preview", "--desired-state", str(chosen), "--date", "2026-07-04"])
            )
        self.assertEqual(flagged.desired_state_dir, chosen)

    def test_ble_address_normalizes_dashes(self) -> None:
        self.assertEqual(normalize_ble_address("aa-bb-cc-dd-ee-ff"), "AA:BB:CC:DD:EE:FF")
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
