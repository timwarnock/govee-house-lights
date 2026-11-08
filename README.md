# House Lights

Local control for a Govee Permanent Outdoor Lights Pro (H706C). The computer talks to the lights over Bluetooth or the local LAN API. There is no need for a Govee cloud account and no API key.

The YAML is the definition of the lights. The default files are in `desired-state/`. The machine settings are `config.json` in this directory. That file is gitignored. Edit either one, then reinstall:

```bash
make install
```

`make install` creates `config.json` when it is missing, runs `make test`, installs the `house-lights` command, and restarts the daemon. The service stores the absolute path of this checkout, so run `make install` again if you move the directory. The daemon reads this project's `desired-state/` and `config.json`. It sleeps until the next sunrise, sunset, or midnight color change, sends what the YAML says for that moment, and closes Bluetooth.

`make config` only creates `config.json`. It calls ipinfo.io once for `lat`, `lon`, and `timezone`, prints the city, region, and country, and does not overwrite a file that is already there. If the lookup fails, it prints what to write yourself and `make install` stops. Once the file exists, edit it whenever you want and run `make install` again.

`make test` checks that the YAML loads and that `config.json` exists and has every field the daemon needs: `backend`, `lat`, `lon`, `timezone`, `sku`, `timeout`, `retries`, and `retry_delay`. A LAN backend also needs `ip`.

## Setup

Install [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer. Bluetooth needs a powered BlueZ adapter (`bluetoothctl show` reports `Powered: yes`). This program does not pair or bond the light.

- `backend` is `bluetooth` or `lan`. The helper writes `bluetooth`.
- `lat` and `lon` come from ipinfo.io. Change them if the city is wrong.
- `timezone` comes from ipinfo.io.
- For LAN, set `ip` to the light. For Bluetooth, set `ble_address` or leave it out and let a scan save one.
- `sku` is `H706C`. `timeout`, `retries`, and `retry_delay` are the radio settings.
- `enforce_minutes` is optional. Leave it out and the daemon does not correct the lights between edges.

Brightness is `brightness` in `desired-state/default.yaml`, one number from 1 to 100 for the whole string. It is not a config key.

The daemon is a systemd user service. It is not a timer: sunset is a different minute every day. Enable lingering so it keeps running without a login session:

```bash
loginctl enable-linger "$USER"
```

Quit the phone app before a Bluetooth command. The app holds the only connection.

## What you edit

| File | What it does |
| --- | --- |
| `config.json` | Backend, location, and timezone. Gitignored. Created by `make config`. |
| `desired-state/default.yaml` | Color when nothing else matches, and the brightness. |
| `desired-state/holidays.yaml` | One civil day each. The first match wins. |
| `desired-state/seasons.yaml` | Inclusive date ranges. A holiday wins over a season. |
| `desired-state/days/YYYY-MM-DD.yaml` | One civil date. It wins over holidays. |
| `desired-state/days/every-MM-DD.yaml` | That month and day every year. |

A shorter color list repeats from the plug. `description` on a day file is a note. It is not shown on the lights.

```yaml
- name: Example
  month: 7
  day: 4
  colors:
    - [255, 0, 0]
    - [255, 255, 255]
    - [0, 0, 255]
```

`prior_night: true` starts that color at sunset the evening before. `midnight: true` starts it at 00:00 and stops it at the next 00:00. Both together run from the previous sunset until 00:00 on the day after, and the midnight in the middle does not change the color. The shipped file sets those flags only on Easter and Christmas. The agreed rules, and the items that are still open, are in [SCHEDULE.md](SCHEDULE.md).

`easter: 0` is Easter Sunday. A negative number counts back from that Sunday. `nth` is `1` through `5`, or `last`, together with `weekday`.

The Christmas season shipped here is December 24 through December 26. That is the span the night actually changes on. December 1 through January 5 is not settled. Widen `desired-state/seasons.yaml` if you want the longer range.

A reboot does not send a night that already succeeded, so a later change from the phone stays. `make install` forgets that memory and applies the YAML for the current edge.

## Commands

```bash
house-lights preview --date 2026-12-25
house-lights preview --desired-state /path/to/yaml --date 2026-12-24
house-lights on --backend bluetooth
house-lights off --backend bluetooth
house-lights status --backend bluetooth
```

`preview` does not open the network or Bluetooth. Run from this directory and it reads `config.json`, then prints today's pattern, sunset, sunrise, and any midnight change. `on` sends the YAML color for that civil date now. The daemon is what keeps the string matched to the files from sunset through sunrise.

A color list repeats from the plug, one color per light. Bluetooth sends that list. A mixed list over LAN is sent as the first color only, and the command says so.

## Make targets

| Target | What it does |
| --- | --- |
| `make config` | Create `config.json` if it is missing. |
| `make test` | Validate `desired-state/` and `config.json`. |
| `make install` | Create `config.json` if it is missing, run the tests, install the command and the daemon, and apply the YAML. |
| `make uninstall` | Stop and remove the daemon and the command. The lights stay as they are. `config.json` stays. |
| `make clean` | Remove the local virtualenv and build output. |

## Development

```bash
uv sync
uv run house-lights preview --date 2026-07-04
```

Dependencies live in `pyproject.toml`. `uv.lock` pins them.
