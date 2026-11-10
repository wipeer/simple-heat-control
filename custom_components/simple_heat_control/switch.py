"""Boiler control switch: off = Simple Heat Control never calls myVaillant (kill switch)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .binary_sensor import boiler_device
from .const import DOMAIN
from .hub import Hub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub = hass.data[DOMAIN]
    async_add_entities([BoilerControlSwitch(hub, entry.entry_id), DryRunSwitch(hub, entry.entry_id)])


class DryRunSwitch(SwitchEntity):
    """On = rooms and boiler compute and show everything, but nothing is sent to any device.

    The setting lives in Simple Heat Control's storage (not in this entity), so it also holds for rooms
    and is on after a fresh install until switched off.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "dry_run"
    _attr_icon = "mdi:test-tube"

    def __init__(self, hub: Hub, entry_id: str) -> None:
        self.hub = hub
        self._attr_unique_id = f"{entry_id}_dry_run"
        self._attr_device_info = boiler_device(entry_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.add_dry_run_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self.hub.dry_run

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_set_dry_run(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_set_dry_run(False)


class BoilerControlSwitch(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "boiler_control"
    _attr_icon = "mdi:fire-circle"

    def __init__(self, hub: Hub, entry_id: str) -> None:
        self.hub = hub
        self._attr_unique_id = f"{entry_id}_control"
        self._attr_device_info = boiler_device(entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and self.hub.boiler is not None:
            self.hub.boiler.enabled = last.state != "off"
        self.async_on_remove(self.hub.boiler.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return bool(self.hub.boiler and self.hub.boiler.enabled)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.boiler.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.boiler.async_set_enabled(False)
