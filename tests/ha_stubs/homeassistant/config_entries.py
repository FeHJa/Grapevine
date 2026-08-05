from __future__ import annotations

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
    """Test double for hass.config_entries — just enough for the unique_id
    collision check config_flow.py relies on."""

    def __init__(self) -> None:
        self.entries: list[ConfigEntry] = []

    def async_entries(self, domain: str | None = None) -> list[ConfigEntry]:
        return list(self.entries)


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
