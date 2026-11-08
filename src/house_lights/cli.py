"""Command line for local Govee H706C control."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

from house_lights import __version__
from house_lights.backend import ApplyResult, GridResult, LightsBackend
from house_lights.grid import load_grid
from house_lights.holidays import RED, WHITE, BLUE, RGB, pattern_for
from house_lights.schedule import NightRunner, run_forever, sun_events
from house_lights.settings import Settings, UsageError, settings_from_namespace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="house-lights",
        description=(
            "Local control for Govee Permanent Outdoor Lights Pro (H706C). "
            "LAN and Bluetooth share one backend interface. No Govee cloud API."
        ),
    )
    parser.add_argument("--version", action="version", version=f"house-lights {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="optional JSON settings file; flags override it")
    common.add_argument("--backend", choices=("lan", "bluetooth"))
    common.add_argument("--ip", help="LAN device IPv4 (default 192.168.0.119)")
    common.add_argument("--ble-address", dest="ble_address", help="Bluetooth address AA:BB:CC:DD:EE:FF")
    common.add_argument("--sku", help="Govee SKU (default H706C)")
    common.add_argument("--lat", type=float, help="latitude in decimal degrees; required for run")
    common.add_argument("--lon", type=float, help="longitude in decimal degrees; required for run")
    common.add_argument("--timezone", help="IANA timezone (default America/Chicago)")
    common.add_argument("--brightness", type=int, help="1-100 (default 70)")
    common.add_argument(
        "--segments",
        type=int,
        help="Bluetooth segment count override; omit to use the device or library count",
    )
    common.add_argument("--timeout", type=float, help="scan and LAN reply timeout seconds (default 8)")
    common.add_argument("--retries", type=int, help="attempts per command after a failure (default 3)")
    common.add_argument("--retry-delay", dest="retry_delay", type=float, help="seconds between retries (default 1)")
    common.add_argument(
        "--poll-interval",
        dest="poll_interval",
        type=float,
        help="seconds between scheduler checks (default 60)",
    )
    common.add_argument(
        "--scan",
        action="store_true",
        help="Accepted. Bluetooth always scans before connect so BlueZ has a fresh advertisement",
    )
    common.add_argument("--ble-cache", dest="ble_cache", help="JSON file for the last BLE address and SKU")
    common.add_argument("--verbose", action="store_true")

    for name, help_text in (
        ("run", "turn on at local sunset and off at local sunrise"),
        ("on", "turn on now and paint the still pattern for the date"),
        ("off", "turn off now"),
        ("status", "read device status when the backend can"),
        ("preview", "print the still pattern for a date; no hardware"),
        ("paint", "paint a 120-light grid from a JSON file"),
    ):
        command = sub.add_parser(name, parents=[common], help=help_text)
        if name in {"on", "preview"}:
            command.add_argument(
                "--date",
                help="YYYY-MM-DD civil date for the pattern (default: today in --timezone)",
            )
        if name == "paint":
            command.add_argument(
                "--grid",
                help="JSON file: {\"lights\": [[r, g, b], ...]} of 120 colors, or a shorter list that repeats",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    try:
        settings = settings_from_namespace(args)
    except UsageError as exc:
        parser.error(str(exc))
    try:
        if settings.command == "preview":
            return _preview(settings)
        if settings.command == "paint":
            assert settings.grid is not None
            colors, source_count = load_grid(settings.grid)
        else:
            colors, source_count = None, None
        return asyncio.run(_hardware(settings, colors, source_count))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("house_lights").error("%s", exc)
        return 1


def _preview(settings: Settings) -> int:
    day = settings.when or datetime.now(ZoneInfo(settings.timezone)).date()
    pattern = pattern_for(day)
    print(f"date: {day.isoformat()}")
    print(f"pattern: {pattern.name}")
    print("colors: " + ", ".join(
        f"{name} {_fmt_rgb(rgb)}" for name, rgb in zip(pattern.color_names, pattern.colors, strict=True)
    ))
    if pattern.mixed:
        print("static: repeating sequence, held still")
    else:
        print("static: solid color, held still")
    if settings.lat is not None and settings.lon is not None:
        events = sun_events(settings.lat, settings.lon, day, settings.timezone)
        print(f"timezone: {settings.timezone}")
        print(f"sunrise: {events.sunrise.isoformat(timespec='seconds')}")
        print(f"sunset: {events.sunset.isoformat(timespec='seconds')}")
        print("lights: on from sunset through the following sunrise")
    return 0


async def _hardware(
    settings: Settings,
    colors: tuple[RGB, ...] | None = None,
    source_count: int | None = None,
) -> int:
    backend = _build_backend(settings)
    try:
        await backend.open()
        if settings.command == "status":
            return _print_status(await backend.status(), settings)
        if settings.command == "off":
            await backend.turn_off()
            print("off")
            return 0
        if settings.command == "on":
            return await _turn_on(backend, settings)
        if settings.command == "paint":
            assert colors is not None and source_count is not None
            return await _paint(backend, settings, colors, source_count)
        if settings.command == "run":
            await _run(backend, settings)
            return 0
        raise UsageError(f"unknown command {settings.command}")
    finally:
        await backend.close()


async def _paint(
    backend: LightsBackend,
    settings: Settings,
    colors: tuple[RGB, ...],
    source_count: int,
) -> int:
    if source_count == len(colors):
        print(f"grid: {len(colors)} lights")
    else:
        print(f"grid: {source_count} entries repeated to {len(colors)} lights")
    await backend.turn_on()
    await backend.set_brightness(settings.brightness)
    try:
        result = await backend.apply_grid(colors, brightness=settings.brightness)
    except Exception as exc:
        print(f"sketch failed: {exc}")
        if settings.backend == "bluetooth":
            await _restore_segment_rwb(backend)
        return 1
    _print_grid(result)
    return 0


async def _restore_segment_rwb(backend: LightsBackend) -> None:
    try:
        await backend.apply_pattern((RED, WHITE, BLUE))
    except Exception as exc:
        print(f"could not restore the red, white, blue pattern: {exc}")
        return
    print("restored the red, white, blue pattern")


def _print_grid(result: GridResult) -> None:
    print(
        f"paint: {result.light_count} lights in {result.group_count} groups "
        f"via {result.mode}, {result.upload_packets} upload packets"
    )
    if result.group_count <= 8:
        print("groups: " + ", ".join(_fmt_rgb(color) for color in result.colors))
    print(result.note)


async def _turn_on(backend: LightsBackend, settings: Settings) -> int:
    day = settings.when or datetime.now(ZoneInfo(settings.timezone)).date()
    pattern = pattern_for(day)
    await backend.turn_on()
    await backend.set_brightness(settings.brightness)
    result = await backend.apply_pattern(pattern.colors)
    _print_apply(pattern.name, result)
    return 0


async def _run(backend: LightsBackend, settings: Settings) -> None:
    assert settings.lat is not None and settings.lon is not None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    logging.getLogger("house_lights").info(
        "scheduler running in %s at lat %s lon %s; Ctrl-C to stop",
        settings.timezone,
        settings.lat,
        settings.lon,
    )
    await run_forever(
        backend,
        NightRunner(),
        latitude=settings.lat,
        longitude=settings.lon,
        timezone=settings.timezone,
        brightness=settings.brightness,
        poll_interval=settings.poll_interval,
        stop=stop,
    )


def _print_status(status, settings: Settings) -> int:
    if status is None:
        print(f"{settings.backend}: status is not available")
        return 0
    print(f"backend: {settings.backend}")
    print(f"on: {_yes_no(status.is_on)}")
    print(f"brightness: {status.brightness}")
    print(f"color: {_fmt_rgb(status.rgb) if status.rgb else 'unknown'}")
    print(f"color_temp_kelvin: {status.color_temp_kelvin}")
    if status.detail:
        print(f"detail: {status.detail}")
    return 0


def _print_apply(name: str, result: ApplyResult) -> None:
    sent = ", ".join(_fmt_rgb(color) for color in result.colors_sent)
    print(f"on: {name} via {result.mode} colors {sent}")
    if result.note:
        print(result.note)


def _fmt_rgb(rgb: tuple[int, int, int]) -> str:
    return f"({rgb[0]}, {rgb[1]}, {rgb[2]})"


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _build_backend(settings: Settings) -> LightsBackend:
    if settings.backend == "lan":
        from house_lights.lan import LanBackend

        return LanBackend(
            settings.ip,
            timeout=settings.timeout,
            retries=settings.retries,
            retry_delay=settings.retry_delay,
        )
    if settings.backend == "bluetooth":
        from house_lights.bluetooth import BluetoothBackend

        return BluetoothBackend(settings)
    raise UsageError("pass --backend lan or --backend bluetooth")


if __name__ == "__main__":
    raise SystemExit(main())
