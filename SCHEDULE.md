# Schedule

Agreed design for the house lights. The YAML in `desired-state/` is the definition. `config.json` in the repo root is gitignored and holds the machine settings. The daemon makes the string match that directory.

Do not add a rule that is not written here. Items under **Open** are not decided.

## Power

Every sunset turns the string on. Every sunrise turns it off. Sun times come from local `astral` (pinned 3.2) using the latitude, longitude, and timezone in `config.json`. No network lookup. Official sunrise and sunset (upper limb plus refraction).

Latitude and longitude live in the gitignored `config.json`. They are not committed.

If the phone app changes the lights later that night, leave them, unless enforce mode is on. There is no global midnight resend.

The Govee Home sunrise and sunset automation is a cloud rule. Disable it once this daemon owns the night. This H706C does not answer the LAN API. Bluetooth is the path that sets a color on each light.

## What a match sends

A color list may be any length. Fewer than 120 colors repeats from the plug until 120. The still-scene encoder refuses more than 77 distinct colors. That limit is an implementation fact, not a schedule rule.

`default.yaml` is warm white `(255, 197, 143)`. A season that would only be warm white is omitted, so those nights use the default. If nothing matches and there is no default file, sunset still turns the string on and sends no color list.

Brightness is the `brightness` key in `desired-state/default.yaml`. It is one number for the whole string. Per-entry brightness is not decided.

## Precedence

The default YAML lives in `desired-state/`. First hit wins.

1. `days/YYYY-MM-DD.yaml` for that civil date. Deferred. Do not add one-off day files unless asked.
2. `days/every-MM-DD.yaml` for that month and day, every year. The `every-` prefix keeps these files together when the directory is sorted.
3. The first matching entry in `holidays.yaml`.
4. The first matching entry in `seasons.yaml`.
5. `default.yaml`.

All of these files are optional.

A recurring file has a `description` field. It is informational only. It is not matched, not shown on the lights, and not sent. Example: `description: Michael's birthday` in `days/every-05-30.yaml`.

Other YAML key names are not decided. The behaviors below are decided.

## Prior night and midnight

These are independent. A holiday may set either, both, or neither. Sunset and sunrise still own power. A midnight boundary only changes the color list while the lights are already on.

* **Neither.** Sunset on the holiday sends that color list. It stays through the next sunrise.
* **Prior night.** That color list starts at sunset the evening before and stays through the sunrise after the holiday.
* **Midnight.** The color list starts at 00:00 on the holiday, if the lights are on, and stops at the next 00:00.
* **Both.** The color list starts at sunset the evening before and stops at 00:00 on the day after the holiday. The midnight in the middle of that span does not change the color. The morning after does not keep it.

Christmas uses midnight and does not use the prior night.

* December 24 sunset until midnight: the Christmas season, classic multicolor. Red `(255, 0, 0)`, green `(0, 255, 0)`, blue `(0, 0, 255)`, orange `(255, 165, 0)`.
* December 25 at midnight: white `(255, 255, 255)` and gold `(255, 215, 0)`.
* Those colors stay up through Christmas morning, go off at sunrise, and come back on at Christmas sunset.
* December 26 at midnight: the Christmas season returns until sunrise.

Easter uses the prior night only. The vigil starts at Saturday sunset and the same white and gold stay through Easter morning. No midnight cut. Western Easter is the Gregorian computus. 2026 is April 5. Chicago keeps Ascension on the Sunday, Easter plus 42 days, not Thursday.

No other holiday is assigned a prior night or a midnight boundary.

## Daemon

The process owns the clock. It computes the next sunrise, sunset, or midnight color change and sleeps until that absolute wall time, so a reboot or a wake from suspend lands on the right action. It closes Bluetooth after each send.

systemd starts it at boot and restarts it if it dies. A user service needs `loginctl enable-linger` for the user who owns the Bluetooth session. systemd timers are the wrong tool: sunset is a different minute every day.

