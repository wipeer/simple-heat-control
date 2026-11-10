"""Setup UI: add a room or the boiler; change their settings later under Configure."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .const import (
    CONF_BOILER_CLIMATE, CONF_BOILER_STATUS_SENSOR, CONF_CLOSE_WHEN_SATISFIED, CONF_ENTRY_TYPE,
    CONF_HYSTERESIS, CONF_NAME, CONF_OUTDOOR_SENSOR, CONF_REGULATION, CONF_RELAY, CONF_STALE_MINUTES,
    CONF_TEMP_SENSOR, CONF_TRV, CONF_VALVE_POSITION, CONF_VETO_HOURS, CONF_VETO_TEMP,
    DEFAULT_CLOSE_WHEN_SATISFIED, DEFAULT_HYSTERESIS, DEFAULT_REGULATION, DEFAULT_STALE_MINUTES,
    DEFAULT_VETO_HOURS, DEFAULT_VETO_TEMP, DOMAIN, ENTRY_BOILER, ENTRY_ROOM,
)


def _opt(key: str, defaults: dict, fallback: Any = None) -> vol.Optional:
    value = defaults.get(key, fallback)
    return vol.Optional(key, description={"suggested_value": value}) if value is not None else vol.Optional(key)


def room_schema(d: dict, with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=d.get(CONF_NAME, ""))] = sel.TextSelector()
    fields.update({
        vol.Required(CONF_TEMP_SENSOR, default=d.get(CONF_TEMP_SENSOR, vol.UNDEFINED)):
            sel.EntitySelector(sel.EntitySelectorConfig(domain="sensor", device_class="temperature")),
        vol.Required(CONF_TRV, default=d.get(CONF_TRV, vol.UNDEFINED)):
            sel.EntitySelector(sel.EntitySelectorConfig(domain="climate")),
        _opt(CONF_VALVE_POSITION, d): sel.EntitySelector(sel.EntitySelectorConfig(domain="sensor")),
        _opt(CONF_RELAY, d): sel.EntitySelector(sel.EntitySelectorConfig(domain=["switch", "light", "input_boolean"])),
        _opt(CONF_OUTDOOR_SENSOR, d): sel.EntitySelector(sel.EntitySelectorConfig(domain="sensor", device_class="temperature")),
        vol.Required(CONF_REGULATION, default=d.get(CONF_REGULATION, DEFAULT_REGULATION)): sel.SelectSelector(
            sel.SelectSelectorConfig(options=["off", "light", "medium", "strong"], translation_key="regulation",
                                     mode=sel.SelectSelectorMode.DROPDOWN)),
        vol.Required(CONF_HYSTERESIS, default=d.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)): sel.NumberSelector(
            sel.NumberSelectorConfig(min=0.1, max=2.0, step=0.1, unit_of_measurement="°C", mode=sel.NumberSelectorMode.BOX)),
        vol.Required(CONF_CLOSE_WHEN_SATISFIED, default=d.get(CONF_CLOSE_WHEN_SATISFIED, DEFAULT_CLOSE_WHEN_SATISFIED)):
            sel.BooleanSelector(),
        vol.Required(CONF_STALE_MINUTES, default=d.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES)): sel.NumberSelector(
            sel.NumberSelectorConfig(min=15, max=1440, step=5, unit_of_measurement="min", mode=sel.NumberSelectorMode.BOX)),
    })
    return vol.Schema(fields)


def boiler_schema(d: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_BOILER_CLIMATE, default=d.get(CONF_BOILER_CLIMATE, vol.UNDEFINED)):
            sel.EntitySelector(sel.EntitySelectorConfig(domain="climate")),
        vol.Required(CONF_VETO_TEMP, default=d.get(CONF_VETO_TEMP, DEFAULT_VETO_TEMP)): sel.NumberSelector(
            sel.NumberSelectorConfig(min=15, max=30, step=0.5, unit_of_measurement="°C", mode=sel.NumberSelectorMode.BOX)),
        vol.Required(CONF_VETO_HOURS, default=d.get(CONF_VETO_HOURS, DEFAULT_VETO_HOURS)): sel.NumberSelector(
            sel.NumberSelectorConfig(min=0.5, max=12, step=0.5, unit_of_measurement="h", mode=sel.NumberSelectorMode.BOX)),
        _opt(CONF_BOILER_STATUS_SENSOR, d): sel.EntitySelector(sel.EntitySelectorConfig(domain="sensor")),
    })


def _clean(user_input: dict) -> dict:
    return {k: v for k, v in user_input.items() if v not in (None, "")}


class HeatControlConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["room", "boiler"])

    async def async_step_room(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            data = {CONF_ENTRY_TYPE: ENTRY_ROOM, **_clean(user_input)}
            return self.async_create_entry(title=user_input[CONF_NAME], data=data)
        return self.async_show_form(step_id="room", data_schema=room_schema({}, with_name=True))

    async def async_step_boiler(self, user_input: dict | None = None) -> ConfigFlowResult:
        for entry in self._async_current_entries():
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_BOILER:
                return self.async_abort(reason="boiler_exists")
        if user_input is not None:
            return self.async_create_entry(title="Boiler", data={CONF_ENTRY_TYPE: ENTRY_BOILER, **_clean(user_input)})
        return self.async_show_form(step_id="boiler", data_schema=boiler_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeatControlOptionsFlow()


class HeatControlOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        is_boiler = self.config_entry.data[CONF_ENTRY_TYPE] == ENTRY_BOILER
        if user_input is not None:
            # a cleared optional field is missing from user_input; store None so it overrides entry.data
            data = dict(user_input)
            for key in (CONF_VALVE_POSITION, CONF_RELAY, CONF_OUTDOOR_SENSOR, CONF_BOILER_STATUS_SENSOR):
                data.setdefault(key, None)
            return self.async_create_entry(data=data)
        schema = boiler_schema(current) if is_boiler else room_schema(current, with_name=False)
        return self.async_show_form(step_id="init", data_schema=schema)
