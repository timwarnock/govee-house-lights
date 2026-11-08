# Schedule

How the daemon applies `desired-state/`.

That directory is the source of truth for dates, colors, and brightness. This file describes the mechanism. When this file and the YAML disagree, the daemon sends the YAML. Edit the YAML to change the lights, then update this file so the description still matches. Do not edit the YAML to match this file.

`config.json` in the repo root is gitignored. It holds the machine settings: backend, latitude, longitude, timezone, and the radio. It is not the light definition.

## Files

| File | What it holds |
| --- | --- |
| `desired-state/default.yaml` | Colors and brightness when nothing else matches. |
| `desired-state/holidays.yaml` | One civil day per entry. The first matching entry wins. |
| `desired-state/seasons.yaml` | Inclusive ranges. A holiday wins over a season. |
| `desired-state/days/YYYY-MM-DD.yaml` | One civil date. It wins over holidays. |
| `desired-state/days/every-MM-DD.yaml` | That month and day every year. |

All of these files are optional. The `days/` directory in this repo has no day files. `description` on an entry is a note. It is not matched and it is not sent.

Read the YAML for the current names, dates, colors, and brightness. A summary in this file can go stale. The file cannot.

## Colors

The color list comes from the first match:

1. `days/YYYY-MM-DD.yaml` for a night that started at that date's sunset.
2. `days/every-MM-DD.yaml` for that month and day.
3. The first holiday whose window covers the moment.
4. The first season that contains the civil date.
5. `default.yaml`.

A shorter list repeats from the plug, one color per light. The still-scene encoder refuses more than 77 distinct colors. That limit is in the sender. If nothing matches and there is no default file, sunset still turns the string on and sends no color list.

`house-lights preview` prints the civil-date match for `--date`. Sunset and midnight in that output use the windows above, so they can name a different entry than the date line.

## Brightness

Brightness is one number for the whole string, from 1 to 100. It is its own field. The same order applies, and the first entry that sets `brightness` wins. An entry that omits the key leaves the number for the next entry. `default.yaml` is last. A missing key there, or a missing default file, means 100.

The numbers in the current files are the numbers in those files.

## Power

Every sunset turns the string on. Every sunrise turns it off. Sun times come from local `astral` (pinned 3.2) using the latitude, longitude, and timezone in `config.json`. There is no network lookup for the sun. The calculation is official sunrise and sunset, upper limb plus refraction.

A change made from the phone stays until the next edge, unless `enforce_minutes` is set in `config.json`. There is no separate midnight resend of the whole night.

The Govee Home sunrise and sunset automation is a cloud rule. Disable it once this daemon owns the night. This H706C does not answer the LAN API. Bluetooth is the path that sets a color on each light.

## Holiday windows

`prior_night` and `midnight` are independent. A holiday may set either, both, or neither. Sunset and sunrise still own power. Which entries set the flags is in `holidays.yaml`.

* **Neither.** Sunset on the holiday sends that color list. It stays through the next sunrise.
* **Prior night.** The list starts at sunset the evening before and stays through the sunrise after the holiday.
* **Midnight.** The list starts at 00:00 on the holiday, while the lights are on, and stops at the next 00:00.
* **Both.** The list starts at sunset the evening before and stops at 00:00 on the day after the holiday. The midnight in the middle of that span does not change the color.

A season rolling from one civil date to the next at midnight is not a color boundary. A midnight wake happens when a holiday window starts or ends at that midnight and the color list or the brightness actually changes.

A holiday date is a fixed `month` and `day`, an `easter` offset in days, or `month` plus `weekday` and `nth`. `easter: 0` is Easter Sunday on the Gregorian computus. A negative offset counts back from that Sunday. `nth` is `1` through `5`, or `last`. Movable rows are listed first in the file so they beat a fixed feast on the same civil date.

## Daemon

The process owns the clock. It computes the next sunrise, sunset, or midnight color change and sleeps until that absolute wall time. A reboot or a wake from suspend lands on the edge that is due. It closes Bluetooth after each send.

systemd starts it at boot and restarts it if it dies. A user service needs `loginctl enable-linger` for the user who owns the Bluetooth session. systemd timers do not schedule sunset. Sunset is a different minute every day.

`enforce_minutes` is optional and off when the key is absent. When it is set, the process wakes on that interval, reads status, and corrects power and brightness. Status cannot see the 120-light color list, so the check resends that list. Each check holds the radio for about 30 seconds.

On startup the process applies the current edge if that edge has not already succeeded. The succeeded edge is `desired-state/daemon.json`. A later restart leaves a phone change in place. `make install` deletes that file and restarts the service, which sends the current edge from the YAML.

## Not in the files

These ideas have been discussed and are not in `desired-state/`. Add one only when the user asks for it. This list is not a backlog to implement.

* A midnight boundary on New Year's Day.
* A prior night on July 3 for Independence Day.
* Joining All Saints and All Souls into one window.
* Juneteenth, Martin Luther King Jr. Day, Labor Day, Halloween, and Valentine's Day.
