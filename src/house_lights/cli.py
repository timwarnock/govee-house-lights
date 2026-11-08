"""Command line for local Govee H706C control."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from house_lights import __version__
from house_lights.backend import ApplyResult, LightsBackend
from house_lights.daemon import run_daemon
from house_lights.plan import Declaration, Palette, Planner, default_config_path, resolve_desired_state_dir
from house_lights.settings import Settings, UsageError, settings_from_namespace
from house_lights.still import RGB


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
    common.add_argument("--ip", help="LAN IPv4 address; required with --backend lan")
    common.add_argument("--ble-address", dest="ble_address", help="Bluetooth address AA:BB:CC:DD:EE:FF")
    common.add_argument("--sku", help="Govee SKU (default H706C)")
    common.add_argument("--lat", type=float, help="latitude in decimal degrees; required for daemon and run")
    common.add_argument("--lon", type=float, help="longitude in decimal degrees; required for daemon and run")
    common.add_argument(
        "--desired-state",
        dest="desired_state_dir",
        help="directory of desired-state YAML; overrides the config key and the default desired-state/",
    )
    common.add_argument("--timezone", help="IANA timezone (default America/Chicago)")
    common.add_argument(
        "--brightness",
        type=int,
        help="1-100 override for this command; the default is brightness in desired-state/default.yaml",
    )
    common.add_argument("--timeout", type=float, help="scan and LAN reply timeout seconds (default 8)")
    common.add_argument("--retries", type=int, help="attempts per command after a failure (default 3)")
    common.add_argument("--retry-delay", dest="retry_delay", type=float, help="seconds between retries (default 1)")
    common.add_argument(
        "--scan",
        action="store_true",
        help="Accepted. Bluetooth always scans before connect so BlueZ has a fresh advertisement",
    )
    common.add_argument("--ble-cache", dest="ble_cache", help="JSON file for the last BLE address and SKU")
    common.add_argument("--verbose", action="store_true")

    for name, help_text in (
        ("daemon", "keep the lights matched to the YAML"),
        ("on", "turn on now and send the color for the date"),
        ("off", "turn off now"),
        ("status", "read device status when the backend can"),
        ("preview", "print the color for a date; no hardware"),
    ):
        command = sub.add_parser(name, parents=[common], help=help_text)
        if name in {"on", "preview"}:
            command.add_argument(
                "--date",
                help="YYYY-MM-DD civil date (default: today in --timezone)",
            )
        if name == "daemon":
            command.add_argument("--state", dest="state_path", help="file that remembers the last succeeded edge")
            command.add_argument(
                "--enforce-minutes",
                dest="enforce_minutes",
                type=int,
                help="optional correction interval in minutes; off when omitted",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "config", None):
        found = default_config_path()
        if found is not None:
            args.config = str(found)
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
        if settings.command == "daemon":
            return asyncio.run(_daemon(settings))
        return asyncio.run(_hardware(settings))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("house_lights").error("%s", exc)
        return 1


def _preview(settings: Settings) -> int:
    declaration = _declaration(settings)
    zone = ZoneInfo(settings.timezone)
    day = settings.when or datetime.now(zone).date()
    palette = declaration.on_date(day)
    print(f"date: {day.isoformat()}")
    print(f"brightness: {declaration.brightness}")
    print(f"pattern: {palette.source}")
    _print_palette(palette)
    if settings.lat is None or settings.lon is None:
        return 0
    planner = Planner(declaration, settings.lat, settings.lon, settings.timezone)
    sunrise = planner.sunrise_edge(day)
    sunset = planner.sunset_edge(day)
    midnight = planner.midnight_boundary(day + timedelta(days=1))
    print(f"timezone: {settings.timezone}")
    print(f"sunrise: {sunrise.when.isoformat(timespec='seconds')}")
    print(f"sunset: {sunset.when.isoformat(timespec='seconds')}")
    print(f"sunset colors: {sunset.source} {_color_text(sunset.colors)}")
    if midnight is None:
        print("midnight: no color change")
    else:
        print(
            f"midnight: {midnight.when.isoformat(timespec='seconds')} "
            f"{midnight.source} {_color_text(midnight.colors)}"
        )
    print("lights: on from sunset through the following sunrise")
    return 0


async def _daemon(settings: Settings) -> int:
    assert settings.lat is not None and settings.lon is not None
    declaration = _declaration(settings)
    planner = Planner(declaration, settings.lat, settings.lon, settings.timezone)
    backend = _build_backend(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    state_path = settings.state_path or (declaration.directory / "daemon.json")
    log = logging.getLogger("house_lights")
    log.info("desired-state %s timezone %s", declaration.directory, settings.timezone)
    nxt = planner.next_edge(datetime.now(ZoneInfo(settings.timezone)))
    if nxt is not None:
        log.info("next %s at %s", nxt.ident, nxt.when.isoformat(timespec="seconds"))
    await run_daemon(
        backend,
        planner,
        brightness=_brightness(settings, declaration),
        state_path=state_path,
        stop=stop,
        enforce_minutes=settings.enforce_minutes,
    )
    return 0


def _brightness(settings: Settings, declaration: Declaration) -> int:
    if settings.brightness is not None:
        return settings.brightness
    return declaration.brightness


def _declaration(settings: Settings) -> Declaration:
    return Declaration.load(resolve_desired_state_dir(settings.desired_state_dir))


async def _hardware(settings: Settings) -> int:
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
        raise UsageError(f"unknown command {settings.command}")
    finally:
        await backend.close()


async def _turn_on(backend: LightsBackend, settings: Settings) -> int:
    declaration = _declaration(settings)
    day = settings.when or datetime.now(ZoneInfo(settings.timezone)).date()
    palette = declaration.on_date(day)
    await backend.turn_on()
    await backend.set_brightness(_brightness(settings, declaration))
    if not palette.colors:
        print(f"on: {palette.source}, no color list")
        return 0
    result = await backend.apply_pattern(palette.colors)
    _print_apply(palette.source, result)
    return 0


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


_COLOR_NAMES: dict[RGB, str] = {
    (255, 0, 0): "red",
    (0, 255, 0): "green",
    (0, 128, 0): "green",
    (0, 0, 255): "blue",
    (0, 56, 168): "blue",
    (255, 255, 255): "white",
    (255, 215, 0): "gold",
    (255, 197, 143): "warm white",
    (255, 165, 0): "orange",
    (102, 0, 153): "violet",
    (153, 0, 0): "deep red",
    (135, 206, 235): "sky blue",
}


def _print_palette(palette: Palette) -> None:
    print(f"colors: {_color_text(palette.colors)}")
    if not palette.colors:
        return
    if len(set(palette.colors)) > 1:
        print("static: repeating sequence, held still")
    else:
        print("static: solid color, held still")


def _color_text(colors: tuple[RGB, ...] | None) -> str:
    if not colors:
        return "none"
    parts: list[str] = []
    for rgb in colors:
        name = _COLOR_NAMES.get(rgb)
        rendered = _fmt_rgb(rgb)
        parts.append(f"{name} {rendered}" if name else rendered)
    return ", ".join(parts)


def _fmt_rgb(rgb: tuple[int, int, int]) -> str:
    return f"({rgb[0]}, {rgb[1]}, {rgb[2]})"


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _build_backend(settings: Settings) -> LightsBackend:
    if settings.backend == "lan":
        from house_lights.lan import LanBackend

        if not settings.ip:
            raise UsageError("LAN needs --ip or an ip key in --config")
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
