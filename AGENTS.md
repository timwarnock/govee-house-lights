# AGENTS.md

`desired-state/` is the source of truth for the lights. Read those YAML files before any schedule work. Dates, colors, and brightness are whatever the files say. [SCHEDULE.md](SCHEDULE.md) describes how the daemon applies that directory. When the document and the YAML disagree, the YAML wins. Do not edit the YAML to match the document. When the user changes the YAML, update the document so it still describes the files.

Do not add a holiday, season, date, color, or brightness the user did not ask for. `config.json` in the repo root is gitignored and holds the machine settings. The daemon reads that directory and that file. Do not put those settings under the home directory.

Push and clone only through the timwarnock host:

```bash
git clone git@github-timwarnock:timwarnock/govee-house-lights.git
```

`github-timwarnock` uses `~/.ssh/id_rsa`. The default ssh-agent on this laptop often has only the rschristopher key. That key can read this public repo and cannot push. The gnome-keyring agent at `/run/user/1000/gcr/ssh` has the timwarnock key. Do not push with the rschristopher key.

Do not invent schedule rules. Do not turn the lights on or off unless the user asked for that command. A status read does not prove the per-light colors. The phone app takes the one Bluetooth link. This unit does not answer the LAN API.

Color lists go out as the still scene in `src/house_lights/still.py`: upload comm `0x02`, then scene `11183`. One palette color per light, repeating from the plug. Do not send a bare scene `0x003b`.

The runner is `house-lights daemon`. It sleeps until the next sunrise, sunset, or midnight color change, then sends what the YAML says. systemd only keeps that process alive. Do not schedule sunset with systemd timers. `make install` installs the CLI and the user service and can change the lights. Do not run it unless the user asked.
