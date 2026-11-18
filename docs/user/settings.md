# Setup and settings

Add the integration under *Settings → Devices & services → Add integration → Simple Heat Control*. Choose
**Set up the boiler** first (once), then **Add a room** for each room. Change any setting later with *Configure* on
the entry (a room's name is fixed).

## Room

| Field | Default | Meaning |
|---|---|---|
| Name | | shown on the card and used for the room's device |
| Room temperature sensors | | one or more temperature sensors, away from the radiator; the first is the main one for *backup* |
| With several sensors, use | average | average, coldest, warmest, median or backup |
| Radiator valve (TRV) | | the `climate` entity of the valve |
| Valve position sensor | none | optional, shown on the card |
| Convector fan relay | none | optional switch, light or input boolean, on while the room heats |
| Outdoor temperature sensor | none | optional; ignored while the house sets one in Options |
| TRV setpoint regulation | medium | off, light, medium, strong |
| Hysteresis | 0.5 °C | 0.1 to 2.0; ignored while the house sets one in Options |
| Smart heating | 0.5 °C | 0 to 2.0, 0 = off; ignored while the house sets one in Options |
| Close the valve when the room is warm | on | |
| Room sensor is stale after | 180 min | 15 to 1440 |

New rooms start with 20 °C all week in every preset.

## Boiler

| Field | Default | Meaning |
|---|---|---|
| Boiler climate | | the myVaillant zone's `climate` entity |
| Quick veto temperature | 28 °C | 15 to 30 |
| Quick veto duration | 0.5 h | 0.5 to 12 |
| Boiler status sensor | none | optional, shown on the card |

Only one boiler can be set up. The boiler device also carries the *Dry run* and *Boiler control* switches, the
*House preset* select, and the heat demand sensors.

## House-wide options

On the card, under *⚙ Options* (administrators only, shared by every browser): live or dry run, time format, a
house-wide hysteresis, smart heating and outdoor thermometer, and the language. See [the card](card.md).

## Before a room goes live

Stop anything else that drives the same TRV: turn off its Versatile Thermostat, disable Scheduler schedules that
call it, and turn off VT's central boiler. Then switch dry run off.
