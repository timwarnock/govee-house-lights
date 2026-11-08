import asyncio
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from house_lights.holidays import INDEPENDENCE, NEW_YEAR
from house_lights.schedule import NightRunner, is_night, sun_events

# A Chicago-area coordinate used only as a sun-math fixture. It is not a
# stored home address; `run` still requires the caller to pass lat/lon.
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


class FakeBackend:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def turn_on(self) -> None:
        self.events.append("on")

    async def turn_off(self) -> None:
        self.events.append("off")

    async def set_brightness(self, percent: int) -> None:
        self.events.append(("brightness", percent))

    async def apply_pattern(self, colors) -> object:
        self.events.append(("pattern", tuple(colors)))
        from house_lights.backend import ApplyResult

        return ApplyResult(mode="fake", colors_sent=tuple(colors))

    async def status(self):
        return None


class RunnerTests(unittest.TestCase):
    def test_july_fourth_evening_paints_red_white_blue(self) -> None:
        backend = FakeBackend()
        runner = NightRunner()
        now = datetime(2026, 7, 4, 21, 30, tzinfo=ZoneInfo(TZ))
        phase = asyncio.run(
            runner.apply_phase(
                backend,
                now=now,
                latitude=FIXTURE_LAT,
                longitude=FIXTURE_LON,
                timezone=TZ,
                brightness=55,
            )
        )
        self.assertEqual(phase, "night")
        self.assertEqual(backend.events[0], "on")
        self.assertEqual(backend.events[1], ("brightness", 55))
        self.assertEqual(backend.events[2], ("pattern", INDEPENDENCE.colors))

    def test_july_fourth_noon_turns_off(self) -> None:
        backend = FakeBackend()
        runner = NightRunner()
        now = datetime(2026, 7, 4, 12, 0, tzinfo=ZoneInfo(TZ))
        phase = asyncio.run(
            runner.apply_phase(
                backend,
                now=now,
                latitude=FIXTURE_LAT,
                longitude=FIXTURE_LON,
                timezone=TZ,
                brightness=55,
            )
        )
        self.assertEqual(phase, "day")
        self.assertEqual(backend.events, ["off"])

    def test_new_year_after_midnight_uses_that_civil_date(self) -> None:
        backend = FakeBackend()
        now = datetime(2027, 1, 1, 0, 30, tzinfo=ZoneInfo(TZ))
        phase = asyncio.run(
            NightRunner().apply_phase(
                backend,
                now=now,
                latitude=FIXTURE_LAT,
                longitude=FIXTURE_LON,
                timezone=TZ,
                brightness=40,
            )
        )
        self.assertEqual(phase, "night")
        self.assertEqual(backend.events[-1], ("pattern", NEW_YEAR.colors))

    def test_same_phase_is_not_sent_twice(self) -> None:
        backend = FakeBackend()
        runner = NightRunner()
        now = datetime(2026, 7, 4, 21, 30, tzinfo=ZoneInfo(TZ))
        kwargs = dict(
            now=now,
            latitude=FIXTURE_LAT,
            longitude=FIXTURE_LON,
            timezone=TZ,
            brightness=55,
        )

        async def twice() -> None:
            await runner.apply_phase(backend, **kwargs)
            await runner.apply_phase(backend, **kwargs)

        asyncio.run(twice())
        self.assertEqual(backend.events.count("on"), 1)


if __name__ == "__main__":
    unittest.main()
