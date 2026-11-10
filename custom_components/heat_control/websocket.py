"""Websocket commands used by the heat-control card."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from . import i18n
from .const import DOMAIN
from .hub import Hub


def _hub(hass: HomeAssistant) -> Hub:
    return hass.data[DOMAIN]


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_config)
    websocket_api.async_register_command(hass, ws_set_schedule)
    websocket_api.async_register_command(hass, ws_set_override)
    websocket_api.async_register_command(hass, ws_clear_override)
    websocket_api.async_register_command(hass, ws_set_dry_run)
    websocket_api.async_register_command(hass, ws_preset_create)
    websocket_api.async_register_command(hass, ws_preset_rename)
    websocket_api.async_register_command(hass, ws_preset_delete)
    websocket_api.async_register_command(hass, ws_preset_activate)
    websocket_api.async_register_command(hass, ws_options_set)
    websocket_api.async_register_command(hass, ws_translations)


@websocket_api.websocket_command({vol.Required("type"): "heat_control/config"})
@callback
def ws_config(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    hub = _hub(hass)
    registry = er.async_get(hass)
    rooms = []
    for room_id, room in hub.rooms.items():
        rooms.append({
            "room_id": room_id,
            "name": room.name,
            "climate": registry.async_get_entity_id("climate", DOMAIN, f"{room_id}_climate"),
            "trv": room.trv,
            "preset": hub.active_preset(room_id),
            "schedule": hub.get_schedule(room_id),
            "schedules": {p: hub.get_schedule(room_id, p) for p in hub.presets},
        })
    boiler = None
    if hub.boiler is not None:
        boiler = {
            "climate": hub.boiler.climate,
            "demand": registry.async_get_entity_id("binary_sensor", DOMAIN, f"{hub.boiler_entry_id}_demand"),
        }
    connection.send_result(msg["id"], {"rooms": sorted(rooms, key=lambda r: r["name"]), "boiler": boiler,
                                       "dry_run": hub.dry_run, "presets": hub.presets, **_texts(hub)})


def _texts(hub: Hub) -> dict:
    """Options plus the texts the card shows, in the language in use."""
    custom = hub.custom_translation
    return {
        "options": hub.options,
        "language": hub.language(),
        "strings": hub.strings(),
        "languages": {code: texts.get("_name", code) for code, texts in hub.builtin_languages.items()},
        "custom": None if not custom else {"name": custom.get("_name") or "Custom",
                                           "language": custom.get("_language")},
    }


@websocket_api.websocket_command({vol.Required("type"): "heat_control/dry_run/set", vol.Required("dry_run"): bool})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_dry_run(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _hub(hass).async_set_dry_run(msg["dry_run"])
    connection.send_result(msg["id"], {"dry_run": _hub(hass).dry_run})


def _room_or_error(hass, connection, msg) -> bool:
    if msg["room_id"] not in _hub(hass).rooms:
        connection.send_error(msg["id"], "not_found", f"no room {msg['room_id']}")
        return False
    return True


@websocket_api.websocket_command({
    vol.Required("type"): "heat_control/schedule/set",
    vol.Required("room_id"): str,
    vol.Required("schedule"): dict,
    vol.Optional("preset"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_schedule(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not _room_or_error(hass, connection, msg):
        return
    try:
        clean = await _hub(hass).async_set_schedule(msg["room_id"], msg["schedule"], msg.get("preset"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_schedule", str(err))
        return
    connection.send_result(msg["id"], {"schedule": clean})


@websocket_api.websocket_command({
    vol.Required("type"): "heat_control/override/set",
    vol.Required("room_id"): str,
    vol.Required("temperature"): vol.All(vol.Coerce(float), vol.Range(min=5, max=30)),
    vol.Optional("until"): vol.Any(None, str),
})
@websocket_api.async_response
async def ws_set_override(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not _room_or_error(hass, connection, msg):
        return
    hub = _hub(hass)
    until = msg.get("until", "next")
    if until == "next":  # default: until the schedule's next change
        state = hub.rooms[msg["room_id"]].schedule_state
        until = state.next_change.isoformat() if state and state.next_change else None
    await hub.async_set_override(msg["room_id"], msg["temperature"], until)
    connection.send_result(msg["id"], {"override": hub.get_override(msg["room_id"])})


@websocket_api.websocket_command({vol.Required("type"): "heat_control/override/clear", vol.Required("room_id"): str})
@websocket_api.async_response
async def ws_clear_override(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not _room_or_error(hass, connection, msg):
        return
    await _hub(hass).async_clear_override(msg["room_id"])
    connection.send_result(msg["id"], {})


# ---- presets ------------------------------------------------------------------------------------
async def _preset_call(connection, msg, call) -> None:
    try:
        result = await call
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_preset", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "heat_control/preset/create",
    vol.Required("name"): str,
    vol.Optional("copy_from"): str,
    vol.Optional("temperature"): vol.Coerce(float),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_preset_create(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    async def run():
        name = await _hub(hass).async_create_preset(msg["name"], msg.get("copy_from"), msg.get("temperature"))
        return {"name": name}
    await _preset_call(connection, msg, run())


@websocket_api.websocket_command({
    vol.Required("type"): "heat_control/preset/rename", vol.Required("name"): str, vol.Required("new_name"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_preset_rename(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    async def run():
        return {"name": await _hub(hass).async_rename_preset(msg["name"], msg["new_name"])}
    await _preset_call(connection, msg, run())


@websocket_api.websocket_command({vol.Required("type"): "heat_control/preset/delete", vol.Required("name"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_preset_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    async def run():
        await _hub(hass).async_delete_preset(msg["name"])
        return {}
    await _preset_call(connection, msg, run())


@websocket_api.websocket_command({
    vol.Required("type"): "heat_control/preset/activate",
    vol.Required("name"): str,
    vol.Optional("room_id"): str,  # one room; without it, every room
})
@websocket_api.async_response
async def ws_preset_activate(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if "room_id" in msg and not _room_or_error(hass, connection, msg):
        return
    rooms = [msg["room_id"]] if "room_id" in msg else None

    async def run():
        return {"changed": await _hub(hass).async_activate_preset(msg["name"], rooms)}
    await _preset_call(connection, msg, run())


# ---- options and translations ------------------------------------------------------------------
@websocket_api.websocket_command({
    vol.Required("type"): "heat_control/options/set",
    vol.Optional("time_format"): vol.In(["auto", "12", "24"]),
    vol.Optional("language"): str,
    vol.Optional("translation"): vol.Any(None, dict),  # null removes the custom translation
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_options_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    hub = _hub(hass)
    try:
        report = await hub.async_set_options(msg.get("time_format"), msg.get("language"),
                                             msg["translation"] if "translation" in msg else i18n.MISSING)
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_options", str(err))
        return
    connection.send_result(msg["id"], {"report": report, **_texts(hub)})


@websocket_api.websocket_command({vol.Required("type"): "heat_control/translations"})
@callback
def ws_translations(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Every built-in language file and the custom translation, for exporting."""
    hub = _hub(hass)
    connection.send_result(msg["id"], {"builtin": hub.builtin_languages, "custom": hub.custom_translation})
