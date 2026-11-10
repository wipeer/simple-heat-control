"""Preset selects: one per room, and a house-wide one that sets every room to the same preset."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .binary_sensor import boiler_device
from .climate import room_device
from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_BOILER
from .hub import Hub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: Hub = hass.data[DOMAIN]
    if entry.data[CONF_ENTRY_TYPE] == ENTRY_BOILER:
        async_add_entities([HousePresetSelect(hub, entry.entry_id)])
    else:
        async_add_entities([RoomPresetSelect(hub, entry.entry_id)])


class _PresetSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.add_preset_listener(self.async_write_ha_state))

    @property
    def options(self) -> list[str]:
        return self.hub.presets


class RoomPresetSelect(_PresetSelect):
    """The preset this room's schedule follows. Choosing one clears the room's manual override."""

    _attr_translation_key = "preset"

    def __init__(self, hub: Hub, room_id: str) -> None:
        super().__init__(hub)
        self.room_id = room_id
        self._attr_unique_id = f"{room_id}_preset"
        self._attr_device_info = room_device(hub.rooms[room_id])

    @property
    def current_option(self) -> str:
        return self.hub.active_preset(self.room_id)

    async def async_select_option(self, option: str) -> None:
        await self.hub.async_activate_preset(option, [self.room_id])


class HousePresetSelect(_PresetSelect):
    """Sets every room to one preset. Shows that preset while all rooms use it, unknown when they differ."""

    _attr_translation_key = "house_preset"

    def __init__(self, hub: Hub, entry_id: str) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{entry_id}_house_preset"
        self._attr_device_info = boiler_device(entry_id)

    @property
    def current_option(self) -> str | None:
        used = {self.hub.active_preset(r) for r in self.hub.rooms}
        return used.pop() if len(used) == 1 else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"rooms": {room.name: self.hub.active_preset(r) for r, room in sorted(
            self.hub.rooms.items(), key=lambda item: item[1].name)}}

    async def async_select_option(self, option: str) -> None:
        await self.hub.async_activate_preset(option)
