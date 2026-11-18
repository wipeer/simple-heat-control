# The card

The integration loads the card itself. Add it to a dashboard:

```yaml
type: custom:simple-heat-control-card
# time_format: 24   # optional, 12 or 24; used only while Options → Time format is Automatic
```

It shows one row per room plus the Vaillant program (read only): the day's blocks coloured by temperature, a "now"
line, the status, the reason, the next change, the TRV setpoint and the valve position. Above the rooms, the
*House preset* chips switch every room (with a preview of each room's day before and after), and
*Manage presets…* creates, renames and deletes presets.

## Presets

A preset is a named set of weekly schedules, e.g. *Normal*, *Home*, *Away*, *Vacation*. Names are shared by the
whole house, but **every room has its own week in every preset** and its own active preset.

- **House preset** switches every room to the preset with that name at once. It shows that preset while all rooms
  use it, and *unknown* while they differ.
- **A room's preset** switches only that room (e.g. the guest room stays on *Away*).
- A new preset starts as a copy of another preset (each room keeps its own week) or as one temperature in every
  room all week (handy for *Vacation*). The last preset, and a preset a room is using, can't be deleted.

## Click a room

- **Override**: set the temperature (± buttons or type it), choose how long it lasts (30 min, 1, 2, 4 or 8 hours,
  until the schedule's next change, or until you clear it) and press *Set override*. *Back to schedule* ends it
  early. It survives a restart.
- Pick the preset to edit (✓ = the one the room follows now; *Use … in this room now* switches it).
- The whole week is shown as bars; click a day to edit its blocks (± buttons for the temperature, *Add block*
  splits the longest block).
- Copy a day to chosen days (quick picks Mon–Fri, Sat–Sun, all), or the whole week to another room and/or preset.
  Every copy, discard and preset switch first shows each affected day **before → after**, with changed blocks
  outlined, and only happens after you confirm.
- Days with unsaved changes are marked ●; leaving the editor or switching room/preset asks before throwing them
  away.

## ⚙ Options

Administrators only; shared by every browser and phone.

- **Mode**: live or dry run (going live asks first).
- **Time format**: automatic (the card's `time_format:`, else your HA profile), 24 h or 12 h.
- **Heating for the whole house**: a hysteresis, smart heating and an outdoor thermometer. When set here, every
  room uses them and its own setting is ignored; empty = each room uses its own.
- **Language**: automatic (Home Assistant's language), English, Čeština, or a loaded translation. It covers the
  card and the texts the integration computes (reasons, TRV actions, boiler status).

### Your own translation

*Export English (template)* downloads one `"key": "text"` per line. Translate the texts, keep everything in
`{curly braces}` unchanged, set `_language` (e.g. `de`, used for plural forms) and `_name`, then *Load from
file…* or paste it. Unknown keys are reported and ignored; missing texts stay English. A text can also be plural
forms, e.g. `{"one": "{n} day", "few": "{n} days", "other": "{n} days"}`.

Entity ids are made from entity names in HA's language when an entity is first created, so in a Czech Home
Assistant new entities get Czech-based ids. Existing ids don't change.
