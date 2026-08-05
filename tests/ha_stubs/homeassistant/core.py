from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


def callback(func):
    """Real HA uses this to mark a function as safe to call directly on
    the event loop. Our fake doesn't need the distinction; identity is
    enough for tests."""
    return func


class State:
    def __init__(self, entity_id: str, state: str, attributes: dict | None = None) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class Event:
    def __init__(self, event_type: str, data: dict | None = None) -> None:
        self.event_type = event_type
        self.data = data or {}


class ServiceCall:
    def __init__(self, domain: str, service: str, data: dict | None = None) -> None:
        self.domain = domain
        self.service = service
        self.data = data or {}


class StateMachine:
    def __init__(self) -> None:
        self._states: dict[str, State] = {}

    def get(self, entity_id: str) -> State | None:
        return self._states.get(entity_id)

    def async_set(self, entity_id: str, state: str, attributes: dict | None = None) -> None:
        self._states[entity_id] = State(entity_id, state, attributes)

    def async_remove(self, entity_id: str) -> None:
        self._states.pop(entity_id, None)


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = {}

    def async_listen(self, event_type: str, listener: Callable) -> Callable[[], None]:
        self._listeners.setdefault(event_type, []).append(listener)

        def _unsub() -> None:
            if listener in self._listeners.get(event_type, []):
                self._listeners[event_type].remove(listener)

        return _unsub

    def async_fire(self, event_type: str, data: dict | None = None) -> None:
        for listener in list(self._listeners.get(event_type, [])):
            listener(Event(event_type, data))


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[tuple[str, str], tuple[Callable, Any]] = {}

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self._services

    def async_register(self, domain: str, service: str, handler: Callable, schema: Any = None) -> None:
        self._services[(domain, service)] = (handler, schema)

    def async_remove(self, domain: str, service: str) -> None:
        self._services.pop((domain, service), None)

    async def async_call(self, domain: str, service: str, service_data: dict | None = None) -> None:
        handler, schema = self._services[(domain, service)]
        data = schema(service_data or {}) if schema is not None else (service_data or {})
        await handler(ServiceCall(domain, service, data))


class HomeAssistant:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.states = StateMachine()
        self.bus = EventBus()
        self.services = ServiceRegistry()
        self.config_entries: Any = None
        self._tasks: set[asyncio.Task] = set()

    def async_create_background_task(
        self, target, name: str | None = None, eager_start: bool = True
    ) -> asyncio.Task:
        task = asyncio.ensure_future(target)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
