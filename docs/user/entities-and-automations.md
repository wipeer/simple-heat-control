# Entities and automations

Entity ids depend on the device name and area Home Assistant gives them, and on HA's language when they were
created (a boiler device in the area Koupelna gives `switch.koupelna_simple_heat_control_boiler_dry_run`). Look yours up
under *Settings → Devices & services → Simple Heat Control*; the names below are what to look for.

## Per room (device = room name)

- **Climate** (the room's name): on/off and target. Setting a temperature is an override until the schedule's next
  change. Preset `schedule` clears the override. Attributes hold everything:
  `reason`, `schedule_target`, `next_change`, `next_target`, `override`, `preset`, `sensor_readings` (each sensor's
  value, age, whether fresh and whether used), `sensor_age_min`, `trv_setpoint`, `trv_action`, `trv_problem`,
  `valve_position`, `regulation_detail` (the p, i and ext parts of the offset), `smart_heating_active`,
  `actions` (recent calls, or would-be calls in dry run), `last_error`.
- **Heat demand** binary sensor: on while the room wants heat, with `reason`.
- **Preset** select: the preset this room follows.

## Boiler device

- **Heat demand** binary sensor: on while any room asks for heat. Attributes: which rooms, the quick veto state, the
  last cloud call, the last error.
- **Heat requested by** sensor: the names of the rooms asking for heat now, or "nobody". Attributes `rooms`,
  `count`, `since`, and `log`: the last 30 times a room started or stopped asking, newest first, each with the room's
  reason. Home Assistant's history and logbook record every change of the state; `log` itself is kept in memory
  and is empty after a restart. Rooms that only take heat through smart heating don't ask, so they aren't listed.
- **Boiler control** switch: off = never touch the boiler.
- **Dry run** switch: dry run for all rooms and the boiler.
- **House preset** select: sets every room to one preset; shows *unknown* while rooms use different presets.

## Automation examples

Switch the whole house to a preset:

```yaml
action: select.select_option
target:
  entity_id: select.simple_heat_control_boiler_house_preset   # yours may differ
data:
  option: Vacation
```

Switch one room: use that room's *Preset* select the same way. Choosing the preset a room already uses changes
nothing, so an automation can re-select it safely. A room whose preset changes loses its manual override.

Override a room for 90 minutes: the card does it, and from scripts the websocket command
`simple_heat_control/override/set` takes `room_id`, `temperature` and one of `minutes` or `until` (an ISO time, or
null for no end).

Renaming a preset changes the option name; update automations that use the old name.

## History and notifications

Because *Heat requested by* changes whenever a room starts or stops asking, its history shows who kept the boiler
busy and when. A state-change trigger on it works for "tell me when the boiler starts for the guest room".
