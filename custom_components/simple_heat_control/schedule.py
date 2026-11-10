"""Weekly schedules. Pure Python, no Home Assistant imports.

A schedule is {"mon": [["00:00", 21.5], ["06:00", 23.0], ...], "tue": [...], ...}.
Each day is a list of change points sorted by time; the first one must be 00:00.
A point's temperature holds until the next point (or the end of the day).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MIN_TEMP = 5.0
MAX_TEMP = 30.0


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    value = int(hours) * 60 + int(minutes)
    if not 0 <= value < 24 * 60 or int(minutes) >= 60:
        raise ValueError(f"time out of range: {hhmm}")
    return value


def default_schedule(temp: float) -> dict:
    return {day: [["00:00", float(temp)]] for day in DAYS}


def validate(schedule: dict) -> dict:
    """Return a normalised copy, or raise ValueError saying what is wrong."""
    if not isinstance(schedule, dict):
        raise ValueError("schedule must be an object")
    out: dict = {}
    for day in DAYS:
        points = schedule.get(day)
        if not isinstance(points, list) or not points:
            raise ValueError(f"{day}: needs at least one block")
        parsed = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError(f"{day}: each block is [\"HH:MM\", temperature]")
            minute = _minutes(str(point[0]))
            temp = float(point[1])
            if not MIN_TEMP <= temp <= MAX_TEMP:
                raise ValueError(f"{day} {point[0]}: temperature {temp} outside {MIN_TEMP}-{MAX_TEMP}")
            parsed.append((minute, round(temp * 2) / 2))
        parsed.sort()
        if parsed[0][0] != 0:
            raise ValueError(f"{day}: first block must start at 00:00")
        if len({m for m, _ in parsed}) != len(parsed):
            raise ValueError(f"{day}: two blocks start at the same time")
        out[day] = [[f"{m // 60:02d}:{m % 60:02d}", t] for m, t in parsed]
    return out


@dataclass(frozen=True)
class ScheduleState:
    target: float
    block_start: datetime
    next_change: datetime | None  # None when the temperature never changes in the next 7 days
    next_target: float | None


def _day_points(schedule: dict, day_index: int) -> list[tuple[int, float]]:
    return [(_minutes(t), float(v)) for t, v in schedule[DAYS[day_index]]]


def state_at(schedule: dict, now: datetime) -> ScheduleState:
    """Target at `now` and the next time the target actually changes."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minute_now = now.hour * 60 + now.minute
    points = _day_points(schedule, now.weekday())
    current = points[0]
    for point in points:
        if point[0] <= minute_now:
            current = point
    target = current[1]
    block_start = midnight + timedelta(minutes=current[0])

    for day_offset in range(0, 8):
        day_midnight = midnight + timedelta(days=day_offset)
        for minute, temp in _day_points(schedule, (now.weekday() + day_offset) % 7):
            when = day_midnight + timedelta(minutes=minute)
            if when <= now:
                continue
            if temp != target:
                return ScheduleState(target, block_start, when, temp)
    return ScheduleState(target, block_start, None, None)
