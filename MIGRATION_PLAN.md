# Migration Plan: Blueprint → Integration

Source blueprint: https://github.com/FeHJa/HA-Blueprint-MQTT-Bridge/blob/main/mqtt_bridge.yaml
Wire protocol contract: `PROTOCOL.md` (authoritative for Phase 1 behavior)

## Goal

Replace the YAML automation blueprint with a native Home Assistant custom
integration (`custom_components/ha_mqtt_bridge/`) that is functionally
identical on the wire — any other instance still running the blueprint, or
another migrated instance, must interoperate without changes on its end.

## Guiding principle

Phase 1 is a **behavior-preserving port**, not a redesign. Every detail in
`PROTOCOL.md`, including both documented "known limitations," must be
reproduced exactly. Anything that looks like an improvement (fixing the
object_id collision, per-domain discovery components, availability/LWT)
is explicitly deferred to a later phase so the two known limitations can be
verified against real behavior before anyone decides whether to keep them.

## Target architecture

```
custom_components/ha_mqtt_bridge/
├── __init__.py          # async_setup_entry / async_unload_entry, wires everything together
├── manifest.json         # domain, deps (mqtt), config_flow: true, iot_class
├── const.py               # DOMAIN, CONF_* keys, defaults, sw_version, the 8 regex patterns
├── config_flow.py         # ConfigFlow + OptionsFlow — maps blueprint inputs (§1)
├── coordinator.py         # entity-tracking, time_pattern interval, on-demand republish, jitter
├── discovery.py           # payload building (§3), device_class/unit resolution (§3 table)
├── mqtt_bridge.py         # publish own discovery+state (§2-4), subscribe+forward (§5), loop guard
└── strings.json / translations/en.json
tests/
├── test_config_flow.py
├── test_discovery.py      # regex table, name fallback, device_class/unit precedence
├── test_mqtt_bridge.py    # topic construction, forwarding, loop prevention
└── test_coordinator.py    # time_pattern trigger, jitter bounds, on-demand republish
```

Rationale for the split: `discovery.py` is pure functions (entity/state in,
payload dict out) so the device_class/unit regex table and name-fallback
logic can be unit-tested without a running HA instance or MQTT broker.
`mqtt_bridge.py` owns all `homeassistant.components.mqtt` interaction
(`async_subscribe`/`async_publish`). `coordinator.py` owns timing: the
`time_pattern` interval, the on-demand republish entry point, and jitter.

## Config entry mapping (§1)

| Blueprint input | Config entry field | Notes |
|---|---|---|
| `entities` | `data[CONF_ENTITIES]` | list of entity_ids, any domain |
| `shared_discovery_prefix` | `data[CONF_SHARED_DISCOVERY_PREFIX]` | default `share/homeassistant/` |
| `local_discovery_prefix` | `data[CONF_LOCAL_DISCOVERY_PREFIX]` | default `homeassistant` |
| `sensor_value_prefix` | `data[CONF_SENSOR_VALUE_PREFIX]` | default `share/jakob/` |
| `time_pattern` | `options[CONF_TIME_PATTERN_MINUTES]` | default 1; options flow so it's editable without reauth |
| `bridge_name` | `data[CONF_BRIDGE_NAME]` | slugified once at setup into `bridge_id`, stored alongside |

`entities` and prefixes go in `data` (identity of the bridge instance);
`time_pattern` goes in `options` (safely reconfigurable, triggers an entry
update listener that resets the interval timer). Config flow validates
`bridge_name` slugifies to a non-empty string and `entities` is non-empty.

## Phase breakdown

### Phase 1 — Protocol-faithful core (this migration's primary deliverable)

1. Scaffold: `manifest.json`, `const.py`, minimal `config_flow.py` (single
   step form for the 6 inputs above), `__init__.py` with
   `async_setup_entry`/`async_unload_entry`.
2. `discovery.py`: build the discovery payload (§3) exactly — field
   presence/omission rules, the 8-pattern regex table ported **verbatim**,
   friendly_name → title-cased object_id fallback.
