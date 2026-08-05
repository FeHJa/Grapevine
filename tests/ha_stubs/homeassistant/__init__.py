"""A minimal, hand-written fake of Home Assistant's Python surface.

This is NOT Home Assistant, and it is only ever imported from tests/ (see
conftest.py) via a sys.path prepend. It exists because this project's dev
sandbox cannot install a real `homeassistant` package matching the 2026.7
core floor (see requirements_test.txt for details/history). It implements
just enough of the state machine, event bus, service registry, config
entries and MQTT client surface for custom_components/grapevine to
run against in tests, with test-only helpers to drive it
(async_fire_time_changed, async_fire_mqtt_message, etc).

Treat tests that pass against this stub as "our code's control flow does
what we intended" — not as a substitute for running the real Phase 1
acceptance tests (MIGRATION_PLAN.md) against actual Home Assistant core
with pytest-homeassistant-custom-component before release.
"""
