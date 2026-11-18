# How heating is decided

Every minute, and whenever a room sensor changes, each room goes through the same steps.

## 1. The room temperature

A room has one or more temperature sensors. With several, *With several sensors, use* decides:

| Setting | The room temperature is … |
|---|---|
| average (default) | the mean of the working sensors |
| coldest | the lowest |
| warmest | the highest |
| median | the middle one |
| backup | the first sensor; the others only stand in while it is stale or unavailable |

A sensor that hasn't reported for *Room sensor is stale after* (default 180 minutes) or is unavailable is left
out, and the reason says so, e.g. `· 1 of 3 sensors stale`.

## 2. The target

The target comes from the room's weekly schedule in its active preset (see [the card](card.md)). A manual
override replaces it until it ends: after a chosen time, at the schedule's next change, or until you clear it.
Overrides survive a restart.

## 3. Does the room want heat?

With a hysteresis of 0.5 °C (default):
- heating **starts** when the room is more than 0.5 °C below the target;
- heating **stops** when the room reaches the target;
- in between, whatever it was doing continues.

The reason shows the numbers, e.g. `19.2 < 21.0 − 0.5 → heat`. You can set the hysteresis per room, or once for
the whole house in the card's Options (the house value then wins).

## 4. Smart heating

When the boiler is running for another room, a room that doesn't ask for heat can take some of it, up to
target + 0.5 °C (default). It joins at or below *target + 0.5 − hysteresis* (with the defaults: at or below the
target) and a room that was heating on its own carries on past its target.

A room that only takes heat this way never asks the boiler itself, so it can't start it or keep it running; when
the last asking room is warm, it stops too. The card shows it as *smart heating*. Set it to 0 to turn it off.

## 5. The radiator valve (TRV)

While a room wants heat, its TRV is set to `heat`, preset `manual` (so its own schedule can't interfere) and a
**regulated setpoint**. The TRV sits next to the radiator and reads too warm, so the setpoint is raised above the
target until the *room* sensor, not the TRV, reaches it:

```
setpoint = target + kp · error + ki · accumulated error + k_ext · (room − outdoor)
```
capped (medium: ±2 °C) and recalculated every 5 minutes. The *TRV setpoint regulation* setting picks the strength:
off (plain target), light, medium (default) or strong. The formula and numbers are the same as in Versatile
Thermostat 10.6.4. An outdoor thermometer, per room or house-wide, sharpens it.

While a room doesn't want heat, the TRV gets its minimum setpoint (valve closed). Turn off *Close the valve when
the room is warm* to leave it on the regulated setpoint instead.

A convector relay, if set, is on while the room heats, smart heating included.

## 6. When the room sensors fail

If no room sensor has reported for the stale time, the TRV gets the plain target and regulates on its own sensor.
The room counts as wanting heat while the TRV reports `heating`.

## 7. The boiler

While any room asks for heat, a myVaillant **quick veto** (default 28 °C for 0.5 h) is set on the Vaillant zone. It
is re-sent 5 minutes before it runs out, and cancelled when no room asks. Cloud calls are at most one per minute.
The *Boiler control* switch off means the integration never touches the boiler.

## Dry run

On after a fresh install. Everything is calculated and shown, but nothing is sent to TRVs, relays or the boiler.
Each room's `actions` attribute and the card's *Recent actions* list the calls it would have made. Turning dry run
on cancels a quick veto Simple Heat Control had set.
