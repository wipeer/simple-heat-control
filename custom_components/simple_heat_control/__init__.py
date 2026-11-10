"""Simple Heat Control: per-room heating with a visible reason for everything it does."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import websocket
from .boiler import BoilerController
from .const import CARD_FILE, CONF_ENTRY_TYPE, DOMAIN, ENTRY_BOILER, ENTRY_ROOM, FRONTEND_URL
from .hub import Hub
from .room import RoomController

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ROOM_PLATFORMS = [Platform.CLIMATE, Platform.BINARY_SENSOR, Platform.SELECT]
BOILER_PLATFORMS = [Platform.BINARY_SENSOR, Platform.SWITCH, Platform.SELECT]


def _options(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hub = Hub(hass)
    await hub.async_load()
    hass.data[DOMAIN] = hub
    websocket.async_register(hass)

    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(Path(__file__).parent / "frontend"), False)]
    )
    # loads the card on every dashboard, so no Lovelace resource has to be added by hand
    add_extra_js_url(hass, f"{FRONTEND_URL}/{CARD_FILE}?v={integration.version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub: Hub = hass.data[DOMAIN]
    options = _options(entry)
    if entry.data[CONF_ENTRY_TYPE] == ENTRY_BOILER:
        hub.boiler = BoilerController(hass, hub, options)
        hub.boiler_entry_id = entry.entry_id
        await hass.config_entries.async_forward_entry_setups(entry, BOILER_PLATFORMS)
        await hub.boiler.async_start()
        await hub.async_update_boiler()
    else:
        room = RoomController(hass, hub, entry.entry_id, options)
        hub.rooms[entry.entry_id] = room
        # entities first: the climate entity restores on/off before the room starts acting
        await hass.config_entries.async_forward_entry_setups(entry, ROOM_PLATFORMS)
        await room.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub: Hub = hass.data[DOMAIN]
    if entry.data[CONF_ENTRY_TYPE] == ENTRY_BOILER:
        ok = await hass.config_entries.async_unload_platforms(entry, BOILER_PLATFORMS)
        if ok and hub.boiler is not None:
            await hub.boiler.async_stop()
            hub.boiler = None
            hub.boiler_entry_id = None
        return ok
    ok = await hass.config_entries.async_unload_platforms(entry, ROOM_PLATFORMS)
    if ok:
        room = hub.rooms.pop(entry.entry_id, None)
        if room is not None:
            await room.async_stop()
        await hub.async_update_boiler()
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_ROOM and DOMAIN in hass.data:
        await hass.data[DOMAIN].async_remove_room(entry.entry_id)
