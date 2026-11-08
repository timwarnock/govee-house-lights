import tempfile
import unittest
from pathlib import Path

from house_lights.ble_store import load, save


class BleStoreTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "ble.json"
            self.assertIsNone(load(path))
            save(path, "AA:BB:CC:DD:EE:FF", "H706C")
            saved = load(path)
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.address, "AA:BB:CC:DD:EE:FF")
            self.assertEqual(saved.sku, "H706C")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
