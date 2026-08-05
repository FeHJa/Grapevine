# Wire Protocol Contract (reverse-engineered from the blueprint)

Source: https://github.com/FeHJa/HA-Blueprint-MQTT-Bridge/blob/main/mqtt_bridge.yaml

This is the exact behavior Phase 1 of the integration must reproduce. Treat every detail
here as intentional/required unless explicitly marked "known limitation."

## 1. Configuration inputs (blueprint inputs → become config_entry data/options)

| Input | Default | Purpose |
|---|---|---|
| `entities` | — | list of entity_ids to bridge, any domain |
| `shared_discovery_prefix` | `share/homeassistant/` | shared federation prefix on the broker |
| `local_discovery_prefix` | `homeassistant` | this instance's own discovery prefix |
| `sensor_value_prefix` | `share/jakob/` | where this instance's own state values are published |
| `time_pattern` | `/1` | periodic full-republish interval, minutes |
| `bridge_name` | `Bridge Jakob` | human name; slugified into `bridge_id` |

`slug_bridge_name` = lowercase `bridge_name`, spaces → `_`, then strip everything not in
`[a-z0-9_]`.

## 2. Topic layout

- Own discovery config → `{shared_discovery_prefix}sensor/{object_id}/config` (retained)
- Own state value → `{sensor_value_prefix}sensor/{object_id}` (retained)
- Forwarded remote discovery → `{local_discovery_prefix}/{component}/{object_id}/config` (retained)
- `object_id` = `entity_id.split('.')[-1]` (domain stripped)
- `component` / `object_id` for forwarding are parsed positionally from the incoming topic,
  at the position right after the shared prefix

**Known limitation (do not fix in Phase 1):** `object_id` excludes the domain, so two
entities in different domains sharing an object_id (e.g. `sensor.garage` and
`binary_sensor.garage`) collide on the same topic — the retained message from whichever
publishes last wins.

**Known limitation (do not fix in Phase 1):** the discovery *component* segment for own
entities is hardcoded to `sensor` regardless of the source entity's actual domain. A
bridged `binary_sensor` or `input_boolean` is published as a generic MQTT `sensor`, not as
its native discovery type.

## 3. Discovery payload (own entities → shared prefix)

```json
{
  "name": "<friendly_name, or title-cased object_id if missing>",
  "state_topic": "<sensor_value_prefix>sensor/<object_id>",
  "unique_id": "<slug_bridge_name>::<entity_id>",
  "device_class": "<omitted entirely if unknown, not null>",
  "unit_of_measurement": "<omitted entirely if unknown, not null>",
  "bridge_id": "<slug_bridge_name>",
  "device": {
    "identifiers": ["<slug_bridge_name>"],
    "name": "<bridge_name>",
    "sw_version": "1.0.3"
  }
}
```

### device_class / unit_of_measurement resolution order

1. Use the source entity's actual `device_class` / `unit_of_measurement` attribute if present.
2. Else, regex-match the `object_id` suffix against these 8 known patterns (first match
   wins, case-insensitive, pattern shape is `(^|_)<word>(_|$)`):

| object_id contains | device_class | unit |
|---|---|---|
| `temperature` | temperature | °C |
| `humidity` | humidity | % |
| `pressure` | pressure | hPa |
| `power` | power | W |
| `energy` | energy | kWh |
| `current` | current | A |
| `voltage` | voltage | V |
| `light` | illuminance | lx |

3. If neither matches, the key is omitted from the payload entirely (not sent as `null`).

Port these regexes verbatim — do not rewrite or "simplify" them.

## 4. State payload

Raw state string only (no JSON wrapping), published retained to the state topic. Uses
`trigger.to_state.state` on state-triggered publishes (cheaper than re-reading `states()`).

## 5. Incoming discovery handling (federation from other instances)

- Subscribe to `{shared_discovery_prefix}+/+/config` (the blueprint hardcodes this as a
  literal string rather than substituting the configured prefix — a blueprint-engine
  limitation, not a protocol requirement; the integration should subscribe using the
  actually configured `shared_discovery_prefix`)
- On message: parse `component` / `object_id` from the topic (see §2), forward the
  **payload verbatim, unchanged bytes**, to `{local_discovery_prefix}/{component}/{object_id}/config`,
  retained
- **Loop prevention (must be preserved exactly):** skip forwarding if
  `payload.bridge_id == own slug_bridge_name`, OR `payload.unique_id` starts with
  `"{slug_bridge_name}::"` or `"{slug_bridge_name}."`. The other two instances rely on
  recognizing this bridge_id/unique_id prefix convention to avoid re-forwarding your own
  messages back to you — if this logic isn't preserved exactly, expect forwarding loops.

## 6. Timing / triggers

- State-change on any bridged entity → publish discovery + state for that one entity
- Time-pattern trigger (every `time_pattern` minutes) → full republish loop over all bridged
  entities (discovery + state) — this is the resync-after-restart / retained-message-refresh
  mechanism
- On-demand full republish (was a custom HA event `force_republish_sensors` in the
  blueprint) → same as above
- Incoming MQTT discovery on the shared prefix → forwarding logic (§5)
- **Jitter:** before any discovery/state publish, a random 0–9 second delay is applied.
  This desyncs near-simultaneous publishes from multiple instances hitting the broker at
  the same moment (three instances all firing on the same time-pattern minute mark would
  otherwise collide). Preserve this or a functionally equivalent spread mechanism.
- Original automation ran with `mode: parallel, max: 50` — relevant because bursts of state
  changes across many bridged entities can produce many simultaneous publishes.

## 7. Deliberately dropped feature

The blueprint name is "...(stable, no availability)" — availability/LWT tracking existed at
some point and was removed for stability. Check the source repo's commit history for why
before reintroducing this in Phase 3.
