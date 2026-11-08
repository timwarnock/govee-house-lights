import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "contrib" / "config_ready.py"


class ConfigReadyTests(unittest.TestCase):
    def test_example_is_not_ready(self) -> None:
        result = _run(ROOT / "config.example.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("lat", result.stderr)

    def test_bluetooth_with_coordinates_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({"backend": "bluetooth", "lat": 1, "lon": 2}),
                encoding="utf-8",
            )
            self.assertEqual(_run(path).returncode, 0)

    def test_lan_needs_an_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({"backend": "lan", "lat": 1, "lon": 2}),
                encoding="utf-8",
            )
            result = _run(path)
            self.assertEqual(result.returncode, 1)
            self.assertIn("ip", result.stderr)
            path.write_text(
                json.dumps({"backend": "lan", "lat": 1, "lon": 2, "ip": "192.168.1.100"}),
                encoding="utf-8",
            )
            self.assertEqual(_run(path).returncode, 0)


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
