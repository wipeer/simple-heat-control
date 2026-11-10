"""Room heat demand with hysteresis. Pure Python, no Home Assistant imports.

Heating starts when the room falls `hysteresis` below the target and stops when the room
reaches the target. In between, the previous state holds.
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
