import unittest
from pathlib import Path


class NoCloudTests(unittest.TestCase):
    def test_sources_do_not_call_govee_cloud(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src"
        banned = (
            "openapi.api.govee.com",
            "developer.govee.com",
            "app.govee.com",
            "govee-ble-local[cloud]",
            "api_key",
            "api-key",
        )
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for needle in banned:
                self.assertNotIn(needle, text, f"{path.name} contains {needle}")


if __name__ == "__main__":
    unittest.main()
