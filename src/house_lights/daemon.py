"""Lights daemon.

The process sleeps until the next sunrise, sunset, or midnight color change,
sends that edge, and closes the transport. A later restart does not send the
same edge again, so a change made from the phone stays put. ``make install``
deletes the edge file before it restarts the process, which applies the
YAML that was just installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from house_lights.backend import LightsBackend
from house_lights.plan import Edge, Planner

log = logging.getLogger("house_lights")

# After a failed send, wait this long and try the current edge again.
FAILURE_RETRY_SECONDS = 60.0
# Monotonic sleep does not move during suspend. Recheck the wall clock on
# this interval so a resume still lands on the edge that is due.
WALL_SLICE_SECONDS = 30.0

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[bool]]


def load_edge(path: Path) -> str | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("ignoring unreadable edge file %s: %s", path, exc)
        return None
    edge = raw.get("edge") if isinstance(raw, dict) else None
    if not isinstance(edge, str) or not edge:
        return None
    return edge


def save_edge(path: Path, ident: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"edge": ident}, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def sunset_already_applied(succeeded: str | None, edge: Edge) -> bool:
    """True when this midnight belongs to a night whose sunset already succeeded."""
    if edge.kind != "midnight" or succeeded is None:
        return False
    night = edge.when.date() - timedelta(days=1)
    return succeeded == f"sunset:{night.isoformat()}"


async def sleep_until(
    deadline: datetime,
    *,
    now: Clock,
    sleep: Sleep,
    stop: asyncio.Event,
    slice_seconds: float = WALL_SLICE_SECONDS,
) -> None:
    """Wait until ``deadline`` on the wall clock, or until ``stop`` is set."""
    while not stop.is_set():
        remaining = (deadline - now()).total_seconds()
        if remaining <= 0:
            return
        if await sleep(min(remaining, slice_seconds)):
            return


async def run_daemon(
    backend: LightsBackend,
    planner: Planner,
    *,
    state_path: Path,
    stop: asyncio.Event,
    now: Clock | None = None,
    sleep: Sleep | None = None,
    enforce_minutes: int | None = None,
    slice_seconds: float = WALL_SLICE_SECONDS,
    failure_retry: float = FAILURE_RETRY_SECONDS,
) -> None:
    clock = now or (lambda: datetime.now(planner.zone))
    sleeper = sleep or _stop_sleep(stop)
    next_enforce = clock() + timedelta(minutes=enforce_minutes) if enforce_minutes else None
    while not stop.is_set():
        moment = clock()
        try:
            current = planner.current_edge(moment)
            succeeded = load_edge(state_path)
            if current is not None and current.ident != succeeded:
                log.info("apply %s (%s)", current.ident, current.source)
                await perform(
                    backend,
                    current,
                    sunset_already_on=sunset_already_applied(succeeded, current),
                )
                save_edge(state_path, current.ident)
                nxt = planner.next_edge(clock())
                if nxt is not None:
                    log.info("next %s at %s", nxt.ident, nxt.when.isoformat(timespec="seconds"))
            elif next_enforce is not None and current is not None and moment >= next_enforce:
                log.info("enforce %s", current.ident)
                await enforce(backend, current)
                next_enforce = clock() + timedelta(minutes=enforce_minutes or 0)
            await sleep_until(
                _deadline(planner, clock(), next_enforce, failure_retry),
                now=clock,
                sleep=sleeper,
                stop=stop,
                slice_seconds=slice_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("daemon step failed: %s", exc)
            await sleep_until(
                clock() + timedelta(seconds=failure_retry),
                now=clock,
                sleep=sleeper,
                stop=stop,
                slice_seconds=slice_seconds,
            )


async def perform(
    backend: LightsBackend,
    edge: Edge,
    *,
    sunset_already_on: bool,
) -> None:
    await backend.open()
    try:
        await send_edge(backend, edge, sunset_already_on=sunset_already_on)
    finally:
        await backend.close()


async def send_edge(
    backend: LightsBackend,
    edge: Edge,
    *,
    sunset_already_on: bool,
) -> None:
    if edge.kind == "sunrise":
        await backend.turn_off()
        log.info("off for %s", edge.ident)
        return
    colors_only = edge.kind == "midnight" and sunset_already_on
    if not colors_only:
        await backend.turn_on()
    await backend.set_brightness(edge.brightness)
    if edge.colors is None:
        log.info("%s has no color list", edge.ident)
        return
    result = await backend.apply_pattern(edge.colors)
    if result.note:
        log.warning("%s", result.note)
    else:
        log.info("sent %s via %s", edge.source, result.mode)


async def enforce(backend: LightsBackend, edge: Edge) -> None:
    """Correct power and brightness, and resend colors. Status cannot see them."""
    await backend.open()
    try:
        status = await backend.status()
        if edge.kind == "sunrise":
            if status is None or status.is_on is not False:
                await backend.turn_off()
            return
        if status is None or status.is_on is not True:
            await backend.turn_on()
        if status is None or status.brightness != edge.brightness:
            await backend.set_brightness(edge.brightness)
        if edge.colors is not None:
            result = await backend.apply_pattern(edge.colors)
            if result.note:
                log.warning("%s", result.note)
    finally:
        await backend.close()


def _deadline(
    planner: Planner,
    moment: datetime,
    next_enforce: datetime | None,
    failure_retry: float,
) -> datetime:
    times: list[datetime] = []
    nxt = planner.next_edge(moment)
    if nxt is not None:
        times.append(nxt.when)
    if next_enforce is not None:
        times.append(next_enforce)
    if not times:
        return moment + timedelta(seconds=failure_retry)
    return min(times)


def _stop_sleep(stop: asyncio.Event) -> Sleep:
    async def sleep(seconds: float) -> bool:
        if seconds <= 0:
            return stop.is_set()
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

    return sleep
