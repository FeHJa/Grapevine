"""In-memory fake MQTT client — a dict of topic-filter -> subscribers and
a list of published messages, scoped per fake HomeAssistant instance via
hass.data. Real broker semantics (retained-message replay to new
subscribers, QoS) are not modeled; only single-level '+' wildcard
matching is, since that's all this project's topic filters use.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

_STATE_KEY = "_fake_mqtt"


@dataclass
class ReceiveMessage:
    topic: str
    payload: str


class _FakeMqttState:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []
        self.subscriptions: dict[str, list[Callable]] = {}
        self.client_ready = True


def _state(hass) -> _FakeMqttState:
    return hass.data.setdefault(_STATE_KEY, _FakeMqttState())


async def async_wait_for_mqtt_client(hass) -> bool:
    return _state(hass).client_ready


async def async_publish(hass, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
    _state(hass).published.append((topic, payload, retain))


async def async_subscribe(hass, topic: str, msg_callback: Callable, qos: int = 0) -> Callable[[], None]:
    subs = _state(hass).subscriptions.setdefault(topic, [])
    subs.append(msg_callback)

    def _unsub() -> None:
        if msg_callback in subs:
            subs.remove(msg_callback)

    return _unsub


async def async_fire_mqtt_message(hass, topic: str, payload: str) -> None:
    """Test helper: deliver a message to every subscription whose filter
    matches `topic` (single-level '+' wildcard only)."""
    for filter_topic, callbacks in _state(hass).subscriptions.items():
        if _topic_matches(filter_topic, topic):
            for cb in list(callbacks):
                result = cb(ReceiveMessage(topic=topic, payload=payload))
                if hasattr(result, "__await__"):
                    await result


def _topic_matches(filter_topic: str, topic: str) -> bool:
    filter_parts = filter_topic.split("/")
    topic_parts = topic.split("/")
    if len(filter_parts) != len(topic_parts):
        return False
    return all(f == "+" or f == t for f, t in zip(filter_parts, topic_parts))
