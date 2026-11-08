# AGENTS.md

Read [SCHEDULE.md](SCHEDULE.md) before any schedule work. It is the agreed design. It is not implemented.

Push and clone only through the timwarnock host:

```bash
git clone git@github-timwarnock:timwarnock/govee-house-lights.git
```

`github-timwarnock` uses `~/.ssh/id_rsa`. The default ssh-agent on this laptop often has only the rschristopher key. That key can read this public repo and cannot push. The gnome-keyring agent at `/run/user/1000/gcr/ssh` has the timwarnock key. Do not push with the rschristopher key.

Do not invent schedule rules. Do not turn the lights on or off unless the user asked for that command. A status read does not prove the per-light colors. The phone app takes the one Bluetooth link. This unit does not answer the LAN API.

The working Bluetooth paint is the still scene in `src/house_lights/still.py`: upload comm `0x02`, then scene `11183`. One palette color per light, repeating from the plug. Do not use `paint`. Do not send a bare scene `0x003b`.

The runner is a daemon that sleeps until the next sunrise or sunset. systemd only keeps that process alive. Do not schedule sunset with systemd timers. The daemon is not installed.
