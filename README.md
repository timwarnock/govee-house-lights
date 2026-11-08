# House Lights

Local control for a Govee Permanent Outdoor Lights Pro (H706C). The computer talks to the lights over Bluetooth or the local LAN API. There is no need for a Govee cloud account and no API key.

The YAML is the definition of the lights. The default files are in `desired-state/`. Edit those files, then reinstall:

```bash
make install
```

`make install` runs `make test`, installs the `house-lights` command, copies `desired-state/` to `~/.local/share/house-lights/desired-state`, and restarts the daemon. The daemon sleeps until the next sunrise, sunset, or midnight color change, sends what the YAML says for that moment, and closes Bluetooth. That is how the string is kept matched to the files.

`--desired-state /path/to/directory` uses another directory of the same files. A `desired_state` key in the config file does the same for the daemon. The command-line flag wins when both are set. Leave the key out to use the installed default.

`make test` checks that the YAML loads: file names, dates, and colors. A file that the program cannot read fails the test, and the install stops.

## Setup

Install [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer. Bluetooth needs a powered BlueZ adapter (`bluetoothctl show` reports `Powered: yes`). This program does not pair or bond the light.

```bash
cp config.example.json ~/.config/house-lights/config.json
```

Edit that file before the first install that should start the lights.

- `backend` is `bluetooth` or `lan`.
- `lat` and `lon` are decimal degrees for local sunrise and sunset. Leave them out of the repo. Put them only in the config file.
- `timezone` defaults to `America/Chicago`.
- For LAN, set `ip` to the light. For Bluetooth, set `ble_address` or leave it out and let a scan save one.
- `brightness` defaults to 70.
- `desired_state` is an optional path to another directory of YAML files. Leave it out to use the installed default.

`make install` copies `config.example.json` into place when that file is missing. It does not overwrite a config you have already edited. The service stays off until `backend`, `lat`, and `lon` are set. A LAN backend also needs `ip`.

The daemon is a systemd user service. It is not a timer: sunset is a different minute every day. Enable lingering so it keeps running without a login session:

```bash
loginctl enable-linger "$USER"
```

Quit the phone app before a Bluetooth command. The app holds the only connection.

## What you edit

| File | What it does |
| --- | --- |
| `desired-state/default.yaml` | Color when nothing else matches. |
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
house-lights preview --desired-state /path/to/yaml --date 2026-12-25
house-lights preview --date 2026-12-24 --lat LAT --lon LON
house-lights on --backend bluetooth
house-lights off --backend bluetooth
house-lights status --backend bluetooth
```

`preview` does not open the network or Bluetooth. With `lat` and `lon` it also prints sunset colors and any midnight change. `on` sends the YAML color for that civil date now. The daemon is what keeps the string matched to the files from sunset through sunrise.

A color list repeats from the plug, one color per light. Bluetooth sends that list. A mixed list over LAN is sent as the first color only, and the command says so.

## Make targets

| Target | What it does |
| --- | --- |
| `make test` | Run the tests and validate `desired-state/`. |
| `make install` | Run the tests, install the command and the daemon, and apply the YAML. |
| `make uninstall` | Stop and remove the daemon and the command. The lights stay as they are. The config file stays. |
| `make clean` | Remove the local virtualenv and build output. |

## Development

```bash
uv sync
uv run house-lights preview --date 2026-07-04
```

Dependencies live in `pyproject.toml`. `uv.lock` pins them.
