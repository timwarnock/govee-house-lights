import calendar
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from house_lights.plan import Declaration, DeclarationError, Planner, easter_sunday

# A Chicago-area coordinate used only as a sun-math fixture.
FIXTURE_LAT = 41.8781
FIXTURE_LON = -87.6298
TZ = "America/Chicago"
ZONE = ZoneInfo(TZ)
WARM = (255, 197, 143)
SEASON = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 165, 0))
WHITE_GOLD = ((255, 255, 255), (255, 215, 0))
RWB = ((255, 0, 0), (255, 255, 255), (0, 0, 255))


class ComputusTests(unittest.TestCase):
    def test_easter_2026_matches_the_design_dates(self) -> None:
        easter = easter_sunday(2026)
        self.assertEqual(easter, date(2026, 4, 5))
        self.assertEqual(easter.weekday(), calendar.SUNDAY)
        self.assertEqual(easter + timedelta(days=-46), date(2026, 2, 18))
        self.assertEqual(easter + timedelta(days=-1), date(2026, 4, 4))
        self.assertEqual(easter + timedelta(days=1), date(2026, 4, 6))
        self.assertEqual(easter + timedelta(days=42), date(2026, 5, 17))
        self.assertEqual((easter + timedelta(days=42)).weekday(), calendar.SUNDAY)
        self.assertEqual(easter + timedelta(days=48), date(2026, 5, 23))
        self.assertEqual(easter + timedelta(days=49), date(2026, 5, 24))

    def test_nth_weekday_matches_the_calendar(self) -> None:
        self.assertEqual(_nth(2026, 2, calendar.MONDAY, 3), date(2026, 2, 16))
        self.assertEqual(_last(2026, 5, calendar.MONDAY), date(2026, 5, 25))
        self.assertEqual(_nth(2026, 10, calendar.MONDAY, 2), date(2026, 10, 12))
        self.assertEqual(_nth(2026, 11, calendar.THURSDAY, 4), date(2026, 11, 26))


