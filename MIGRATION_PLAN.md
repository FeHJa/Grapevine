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
├── manifest.json         # domain, dependencies: [mqtt], config_flow: true, iot_class
├── const.py               # DOMAIN, CONF_* keys, defaults, sw_version, the 8 regex patterns
├── config_flow.py         # ConfigFlow + OptionsFlow — maps blueprint inputs (§1), sets unique_id
├── scheduler.py            # entity-tracking, time_pattern trigger, on-demand republish, jitter
├── discovery.py           # payload building (§3), device_class/unit resolution (§3 table)
├── mqtt_bridge.py         # publish own discovery+state (§2-4), subscribe+forward (§5), loop guard
└── strings.json / translations/en.json
tests/
├── test_config_flow.py
├── test_discovery.py      # regex table, name fallback, device_class/unit precedence
├── test_mqtt_bridge.py    # topic construction, forwarding, loop prevention
├── test_scheduler.py       # time_pattern trigger, jitter bounds, on-demand republish
└── test_integration.py    # entry setup/reload/unload against pytest-homeassistant-custom-component
```

Rationale for the split: `discovery.py` is pure functions (entity/state in,
payload dict out) so the device_class/unit regex table and name-fallback
logic can be unit-tested without a running HA instance or MQTT broker.
`mqtt_bridge.py` owns all `homeassistant.components.mqtt` interaction
(`async_subscribe`/`async_publish`). `scheduler.py` owns timing: the
`time_pattern` trigger, the on-demand republish entry point, and jitter.

**Naming note:** this module is deliberately *not* called `coordinator.py`
and does not subclass HA's `DataUpdateCoordinator` — Phase 1 has no
"pull data periodically into entities" use case that pattern is for, and
naming it `coordinator.py` would invite someone to bolt that base class on
incorrectly later. Wired-up runtime objects (the MQTT bridge instance, the
scheduler, unsub callbacks) live on `entry.runtime_data`
(the standard 2026.x-core pattern), not an ad-hoc `hass.data[DOMAIN]` dict.

**Lifecycle/cleanup (must be explicit in `__init__.py`):** every
subscription and background trigger registered during `async_setup_entry`
must be unregistered via `entry.async_on_unload`, specifically: the
federation `async_subscribe` unsub callback, the `time_pattern` trigger's
cancel callback, and any in-flight jittered publish tasks. This matters
concretely for Phase 2's options-flow reload of `time_pattern` — without
it, a reload leaks the old MQTT subscription and every future incoming
discovery message gets forwarded twice.

**MQTT readiness:** `manifest.json` must declare `"dependencies": ["mqtt"]`,
and setup must wait for the MQTT client to be connected (e.g.
`mqtt.async_wait_for_mqtt_client`) before the first publish/subscribe —
otherwise a publish attempted during HA startup, before the broker
connection is up, is silently lost.

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
`bridge_name` slugifies to a non-empty string and `entities` is non-empty,
and sets `config_entry.unique_id = slug_bridge_name` — this both blocks
accidentally creating two entries with the same bridge identity and gives
Phase 2 multi-entry support a cheap collision guard when
`shared_discovery_prefix` overlaps between entries.

**Known UX tradeoff, flagged not resolved:** every field listed above under
`data` was a freely-editable blueprint input, not credential-like identity.
Putting them in `data` means changing any of them post-setup requires a
reconfigure flow (or delete/recreate) rather than an options edit. This is
the conventional HA split (identity vs. safely-reconfigurable), but if
`entities`/prefixes turn out to need frequent editing in practice, revisit
moving more of them into `options` before Phase 2 locks in the flow.

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
4. `scheduler.py`:
   - State-change listener on bridged entities → publish discovery+state
     for that one entity, using `trigger`/event `to_state.state` directly
     (§4), not a fresh `states()` read.
   - `time_pattern` trigger → full republish loop over all entities. Use
     a clock-aligned trigger (`async_track_time_change`/the same
     primitive HA's own `time_pattern` automation trigger is built on),
     **not** `async_track_time_interval` anchored to setup time — the §6
     jitter rationale ("three instances firing on the same minute mark")
     only holds if all instances actually fire on the same wall-clock
     minute, which a setup-time-anchored interval does not guarantee.
   - On-demand republish: a domain service call,
     `ha_mqtt_bridge.republish`, targeting a config entry (via a
     `config_entry_id`/device selector in `services.yaml`), doing the
     same full republish loop as the time_pattern trigger. This is the
     Phase 1 replacement for the blueprint's `force_republish_sensors`
     event. A `button` entity is deferred to Phase 2 but will be a thin
     wrapper that calls this same service. Services are registered once
     per domain, not per entry, so the handler must dispatch on the
     targeted entry via an entry-keyed registry (small dict of
     `entry_id -> handler`), not a singleton — this keeps multi-entry
     (Phase 2) from requiring a signature change later.
   - Jitter: random 0–9s delay before each discovery/state publish,
     applied per-publish via `hass.async_create_background_task` (tracked
     and auto-cancelled on unload) rather than raw `asyncio.create_task`,
     so a full republish burst can't leak untracked tasks past entry
     unload (equivalent in spirit to the blueprint's `mode: parallel, max: 50`).
5. Unit tests for `discovery.py` (regex table, fallbacks) and
   `mqtt_bridge.py` (topic strings, forwarding, loop guard) — these encode
   `PROTOCOL.md` as executable spec. In addition, integration-level tests
   using `pytest-homeassistant-custom-component` (`hass` + `mqtt_mock`
   fixtures) covering config-entry setup/reload/unload: subscription is
   created on setup, torn down on unload/reload (no duplicate forwarding
   after a reload), and the `time_pattern` trigger is cancelled on unload.
   Pure-function tests alone won't catch this class of plumbing bug.
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
- Broaden test coverage (config flow, scheduler timing) toward CI.
- `button` entity per config entry that calls `ha_mqtt_bridge.republish`.
- **Multi-entry support** (lower priority — not currently needed, but
  worth designing for): allow multiple config entries so one HA install
  can run several bridge instances (e.g. against different brokers or
  with different `bridge_name`/prefixes). Phase 1 targets a single entry;
  as long as `unique_id`/service registration in Phase 1 are keyed per
  config entry rather than assumed global, this should not require
  rework later. Note: two entries sharing the same `shared_discovery_prefix`
  will each independently process every retained federation message
  (wasteful, not incorrect) — acceptable for Phase 2, worth a mention in
  docs/options-flow help text.

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

## Architecture review (pre-implementation gate)

Before starting Phase 1 coding, this plan was reviewed by a dedicated
software-architecture pass. Findings already folded into the sections
above:

- Renamed `coordinator.py` → `scheduler.py` to avoid implying HA's
  `DataUpdateCoordinator` pattern, which doesn't fit this use case.
- Runtime state lives on `entry.runtime_data`, not `hass.data[DOMAIN]`.
- Explicit unload/reload cleanup requirement (subscriptions, trigger
  cancellation, in-flight jittered tasks) called out in Phase 1 step 4.
- `time_pattern` must be a clock-aligned trigger, not a setup-time-anchored
  interval, or the §6 jitter rationale doesn't hold.
- `config_entry.unique_id = slug_bridge_name` added to the config-flow
  mapping section.
- `manifest.json` MQTT dependency + wait-for-client requirement added.
- Jittered publishes must use `hass.async_create_background_task`, not
  raw `asyncio.create_task`, so they're cancelled on unload.
- Service registration must dispatch per targeted config entry (small
  entry-keyed registry), since HA services are domain-global — flagged in
  Phase 1 step 4 to avoid a signature change when Phase 2 multi-entry
  lands.
- Testing strategy extended to include `pytest-homeassistant-custom-component`
  integration tests for entry setup/reload/unload, not just pure-function
  unit tests.
- Two open tradeoffs flagged but deliberately left as-is for now: the
  data/options split may need revisiting if `entities`/prefixes turn out
  to need frequent edits (see Config entry mapping section), and
  same-prefix multi-entry federation overlap is accepted as a documented
  Phase 2 wrinkle rather than solved now.
