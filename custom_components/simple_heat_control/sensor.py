"""Heat requests: which rooms ask the boiler for heat right now, with a log of who asked and when."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .binary_sensor import boiler_device
from .const import DOMAIN
from .hub import Hub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([HeatRequestedBy(hass.data[DOMAIN], entry.entry_id)])


class HeatRequestedBy(SensorEntity):
    """State: the names of the rooms asking for heat (or "nobody"). Home Assistant's history and logbook
    record every change of it; `log` holds the latest ones with each room's reason (not kept in the
    database, and empty after a restart)."""

    _attr_has_entity_name = True
    _attr_translation_key = "heat_requested_by"
    _attr_icon = "mdi:radiator"
    _unrecorded_attributes = frozenset({"log"})

    def __init__(self, hub: Hub, entry_id: str) -> None:
        self.hub = hub
        self._attr_unique_id = f"{entry_id}_requested_by"
        self._attr_device_info = boiler_device(entry_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.add_request_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        rooms = self.hub.request_log.asking
        return (", ".join(rooms) if rooms else self.hub.t("requests.none"))[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        log = self.hub.request_log
        return {"rooms": list(log.asking), "count": len(log.asking), "since": log.since,
                "log": list(reversed(log.entries))}  # newest first
