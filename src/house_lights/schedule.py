"""Sunset-to-sunrise decisions.

Coordinates come from the caller. This module does not embed a home location.
``astral`` computes local sunrise and sunset:
https://pypi.org/project/astral/
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun


class ScheduleError(Exception):
    pass


@dataclass(frozen=True)
class SunEvents:
    sunrise: datetime
    sunset: datetime


def sun_events(latitude: float, longitude: float, day: date, timezone: str) -> SunEvents:
    zone = ZoneInfo(timezone)
    events = sun(Observer(latitude, longitude), date=day, tzinfo=zone)
    return SunEvents(sunrise=events["sunrise"], sunset=events["sunset"])


def is_night(now: datetime, latitude: float, longitude: float, timezone: str) -> bool:
    """True from local sunset until the next local sunrise.

    ``now`` is converted into ``timezone``. A clock time before today's
    sunrise is still night (the previous evening's window). A clock time
    from today's sunset onward is night.
    """
    if now.tzinfo is None:
        raise ScheduleError("clock must be timezone-aware")
    local = now.astimezone(ZoneInfo(timezone))
    events = sun_events(latitude, longitude, local.date(), timezone)
    return local < events.sunrise or local >= events.sunset
