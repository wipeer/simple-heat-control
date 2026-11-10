"""Demand sensors: one per room ("this room wants heat") and one for the boiler."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .climate import room_device
from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_BOILER
from .hub import Hub


def boiler_device(entry_id: str) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry_id)}, name="Simple Heat Control boiler", manufacturer="Simple Heat Control", model="Boiler")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: Hub = hass.data[DOMAIN]
    if entry.data[CONF_ENTRY_TYPE] == ENTRY_BOILER:
        async_add_entities([BoilerDemand(hub, entry.entry_id)])
    else:
        async_add_entities([RoomDemand(hub, entry.entry_id)])


class RoomDemand(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "room_demand"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, hub: Hub, room_id: str) -> None:
        self.room = hub.rooms[room_id]
        self._attr_unique_id = f"{room_id}_demand"
        self._attr_device_info = room_device(self.room)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.room.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self.room.demand

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"reason": self.room.reason}


class BoilerDemand(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "boiler_demand"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, hub: Hub, entry_id: str) -> None:
        self.hub = hub
        self._attr_unique_id = f"{entry_id}_demand"
        self._attr_device_info = boiler_device(entry_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.boiler.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return bool(self.hub.boiler and self.hub.boiler.demand)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.hub.boiler.attributes() if self.hub.boiler else {}
