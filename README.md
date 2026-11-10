# Heat Control for Home Assistant

A small custom integration (`heat_control`) that heats each room from its own temperature sensor and
starts the Vaillant boiler when any room needs heat — and shows **why** it does everything.

## How it works

Per room, every minute and whenever the room sensor changes:

1. **Target** = the room's weekly schedule in its active preset, or a manual override (until the next
   schedule change, or until cleared).
2. **Demand** (hysteresis, default 0.5 °C): heating starts when the room is 0.5 °C below the target and
   stops when it reaches the target.
3. **TRV**: while the room wants heat, the TRV gets `heat`, preset `manual` (so its own schedule can't
   interfere) and a regulated setpoint. While it doesn't, the TRV gets its minimum setpoint (valve
   closed) — switchable with *Close the valve when the room is warm*.
4. **Regulation** is the same as Versatile Thermostat 10.6.4 (`light`/`medium`/`strong`): the TRV sits
   next to the radiator and reads too warm, so its setpoint is raised by
   `kp·error + ki·accumulated error + k_ext·(room − outdoor)`, capped (medium: ±2 °C), recalculated every
   5 min.
5. **Convector relay** (optional) is on while the room wants heat.
6. **Stale sensor**: if the room sensor hasn't reported for *stale minutes* (default 180), the TRV gets
   the plain target and regulates on its own sensor; the room counts as wanting heat while the TRV
   reports `heating`.

Boiler: while any room wants heat, a myVaillant **quick veto** (default 28 °C for 0.5 h) is set on the
Vaillant zone and re-sent 5 min before it runs out; when no room wants heat it is cancelled. Cloud
calls are at most one per minute. The *Boiler control* switch off = never touch the boiler.

## Dry run

**On after a fresh install.** Everything is calculated and shown (targets, demand, reasons, the TRV
setpoint and boiler quick veto it *would* send), but nothing is sent to TRVs, relays or the boiler.
Each room's `actions` attribute and the card's *Recent actions* list the calls it would have made.

Switch it with the *Dry run* switch on the Heat Control boiler device or in the card's *Options*. Turning dry
run on cancels a real quick veto Heat Control had set. The setting is stored by Heat Control itself,
so it also holds for rooms before the boiler is set up.

## Presets

A preset is a named set of weekly schedules, e.g. *Normal*, *Home*, *Away*, *Vacation*. Preset names
are shared by the whole house, but **every room has its own week in every preset** and its own
active preset:

- **House preset** switches every room to the preset with that name at once (e.g. all rooms to
  *Vacation*). It shows that preset while all rooms use it, and *unknown* while they differ.
- **A room's preset** switches only that room (e.g. the guest room stays on *Away*).
- A room whose preset changes loses its manual override. Choosing the preset a room already uses
  changes nothing, so an automation can re-select it safely.
- A new preset starts as a copy of another preset (each room keeps its own week) or as one
  temperature in every room all week (handy for *Vacation*). Rename and delete are on the card;
  the last preset and a preset a room is using can't be deleted.
- After updating from 0.3.0, every room's existing week becomes the preset *Normal*.

Automations use the select entities, e.g.:

```yaml
action: select.select_option
target:
  entity_id: select.heat_control_boiler_house_preset   # or a room's Preset entity
data:
  option: Vacation
```

Renaming a preset changes the option name; automations that use the old name need updating.

## Entities

Entity ids depend on the device name and area HA gives them (e.g. a boiler device in the area
Koupelna gives `switch.koupelna_heat_control_boiler_dry_run`), so names are given here.

Per room (device = room name):
- room climate — on/off, target. Setting a temperature = override until the next schedule change.
  Preset `schedule` clears the override. Attributes hold everything: `reason`, `schedule_target`,
  `next_change`, `override`, `sensor_age_min`, `trv_setpoint`, `trv_action`, `trv_problem`,
  `regulation_detail` (p/i/ext parts of the offset), `last_error`.
- room *Heat demand* binary sensor — on while the room wants heat, with `reason`.
- room *Preset* select — the preset this room follows (also the `preset` attribute of the climate).

Boiler:
- boiler *Heat demand* binary sensor — on while any room wants heat; attributes say which
  rooms, the quick veto state, last cloud call and error.
- *Boiler control* switch — kill switch for boiler calls.
- *Dry run* switch — dry run for rooms and boiler (see above).
- *House preset* select — sets every room to one preset (see Presets). It lives on the boiler
  device, so it needs the boiler set up.

## Card

The integration loads the card itself. Add to a dashboard:

```yaml
type: custom:heat-control-card
# time_format: 24   # optional, 12 or 24; used only while Options → Time format is Automatic
```

### Options

*⚙ Options* at the top of the card (administrators only; shared by every browser and phone):

- **Mode**: live or dry run (going live asks first).
- **Time format**: automatic (the card's `time_format:`, else your HA profile), 24 h or 12 h.
- **Language**: automatic (Home Assistant's language), English, Čeština, or a loaded translation. It
  covers the card and the texts Heat Control computes (reasons, TRV actions, boiler status), so
  those attributes change language too. HA's own setup dialogs and entity names follow each user's
  HA language (`translations/en.json`, `translations/cs.json`).
- **Your own translation**: *Export English (template)* downloads
  [`lang/en.json`](custom_components/heat_control/lang/en.json): one `"key": "text"` per line.
  Translate the texts, keep everything in `{curly braces}` unchanged, set `_language` (e.g. `de`, used
  for plural forms) and `_name`, then *Load from file…* or paste it. Unknown keys are reported and
  ignored; missing texts stay English. A text can also be plural forms, e.g.
  `{"one": "{n} day", "few": "{n} days", "other": "{n} days"}`.

Entity ids are made from the entity names in HA's language when an entity is first created, so in a
Czech Home Assistant new entities get Czech-based ids (e.g. the House preset select). Existing ids
don't change.

One row per room plus the Vaillant program (read only): the day's blocks coloured by temperature, a
"now" line, status, reason, next change, TRV setpoint and valve position. Above the rooms, the
*House preset* chips switch every room (with a preview of each room's day before and after), and
*Manage presets…* creates, renames and deletes presets.

Click a room to set an override, turn it on/off, or edit its schedule:
- pick the preset to edit (✓ = the one the room follows now; *Use … in this room now* switches it);
- the whole week is shown as bars; click a day to edit its blocks (± buttons for the temperature,
  *Add block* splits the longest block);
- copy a day to chosen days (quick picks Mon–Fri / Sat–Sun / all), or copy the whole week to another
  room and/or preset. Every copy, discard and preset switch first shows each affected day **before →
  after**, with the changed blocks outlined, and only happens after you confirm;
- days with unsaved changes are marked ●; leaving the editor or switching room/preset asks before
  throwing them away.

New rooms start with 20 °C all week in every preset.

## Install

**HACS / Home Assistant Marketplace** (recommended): add `https://github.com/wipeer/simple-heat-control`
as a custom repository of type *Integration*, install *Simple Heat Control*, and restart Home
Assistant. Updates then show up like any other.

**By hand**: copy `custom_components/heat_control` from the latest release into your Home Assistant
`config/custom_components/` folder and restart Home Assistant.

Then *Settings → Devices & services → Add integration → Heat Control*: first *Set up the boiler*,
then *Add a room* once per room. It starts in dry run: check the card, then switch dry run off in
the card's *Options*.

**Before a room goes live**, stop anything else that drives the same TRV: turn off its Versatile
Thermostat, disable the Scheduler schedules that call it, and turn off VT's central boiler.

## License

[MIT](LICENSE). No warranty: this software switches your heating; check what it does in dry run
before going live.
