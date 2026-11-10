"""Boiler: any room with demand → myVaillant quick veto; no demand → cancel it.

The Vaillant only listens to its own living-room thermostat, so a quick veto at a high
temperature forces it to heat. It runs out by itself after `quick_veto_hours`; while rooms still
ask for heat it is re-sent shortly before it ends. Calls go to the myVaillant cloud, so they are
kept rare (at most one per BOILER_MIN_CALL_SECONDS).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    BOILER_MIN_CALL_SECONDS, BOILER_REFRESH_BEFORE_MIN, CONF_BOILER_CLIMATE, CONF_BOILER_STATUS_SENSOR,
    CONF_VETO_HOURS, CONF_VETO_TEMP, DEFAULT_VETO_HOURS, DEFAULT_VETO_TEMP, TICK_SECONDS,
)

if TYPE_CHECKING:
    from .hub import Hub

_LOGGER = logging.getLogger(__name__)


class BoilerController:
    def __init__(self, hass: HomeAssistant, hub: Hub, options: dict[str, Any]) -> None:
        self.hass = hass
        self.hub = hub
        self.climate: str = options[CONF_BOILER_CLIMATE]
        self.status_sensor: str | None = options.get(CONF_BOILER_STATUS_SENSOR) or None
        self.veto_temp = float(options.get(CONF_VETO_TEMP, DEFAULT_VETO_TEMP))
        self.veto_hours = float(options.get(CONF_VETO_HOURS, DEFAULT_VETO_HOURS))

        self.enabled = True
        self.demand = False
        self.rooms: list[str] = []
        self.active = False  # a quick veto we set is believed to be running
        self.simulated = False  # `active` only comes from dry run; nothing was really sent
        self.veto_until: datetime | None = None
        self.last_call: datetime | None = None
        self.last_call_text: str | None = None
        self.last_error: str | None = None
        self.reason = hub.t("boiler.starting")

        self._lock = asyncio.Lock()
        self._unsubs: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=TICK_SECONDS)))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_apply()

    async def async_set_demand(self, rooms: list[str]) -> None:
        changed = rooms != self.rooms
        self.rooms = rooms
        self.demand = bool(rooms)
        if changed:
            await self.async_apply()

    async def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        await self.async_apply()

    def _can_call(self, now: datetime) -> bool:
        return self.last_call is None or (now - self.last_call).total_seconds() >= BOILER_MIN_CALL_SECONDS

    async def async_leave_dry_run(self) -> None:
        """Forget the pretend quick veto so the real one is sent if rooms still want heat."""
        if self.simulated:
            self.active = False
            self.veto_until = None
            self.simulated = False
            self.last_call = None
        await self.async_apply()

    async def async_enter_dry_run(self) -> None:
        """A real quick veto we set is cancelled before going quiet."""
        async with self._lock:
            if self.active and not self.simulated:
                now = dt_util.now()
                self.last_call = now
                try:
                    await self.hass.services.async_call(
                        "mypyllant", "cancel_quick_veto", {"entity_id": self.climate}, blocking=True)
                    self.last_call_text = self.hub.t("boiler.cancel_dry_on", time=now.strftime("%H:%M"))
                    self.active = False
                    self.veto_until = None
                except Exception as err:
                    self.last_error = f"mypyllant.cancel_quick_veto: {err}"
        await self.async_apply()

    async def _call(self, service: str, data: dict, text: str, now: datetime) -> bool:
        self.last_call = now
        if self.hub.dry_run:
            self.simulated = True
            self.last_error = None
            self.last_call_text = self.hub.t("boiler.call_dry", what=text, time=now.strftime("%H:%M"))
            return True
        self.simulated = False
        try:
            await self.hass.services.async_call("mypyllant", service, {"entity_id": self.climate, **data}, blocking=True)
        except Exception as err:
            self.last_error = f"mypyllant.{service}: {err}"
            _LOGGER.warning("boiler: mypyllant.%s failed: %s", service, err)
            return False
        self.last_error = None
        self.last_call_text = self.hub.t("boiler.call_done", what=text, time=now.strftime("%H:%M"))
        return True

    async def async_apply(self) -> None:
        async with self._lock:
            now = dt_util.now()
            t = self.hub.t
            if not self.enabled:
                if self.active and self._can_call(now) and await self._call("cancel_quick_veto", {}, t("boiler.what_cancel"), now):
                    self.active = False
                self.reason = t("boiler.control_off")
            elif self.demand:
                asked = ", ".join(self.rooms)
                due = (not self.active or self.veto_until is None
                       or now >= self.veto_until - timedelta(minutes=BOILER_REFRESH_BEFORE_MIN))
                if due and self._can_call(now):
                    text = t("boiler.what_veto", temperature=f"{self.veto_temp:g}", hours=f"{self.veto_hours:g}")
                    if await self._call("set_quick_veto",
                                        {"temperature": self.veto_temp, "duration_hours": self.veto_hours}, text, now):
                        self.active = True
                        self.veto_until = now + timedelta(hours=self.veto_hours)
                if self.active and self.veto_until:
                    self.reason = t("boiler.veto_until", rooms=asked, time=self.veto_until.strftime("%H:%M"))
                else:
                    self.reason = t("boiler.veto" if self.active else "boiler.waiting", rooms=asked)
            else:
                if self.active and self._can_call(now) and await self._call("cancel_quick_veto", {}, t("boiler.what_cancel"), now):
                    self.active = False
                    self.veto_until = None
                self.reason = t("boiler.cancel_pending" if self.active else "boiler.no_demand")
        for update in list(self._listeners):
            update()

    def attributes(self) -> dict[str, Any]:
        status = self.hass.states.get(self.status_sensor).state if self.status_sensor and self.hass.states.get(self.status_sensor) else None
        return {
            "dry_run": self.hub.dry_run,
            "reason": self.hub.t("boiler.dry_prefix", reason=self.reason) if self.hub.dry_run else self.reason,
            "rooms": self.rooms,
            "control_enabled": self.enabled,
            "quick_veto_active": self.active,
            "quick_veto_until": self.veto_until.isoformat() if self.veto_until else None,
            "last_call": self.last_call_text,
            "last_error": self.last_error,
            "boiler_climate": self.climate,
            "boiler_status": status,
        }
