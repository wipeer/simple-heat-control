"""Shared state: presets, schedules, overrides and options (stored), texts, rooms, boiler."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import i18n, presets
from .const import DEFAULT_SCHEDULE_TEMP, STORAGE_KEY, STORAGE_VERSION
from .schedule import validate

DEFAULT_OPTIONS = {"time_format": "auto", "language": "auto"}

if TYPE_CHECKING:
    from .boiler import BoilerController
    from .room import RoomController


class Hub:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # dry run is on until switched off once: a fresh install only shows what it would do
        self._data: dict[str, Any] = presets.migrate({"schedules": {}, "overrides": {}, "dry_run": True})
        self._dry_run_listeners: list = []
        self._preset_listeners: list = []
        self._builtin: dict[str, dict] = {}  # language code → texts, from lang/*.json
        self.t = i18n.Translator({}, {})
        self.rooms: dict[str, RoomController] = {}
        self.boiler: BoilerController | None = None
        self.boiler_entry_id: str | None = None

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self._data = presets.migrate({"presets": data.get("presets"), "schedules": data.get("schedules", {}),
                                          "active": data.get("active"), "overrides": data.get("overrides", {}),
                                          "dry_run": data.get("dry_run", True)})
            self._data["options"] = {**DEFAULT_OPTIONS, **(data.get("options") or {})}
            self._data["translation"] = data.get("translation")
        self._data.setdefault("options", dict(DEFAULT_OPTIONS))
        self._data.setdefault("translation", None)
        self._builtin = await self.hass.async_add_executor_job(i18n.load_builtin)
        self._use_language()

    async def _async_save(self) -> None:
        await self._store.async_save(self._data)

    # ---- options: time format and language, shared by every browser ---------------------------
    @property
    def options(self) -> dict:
        return dict(self._data["options"])

    @property
    def custom_translation(self) -> dict | None:
        return self._data["translation"]

    @property
    def builtin_languages(self) -> dict[str, dict]:
        return self._builtin

    def language(self) -> str:
        """The language in use: a built-in code or "custom". "auto" follows HA's language."""
        chosen = self._data["options"]["language"]
        if chosen == "custom" and self.custom_translation:
            return "custom"
        if chosen in self._builtin:
            return chosen
        system = (self.hass.config.language or "en").split("-")[0].lower()
        return system if system in self._builtin else "en"

    def strings(self) -> dict:
        """All texts in the language in use; English fills what a translation lacks."""
        language = self.language()
        chosen = self.custom_translation if language == "custom" else self._builtin.get(language, {})
        return {**self._builtin.get("en", {}), **chosen}

    def _use_language(self) -> None:
        self.t = i18n.Translator(self.strings(), self._builtin.get("en", {}))

    async def async_set_options(self, time_format: str | None = None, language: str | None = None,
                                translation: Any = i18n.MISSING) -> dict:
        """Change options; returns the report on an uploaded translation (unknown and missing keys)."""
        report: dict = {}
        if translation is not i18n.MISSING:
            if translation is None:
                self._data["translation"] = None
                if self._data["options"]["language"] == "custom":
                    self._data["options"]["language"] = "auto"
            else:
                clean, report = i18n.check_custom(translation, self._builtin.get("en", {}))
                self._data["translation"] = clean
        if time_format is not None:
            if time_format not in ("auto", "12", "24"):
                raise ValueError("time format is auto, 12 or 24")
            self._data["options"]["time_format"] = time_format
        if language is not None:
            if language not in ("auto", "custom", *self._builtin):
                raise ValueError(f"unknown language {language}")
            if language == "custom" and not self.custom_translation:
                raise ValueError("load a translation first")
            self._data["options"]["language"] = language
        await self._async_save()
        self._use_language()
        # reasons are text: compute them again in the new language
        for room in self.rooms.values():
            await room.async_evaluate()
        if self.boiler is not None:
            await self.boiler.async_apply()
        return report

    # ---- dry run: everything is computed and shown, nothing is sent to devices ----------------
    @property
    def dry_run(self) -> bool:
        return bool(self._data["dry_run"])

    def add_dry_run_listener(self, update):
        self._dry_run_listeners.append(update)
        return lambda: self._dry_run_listeners.remove(update)

    async def async_set_dry_run(self, on: bool) -> None:
        if on == self.dry_run:
            return
        self._data["dry_run"] = on
        await self._async_save()
        if on and self.boiler is not None:
            await self.boiler.async_enter_dry_run()  # cancels a real quick veto we set
        for update in list(self._dry_run_listeners):
            update()
        for room in self.rooms.values():
            room.actions.clear()
            await room.async_evaluate(force=True)
        if not on and self.boiler is not None:
            await self.boiler.async_leave_dry_run()

    # ---- presets and schedules -----------------------------------------------------------------
    @property
    def presets(self) -> list[str]:
        return list(self._data["presets"])

    def add_preset_listener(self, update):
        self._preset_listeners.append(update)
        return lambda: self._preset_listeners.remove(update)

    def _notify_presets(self) -> None:
        for update in list(self._preset_listeners):
            update()

    def active_preset(self, room_id: str) -> str:
        return presets.active(self._data, room_id)

    def get_schedule(self, room_id: str, preset: str | None = None) -> dict:
        return presets.week(self._data, room_id, preset or self.active_preset(room_id), DEFAULT_SCHEDULE_TEMP)

    async def async_set_schedule(self, room_id: str, schedule: dict, preset: str | None = None) -> dict:
        preset = preset or self.active_preset(room_id)
        if preset not in self._data["presets"]:
            raise ValueError(f"no preset called {preset}")
        clean = validate(schedule)
        self._data["schedules"].setdefault(room_id, {})[preset] = clean
        await self._async_save()
        if room_id in self.rooms and preset == self.active_preset(room_id):
            await self.rooms[room_id].async_evaluate(force=True)
        return clean

    async def async_create_preset(self, name: str, copy_from: str | None = None,
                                  temperature: float | None = None) -> str:
        name = presets.create(self._data, name, list(self.rooms), DEFAULT_SCHEDULE_TEMP, copy_from, temperature)
        await self._async_save()
        self._notify_presets()
        return name

    async def async_rename_preset(self, old: str, new: str) -> str:
        new = presets.rename(self._data, old, new)
        await self._async_save()
        self._notify_presets()
        for room_id, room in self.rooms.items():
            if self.active_preset(room_id) == new:
                await room.async_evaluate()  # refreshes the room's `preset` attribute
        return new

    async def async_delete_preset(self, name: str) -> None:
        presets.delete(self._data, name, {r: room.name for r, room in self.rooms.items()})
        await self._async_save()
        self._notify_presets()

    async def async_activate_preset(self, name: str, room_ids: list[str] | None = None) -> list[str]:
        """Switch rooms (all when None) to a preset. Rooms whose preset changes lose their manual
        override; re-selecting the preset a room already uses leaves it alone."""
        room_ids = list(self.rooms) if room_ids is None else room_ids
        changed = presets.activate(self._data, name, room_ids)
        for room_id in changed:
            self._data["overrides"].pop(room_id, None)
        await self._async_save()
        for room_id in changed:
            if room_id in self.rooms:
                await self.rooms[room_id].async_evaluate(force=True)
        self._notify_presets()
        return changed

    # ---- manual overrides -----------------------------------------------------------------------
    def get_override(self, room_id: str) -> dict | None:
        return self._data["overrides"].get(room_id)

    async def async_set_override(self, room_id: str, temperature: float, until: str | None) -> None:
        self._data["overrides"][room_id] = {"temperature": round(float(temperature) * 2) / 2, "until": until}
        await self._async_save()
        if room_id in self.rooms:
            await self.rooms[room_id].async_evaluate(force=True)

    async def async_clear_override(self, room_id: str, evaluate: bool = True) -> None:
        if self._data["overrides"].pop(room_id, None) is not None:
            await self._async_save()
        if evaluate and room_id in self.rooms:
            await self.rooms[room_id].async_evaluate(force=True)

    async def async_remove_room(self, room_id: str) -> None:
        self._data["schedules"].pop(room_id, None)
        self._data["active"].pop(room_id, None)
        self._data["overrides"].pop(room_id, None)
        await self._async_save()

    # ---- boiler ---------------------------------------------------------------------------------
    async def async_update_boiler(self) -> None:
        if self.boiler is None:
            return
        asking = sorted(r.name for r in self.rooms.values() if r.demand and r.hvac_on)
        await self.boiler.async_set_demand(asking)
