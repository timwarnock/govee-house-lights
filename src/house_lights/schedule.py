"""Sunset-to-sunrise decisions.

Coordinates come from the caller. This module does not embed a home location.
``astral`` computes local sunrise and sunset:
https://pypi.org/project/astral/
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun

from house_lights.backend import LightsBackend
from house_lights.holidays import pattern_for

log = logging.getLogger("house_lights")


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
        raise ScheduleError("scheduler clock must be timezone-aware")
    local = now.astimezone(ZoneInfo(timezone))
    events = sun_events(latitude, longitude, local.date(), timezone)
    return local < events.sunrise or local >= events.sunset


class NightRunner:
    """Apply the civil-date pattern at night, and turn the lights off by day.

    The pattern follows the local calendar date, including the hours after
    midnight. A successful phase is not sent again until the date or
    day/night phase changes.
    """

    def __init__(self) -> None:
        self._last: tuple | None = None

    async def apply_phase(
        self,
        backend: LightsBackend,
        *,
        now: datetime,
        latitude: float,
        longitude: float,
        timezone: str,
        brightness: int,
    ) -> str:
        local = now.astimezone(ZoneInfo(timezone))
        night = is_night(local, latitude, longitude, timezone)
        pattern = pattern_for(local.date())
        if night:
            signature = ("night", pattern.key, brightness, local.date().isoformat())
        else:
            signature = ("day", local.date().isoformat())
        if signature == self._last:
            log.debug("lights already match %s", signature[0])
            return signature[0]
        if night:
            log.info(
                "night window, %s: %s",
                local.date().isoformat(),
                pattern.name,
            )
            await backend.turn_on()
            await backend.set_brightness(brightness)
            result = await backend.apply_pattern(pattern.colors)
            if result.note:
                log.warning("%s", result.note)
            else:
                log.info("applied %s via %s", pattern.name, result.mode)
        else:
            log.info("daytime %s: turning lights off", local.date().isoformat())
            await backend.turn_off()
        self._last = signature
        return signature[0]


async def run_forever(
    backend: LightsBackend,
    runner: NightRunner,
    *,
    latitude: float,
    longitude: float,
    timezone: str,
    brightness: int,
    poll_interval: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            await runner.apply_phase(
                backend,
                now=datetime.now(ZoneInfo(timezone)),
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
                brightness=brightness,
            )
        except Exception as exc:
            log.error("scheduler step failed: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval)
        except TimeoutError:
            continue
