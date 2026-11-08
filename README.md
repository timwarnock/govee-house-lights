# House Lights

Local command-line control for Tim Warnock's Govee Permanent Outdoor Lights Pro, model **H706C** (200 ft). The laptop talks to the lights on the home network or over Bluetooth. There is no Govee cloud account, no API key, and no telemetry.

One Python interface, `LightsBackend`, has two implementations:

- `--backend lan` speaks the official local LAN UDP API.
- `--backend bluetooth` wraps the published package `govee-ble-local` 1.10.0.

The scheduler and the `on` / `off` / `status` commands call that interface and do not care which backend is plugged in.

The agreed schedule is [SCHEDULE.md](SCHEDULE.md). It is not built yet. `src/house_lights/holidays.py` is the old preview table. Do not treat that table as the schedule.

The lights are already on Wi-Fi at **192.168.0.119**. The Wi-Fi MAC for this install is **D4-13-68-B6-D3-92**. That MAC is not used as the Bluetooth address. Pass `--ble-address`, or let a scan save one.

## Install on Ubuntu

Python 3.11 or newer, plus BlueZ for the Bluetooth backend:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip bluez
sudo systemctl enable --now bluetooth
```

The adapter has to be powered. `bluetoothctl show` should report `Powered: yes`. This program does not pair or bond the light. `govee-ble-local` connects on its own when a command runs.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Do not install `govee-ble-local[cloud]`. That extra is not a dependency here.

Check holiday dates with no lights in reach:

```bash
python -m unittest discover -s tests -v
house-lights preview --date 2026-07-04
house-lights preview --date 2026-12-25
house-lights preview --date 2026-12-31
house-lights preview --date 2026-01-01
```

`python -m house_lights` is the same entry point as `house-lights`.

## Flags

Flags are enough. `--config path.json` is optional; any flag you pass replaces the same key in the file. See `config.example.json`.

| Flag | Default | Role |
| --- | --- | --- |
| `--backend {lan,bluetooth}` | required for hardware commands | which implementation to construct |
| `--ip` | `192.168.0.119` | LAN unicast address |
| `--ble-address` | saved address, else scan | Bluetooth address |
| `--sku` | `H706C` | model passed to `create_device` |
| `--lat`, `--lon` | none | required together for `run` |
| `--timezone` | `America/Chicago` | civil dates and sun times |
| `--brightness` | `70` | percent, 1–100 |
| `--segments` | device read, else library profile | Bluetooth segment override |
| `--timeout` | `8` | seconds for a BLE scan or a LAN status reply |
| `--retries` | `3` | extra tries after a failed command |
| `--retry-delay` | `1` | seconds between those tries |
| `--poll-interval` | `60` | seconds between scheduler checks |
| `--scan` | off | Accepted. Bluetooth always scans before connect |
| `--ble-cache` | `~/.local/state/house-lights/ble.json` | last BLE address and SKU |
| `--date` | today | `preview` and `on` only, `YYYY-MM-DD` |
| `--grid` | none | `paint` only, JSON file of per-light colors |
| `--verbose` | off | debug log |

`run` refuses to start until both `--lat` and `--lon` are present (flags or config). This repo does not store a home coordinate.

## LAN backend

Source: [Govee LAN API guide](https://app-h5.govee.com/user-manual/wlan-guide).

The guide's preparation step is to turn on the LAN switch in the device settings page of Govee Home. This client then:

1. Joins UDP multicast `239.255.255.250`, sends the documented `scan` JSON to port **4001**, and listens on port **4002**.
2. Sends control JSON by unicast UDP to `--ip` port **4003**.

Commands implemented, and no others: `scan`, `turn`, `brightness`, `devStatus`, `colorwc`.

`colorwc` paints **one** RGB color or **one** color temperature on the whole device. The guide says a non-zero `colorTemInKelvin` replaces RGB, and `0` means the device uses `r`, `g`, and `b`. This client always sends `colorTemInKelvin: 0` plus one RGB triple.

A holiday look with several colors does not become per-bulb color over LAN. The client sends the **first** color of the sequence to the whole device and logs that mixed colors need `--backend bluetooth`.

The supported-products section of the LAN guide, as fetched while writing this file, names many SKUs including H706A and does not clearly name H706C. The LAN commands above are still the only ones sent to `192.168.0.119`. Try them:

```bash
house-lights status --backend lan
house-lights on --backend lan --date 2026-07-04
house-lights off --backend lan
house-lights run --backend lan --lat LAT --lon LON
```

`LAT` and `LON` are your decimal-degree coordinates. A missing scan reply does not change the target IP. Each LAN command also spends up to 2 seconds (or `--timeout`, if that is shorter) waiting for a scan packet, then sends the unicast command to the configured IP. `status` waits up to `--timeout` for a `devStatus` reply on port 4002. Port 4002 needs to be free.

## Bluetooth backend

Package: [`govee-ble-local` 1.10.0 on PyPI](https://pypi.org/project/govee-ble-local/1.10.0/). Wheel inspected for this repo:

<https://files.pythonhosted.org/packages/74/c5/fc5a0dd4e76e4b8836eefa97b69bbca9797d03fa04c5bd6daefcc80cf013/govee_ble_local-1.10.0-py3-none-any.whl>

The publisher-declared repository <https://github.com/Brady-Woods/govee-ble-local> returned **HTTP 404** on 2026-11-07. Behavior below is taken from that PyPI long description and from the installed 1.10.0 sources, not from a GitHub checkout.

H706C is on the modelled row with H706A, H706B, H806A, and H806C (`support: modelled` in the generated device table, goods type 180). `profile_for("H706C")` is `None` until `allow_modelled=True`. Discovery and `create_device` in this CLI always pass `allow_modelled=True`.

This string advertises an encrypted pact `(2, 1)` and its BGC characteristic reports AES-GCM version 2. `govee-ble-local` 1.10.0 connects and then refuses that handshake. `house_lights.gcm_link` adds it: an `e7 11` handshake, then each 20-byte library frame is sealed with AES-GCM. On 2026-11-07 the outdoor string `Govee_H706C_481F` (`C0:EA:B6:8A:48:1F`) accepted a 16-byte tag. A status read came back on, brightness 100, 24 segments. A brightness write to 40 and back to 100 was accepted. The library's static segment count for this model is still 12; the device-reported count was 24.

The modelled row's capabilities include power, brightness, RGB, color temperature, and segments. A single-color pattern calls `set_rgb`. A multi-color pattern uploads a still rgbic scene (comm `0x02`, one light per color) and activates scene `11183`. On 2026-11-07 the outdoor string showed that as red, white, blue, one light at a time, from the plug through the far end.

### Segment count

Do not treat any one number as a proven H706C segment count.

- In `govee-ble-local` 1.10.0 the modelled H706C profile's static `segments` value is **12** (`num_segments` on the goods-type 180 wire row, `ic_pieces: fixed`). `Device.segment_count` uses a runtime read when it has one.
- The same profile has `special_info_read`. The library's own docstring says goods type 180 reports its count on the `ac a1` special-info read, and `set_segment_rgb` asks for that read when no count has been set yet. `update()` includes that read. A caller count set with `set_segment_count` stands until the next read of that count.
- `set_segment_count` rejects values outside `1..112` on this color scheme (`build.MAX_MASK_SEGMENTS` / `piece_cap("h60a6")`). Passing `--segments 120` raises `GoveeBleInvalidValue` from the library.
- A retailer listing titles the white 200 ft H706C kit as "200ft with 120 RGBIC LED Lights" and lists 120 light sources, model H706C: <https://www.amazon.com/dp/B0DX1WPB9J>. The [Govee US product page](https://us.govee.com/products/govee-rgbicww-led-permanent-outdoor-lights) names H706C as the 200 ft model. The page fetched for this README did not state a light count. 120 physical lights are not the same thing as the library's 12-segment wire default, and 120 is above the 112-segment mask cap, so **120 is not the default**.

A multi-color `on` does not read or write the segment count. `--segments` does not change that pattern.

```bash
house-lights status --backend bluetooth
house-lights on --backend bluetooth --ble-address AA:BB:CC:DD:EE:FF --date 2026-12-25
house-lights run --backend bluetooth --lat LAT --lon LON
```

The second Bluetooth run can omit `--ble-address` when the cache already has the SKU. Every Bluetooth command scans first. Connecting from the saved address alone leaves BlueZ in `Connect` until the library's 45 second limit, which is the `operation exceeded 45s` failure.

## Per-light grid

`set_segment_rgb` paints a whole controller segment: five lights, one color. A physical 10-light piece plus its connector is two of those segments. `paint` sends a 120-light picture instead, one color per light, using the Govee app's Finger Sketch layout.

That layout was traced on an H70C5 and replayed over LAN there (`gdeboos/ha-liday-show`, `docs/govee-protocols.md`). `govee-ble-local` marks H706C DIY untraced, so this client builds the same bytes and sends them over Bluetooth. The picture is effect `0x0f` (Gradient) at speed `0`, which holds still on the H70C5. Several other effect bytes turn that string off, so `paint` does not take an effect flag. Brightness in the picture is `--brightness` (`100` is byte `0x64`). The upload is an `0xA3` kind `0x03`, then the show packet `33 05 0a 20 03`. The show packet is sent only after the upload ack.

On 2026-11-07 this string (`C0:EA:B6:8A:48:1F`) acked a 9-packet upload (`a3 03 00`) and the show packet (`33 05 00`) for `grids/rwb.json` at brightness 100. The house showed solid red, the picture's background color, so this controller did not apply the per-light groups. The per-segment red, white, blue pattern was written back and read back as 24 segments. `status` still cannot read per-light color.

The JSON file is an object with a `lights` array, or the array itself. Each entry is `[r, g, b]`, `#rrggbb`, or a name (`red`, `white`, `blue`, `green`, `black`, `gold`, `pink`, `purple`, `orange`, `warm white`). A list of 120 is used as-is. A shorter list is repeated when its length divides 120, so three entries become light, light, light along the string from the plug. Light 0 is the plug end. Bulbs are all listed; the header background is the most common color, ties going to the one that appears first.

