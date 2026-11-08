import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from house_lights.schedule import is_night, sun_events

# A Chicago-area coordinate used only as a sun-math fixture. It is not a
# stored home address. The daemon requires the caller to pass lat/lon.
FIXTURE_LAT = 41.8781
FIXTURE_LON = -87.6298
TZ = "America/Chicago"


class SunTests(unittest.TestCase):
    def test_night_is_sunset_until_sunrise(self) -> None:
        day = datetime(2026, 7, 4).date()
        events = sun_events(FIXTURE_LAT, FIXTURE_LON, day, TZ)
        zone = ZoneInfo(TZ)
        before_sunset = events.sunset - timedelta(minutes=1)
        after_sunset = events.sunset + timedelta(minutes=1)
        before_sunrise = events.sunrise - timedelta(minutes=1)
        after_sunrise = events.sunrise + timedelta(minutes=1)
        self.assertFalse(is_night(before_sunset, FIXTURE_LAT, FIXTURE_LON, TZ))
        self.assertTrue(is_night(after_sunset, FIXTURE_LAT, FIXTURE_LON, TZ))
        self.assertTrue(is_night(before_sunrise, FIXTURE_LAT, FIXTURE_LON, TZ))
        self.assertFalse(is_night(after_sunrise, FIXTURE_LAT, FIXTURE_LON, TZ))
        noon = datetime(2026, 7, 4, 12, 0, tzinfo=zone)
        self.assertFalse(is_night(noon, FIXTURE_LAT, FIXTURE_LON, TZ))


if __name__ == "__main__":
    unittest.main()
