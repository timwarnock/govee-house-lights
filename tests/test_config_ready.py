import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "contrib" / "config_ready.py"

COMPLETE = {
    "backend": "bluetooth",
    "lat": 1,
    "lon": 2,
    "timezone": "America/Chicago",
    "sku": "H706C",
    "timeout": 8,
    "retries": 3,
    "retry_delay": 1.0,
}


class ConfigReadyTests(unittest.TestCase):
    def test_repo_config_is_complete(self) -> None:
        result = _run(ROOT / "config.json")
        self.assertEqual(result.returncode, 0, result.stderr.strip() or "config.json is missing")

    def test_complete_bluetooth_config_is_ready(self) -> None:
        self.assertEqual(_run(_write(COMPLETE)).returncode, 0)

    def test_lan_needs_an_address(self) -> None:
        data = dict(COMPLETE, backend="lan")
        result = _run(_write(data))
        self.assertEqual(result.returncode, 1)
        self.assertIn("ip", result.stderr)
        data["ip"] = "192.168.1.100"
        self.assertEqual(_run(_write(data)).returncode, 0)

    def test_missing_timezone_is_not_ready(self) -> None:
        data = dict(COMPLETE)
        del data["timezone"]
        result = _run(_write(data))
        self.assertEqual(result.returncode, 1)
        self.assertIn("timezone", result.stderr)

    def test_missing_file(self) -> None:
        result = _run(Path(tempfile.gettempdir()) / "house-lights-missing-config-does-not-exist.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not found", result.stderr)


def _write(data: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    with handle:
        json.dump(data, handle)
    return Path(handle.name)


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