`grids/rwb.json` is red, white, blue. LAN `colorwc` cannot paint a grid, so `paint --backend lan` stops without sending a color.

```bash
house-lights paint --backend bluetooth --grid grids/rwb.json --brightness 100
```

If the upload or the show packet fails, `paint` puts the per-segment red, white, blue pattern back. Quit the Govee phone app first. It takes the one Bluetooth link, and a later phone session can overwrite the picture. `status` still prints `color: unknown` for a per-light picture.

## What the Bluetooth library already does

From the 1.10.0 README and `Device` docstrings:

- `discover(timeout=..., supported_only=True, allow_modelled=False)` and `create_device(..., allow_modelled=False, write_copies=1)`.
- `connect()` is optional. The first operation connects. The link is reused.
- The link drops `idle_disconnect` seconds after the last operation (default 8). After a command the warm window is `ACTIVE_IDLE_DELAY` (30 seconds).
- While the link is up the device sends the profile keep-alive read every 2 seconds. Those reads do not extend the idle window.
- `release()` drops the link now; the next operation reconnects. `stop()` closes the device for good.
- `register_callback` reports state changes. This CLI does not replace any of that.

This CLI adds only the pieces that package does not document as surviving a process restart:

- a JSON file with the last BLE address and SKU, so the next scan can require that address
- a short retry around a failed command (`--retries`), which still uses the library connection rather than a second connection manager

