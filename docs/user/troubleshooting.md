# Troubleshooting

Start with the room's **reason** (card row, or the `reason` attribute of its climate entity) and **TRV action**
(`trv_action`). In dry run, the card's *Recent actions* list shows what would have been sent.

## Reading the reasons

| Reason | Meaning |
|---|---|
| `19.2 < 21.0 − 0.5 → heat` | the room is colder than target minus hysteresis: asking for heat |
| `20.8 < 21.0, heating until target` | already heating, continues until the target is reached |
| `20.8 ≥ 21.0 − 0.5 → no heat` | inside the hysteresis band while not heating: stays off |
| `21.0 ≥ 21.0 → no heat` | target reached |
| `… → smart heating to 21.5` | the boiler runs for another room and this one takes some of it |
| `room sensor stale (no update for 200 min) → TRV on its own sensor` | no fresh room reading; the TRV regulates itself |
| `… · valve closed` | the room doesn't want heat and the TRV was set to its minimum |
| `… · 1 of 3 sensors stale` | some sensors were left out of the room temperature |
| `room switched off` | the room's climate is off |

## A room doesn't heat

1. **Is dry run on?** (Dry run switch or the card's Options.) Then nothing is sent by design.
2. **Is the room off?** Check the room climate's mode.
3. **Is the sensor stale?** `sensor_readings` shows each sensor's age and whether it is fresh. After the stale time,
   the TRV runs on its own sensor.
4. **TRV problem?** `trv_problem` says *TRV unavailable*, or *TRV shows X° but Y° was sent* when the valve hasn't
   taken the setpoint after about 3 minutes.
5. **Is something else driving the TRV?** A Versatile Thermostat or a Scheduler schedule will fight it.
6. `last_error` on the room shows the last failed call.

## The boiler doesn't start

1. The **Heat demand** sensor on the boiler device should be on, listing the asking rooms. If not, no room asks (a
   room that only takes heat through smart heating doesn't ask).
2. **Boiler control** switch off means the boiler is never touched. Dry run on means it is only simulated.
3. The boiler's `last_call` and `last_error` attributes show the last myVaillant call and any error. Calls are
   limited to one per minute.
4. Check that the *Boiler climate* is the myVaillant zone and that the myVaillant integration works on its own.

## Who kept the boiler on?

The *Heat requested by* sensor lists the asking rooms; its `log` attribute has the last 30 starts and stops with each
room's reason (empty after a restart), and Home Assistant's history of the sensor goes back further.