class ScheduleBehaviorTests(unittest.TestCase):
    def test_christmas_windows_and_plain_nights(self) -> None:
        planner = _planner(_design())
        self.assertEqual(_sunset_colors(planner, date(2026, 12, 23)), (WARM,))
        self.assertEqual(_sunset_colors(planner, date(2026, 12, 24)), SEASON)
        self.assertEqual(planner.palette_at(_sunset(planner, date(2026, 12, 24))).source, "Christmas season")

        change = planner.midnight_boundary(date(2026, 12, 25))
        assert change is not None
        self.assertEqual(change.colors, WHITE_GOLD)
        self.assertEqual(change.source, "Christmas")
        self.assertEqual(_sunset_colors(planner, date(2026, 12, 25)), WHITE_GOLD)

        back = planner.midnight_boundary(date(2026, 12, 26))
        assert back is not None
        self.assertEqual(back.colors, SEASON)
        self.assertEqual(_sunset_colors(planner, date(2026, 12, 26)), SEASON)
        self.assertEqual(_sunset_colors(planner, date(2026, 12, 27)), (WARM,))
        self.assertEqual(_sunset_colors(planner, date(2026, 12, 31)), (WARM,))
        self.assertIsNone(planner.midnight_boundary(date(2027, 1, 1)))
        early = datetime(2027, 1, 1, 0, 30, tzinfo=ZONE)
        self.assertEqual(planner.palette_at(early).colors, (WARM,))
        self.assertEqual(planner.current_edge(early).ident, "sunset:2026-12-31")
        self.assertEqual(_sunset_colors(planner, date(2027, 1, 1)), WHITE_GOLD)

    def test_independence_day_has_no_prior_night(self) -> None:
        planner = _planner(_design())
        self.assertEqual(_sunset_colors(planner, date(2026, 7, 3)), (WARM,))
        self.assertEqual(_sunset_colors(planner, date(2026, 7, 4)), RWB)
        self.assertIsNone(planner.midnight_boundary(date(2026, 7, 5)))
        early = planner.sunrise(date(2026, 7, 5)) - timedelta(minutes=30)
        self.assertEqual(planner.palette_at(early).source, "Independence Day")
        self.assertEqual(planner.current_edge(early).kind, "sunset")

    def test_easter_prior_night_has_no_midnight_cut(self) -> None:
        planner = _planner(_design())
        saturday = date(2026, 4, 4)
        sunday = date(2026, 4, 5)
        monday = date(2026, 4, 6)
        self.assertEqual(planner.palette_at(_noon(saturday)).source, "Lent")
        self.assertEqual(planner.palette_at(_sunset(planner, saturday)).source, "Easter")
        self.assertIsNone(planner.midnight_boundary(sunday))
        vigil = datetime(2026, 4, 5, 0, 30, tzinfo=ZONE)
        self.assertEqual(planner.palette_at(vigil).colors, WHITE_GOLD)
        self.assertEqual(planner.current_edge(vigil).ident, "sunset:2026-04-04")
        self.assertEqual(_sunset_colors(planner, sunday), WHITE_GOLD)
        self.assertIsNone(planner.midnight_boundary(monday))
        still_night = planner.sunrise(monday) - timedelta(minutes=20)
        self.assertEqual(planner.palette_at(still_night).source, "Easter")
        self.assertEqual(planner.current_edge(_noon(monday)).kind, "sunrise")

    def test_a_holiday_beats_a_season(self) -> None:
        planner = _planner(_design())
        self.assertEqual(planner.palette_at(_sunset(planner, date(2026, 3, 17))).source, "St. Patrick")

    def test_movable_row_order_decides_a_shared_date(self) -> None:
        shared = next(year for year in range(2000, 2100) if easter_sunday(year) == date(year, 3, 27))
        good_friday = date(shared, 3, 25)
        first = _planner(_two("Good Friday", "Annunciation", good_friday.year))
        self.assertEqual(first.palette_at(_sunset(first, good_friday)).source, "Good Friday")
        reversed_rows = _planner(_two("Annunciation", "Good Friday", good_friday.year))
        self.assertEqual(
            reversed_rows.palette_at(_sunset(reversed_rows, good_friday)).source,
            "Annunciation",
        )

    def test_day_files_beat_holidays_until_sunrise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root,
                holidays=[{
                    "name": "Independence Day",
                    "month": 7,
                    "day": 4,
                    "colors": [list(RWB[0])],
                }],
                days={
                    "2026-07-04.yaml": {"colors": [[0, 255, 0]], "description": "one year"},
                    "every-07-04.yaml": {"colors": [[0, 0, 255]]},
                },
            )
            planner = _planner(root)
            sunset = _sunset(planner, date(2026, 7, 4))
            self.assertEqual(planner.palette_at(sunset).colors, ((0, 255, 0),))
            early = planner.sunrise(date(2026, 7, 5)) - timedelta(minutes=15)
            self.assertEqual(planner.palette_at(early).source, "days/2026-07-04.yaml")

    def test_every_file_covers_that_night_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, days={"every-07-04.yaml": {"colors": [[0, 0, 1]]}})
            planner = _planner(root)
            self.assertEqual(_sunset_colors(planner, date(2026, 7, 4)), ((0, 0, 1),))
            self.assertEqual(_sunset_colors(planner, date(2026, 7, 3)), (WARM,))

    def test_missing_default_sends_no_color_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, default=None)
            planner = _planner(root)
            palette = planner.palette_at(_sunset(planner, date(2026, 3, 3)))
            self.assertIsNone(palette.colors)
            self.assertEqual(palette.source, "none")

    def test_both_flags_skip_the_middle_midnight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, holidays=[{
                "name": "Both",
                "month": 7,
                "day": 4,
                "prior_night": True,
                "midnight": True,
                "colors": [[1, 2, 3]],
            }])
            planner = _planner(root)
            self.assertEqual(planner.palette_at(_sunset(planner, date(2026, 7, 3))).source, "Both")
            self.assertIsNone(planner.midnight_boundary(date(2026, 7, 4)))
            end = planner.midnight_boundary(date(2026, 7, 5))
            assert end is not None
            self.assertEqual(end.colors, (WARM,))

    def test_a_wrapping_season_covers_january(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, seasons=[{
                "name": "Wrap",
                "start": {"month": 12, "day": 1},
                "end": {"month": 1, "day": 5},
                "colors": [[4, 5, 6]],
            }])
            declaration = Declaration.load(root)
            self.assertEqual(declaration.on_date(date(2026, 12, 20)).source, "Wrap")
            self.assertEqual(declaration.on_date(date(2026, 1, 3)).source, "Wrap")
            self.assertEqual(declaration.on_date(date(2026, 6, 1)).source, "default")

    def test_default_brightness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "default.yaml").write_text("brightness: 40\ncolors: [[1, 2, 3]]\n", encoding="utf-8")
            self.assertEqual(Declaration.load(root).brightness, 40)
            (root / "default.yaml").write_text("colors: [[1, 2, 3]]\n", encoding="utf-8")
            self.assertEqual(Declaration.load(root).brightness, 70)
            (root / "default.yaml").write_text("brightness: 0\ncolors: [[1, 2, 3]]\n", encoding="utf-8")
            with self.assertRaises(DeclarationError):
                Declaration.load(root)

    def test_bad_files_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            (root / "default.yaml").write_text("colors: [[256, 0, 0]]\n", encoding="utf-8")
            with self.assertRaises(DeclarationError):
                Declaration.load(root)
            (root / "default.yaml").write_text("note: hi\ncolors: [[1, 2, 3]]\n", encoding="utf-8")
            with self.assertRaises(DeclarationError):
                Declaration.load(root)
            (root / "default.yaml").write_text("colors: [[1, 2, 3]]\n", encoding="utf-8")
            days = root / "days"
            days.mkdir()
            (days / "nope.yaml").write_text("colors: [[1, 2, 3]]\n", encoding="utf-8")
            with self.assertRaises(DeclarationError):
                Declaration.load(root)
            (days / "nope.yaml").unlink()
            (root / "holidays.yaml").write_text("[\n", encoding="utf-8")
            with self.assertRaises(DeclarationError):
                Declaration.load(root)

    def test_palette_longer_than_the_still_scene_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            colors = [[index, 0, 0] for index in range(78)]
            _write(root, default=colors)
            with self.assertRaises(DeclarationError):
                Declaration.load(root)


