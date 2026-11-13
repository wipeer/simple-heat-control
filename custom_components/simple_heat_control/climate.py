"""Room climate entity: on/off, target (= manual override until the next schedule change)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .hub import Hub
from .room import RoomController

PRESET_SCHEDULE = "schedule"
PRESET_OVERRIDE = "override"


def room_device(room: RoomController) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, room.room_id)}, name=room.name, manufacturer="Simple Heat Control", model="Room")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: Hub = hass.data[DOMAIN]
    async_add_entities([RoomClimate(hub, hub.rooms[entry.entry_id])])


class RoomClimate(ClimateEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_SCHEDULE, PRESET_OVERRIDE]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0
    _attr_icon = "mdi:radiator"

    def __init__(self, hub: Hub, room: RoomController) -> None:
        self.hub = hub
        self.room = room
        self._attr_unique_id = f"{room.room_id}_climate"
        self._attr_device_info = room_device(room)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.room.hvac_on = last.state != HVACMode.OFF
        self.async_on_remove(self.room.add_listener(self.async_write_ha_state))

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self.room.hvac_on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        if not self.room.hvac_on:
            return HVACAction.OFF
        return HVACAction.HEATING if self.room.demand or self.room.joining else HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        return self.room.room_temp

    @property
    def target_temperature(self) -> float | None:
        return self.room.target

    @property
    def preset_mode(self) -> str:
        return PRESET_OVERRIDE if self.room.override else PRESET_SCHEDULE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.room.attributes()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.room.async_set_hvac(hvac_mode != HVACMode.OFF)

    async def async_turn_on(self) -> None:
        await self.room.async_set_hvac(True)

    async def async_turn_off(self) -> None:
        await self.room.async_set_hvac(False)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        state = self.room.schedule_state
        until = state.next_change.isoformat() if state and state.next_change else None
        await self.hub.async_set_override(self.room.room_id, temp, until)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_SCHEDULE:
            await self.hub.async_clear_override(self.room.room_id)
        elif self.room.target is not None and not self.room.override:
            await self.async_set_temperature(**{ATTR_TEMPERATURE: self.room.target})