Optional enforce, off unless configured: wake every N minutes, read status, and correct anything that disagrees with the declaration. Status can see power and brightness. It cannot see the 120-light color list, so enforce mode resends that list. Each check holds the radio for about 30 seconds. N should be several minutes if the phone still needs to connect between checks.

On startup, apply the current phase if that edge has not succeeded. Remember a succeeded edge so a later restart leaves a phone change in place. `make install` clears that memory and restarts the user service. The service reads `desired-state/` and `config.json` in the project, so an edited file is applied.

## Holidays

A holiday is one civil day. Colors below are agreed. A shorter list repeats from the plug.

Holy Week and Easter outrank a fixed feast on the same civil date, because the first matching holiday entry wins. Put those rows first. Annunciation stays on March 25 when it is not also Good Friday or Palm Sunday.

| Holiday | When | Colors |
| --- | --- | --- |
| New Year's Day | January 1 | gold `(255, 215, 0)`, white `(255, 255, 255)` |
| Epiphany | January 6 | gold, royal purple `(102, 0, 153)`, crimson `(153, 0, 51)` |
| Candlemas | February 2 | white, amber `(255, 176, 46)` |
| Presidents Day | third Monday of February | red, white, blue |
| St. Patrick | March 17 | deep green `(0, 132, 61)`, gold |
| St. Joseph | March 19 | brown `(121, 85, 61)`, white, gold |
| Annunciation | March 25 | blue `(0, 56, 168)`, white |
| Palm Sunday | Easter minus 7 days | red, green `(0, 128, 0)` |
| Good Friday | Easter minus 2 days | deep red `(153, 0, 0)` |
| Easter | Gregorian computus | white, gold. Prior night on. |
| Ascension | Easter plus 42 days (Sunday) | white, sky blue `(135, 206, 235)` |
| Pentecost | Easter plus 49 days | red, gold |
| Memorial Day | last Monday of May | red, white, blue |
| Independence Day | July 4 | red, white, blue |
| Assumption | August 15 | blue, white, gold |
| Columbus Day | second Monday of October | green `(0, 146, 70)`, white, red `(206, 43, 55)` |
| All Saints | November 1 | white, gold |
| All Souls | November 2 | violet `(102, 0, 153)` |
| Veterans Day | November 11 | red, white, blue |
| Thanksgiving | fourth Thursday of November | orange `(255, 140, 0)`, gold, brown `(139, 90, 43)` |
| Immaculate Conception | December 8 | blue, white |
| Our Lady of Guadalupe | December 12 | rose `(196, 98, 90)`, teal `(0, 128, 128)`, gold |
| Christmas | December 25 | white, gold, from midnight. See above. |

Removed on purpose: Juneteenth, Martin Luther King Jr. Day, Labor Day, Halloween, Valentine's Day.

US dates are the calendar holiday. A Monday holiday is that Monday. July 4 stays July 4 when it falls on a weekend.

## Seasons

A season loses to a holiday. These three are the proposal. The Christmas range is not locked. The season has to include December 24, because that evening is multicolor until midnight, and it has to be in effect again after midnight on December 26.

| Season | Proposed range | Colors |
| --- | --- | --- |
| Lent | Ash Wednesday through the day before Easter | violet `(102, 0, 153)` |
| Eastertide | the day after Easter through the day before Pentecost | white, gold |
| Christmas | December 1 through January 5, not confirmed | red, green, blue, orange |

Omitted, so the night stays warm white: Advent, Ordinary Time, and a summer flag season.

In 2026 the proposed dates are Lent February 18–April 4, Eastertide April 6–May 23, and Christmas December 1–January 5. Holidays inside those ranges still win.

## Open

* Christmas season start and end. December 1 through January 5 is only a proposal.
* New Year's was recommended as the same midnight shape as Christmas: December 31 stays the season until midnight, then gold and white until the next midnight. Not confirmed.
* A July 3 prior night for Independence Day was proposed and not confirmed.
* No holiday besides Christmas and Easter has a prior-night or midnight assignment. All Saints into All Souls was only a suggestion.
* YAML key names, except `description`.
* Where the house latitude and longitude live.
* The enforce interval, if any.
