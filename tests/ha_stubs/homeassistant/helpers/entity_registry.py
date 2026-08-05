from __future__ import annotations

from typing import Any


class RegistryEntry:
    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id


class EntityRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry] = {}

    def async_get(self, entity_id: str) -> RegistryEntry | None:
        return self._entries.get(entity_id)

    def async_remove(self, entity_id: str) -> None:
        self._entries.pop(entity_id, None)

    def _register(self, entity_id: str) -> None:
        self._entries[entity_id] = RegistryEntry(entity_id)


def async_get(hass: Any) -> EntityRegistry:
    return hass.data.setdefault("_fake_entity_registry", EntityRegistry())
