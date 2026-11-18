# Simple Heat Control: user guide

Simple Heat Control heats each room from its own temperature sensors and starts a Vaillant boiler (through
the myVaillant integration) when any room needs heat. Everything it does comes with a reason you can read.

| Page | What's in it |
|---|---|
| [How heating is decided](how-it-works.md) | schedule, target, hysteresis, smart heating, TRV setpoint, the boiler |
| [Setup and settings](settings.md) | every field when adding a room or the boiler, and what the defaults are |
| [Entities and automations](entities-and-automations.md) | what Home Assistant gets, with automation examples |
| [The card](card.md) | the dashboard card: schedules, presets, overrides, options, languages |
| [Troubleshooting](troubleshooting.md) | reading the reasons, and what to check when a room doesn't heat |

New here? Install it (see the [README](../../README.md)), add the boiler, then one room. It starts in **dry run**:
it calculates and shows everything it would do, but sends nothing to any device. Watch the card for a while,
then switch dry run off.
