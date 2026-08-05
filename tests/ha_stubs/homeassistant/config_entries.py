from __future__ import annotations

import importlib
from collections.abc import Iterable
from typing import Any

from .data_entry_flow import AbortFlow

ConfigFlowResult = dict


class ConfigEntry:
    def __init__(
        self,
        *,
        data: dict | None = None,
        options: dict | None = None,
        entry_id: str = "test_entry",
        unique_id: str | None = None,
    ) -> None:
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id
        self.unique_id = unique_id
        self.runtime_data: Any = None
        self._on_unload: list = []

    def async_on_unload(self, func) -> None:
        self._on_unload.append(func)

    async def async_unload(self) -> None:
        """Test helper: run registered on_unload callbacks, most-recently
        registered first (matches real HA's teardown order), then clear."""
        for func in reversed(self._on_unload):
            result = func()
            if hasattr(result, "__await__"):
                await result
        self._on_unload.clear()


class ConfigEntriesRegistry:
    """Test double for hass.config_entries — the unique_id collision check
    config_flow.py relies on, plus a minimal entity-platform forward/unload
    so custom_components.grapevine.sensor's async_setup_entry can be
    driven the same way real HA drives it
    (hass.config_entries.async_forward_entry_setups)."""

    def __init__(self, hass: Any = None) -> None:
        self._hass = hass
        self.entries: list[ConfigEntry] = []
        self._platform_entities: dict[tuple[str, str], list[Any]] = {}

    def async_entries(self, domain: str | None = None) -> list[ConfigEntry]:
        return list(self.entries)

    async def async_forward_entry_setups(self, entry: ConfigEntry, platforms: Iterable[str]) -> None:
        for platform in platforms:
            module = importlib.import_module(f"custom_components.grapevine.{platform}")
            key = (entry.entry_id, platform)
            self._platform_entities.setdefault(key, [])
            await module.async_setup_entry(self._hass, entry, self._make_add_entities(key))

    async def async_unload_platforms(self, entry: ConfigEntry, platforms: Iterable[str]) -> bool:
        for platform in platforms:
            key = (entry.entry_id, platform)
            for entity in self._platform_entities.pop(key, []):
                await entity.async_will_remove_from_hass()
                if entity.entity_id is not None and self._hass is not None:
                    self._hass.states.async_remove(entity.entity_id)
        return True

    def _make_add_entities(self, key: tuple[str, str]):
        def _add_entities(new_entities: Iterable[Any], update_before_add: bool = False) -> None:
            for entity in new_entities:
                entity.hass = self._hass
                entity.entity_id = f"{key[1]}.{_slugify_entity_id(entity.unique_id)}"
                self._platform_entities[key].append(entity)

        return _add_entities


def _slugify_entity_id(value: str | None) -> str:
    if not value:
        return "unknown"
    return "".join(c.lower() if c.isalnum() else "_" for c in value).strip("_")


class ConfigFlow:
    VERSION = 1
    domain: str | None = None

    def __init_subclass__(cls, *, domain: str | None = None, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if domain is not None:
            cls.domain = domain

    def __init__(self) -> None:
        self.hass: Any = None
        self.unique_id: str | None = None

    async def async_set_unique_id(self, unique_id: str) -> None:
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        registry = getattr(self.hass, "config_entries", None)
        if registry is None:
            return
        for entry in registry.async_entries(self.domain):
            if entry.unique_id == self.unique_id:
                raise AbortFlow("already_configured")

    def async_show_form(self, *, step_id: str, data_schema, errors: dict | None = None) -> dict:
        return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {}}

    def async_create_entry(self, *, title: str, data: dict, options: dict | None = None) -> dict:
        return {"type": "create_entry", "title": title, "data": data, "options": options or {}}
