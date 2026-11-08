"""Load a desired-state directory and decide what each sunrise, sunset, and midnight does.

The directory holds ``default.yaml``, ``holidays.yaml``, ``seasons.yaml``, and
``days/``. First match wins: an exact day file, then ``days/every-MM-DD.yaml``,
then the first holiday whose window covers the moment, then the first season
that contains the civil date, then the default. A missing default means sunset
turns the lights on and sends no color list.

``description`` is stored and ignored. The loader accepts the keys named
in this module. The directory is the source of truth for dates and colors.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from house_lights.schedule import ScheduleError, SunEvents, is_night, sun_events
from house_lights.still import RGB, still_scene_value

# Used when default.yaml omits brightness. An entry that omits it falls
# through the match order and then uses the number from default.yaml.
DEFAULT_BRIGHTNESS = 100

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_WHEN_KEYS = frozenset({"easter", "month", "day", "weekday", "nth"})
_HOLIDAY_KEYS = _WHEN_KEYS | {"name", "colors", "prior_night", "midnight", "description", "brightness"}
_SEASON_KEYS = frozenset({"name", "colors", "start", "end", "description", "brightness"})
_DAY_KEYS = frozenset({"colors", "description", "brightness"})


class DeclarationError(Exception):
    """The desired-state directory cannot be loaded."""


def easter_sunday(year: int) -> date:
    """Western Easter, Gregorian computus, for ``year``."""
    if year < 1583:
        raise DeclarationError(f"Easter is not defined here before 1583 (got {year})")
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def project_root() -> Path | None:
    """The checkout that holds ``desired-state/``, from the working directory or this source tree."""
    candidates = [Path.cwd()]
    path = Path(__file__).resolve()
    if len(path.parents) >= 3:
        candidates.append(path.parents[2])
    for root in candidates:
        desired = root / "desired-state"
        if desired.is_dir() and any(desired.glob("*.yaml")):
            return root
    return None


def default_config_path() -> Path | None:
    """``config.json`` in the project root, when that file has been created."""
    root = project_root()
    if root is None:
        return None
    candidate = root / "config.json"
    return candidate if candidate.is_file() else None


def resolve_desired_state_dir(explicit: Path | None) -> Path:
    """Use an explicit path, then the project ``desired-state/`` directory."""
    if explicit is not None:
        return explicit.expanduser()
    root = project_root()
    if root is not None:
        return root / "desired-state"
    raise DeclarationError(
        "desired-state directory not found. Run house-lights from the project, "
        "or pass --desired-state."
    )


@dataclass(frozen=True)
class When:
    """One way to name a civil date. Unused fields stay ``None``."""

    month: int | None = None
    day: int | None = None
    weekday: int | None = None
    nth: int | None = None
    easter: int | None = None

    def resolve(self, year: int) -> date | None:
        """Return the date in ``year``, or ``None`` when that year has no such day."""
        if self.easter is not None:
            return easter_sunday(year) + timedelta(days=self.easter)
        if self.month is None:
            raise DeclarationError("a date needs a month or an easter offset")
        if self.weekday is not None:
            if self.nth == -1:
                return _last_weekday(year, self.month, self.weekday)
            if self.nth is None:
                raise DeclarationError("a weekday date needs nth")
            return _nth_weekday(year, self.month, self.weekday, self.nth)
        if self.day is None:
            raise DeclarationError("a fixed date needs a day")
        try:
            return date(year, self.month, self.day)
        except ValueError:
            return None


@dataclass(frozen=True)
class Palette:
    source: str
    colors: tuple[RGB, ...] | None
    brightness: int


@dataclass(frozen=True)
class Edge:
    kind: str
    when: datetime
    source: str
    colors: tuple[RGB, ...] | None
    brightness: int

    @property
    def ident(self) -> str:
        return f"{self.kind}:{self.when.date().isoformat()}"


@dataclass(frozen=True)
class _Rule:
    source: str
    colors: tuple[RGB, ...]
    when: When | None = None
    prior_night: bool = False
    midnight: bool = False
    start: When | None = None
    end: When | None = None
    brightness: int | None = None


@dataclass(frozen=True)
class Declaration:
    holidays: tuple[_Rule, ...]
    seasons: tuple[_Rule, ...]
    default_colors: tuple[RGB, ...] | None
    brightness: int
    exact_days: dict[date, _Rule]
    every_days: dict[tuple[int, int], _Rule]
    directory: Path

    @classmethod
    def load(cls, directory: Path) -> Declaration:
        directory = directory.expanduser()
        if not directory.is_dir():
            raise DeclarationError(f"desired-state directory not found: {directory}")
        holidays = _load_named_list(directory / "holidays.yaml", _holiday)
        seasons = _load_named_list(directory / "seasons.yaml", _season)
        default_colors, brightness = _load_default(directory / "default.yaml")
        exact_days, every_days = _load_days(directory / "days")
        return cls(
            holidays=holidays,
            seasons=seasons,
            default_colors=default_colors,
            brightness=brightness,
            exact_days=exact_days,
            every_days=every_days,
            directory=directory,
        )

    def on_date(self, day: date) -> Palette:
        """Civil-date match, ignoring sunset and midnight windows."""
        rules: list[_Rule] = []
        exact = self.exact_days.get(day)
        if exact is not None:
            rules.append(exact)
        else:
            every = self.every_days.get((day.month, day.day))
            if every is not None:
                rules.append(every)
        for holiday in self.holidays:
            assert holiday.when is not None
            if holiday.when.resolve(day.year) == day:
                rules.append(holiday)
                break
        for season in self.seasons:
            if _season_includes(season, day):
                rules.append(season)
                break
        return self.palette_from(rules)

    def palette_from(self, rules: list[_Rule]) -> Palette:
        """Colors come from the first rule. Brightness comes from the first rule that sets it."""
        brightness = self.brightness
        for rule in rules:
            if rule.brightness is not None:
                brightness = rule.brightness
                break
        if not rules:
            if self.default_colors is not None:
                return Palette("default", self.default_colors, brightness)
            return Palette("none", None, brightness)
        first = rules[0]
        return Palette(first.source, first.colors, brightness)


class Planner:
    """Sun-aware edges for one coordinate and one declaration."""

    def __init__(self, declaration: Declaration, latitude: float, longitude: float, timezone: str) -> None:
        self.declaration = declaration
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = timezone
        self.zone = ZoneInfo(timezone)
        self._sun: dict[date, SunEvents] = {}

    def palette_at(self, moment: datetime) -> Palette:
        local = self._local(moment)
        rules: list[_Rule] = []
        covered = self._day_covering(local)
        if covered is not None:
            rules.append(covered)
        holiday = self._holiday_covering(local)
        if holiday is not None:
            rules.append(holiday)
        for season in self.declaration.seasons:
            if _season_includes(season, local.date()):
                rules.append(season)
                break
        return self.declaration.palette_from(rules)

    def sunrise_edge(self, day: date) -> Edge:
        return Edge("sunrise", self.sunrise(day), "sunrise", None, self.declaration.brightness)

    def sunset_edge(self, day: date) -> Edge:
        when = self.sunset(day)
        palette = self.palette_at(when)
        return Edge("sunset", when, palette.source, palette.colors, palette.brightness)

    def midnight_boundary(self, day: date) -> Edge | None:
        """A color change at 00:00 on ``day`` while the lights are still on.

        A season rolling over at midnight is not a boundary. A holiday window
        that starts or ends at that midnight is, and only when the colors change.
        ``prior_night`` together with ``midnight`` does not change color at the
        midnight in the middle of that span.
        """
        moment = self.midnight(day)
        if not self._holiday_touches(moment):
            return None
        if not is_night(moment, self.latitude, self.longitude, self.timezone):
            return None
        before = self.palette_at(moment - timedelta(seconds=1))
        after = self.palette_at(moment)
        if before.colors == after.colors and before.brightness == after.brightness:
            return None
        return Edge("midnight", moment, after.source, after.colors, after.brightness)

    def current_edge(self, moment: datetime) -> Edge | None:
        local = self._local(moment)
        past = [edge for edge in self._window(local, days_back=2, days_forward=1) if edge.when <= local]
        if not past:
            return None
        return max(past, key=lambda edge: edge.when)

    def next_edge(self, moment: datetime) -> Edge | None:
        local = self._local(moment)
        future = [edge for edge in self._window(local, days_back=1, days_forward=2) if edge.when > local]
        if not future:
            return None
        return min(future, key=lambda edge: edge.when)

    def sunset(self, day: date) -> datetime:
        return self._events(day).sunset

    def sunrise(self, day: date) -> datetime:
        return self._events(day).sunrise

    def midnight(self, day: date) -> datetime:
        return datetime(day.year, day.month, day.day, tzinfo=self.zone)

    def _local(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            raise ScheduleError("clock must be timezone-aware")
        return moment.astimezone(self.zone)

    def _events(self, day: date) -> SunEvents:
        cached = self._sun.get(day)
        if cached is None:
            cached = sun_events(self.latitude, self.longitude, day, self.timezone)
            self._sun[day] = cached
        return cached

    def _window(self, moment: datetime, *, days_back: int, days_forward: int) -> list[Edge]:
        start = moment.date() - timedelta(days=days_back)
        last = moment.date() + timedelta(days=days_forward)
        found: dict[str, Edge] = {}
        day = start
        while day <= last:
            for edge in (self.sunrise_edge(day), self.sunset_edge(day)):
                found[edge.ident] = edge
            midnight = self.midnight_boundary(day)
            if midnight is not None:
                found[midnight.ident] = midnight
            day += timedelta(days=1)
        return list(found.values())

    def _day_covering(self, moment: datetime) -> _Rule | None:
        candidates = (moment.date() - timedelta(days=1), moment.date())
        for table, label in (
            (self.declaration.exact_days, "exact"),
            (self.declaration.every_days, "every"),
        ):
            for day in candidates:
                rule = _day_rule(table, label, day)
                if rule is None:
                    continue
                if self.sunset(day) <= moment < self.sunrise(day + timedelta(days=1)):
                    return rule
        return None

    def _holiday_covering(self, moment: datetime) -> _Rule | None:
        for holiday in self.declaration.holidays:
            for year in (moment.year - 1, moment.year, moment.year + 1):
                span = self._span(holiday, year)
                if span is None:
                    continue
                start, end = span
                if start <= moment < end:
                    return holiday
        return None

    def _holiday_touches(self, moment: datetime) -> bool:
        for holiday in self.declaration.holidays:
            for year in (moment.year - 1, moment.year, moment.year + 1):
                span = self._span(holiday, year)
                if span is None:
                    continue
                start, end = span
                if start == moment or end == moment:
                    return True
        return False

    def _span(self, holiday: _Rule, year: int) -> tuple[datetime, datetime] | None:
        assert holiday.when is not None
        day = holiday.when.resolve(year)
        if day is None:
            return None
        if holiday.prior_night and holiday.midnight:
            return self.sunset(day - timedelta(days=1)), self.midnight(day + timedelta(days=1))
        if holiday.prior_night:
            return self.sunset(day - timedelta(days=1)), self.sunrise(day + timedelta(days=1))
        if holiday.midnight:
            return self.midnight(day), self.midnight(day + timedelta(days=1))
        return self.sunset(day), self.sunrise(day + timedelta(days=1))


def _day_rule(table: dict, label: str, day: date) -> _Rule | None:
    if label == "exact":
        return table.get(day)
    return table.get((day.month, day.day))


def _season_includes(season: _Rule, day: date) -> bool:
    assert season.start is not None and season.end is not None
    if season.start.easter is not None or season.end.easter is not None:
        start = season.start.resolve(day.year)
        end = season.end.resolve(day.year)
        if start is None or end is None:
            return False
        if start <= end:
            return start <= day <= end
        return day >= start or day <= end
    if season.start.month is None or season.start.day is None:
        raise DeclarationError(f"{season.source}: season bounds must be a fixed date or an easter offset")
    if season.end.month is None or season.end.day is None:
        raise DeclarationError(f"{season.source}: season bounds must be a fixed date or an easter offset")
    start_md = (season.start.month, season.start.day)
    end_md = (season.end.month, season.end.day)
    current = (day.month, day.day)
    if start_md <= end_md:
        return start_md <= current <= end_md
    return current >= start_md or current <= end_md


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date | None:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + (nth - 1) * 7
    if day > calendar.monthrange(year, month)[1]:
        return None
    return date(year, month, day)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _load_named_list(path: Path, parse) -> tuple[_Rule, ...]:
    if not path.is_file():
        return ()
    raw = _read_yaml(path)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise DeclarationError(f"{path.name} must be a list")
    return tuple(parse(item, path.name, index) for index, item in enumerate(raw, start=1))


def _load_default(path: Path) -> tuple[tuple[RGB, ...] | None, int]:
    if not path.is_file():
        return None, DEFAULT_BRIGHTNESS
    raw = _read_yaml(path)
    if not isinstance(raw, dict):
        raise DeclarationError("default.yaml must be a mapping")
    unknown = set(raw) - {"colors", "description", "brightness"}
    if unknown:
        raise DeclarationError(f"default.yaml has unknown keys: {', '.join(sorted(unknown))}")
    _optional_text(raw.get("description"), "default.yaml description")
    return _colors(raw.get("colors"), "default.yaml"), _brightness(
        raw.get("brightness", DEFAULT_BRIGHTNESS), path.name
    )


def _optional_brightness(mapping: dict, where: str) -> int | None:
    if "brightness" not in mapping or mapping["brightness"] is None:
        return None
    return _brightness(mapping["brightness"], where)


def _brightness(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise DeclarationError(f"{where} brightness must be an integer from 1 to 100")
    return value


def _load_days(directory: Path) -> tuple[dict[date, _Rule], dict[tuple[int, int], _Rule]]:
    exact: dict[date, _Rule] = {}
    every: dict[tuple[int, int], _Rule] = {}
    if not directory.exists():
        return exact, every
    if not directory.is_dir():
        raise DeclarationError(f"days path is not a directory: {directory}")
    for path in sorted(directory.iterdir()):
        if path.name.startswith("."):
            continue
        if not path.is_file():
            raise DeclarationError(f"days/{path.name} is not a file")
        if path.suffix != ".yaml":
            raise DeclarationError(f"days/{path.name} is not a yaml file")
        rule = _day_file(path)
        if path.name.startswith("every-"):
            key = _every_key(path)
            every[key] = rule
            continue
        try:
            exact[date.fromisoformat(path.stem)] = rule
        except ValueError as exc:
            raise DeclarationError(
                f"days/{path.name} must be YYYY-MM-DD.yaml or every-MM-DD.yaml"
            ) from exc
    return exact, every


def _day_file(path: Path) -> _Rule:
    raw = _read_yaml(path)
    where = f"days/{path.name}"
    if not isinstance(raw, dict):
        raise DeclarationError(f"{where} must be a mapping")
    unknown = set(raw) - _DAY_KEYS
    if unknown:
        raise DeclarationError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
    _optional_text(raw.get("description"), f"{where} description")
    return _Rule(
        source=where,
        colors=_colors(raw.get("colors"), where),
        brightness=_optional_brightness(raw, where),
    )


def _every_key(path: Path) -> tuple[int, int]:
    stamp = path.stem.removeprefix("every-")
    parts = stamp.split("-")
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise DeclarationError(f"days/{path.name} must be every-MM-DD.yaml")
    try:
        month = int(parts[0])
        day = int(parts[1])
        date(2024, month, day)
    except ValueError as exc:
        raise DeclarationError(f"days/{path.name} is not a real month and day") from exc
    return month, day


def _holiday(raw: object, filename: str, index: int) -> _Rule:
    where = f"{filename} entry {index}"
    mapping = _mapping(raw, where, _HOLIDAY_KEYS)
    name = _required_name(mapping, where)
    when = _parse_when({key: mapping[key] for key in _WHEN_KEYS if key in mapping}, where)
    return _Rule(
        source=name,
        colors=_colors(mapping.get("colors"), where),
        when=when,
        prior_night=_flag(mapping, "prior_night", where),
        midnight=_flag(mapping, "midnight", where),
        brightness=_optional_brightness(mapping, where),
    )


def _season(raw: object, filename: str, index: int) -> _Rule:
    where = f"{filename} entry {index}"
    mapping = _mapping(raw, where, _SEASON_KEYS)
    name = _required_name(mapping, where)
    if "start" not in mapping or "end" not in mapping:
        raise DeclarationError(f"{where} needs start and end")
    return _Rule(
        source=name,
        colors=_colors(mapping.get("colors"), where),
        start=_parse_when(mapping["start"], f"{where} start"),
        end=_parse_when(mapping["end"], f"{where} end"),
        brightness=_optional_brightness(mapping, where),
    )


def _parse_when(raw: object, where: str) -> When:
    mapping = _mapping(raw, where, _WHEN_KEYS)
    if not mapping:
        raise DeclarationError(f"{where} needs a date")
    easter = mapping.get("easter")
    if easter is not None:
        if set(mapping) != {"easter"}:
            raise DeclarationError(f"{where} easter offset cannot be combined with another date field")
        if isinstance(easter, bool) or not isinstance(easter, int):
            raise DeclarationError(f"{where} easter must be an integer offset in days")
        return When(easter=easter)
    month = mapping.get("month")
    if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
        raise DeclarationError(f"{where} month must be an integer from 1 to 12")
    if "weekday" in mapping:
        if set(mapping) != {"month", "weekday", "nth"}:
            raise DeclarationError(f"{where} weekday date uses month, weekday, and nth")
        weekday = mapping.get("weekday")
        if not isinstance(weekday, str) or weekday.lower() not in _WEEKDAYS:
            raise DeclarationError(f"{where} weekday must be a day name, monday through sunday")
        nth = mapping.get("nth")
        if nth == "last":
            return When(month=month, weekday=_WEEKDAYS[weekday.lower()], nth=-1)
        if isinstance(nth, bool) or not isinstance(nth, int) or not 1 <= nth <= 5:
            raise DeclarationError(f"{where} nth must be 1 through 5, or last")
        return When(month=month, weekday=_WEEKDAYS[weekday.lower()], nth=nth)
    if set(mapping) != {"month", "day"}:
        raise DeclarationError(f"{where} fixed date uses month and day")
    day = mapping.get("day")
    if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
        raise DeclarationError(f"{where} day must be an integer from 1 to 31")
    if day > calendar.monthrange(2024, month)[1]:
        raise DeclarationError(f"{where} has no day {day} in month {month}")
    return When(month=month, day=day)


def _colors(raw: object, where: str) -> tuple[RGB, ...]:
    if not isinstance(raw, list) or not raw:
        raise DeclarationError(f"{where} needs a non-empty colors list")
    colors: list[RGB] = []
    for index, item in enumerate(raw, start=1):
        if (
            not isinstance(item, list)
            or len(item) != 3
            or any(isinstance(channel, bool) or not isinstance(channel, int) for channel in item)
        ):
            raise DeclarationError(f"{where} color {index} must be [r, g, b]")
        colors.append((item[0], item[1], item[2]))
    try:
        still_scene_value(colors)
    except ValueError as exc:
        raise DeclarationError(f"{where}: {exc}") from exc
    return tuple(colors)


def _mapping(raw: object, where: str, allowed: frozenset[str]) -> dict:
    if not isinstance(raw, dict):
        raise DeclarationError(f"{where} must be a mapping")
    unknown = set(raw) - allowed
    if unknown:
        raise DeclarationError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
    if "description" in allowed:
        _optional_text(raw.get("description"), f"{where} description")
    return raw


def _required_name(mapping: dict, where: str) -> str:
    name = mapping.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DeclarationError(f"{where} needs a name")
    return name.strip()


def _flag(mapping: dict, key: str, where: str) -> bool:
    value = mapping.get(key, False)
    if not isinstance(value, bool):
        raise DeclarationError(f"{where} {key} must be true or false")
    return value


def _optional_text(value: object, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise DeclarationError(f"{where} must be text")


def _read_yaml(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeclarationError(f"could not read {path}: {exc}") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DeclarationError(f"{path.name} is not valid YAML: {exc}") from exc
