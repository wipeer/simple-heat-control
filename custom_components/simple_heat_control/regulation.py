"""TRV setpoint regulation. Pure Python, no Home Assistant imports.

Same formula and parameters as Versatile Thermostat 10.6.4 (pi_algorithm.py, const.py), so the
TRVs behave as they did under VT:

    setpoint = target + clamp(kp*error + ki*accumulated_error + k_ext*(room - outdoor), +-offset_max)

The TRV measures next to the radiator and reads too warm; raising its setpoint by this offset
makes it keep the valve open until the room sensor, not the TRV, reaches the target.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    kp: float
    ki: float
    k_ext: float
    offset_max: float
    accumulated_error_threshold: float


PARAMS = {
    "off": None,
    "light": Params(0.2, 0.05, 0.05, 1.5, 10),
    "medium": Params(0.3, 0.05, 0.1, 2.0, 20),
    "strong": Params(0.4, 0.08, 0.0, 5.0, 50),
}


@dataclass
class Result:
    setpoint: float
    error: float
    accumulated_error: float
    offset_p: float
    offset_i: float
    offset_ext: float
    offset: float  # after clamping


class Regulator:
    def __init__(self, mode: str) -> None:
        if mode not in PARAMS:
            raise ValueError(f"unknown regulation mode {mode}")
        self.mode = mode
        self.params = PARAMS[mode]
        self.accumulated_error = 0.0

    def reset(self) -> None:
        self.accumulated_error = 0.0

    def calculate(self, target: float, room: float, outdoor: float | None, time_delta: float) -> Result:
        """time_delta is the time since the last calculation in regulation periods (1.0 = one period)."""
        p = self.params
        if p is None:
            return Result(target, target - room, 0.0, 0.0, 0.0, 0.0, 0.0)
        if time_delta > 2.0:  # VT: a long gap counts as one period
            time_delta = 1.0
        error = target - room
        # VT's overheat protection: when the error changes sign, shrink the accumulator fast
        if error * self.accumulated_error < 0:
            self.accumulated_error = self.accumulated_error / (2.0 * max(time_delta, 0.5))
        self.accumulated_error += error * time_delta
        limit = p.accumulated_error_threshold
        self.accumulated_error = min(limit, max(-limit, self.accumulated_error))
        offset_p = p.kp * error
        offset_i = p.ki * self.accumulated_error
        offset_ext = p.k_ext * (room - outdoor) if outdoor is not None else 0.0
        offset = min(p.offset_max, max(-p.offset_max, offset_p + offset_i + offset_ext))
        return Result(round(target + offset, 1), error, self.accumulated_error,
                      offset_p, offset_i, offset_ext, offset)


def round_to_step(value: float, step: float) -> float:
    return round(round(value / step) * step, 3)
