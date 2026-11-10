"""Schedule presets. Pure Python, no Home Assistant imports.

Presets are named house-wide (e.g. Normal, Away, Vacation), but every room keeps its own week for
each preset and its own active preset. Switching "the house" to a preset just sets every room to
the preset with that name.

Stored data:
    presets:   ["Normal", "Vacation", ...]                 order as shown; never empty
    schedules: {room_id: {preset: week, ...}, ...}        week as in schedule.py
    active:    {room_id: preset}                          missing = the first preset
"""
from __future__ import annotations

import copy

from .schedule import MAX_TEMP, MIN_TEMP, default_schedule

DEFAULT_PRESET = "Normal"
MAX_NAME = 30


def migrate(data: dict) -> dict:
    """Fill in preset fields; 0.3.0 and older stored one week per room, which becomes Normal."""
    presets = [p for p in data.get("presets") or [] if isinstance(p, str) and p] or [DEFAULT_PRESET]
    schedules = {}
    for room_id, value in (data.get("schedules") or {}).items():
        schedules[room_id] = {presets[0]: value} if "mon" in value else value
    active = {r: p for r, p in (data.get("active") or {}).items() if p in presets}
    return {**data, "presets": presets, "schedules": schedules, "active": active}


def clean_name(name: str, presets: list[str], renaming: str | None = None) -> str:
    name = " ".join(str(name).split())
    if not name:
        raise ValueError("the preset needs a name")
    if len(name) > MAX_NAME:
        raise ValueError(f"the name is longer than {MAX_NAME} characters")
    if any(p.casefold() == name.casefold() and p != renaming for p in presets):
        raise ValueError(f"there is already a preset called {name}")
    return name


def _require(data: dict, name: str) -> None:
    if name not in data["presets"]:
        raise ValueError(f"no preset called {name}")


def active(data: dict, room_id: str) -> str:
    preset = data["active"].get(room_id)
    return preset if preset in data["presets"] else data["presets"][0]


def week(data: dict, room_id: str, preset: str, default_temp: float) -> dict:
    return data["schedules"].get(room_id, {}).get(preset) or default_schedule(default_temp)


def create(data: dict, name: str, room_ids: list[str], default_temp: float,
           copy_from: str | None = None, temperature: float | None = None) -> str:
    """New preset: every room gets a copy of its `copy_from` week, or `temperature` all week."""
    name = clean_name(name, data["presets"])
    if temperature is not None:
        temperature = float(temperature)
        if not MIN_TEMP <= temperature <= MAX_TEMP:
            raise ValueError(f"temperature {temperature} outside {MIN_TEMP}-{MAX_TEMP}")
    else:
        copy_from = copy_from or data["presets"][0]
        _require(data, copy_from)
    for room_id in set(room_ids) | set(data["schedules"]):
        if temperature is not None:
            new = default_schedule(round(temperature * 2) / 2)
        else:
            new = copy.deepcopy(week(data, room_id, copy_from, default_temp))
        data["schedules"].setdefault(room_id, {})[name] = new
    data["presets"].append(name)
    return name


def rename(data: dict, old: str, new: str) -> str:
    _require(data, old)
    new = clean_name(new, data["presets"], renaming=old)
    data["presets"] = [new if p == old else p for p in data["presets"]]
    for weeks in data["schedules"].values():
        if old in weeks:
            weeks[new] = weeks.pop(old)
    data["active"] = {r: new if p == old else p for r, p in data["active"].items()}
    return new


def delete(data: dict, name: str, room_names: dict[str, str]) -> None:
    """Refuses the last preset and a preset a room is using (room_names: room_id → name)."""
    _require(data, name)
    if len(data["presets"]) == 1:
        raise ValueError("the last preset can't be deleted")
    using = sorted(n for r, n in room_names.items() if active(data, r) == name)
    if using:
        raise ValueError(f"{name} is in use by {', '.join(using)}; switch them to another preset first")
    data["presets"].remove(name)
    for weeks in data["schedules"].values():
        weeks.pop(name, None)


def activate(data: dict, name: str, room_ids: list[str]) -> list[str]:
    """Set rooms to a preset; returns the rooms whose preset actually changed."""
    _require(data, name)
    changed = [r for r in room_ids if active(data, r) != name]
    for room_id in room_ids:
        data["active"][room_id] = name
    return changed