`close` calls `stop()` when the process leaves. Between scheduler polls the library's own idle timer drops the link.

## Night schedule

`run` turns the lights **on from local sunset to local sunrise**, and **off during the day**. Sun times come from [astral](https://pypi.org/project/astral/). The pattern follows the local civil date, including the hours after midnight: 00:30 on January 1 uses the New Year look if the sun is still down.

A phase that already succeeded is not sent again until the date or the day/night phase changes. A failed step is retried on the next poll (`--poll-interval`, default 60 seconds). Each command inside the step has its own `--retries`.

`on` does not wait for sunset. It turns the lights on immediately and paints the pattern for `--date` or for today. `off` only turns them off.

`preview` prints the pattern and does not open a socket or a Bluetooth adapter. Add `--lat` and `--lon` if you also want sunrise and sunset for that date.

## Holiday looks

The rows below are what `preview` and `on` do today. The schedule to build is [SCHEDULE.md](SCHEDULE.md).

All of these are static. On Bluetooth a mixed pattern repeats one light per color from the plug and leaves it. A single color fills the string. Nothing blinks, chases, or strobes.

Edit the table in `src/house_lights/holidays.py` (`TABLE` and the `Pattern` colors). First matching row wins.

| Dates | Name | Sequence |
| --- | --- | --- |
| December 1–26 | Classic Christmas | red `(255, 0, 0)`, green `(0, 255, 0)`, blue `(0, 0, 255)`, orange/yellow `(255, 165, 0)` |
| July 4 | Independence Day | red, white `(255, 255, 255)`, blue |
| December 31 and January 1 | New Year's | gold `(255, 215, 0)`, white |
| October 31 | Halloween | orange `(255, 95, 0)`, purple `(128, 0, 255)` |
| February 14 | Valentine's Day | red, pink `(255, 105, 180)` |
| every other date | Default night | warm white `(255, 197, 143)` |

December 31 is New Year's, not Christmas. December 27 through December 30 use the default night color.

## Layout

```
src/house_lights/backend.py      LightsBackend protocol
src/house_lights/lan.py          official LAN UDP
src/house_lights/bluetooth.py    govee-ble-local wrapper
src/house_lights/holidays.py     editable still patterns
src/house_lights/grid.py         120-light JSON grid and Finger Sketch bytes
grids/rwb.json                   red, white, blue, repeated to 120 lights
src/house_lights/schedule.py     sunset to sunrise
src/house_lights/ble_store.py    address file
src/house_lights/cli.py          house-lights / python -m house_lights
tests/                           pattern, LAN fallback, scheduler, CLI preview
```

## Sources

- LAN API: <https://app-h5.govee.com/user-manual/wlan-guide>
- `govee-ble-local` 1.10.0: <https://pypi.org/project/govee-ble-local/1.10.0/>
- H706C product page (200 ft model name): <https://us.govee.com/products/govee-rgbicww-led-permanent-outdoor-lights>
- Retailer listing that states 120 lights for the 200 ft H706C kit: <https://www.amazon.com/dp/B0DX1WPB9J>
- Sun calculations: <https://pypi.org/project/astral/>
