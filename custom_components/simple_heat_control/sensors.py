"""Combining several room temperature sensors into one reading. Pure Python, no Home Assistant imports.

A reading is (value, age in minutes); value None = unavailable. A reading is fresh when it has a value
and is not older than `stale_minutes`. Stale readings are always left out.

Modes:
    average  mean of the fresh readings
    coldest  lowest fresh reading
    warmest  highest fresh reading
    median   middle fresh reading (mean of the two middle ones for an even count)
    backup   the first fresh reading in the order the sensors were chosen: the first sensor is the
             main one, the others stand in only while it is stale or unavailable
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median

MODES = ("average", "coldest", "warmest", "median", "backup")


@dataclass(frozen=True)
class Combined:
    value: float | None      # None when no reading is fresh
    used: tuple[int, ...]    # indexes of the readings the value comes from
    fresh: tuple[int, ...]   # indexes of all fresh readings


def combine(readings: list[tuple[float | None, float | None]], mode: str, stale_minutes: float) -> Combined:
    fresh = tuple(i for i, (value, age) in enumerate(readings)
                  if value is not None and age is not None and age <= stale_minutes)
    if not fresh:
        return Combined(None, (), ())
    values = [readings[i][0] for i in fresh]
    if mode == "backup":
        return Combined(values[0], (fresh[0],), fresh)
    if mode == "coldest":
        i = min(fresh, key=lambda j: readings[j][0])
        return Combined(readings[i][0], (i,), fresh)
    if mode == "warmest":
        i = max(fresh, key=lambda j: readings[j][0])
        return Combined(readings[i][0], (i,), fresh)
    if mode == "median":
        return Combined(round(median(values), 2), fresh, fresh)
    return Combined(round(mean(values), 2), fresh, fresh)  # average, and any unknown mode
