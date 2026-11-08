import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from house_lights.backend import ApplyResult
from house_lights.daemon import load_edge, run_daemon, save_edge, sleep_until
from house_lights.plan import Declaration, Planner

FIXTURE_LAT = 41.8781
FIXTURE_LON = -87.6298
TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
RWB = ((255, 0, 0), (255, 255, 255))
WHITE = ((255, 255, 255),)


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


class FakeBackend:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.fail = False

    async def open(self) -> None:
        self.events.append("open")

    async def close(self) -> None:
        self.events.append("close")

    async def turn_on(self) -> None:
        self.events.append("on")
        if self.fail:
            raise RuntimeError("radio")

    async def turn_off(self) -> None:
        self.events.append("off")

    async def set_brightness(self, percent: int) -> None:
        self.events.append(("brightness", percent))

    async def apply_pattern(self, colors) -> ApplyResult:
        self.events.append(("pattern", tuple(colors)))
        return ApplyResult(mode="fake", colors_sent=tuple(colors))

    async def status(self):
        self.events.append("status")
        return None


class DaemonTests(unittest.TestCase):
    def test_sunset_applies_once_and_a_restart_leaves_it(self) -> None:
        planner, state = _setup()
        moment = planner.sunset(datetime(2026, 7, 4).date()) + timedelta(minutes=30)
        backend = FakeBackend()
        _run(planner, backend, state, moment)
        self.assertEqual(
            backend.events,
            ["open", "on", ("brightness", 40), ("pattern", RWB), "close"],
        )
        self.assertEqual(load_edge(state), "sunset:2026-07-04")

        again = FakeBackend()
        _run(planner, again, state, moment)
        self.assertEqual(again.events, [])

    def test_a_failed_send_does_not_count_as_succeeded(self) -> None:
        planner, state = _setup()
        moment = planner.sunset(datetime(2026, 7, 4).date()) + timedelta(minutes=30)
        backend = FakeBackend()
        backend.fail = True
        _run(planner, backend, state, moment)
        self.assertEqual(backend.events, ["open", "on", "close"])
        self.assertIsNone(load_edge(state))

    def test_sunrise_turns_the_lights_off(self) -> None:
        planner, state = _setup()
        moment = datetime(2026, 7, 4, 12, tzinfo=ZONE)
        backend = FakeBackend()
        _run(planner, backend, state, moment)
        self.assertEqual(backend.events, ["open", "off", "close"])
        self.assertEqual(load_edge(state), "sunrise:2026-07-04")

    def test_midnight_after_a_succeeded_sunset_sends_colors_only(self) -> None:
        planner, state = _setup()
        save_edge(state, "sunset:2026-12-24")
        moment = datetime(2026, 12, 25, 0, 10, tzinfo=ZONE)
        backend = FakeBackend()
        _run(planner, backend, state, moment)
        self.assertEqual(backend.events, ["open", ("brightness", 40), ("pattern", WHITE), "close"])

    def test_a_missed_sunset_still_turns_the_night_on(self) -> None:
        planner, state = _setup()
        moment = datetime(2026, 12, 25, 0, 10, tzinfo=ZONE)
        backend = FakeBackend()
        _run(planner, backend, state, moment)
        self.assertEqual(
            backend.events,
            ["open", "on", ("brightness", 40), ("pattern", WHITE), "close"],
        )

    def test_enforce_waits_until_its_interval(self) -> None:
        planner, state = _setup()
        noon = datetime(2026, 7, 4, 12, tzinfo=ZONE)
        edge = planner.current_edge(noon)
        assert edge is not None
        save_edge(state, edge.ident)
        clock = Clock(noon)
        stop = asyncio.Event()
        backend = FakeBackend()
        sleeps = {"n": 0}

        async def sleep(seconds: float) -> bool:
            sleeps["n"] += 1
            clock.advance(seconds)
            if sleeps["n"] >= 4:
                stop.set()
                return True
            return False

        asyncio.run(
            run_daemon(
                backend,
                planner,
                state_path=state,
                stop=stop,
                now=clock,
                sleep=sleep,
                enforce_minutes=1,
                slice_seconds=30,
            )
        )
        self.assertIn("off", backend.events)
        self.assertGreaterEqual(clock.moment, noon + timedelta(minutes=1))

    def test_sleep_until_notices_a_wall_clock_jump(self) -> None:
        start = datetime(2026, 7, 4, 12, tzinfo=ZONE)
        clock = Clock(start)

        async def jump(seconds: float) -> bool:
            clock.advance(seconds + 3600)
            return False

        asyncio.run(
            sleep_until(
                start + timedelta(hours=5),
                now=clock,
                sleep=jump,
                stop=asyncio.Event(),
                slice_seconds=30,
            )
        )
        self.assertGreaterEqual(clock.moment, start + timedelta(hours=5))


def _setup() -> tuple[Planner, Path]:
    root = Path(tempfile.mkdtemp())
    (root / "holidays.yaml").write_text(
        "\n".join([
            "- name: Sample",
            "  month: 7",
            "  day: 4",
            "  colors:",
            "    - [255, 0, 0]",
            "    - [255, 255, 255]",
            "- name: Christmas",
            "  month: 12",
            "  day: 25",
            "  midnight: true",
            "  colors:",
            "    - [255, 255, 255]",
        ]),
        encoding="utf-8",
    )
    (root / "seasons.yaml").write_text(
        "\n".join([
            "- name: Christmas season",
            "  start: {month: 12, day: 24}",
            "  end: {month: 12, day: 26}",
            "  colors:",
            "    - [9, 0, 0]",
        ]),
        encoding="utf-8",
    )
    (root / "default.yaml").write_text(
        "brightness: 40\ncolors:\n  - [255, 197, 143]\n",
        encoding="utf-8",
    )
    return Planner(Declaration.load(root), FIXTURE_LAT, FIXTURE_LON, TZ), root / "edge.json"


def _run(planner: Planner, backend: FakeBackend, state: Path, moment: datetime) -> None:
    stop = asyncio.Event()

    async def sleep(_seconds: float) -> bool:
        stop.set()
        return True

    asyncio.run(
        run_daemon(
            backend,
            planner,
            state_path=state,
            stop=stop,
            now=lambda: moment,
            sleep=sleep,
        )
    )


if __name__ == "__main__":
    unittest.main()
