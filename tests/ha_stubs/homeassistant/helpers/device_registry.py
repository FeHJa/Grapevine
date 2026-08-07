from __future__ import annotations

from typing import Any


class DeviceEntry:
    def __init__(
        self,
        device_id: str,
        *,
        config_entry_id: str,
        identifiers: set[tuple[str, str]],
        name: str | None,
    ) -> None:
        self.id = device_id
        self.config_entry_id = config_entry_id
        self.identifiers = identifiers
        self.name = name


class DeviceRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, DeviceEntry] = {}
        self._by_identifiers: dict[frozenset, DeviceEntry] = {}
        self._next_id = 0

    def async_get_or_create(
        self,
        *,
        config_entry_id: str,
        identifiers: set[tuple[str, str]],
        name: str | None = None,
        **_kwargs: Any,
    ) -> DeviceEntry:
        key = frozenset(identifiers)
        existing = self._by_identifiers.get(key)
        if existing is not None:
            return existing
        self._next_id += 1
        entry = DeviceEntry(
            f"device_{self._next_id}",
            config_entry_id=config_entry_id,
            identifiers=identifiers,
            name=name,
        )
        self._entries[entry.id] = entry
        self._by_identifiers[key] = entry
        return entry

    def async_get(self, device_id: str) -> DeviceEntry | None:
        return self._entries.get(device_id)

    def async_remove_device(self, device_id: str) -> None:
        entry = self._entries.pop(device_id, None)
        if entry is not None:
            self._by_identifiers.pop(frozenset(entry.identifiers), None)


def async_get(hass: Any) -> DeviceRegistry:
    return hass.data.setdefault("_fake_device_registry", DeviceRegistry())


def async_entries_for_config_entry(
    registry: DeviceRegistry, config_entry_id: str
) -> list[DeviceEntry]:
    return [
        entry for entry in registry._entries.values() if entry.config_entry_id == config_entry_id
    ]
