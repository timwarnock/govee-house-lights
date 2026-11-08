import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contrib.make_config import config_from_ipinfo, create_config, place_line


class MakeConfigTests(unittest.TestCase):
    def test_ipinfo_fields_become_a_bluetooth_config(self) -> None:
        data = config_from_ipinfo(
            {
                "loc": "41.88,-87.63",
                "timezone": "America/Chicago",
                "city": "Chicago",
                "region": "Illinois",
                "country": "US",
                "ip": "203.0.113.5",
            }
        )
        self.assertEqual(data["backend"], "bluetooth")
        self.assertEqual(data["lat"], 41.88)
        self.assertEqual(data["lon"], -87.63)
        self.assertEqual(data["timezone"], "America/Chicago")
        self.assertEqual(data["sku"], "H706C")
        self.assertNotIn("ip", data)

    def test_place_line_uses_city_region_country(self) -> None:
        self.assertEqual(
            place_line({"city": "Chicago", "region": "Illinois", "country": "US"}),
            "Chicago, Illinois, US",
        )

    def test_existing_file_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"keep": true}\n', encoding="utf-8")

            def fetch() -> dict:
                raise AssertionError("ipinfo should not be called")

            self.assertEqual(create_config(path, fetch), 0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"keep": True})

    def test_failed_lookup_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"

            def fetch() -> dict:
                raise OSError("network down")

            self.assertEqual(create_config(path, fetch), 1)
            self.assertFalse(path.exists())

    def test_bad_loc_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"

            def fetch() -> dict:
                return {"loc": "nope", "timezone": "America/Chicago"}

            self.assertEqual(create_config(path, fetch), 1)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