class ShippedLightsTests(unittest.TestCase):
    def test_repo_desired_state_resolves_a_full_year(self) -> None:
        declaration = Declaration.load(Path(__file__).resolve().parents[1] / "desired-state")
        planner = Planner(declaration, FIXTURE_LAT, FIXTURE_LON, TZ)
        day = date(2026, 1, 1)
        while day.year == 2026:
            declaration.on_date(day)
            planner.sunrise_edge(day)
            planner.sunset_edge(day)
            planner.midnight_boundary(day)
            day += timedelta(days=1)
        self.assertIsNotNone(declaration.on_date(date(2024, 2, 29)))


def _design() -> Path:
    root = Path(tempfile.mkdtemp())
    _write(
        root,
        holidays=[
            {"name": "Palm Sunday", "easter": -7, "colors": [[255, 0, 0], [0, 128, 0]]},
            {"name": "Good Friday", "easter": -2, "colors": [[153, 0, 0]]},
            {"name": "Easter", "easter": 0, "prior_night": True, "colors": [list(item) for item in WHITE_GOLD]},
            {"name": "St. Patrick", "month": 3, "day": 17, "colors": [[0, 132, 61], [255, 215, 0]]},
            {"name": "Annunciation", "month": 3, "day": 25, "colors": [[0, 56, 168], [255, 255, 255]]},
            {"name": "Independence Day", "month": 7, "day": 4, "colors": [list(item) for item in RWB]},
            {
                "name": "New Year's Day",
                "month": 1,
                "day": 1,
                "colors": [list(item) for item in WHITE_GOLD],
            },
            {
                "name": "Christmas",
                "month": 12,
                "day": 25,
                "midnight": True,
                "colors": [list(item) for item in WHITE_GOLD],
            },
        ],
        seasons=[
            {"name": "Lent", "start": {"easter": -46}, "end": {"easter": -1}, "colors": [[102, 0, 153]]},
            {
                "name": "Christmas season",
                "start": {"month": 12, "day": 24},
                "end": {"month": 12, "day": 26},
                "colors": [list(item) for item in SEASON],
            },
        ],
    )
    return root


def _two(first: str, second: str, year: int) -> Path:
    root = Path(tempfile.mkdtemp())
    rows = []
    for name in (first, second):
        if name == "Good Friday":
            rows.append({"name": name, "easter": -2, "colors": [[153, 0, 0]]})
        else:
            rows.append({"name": name, "month": 3, "day": 25, "colors": [[0, 56, 168], [255, 255, 255]]})
    _write(root, holidays=rows)
    assert year
    return root


def _write(root: Path, holidays=None, seasons=None, default=(WARM,), days=None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if holidays is not None:
        (root / "holidays.yaml").write_text(yaml.safe_dump(holidays, sort_keys=False), encoding="utf-8")
    if seasons is not None:
        (root / "seasons.yaml").write_text(yaml.safe_dump(seasons, sort_keys=False), encoding="utf-8")
    if default is not None:
        colors = [list(color) for color in default]
        (root / "default.yaml").write_text(
            yaml.safe_dump({"colors": colors}, sort_keys=False),
            encoding="utf-8",
        )
    if days:
        directory = root / "days"
        directory.mkdir()
        for name, body in days.items():
            (directory / name).write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")


def _planner(root: Path) -> Planner:
    return Planner(Declaration.load(root), FIXTURE_LAT, FIXTURE_LON, TZ)


def _sunset(planner: Planner, day: date) -> datetime:
    return planner.sunset(day) + timedelta(minutes=20)


def _noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=ZONE)


def _sunset_colors(planner: Planner, day: date):
    return planner.palette_at(_sunset(planner, day)).colors


def _nth(year: int, month: int, weekday: int, nth: int) -> date:
    weeks = calendar.monthcalendar(year, month)
    found = [week[weekday] for week in weeks if week[weekday]]
    return date(year, month, found[nth - 1])


def _last(year: int, month: int, weekday: int) -> date:
    weeks = calendar.monthcalendar(year, month)
    found = [week[weekday] for week in weeks if week[weekday]]
    return date(year, month, found[-1])


if __name__ == "__main__":
    unittest.main()
