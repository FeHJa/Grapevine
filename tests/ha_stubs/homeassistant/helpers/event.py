from __future__ import annotations

from collections.abc import Callable


def async_track_state_change_event(hass, entity_ids, action) -> Callable[[], None]:
    entity_id_set = {entity_ids} if isinstance(entity_ids, str) else set(entity_ids)

    def _filtered(event) -> None:
        if event.data.get("entity_id") in entity_id_set:
            action(event)

    return hass.bus.async_listen("state_changed", _filtered)


def async_track_time_change(
    hass, action, second=None, minute=None, hour=None
) -> Callable[[], None]:
    listener = {"action": action, "second": second, "minute": minute, "hour": hour}
    hass._time_change_listeners = getattr(hass, "_time_change_listeners", [])
    hass._time_change_listeners.append(listener)

    def _unsub() -> None:
        if listener in hass._time_change_listeners:
            hass._time_change_listeners.remove(listener)

    return _unsub


def async_fire_time_changed(hass, now) -> None:
    """Test helper: invoke every registered time_change listener whose
    filter matches `now` (None on a field means "match any")."""
    for listener in list(getattr(hass, "_time_change_listeners", [])):
        if listener["second"] is not None and listener["second"] != now.second:
            continue
        if listener["minute"] is not None and listener["minute"] != now.minute:
            continue
        if listener["hour"] is not None and listener["hour"] != now.hour:
            continue
        listener["action"](now)
