"""One room: schedule → target → demand → TRV setpoint and convector relay."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CoreState, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLOSE_WHEN_SATISFIED, CONF_HYSTERESIS, CONF_NAME, CONF_OUTDOOR_SENSOR, CONF_REGULATION,
    CONF_RELAY, CONF_SENSOR_MODE, CONF_STALE_MINUTES, CONF_TEMP_SENSOR, CONF_TRV, CONF_VALVE_POSITION,
    DEFAULT_CLOSE_WHEN_SATISFIED, DEFAULT_HYSTERESIS, DEFAULT_REGULATION, DEFAULT_SENSOR_MODE,
    DEFAULT_STALE_MINUTES, REGULATION_PERIOD_MIN, TICK_SECONDS,
)
from .demand import decide, fmt
from .regulation import Regulator, Result, round_to_step
from .schedule import ScheduleState, state_at
from .sensors import combine

if TYPE_CHECKING:
    from .hub import Hub

_LOGGER = logging.getLogger(__name__)
TRV_RETRY = timedelta(minutes=5)       # don't resend the same setpoint more often than this
TRV_ACCEPT_GRACE = timedelta(minutes=3)  # after this, a TRV still showing another setpoint "didn't accept"


def _float(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


class RoomController:
    def __init__(self, hass: HomeAssistant, hub: Hub, room_id: str, options: dict[str, Any]) -> None:
        self.hass = hass
        self.hub = hub
        self.room_id = room_id
        self.name: str = options[CONF_NAME]
        sensors = options[CONF_TEMP_SENSOR]
        # one or more room sensors; older entries stored a single entity id
        self.temp_sensors: list[str] = [sensors] if isinstance(sensors, str) else list(sensors)
        self.sensor_mode: str = options.get(CONF_SENSOR_MODE, DEFAULT_SENSOR_MODE)
        self.trv: str = options[CONF_TRV]
        self.valve_sensor: str | None = options.get(CONF_VALVE_POSITION) or None
        self.relay: str | None = options.get(CONF_RELAY) or None
        # the room's own values; while the house sets one in Options, the house value is used
        self.own_outdoor_sensor: str | None = options.get(CONF_OUTDOOR_SENSOR) or None
        self.own_hysteresis: float = float(options.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS))
        self.close_when_satisfied: bool = options.get(CONF_CLOSE_WHEN_SATISFIED, DEFAULT_CLOSE_WHEN_SATISFIED)
        self.stale_minutes: float = float(options.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES))
        self.regulator = Regulator(options.get(CONF_REGULATION, DEFAULT_REGULATION))

        # state shown in HA
        self.hvac_on = True
        self.demand = False
        self.reason = hub.t("reason.starting")
        self.room_temp: float | None = None
        self.sensor_age_min: float | None = None
        self.sensor_readings: list[dict] = []
        self.stale = False
        self.outdoor_temp: float | None = None
        self.schedule_state: ScheduleState | None = None
        self.override: dict | None = None
        self.target: float | None = None
        self.regulation: Result | None = None
        self.setpoint: float | None = None
        self.trv_action = hub.t("trv.not_run")
        self.trv_problem: str | None = None
        self.last_sent_setpoint: float | None = None
        self.last_sent_at: datetime | None = None
        self.last_error: str | None = None
        self.valve_position: float | None = None
        self.last_evaluated: datetime | None = None
        self.actions: deque[dict] = deque(maxlen=10)  # what was sent (or would be, in dry run)

        self._last_regulation: datetime | None = None
        self._lock = asyncio.Lock()
        self._unsubs: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []

    # ---- lifecycle -------------------------------------------------------------------------
    async def async_start(self) -> None:
        # a house outdoor sensor isn't watched: the minute tick reads it, which is often enough
        watched = [e for e in (*self.temp_sensors, self.trv, self.valve_sensor, self.own_outdoor_sensor, self.relay) if e]
        self._unsubs.append(async_track_state_change_event(self.hass, watched, self._on_state_change))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=TICK_SECONDS)))
        if self.hass.state is CoreState.running:
            self.hass.async_create_task(self.async_evaluate(force=True))
        else:
            # A plain lambda would run in a worker thread; @callback keeps it on the event loop.
            @callback
            def _started(_event: Event) -> None:
                self.hass.async_create_task(self.async_evaluate(force=True))

            self._unsubs.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _started))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def _on_state_change(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        # our own TRV/relay writes come back as state changes; only re-run the logic for inputs
        if entity_id in self.temp_sensors or entity_id == self.own_outdoor_sensor:
            self.hass.async_create_task(self.async_evaluate())
        else:
            self._read_outputs()
            self._notify()

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_evaluate()

    # ---- controls from entities / websocket ---------------------------------------------------
    async def async_set_hvac(self, on: bool) -> None:
        self.hvac_on = on
        if on:
            self.regulator.reset()
            self._last_regulation = None
        await self.async_evaluate(force=True)

    # ---- the logic ----------------------------------------------------------------------------
    @callback
    def _read_outputs(self) -> None:
        self.valve_position = _float(self.hass.states.get(self.valve_sensor)) if self.valve_sensor else None
        trv = self.hass.states.get(self.trv)
        if trv is None or trv.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self.trv_problem = self.hub.t("trv.problem_unavailable")
            return
        self.trv_problem = None
        trv_target = trv.attributes.get("temperature")
        if (self.last_sent_at and self.last_sent_setpoint is not None and trv_target is not None
                and abs(float(trv_target) - self.last_sent_setpoint) >= 0.25
                and dt_util.now() - self.last_sent_at > TRV_ACCEPT_GRACE):
            self.trv_problem = self.hub.t("trv.problem_mismatch", shown=trv_target, sent=self.last_sent_setpoint)

    async def async_evaluate(self, force: bool = False) -> None:
        async with self._lock:
            try:
                await self._evaluate(force)
            except Exception as err:  # keep the room running; show the error instead of dying
                _LOGGER.exception("%s: evaluation failed", self.name)
                self.last_error = f"{type(err).__name__}: {err}"
        self._notify()
        await self.hub.async_update_boiler()

    @property
    def hysteresis(self) -> float:
        house = self.hub.options.get("hysteresis")
        return float(house) if house is not None else self.own_hysteresis

    @property
    def outdoor_sensor(self) -> str | None:
        return self.hub.options.get("outdoor_sensor") or self.own_outdoor_sensor

    def _read_room_sensors(self, now: datetime) -> None:
        readings = []
        for entity_id in self.temp_sensors:
            state = self.hass.states.get(entity_id)
            age = None
            if state is not None:
                seen = getattr(state, "last_reported", None) or state.last_updated
                age = round((now - seen).total_seconds() / 60, 1)
            readings.append((_float(state), age))
        result = combine(readings, self.sensor_mode, self.stale_minutes)
        self.room_temp = result.value
        self.stale = result.value is None
        self.sensor_readings = [{"entity_id": e, "value": v, "age_min": a, "fresh": i in result.fresh,
                                 "used": i in result.used}
                                for i, (e, (v, a)) in enumerate(zip(self.temp_sensors, readings))]
        # the oldest reading the value comes from; when all are stale, the newest there is
        ages = [readings[i][1] for i in result.used] or [a for _, a in readings if a is not None]
        self.sensor_age_min = (max(ages) if result.used else min(ages)) if ages else None

    async def _evaluate(self, force: bool) -> None:
        now = dt_util.now()
        self.last_evaluated = now
        self.schedule_state = state_at(self.hub.get_schedule(self.room_id), now)
        self.override = self.hub.get_override(self.room_id)
        if self.override and self.override.get("until"):
            until = dt_util.parse_datetime(self.override["until"])
            if until is not None and until <= now:
                await self.hub.async_clear_override(self.room_id, evaluate=False)
                self.override = None
        self.target = float(self.override["temperature"]) if self.override else self.schedule_state.target

        self._read_room_sensors(now)
        self.outdoor_temp = _float(self.hass.states.get(self.outdoor_sensor)) if self.outdoor_sensor else None

        trv = self.hass.states.get(self.trv)
        self._read_outputs()
        was_demand = self.demand
        t = self.hub.t

        if not self.hvac_on:
            self.demand = False
            self.reason = t("reason.room_off")
            self.setpoint = None
            await self._apply_trv(trv, "off", None, force)
        elif self.stale:
            # without a room reading, let the TRV regulate on its own sensor at the plain target
            self.demand = bool(trv and trv.attributes.get("hvac_action") == "heating")
            age = (t("reason.stale_no_reading") if self.sensor_age_min is None
                   or all(r["value"] is None for r in self.sensor_readings)
                   else t("reason.stale_age", minutes=f"{self.sensor_age_min:.0f}"))
            self.reason = t("reason.stale", age=age, target=fmt(self.target))
            self.setpoint = self.target
            await self._apply_trv(trv, "heat", self.setpoint, force)
        else:
            self.demand, key, params = decide(was_demand, self.room_temp, self.target, self.hysteresis)
            self.reason = t(key, **params)
            stale_count = sum(not r["fresh"] for r in self.sensor_readings)
            if stale_count:
                self.reason = t("reason.sensors_partial", reason=self.reason, stale=stale_count,
                                total=len(self.sensor_readings))
            if self.demand or not self.close_when_satisfied:
                due = (force or self.demand != was_demand or self._last_regulation is None
                       or now - self._last_regulation >= timedelta(minutes=REGULATION_PERIOD_MIN))
                if due or self.setpoint is None:
                    periods = 1.0
                    if self._last_regulation is not None:
                        periods = (now - self._last_regulation).total_seconds() / 60 / REGULATION_PERIOD_MIN
                    self.regulation = self.regulator.calculate(self.target, self.room_temp, self.outdoor_temp, periods)
                    self._last_regulation = now
                    self.setpoint = self.regulation.setpoint
            else:
                self.setpoint = self._trv_min(trv)
                self.reason = t("reason.valve_closed", reason=self.reason)
            await self._apply_trv(trv, "heat", self.setpoint, force or self.demand != was_demand)

        await self._apply_relay(self.demand and self.hvac_on)

    # ---- outputs ------------------------------------------------------------------------------
    @staticmethod
    def _trv_min(trv: State | None) -> float:
        return float(trv.attributes.get("min_temp", 5.0)) if trv else 5.0

    def _log(self, text: str) -> None:
        # newest last. In dry run nothing changes on the device, so the same calls come back every
        # minute; those are listed once.
        if self.hub.dry_run and any(a["text"] == text for a in self.actions):
            return
        if not self.actions or self.actions[-1]["text"] != text:
            self.actions.append({"at": dt_util.now().strftime("%H:%M:%S"), "text": text})

    async def _call(self, domain: str, service: str, data: dict) -> bool:
        args = ", ".join(f"{v}" for k, v in data.items() if k != "entity_id")
        if self.hub.dry_run:
            self._log(self.hub.t("action.dry", call=f"{domain}.{service} {data.get('entity_id')} {args}".rstrip()))
            return True
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
            self._log(f"{domain}.{service} {data.get('entity_id')} {args}".rstrip())
            return True
        except Exception as err:
            self.last_error = f"{domain}.{service}: {err}"
            _LOGGER.warning("%s: %s.%s %s failed: %s", self.name, domain, service, data, err)
            return False

    async def _apply_trv(self, trv: State | None, mode: str, setpoint: float | None, force: bool) -> None:
        if trv is None or trv.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self.trv_action = self.hub.t("trv.unavailable_nothing_sent")
            return
        if mode == "off":
            if trv.state != "off" and "off" in trv.attributes.get("hvac_modes", []):
                await self._call("climate", "set_hvac_mode", {"entity_id": self.trv, "hvac_mode": "off"})
                self.trv_action = self.hub.t("trv.dry_off" if self.hub.dry_run else "trv.off")
            else:
                self.trv_action = self.hub.t("trv.off")
            return
        if trv.state != "heat":
            await self._call("climate", "set_hvac_mode", {"entity_id": self.trv, "hvac_mode": "heat"})
        presets = trv.attributes.get("preset_modes") or []
        if "manual" in presets and trv.attributes.get("preset_mode") != "manual":
            # otherwise the TRV's own schedule can overwrite our setpoint
            await self._call("climate", "set_preset_mode", {"entity_id": self.trv, "preset_mode": "manual"})

        step = float(trv.attributes.get("target_temp_step") or 0.5)
        low = float(trv.attributes.get("min_temp", 5.0))
        high = float(trv.attributes.get("max_temp", 30.0))
        value = min(high, max(low, round_to_step(setpoint, step)))
        self.setpoint = value
        current = trv.attributes.get("temperature")
        now = dt_util.now()
        differs = current is None or abs(float(current) - value) >= step / 2
        recently_sent_same = (self.last_sent_setpoint == value and self.last_sent_at is not None
                              and now - self.last_sent_at < TRV_RETRY)
        if self.hub.dry_run:
            if differs:
                await self._call("climate", "set_temperature", {"entity_id": self.trv, "temperature": value})
            self.trv_action = (self.hub.t("trv.dry_send", value=value, current=current) if differs
                               else self.hub.t("trv.already", value=value))
        elif differs and (force or not recently_sent_same):
            if await self._call("climate", "set_temperature", {"entity_id": self.trv, "temperature": value}):
                self.last_sent_setpoint = value
                self.last_sent_at = now
                self.last_error = None
            self.trv_action = self.hub.t("trv.sent", value=value)
        else:
            self.trv_action = self.hub.t("trv.at" if not differs else "trv.waiting", value=value)

    async def _apply_relay(self, on: bool) -> None:
        if not self.relay:
            return
        state = self.hass.states.get(self.relay)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if (state.state == "on") != on:
            domain = self.relay.split(".")[0]
            await self._call(domain, "turn_on" if on else "turn_off", {"entity_id": self.relay})

    # ---- for entities and the card --------------------------------------------------------------
    def attributes(self) -> dict[str, Any]:
        s = self.schedule_state
        r = self.regulation
        return {
            "room_id": self.room_id,
            "dry_run": self.hub.dry_run,
            "demand": self.demand,
            "reason": self.reason,
            "preset": self.hub.active_preset(self.room_id),
            "schedule_target": s.target if s else None,
            "next_change": s.next_change.isoformat() if s and s.next_change else None,
            "next_target": s.next_target if s else None,
            "override": self.override,
            "room_sensors": self.temp_sensors,
            "sensor_mode": self.sensor_mode,
            "sensor_readings": self.sensor_readings,
            "hysteresis": self.hysteresis,
            "outdoor_sensor": self.outdoor_sensor,
            "sensor_age_min": self.sensor_age_min,
            "sensor_stale": self.stale,
            "outdoor_temperature": self.outdoor_temp,
            "trv": self.trv,
            "trv_setpoint": self.setpoint,
            "trv_action": self.trv_action,
            "trv_problem": self.trv_problem,
            "valve_position": self.valve_position,
            "regulation": self.regulator.mode,
            "regulation_detail": None if r is None else {
                "error": round(r.error, 2), "accumulated_error": round(r.accumulated_error, 2),
                "p": round(r.offset_p, 2), "i": round(r.offset_i, 2), "ext": round(r.offset_ext, 2),
                "offset": round(r.offset, 2),
            },
            "last_sent_at": self.last_sent_at.isoformat() if self.last_sent_at else None,
            "last_error": self.last_error,
            "actions": list(self.actions),
            "last_evaluated": self.last_evaluated.isoformat() if self.last_evaluated else None,
        }