3. `mqtt_bridge.py`:
   - Own publish path: discovery → `{shared_discovery_prefix}sensor/{object_id}/config`,
     state → `{sensor_value_prefix}sensor/{object_id}`, both retained (§2, §4).
   - Federation subscribe: `{shared_discovery_prefix}+/+/config` using the
     *configured* prefix (not the blueprint's hardcoded literal — §5).
   - Forwarding: verbatim byte passthrough to
     `{local_discovery_prefix}/{component}/{object_id}/config`, retained.
   - Loop guard ported exactly: skip on `bridge_id` match or `unique_id`
     prefix match (`::` or `.` separator) (§5).
4. `coordinator.py`:
   - State-change listener on bridged entities → publish discovery+state
     for that one entity, using `trigger`/event `to_state.state` directly
     (§4), not a fresh `states()` read.
   - `time_pattern` interval → full republish loop over all entities.
   - On-demand republish: a domain service call,
     `ha_mqtt_bridge.republish`, registered against the config entry,
     doing the same full republish loop as the time_pattern trigger. This
     is the Phase 1 replacement for the blueprint's
     `force_republish_sensors` event. A `button` entity is deferred to
     Phase 2 but will be a thin wrapper that calls this same service, so
     the service is the one place the "full republish" behavior lives.
   - Jitter: random 0–9s delay before each discovery/state publish,
     applied per-publish so a burst of state changes still spreads load
     (equivalent to the blueprint's `mode: parallel, max: 50`).
5. Unit tests for `discovery.py` (regex table, fallbacks) and
   `mqtt_bridge.py` (topic strings, forwarding, loop guard) — these encode
   `PROTOCOL.md` as executable spec.
6. Manual interop test: run this integration alongside a real instance of
   the blueprint (or a second migrated instance) against a shared broker,
   confirm discovery entities appear on both sides and no forwarding loop
   occurs.

**Acceptance criteria:** topic layout, payload shape, regex table, and loop
prevention match `PROTOCOL.md` exactly; both documented known limitations
are present and unfixed; a blueprint instance and this integration
interoperate over the same broker without behavior changes on the
blueprint side.

### Phase 2 — Integration polish

- Options flow for `time_pattern` (and any other fields worth making
  reconfigurable without a full reauth).
- `strings.json`/translations, `manifest.json` metadata for HACS
  (`hacs.json`, versioning), diagnostics platform for support requests.
- Broaden test coverage (config flow, coordinator timing) toward CI.
- `button` entity per config entry that calls `ha_mqtt_bridge.republish`.
- **Multi-entry support** (lower priority — not currently needed, but
  worth designing for): allow multiple config entries so one HA install
  can run several bridge instances (e.g. against different brokers or
  with different `bridge_name`/prefixes). Phase 1 targets a single entry;
  as long as `unique_id`/service registration in Phase 1 are keyed per
  config entry rather than assumed global, this should not require
  rework later.

### Phase 3 — Revisit deliberately-dropped/limited behavior

Only after Phase 1 is proven interoperable and Phase 2 has shipped:

- Investigate blueprint commit history for why availability/LWT tracking
  was removed (§7) before considering reintroducing it.
- Evaluate whether to fix the two known limitations (object_id domain
  collision, hardcoded `sensor` component for own entities) — these are
  wire-protocol changes and would need coordination with other running
  instances, so they're out of scope until Phase 1/2 are stable.

## Decisions

1. **On-demand full republish trigger**: `services.yaml` service call
   `ha_mqtt_bridge.republish` in Phase 1. The Phase 2 `button` entity
   calls this same service rather than duplicating the republish logic.
2. **Minimum HA core version**: `2026.7`. `manifest.json`
   `"homeassistant"` requirement pinned accordingly; target the
   `mqtt` component's `async_subscribe`/`async_publish` API surface as of
   that release.
3. **Multiple config entries**: not needed for Phase 1 (single entry is
   sufficient), but plausible later. Phase 1 must not hardcode
   assumptions that only one entry exists (e.g. service registration and
   any module-level state must be keyed per config entry). Full
   multi-entry support (e.g. per-entry MQTT client considerations) is
   tracked as a lower-priority Phase 2 item.

Phase 1 work can start directly from the file layout above, using
`PROTOCOL.md` as the acceptance spec for each module.
