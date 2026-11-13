"""Room heat demand with hysteresis. Pure Python, no Home Assistant imports.

Heating starts when the room falls `hysteresis` below the target and stops when the room
reaches the target. In between, the previous state holds.

Smart heating (`join`) lets a room that doesn't ask for heat take some anyway while the boiler is
already heating for another room.
"""
from __future__ import annotations


def fmt(value: float) -> str:
    return f"{value:.1f}"


def decide(previous: bool, room: float, target: float, hysteresis: float) -> tuple[bool, str, dict]:
    """Return (demand, reason text key, its placeholders); the key is looked up in lang/*.json."""
    params = {"room": fmt(room), "target": fmt(target), "hysteresis": fmt(hysteresis)}
    if room < target - hysteresis:
        return True, "reason.heat", params
    if room >= target:
        return False, "reason.no_heat", params
    if previous:
        return True, "reason.heating_until", params
    return False, "reason.no_heat_band", params


def join(previous: bool, room: float, target: float, extra: float, hysteresis: float,
         others_heating: bool) -> bool:
    """Smart heating: while the boiler heats for another room, this room may take some of that heat.

    It joins at or below `target + extra − hysteresis` and keeps going until `target + extra`. A room that
    was heating on its own (`previous` covers that too) just carries on to `target + extra`. It never
    asks the boiler for heat itself, so it can't keep the boiler running.
    """
    if extra <= 0 or not others_heating:
        return False
    top = target + extra
    if room >= top:
        return False
    return previous or room <= top - hysteresis
