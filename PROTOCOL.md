# Wire Protocol Contract (reverse-engineered from the blueprint)

Source: https://github.com/FeHJa/HA-Blueprint-MQTT-Bridge/blob/main/mqtt_bridge.yaml

This is the exact behavior Phase 1 of the integration must reproduce. Treat every detail
here as intentional/required unless explicitly marked "known limitation."

## 1. Configuration inputs (blueprint inputs → become config_entry data/options)

| Input | Default | Purpose |
|---|---|---|
| `entities` | — | list of entity_ids to bridge, any domain |
| `shared_discovery_prefix` | `share/homeassistant/` | shared federation prefix on the broker |
| `local_discovery_prefix` | `homeassistant` | this instance's own discovery prefix (blueprint only — **not used by this integration**, see §5a) |
| `sensor_value_prefix` | `share/jakob/` | where this instance's own state values are published |
| `time_pattern` | `/1` | periodic full-republish interval, minutes |
| `bridge_name` | `Bridge Jakob` | human name; slugified into `bridge_id` |

`slug_bridge_name` = lowercase `bridge_name`, spaces → `_`, then strip everything not in
`[a-z0-9_]`.

## 2. Topic layout

- Own discovery config → `{shared_discovery_prefix}sensor/{object_id}/config` (retained)
- Own state value → `{sensor_value_prefix}sensor/{object_id}` (retained)
- Forwarded remote discovery → `{local_discovery_prefix}/{component}/{object_id}/config` (retained)
  — **this is the blueprint's behavior; this integration does not do this, see §5a**
- `object_id` = `entity_id.split('.')[-1]` (domain stripped)
- `component` / `object_id` for forwarding are parsed positionally from the incoming topic,
  at the position right after the shared prefix

**Known limitation (do not fix in Phase 1):** `object_id` excludes the domain, so two
entities in different domains sharing an object_id (e.g. `sensor.garage` and
`binary_sensor.garage`) collide on the same topic — the retained message from whichever
publishes last wins. This happens upstream, on the *origin* bridge's own publish path, so
it isn't affected by §5a's change to how a *receiving* instance materializes incoming
messages — a native entity built from a colliding payload is just as last-write-wins as a
forwarded discovery message would have been.

**Known limitation (do not fix in Phase 1):** the discovery *component* segment for own
entities is hardcoded to `sensor` regardless of the source entity's actual domain. A
bridged `binary_sensor` or `input_boolean` is published as a generic MQTT `sensor`, not as
its native discovery type. Also unaffected by §5a: a receiving instance only ever sees
`component: sensor` in what it gets, native-entity or not.

## 3. Discovery payload (own entities → shared prefix)

```json
{
  "name": "<friendly_name, or title-cased object_id if missing>",
  "state_topic": "<sensor_value_prefix>sensor/<object_id>",
  "unique_id": "<slug_bridge_name>::<entity_id>",
  "device_class": "<omitted entirely if unknown, not null>",
  "unit_of_measurement": "<omitted entirely if unknown, not null>",
  "bridge_id": "<slug_bridge_name>",
  "protocol_version": 1,
  "device": {
    "identifiers": ["<slug_bridge_name>"],
    "name": "<bridge_name>",
    "sw_version": "1.0.3"
  }
}
```

`protocol_version` is a new field, not present in the original blueprint's
payload. It is safe to add: other instances already tolerate the
non-standard `bridge_id` key today (they ignore unknown JSON keys), so one
more integer field does not break their forwarding or loop-prevention
logic. See §8 for why it's there.

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

## 5a. Amendment: local materialization via native entities

**Status: implemented, supersedes the local-forwarding requirement in §5.**
Everything else in §5 — subscribing with the configured `shared_discovery_prefix`,
parsing `component`/`object_id`, and the loop-prevention guard — is unchanged and still
required exactly as written. What changes is only the last step: instead of forwarding
the verbatim payload to `{local_discovery_prefix}/{component}/{object_id}/config` for
Home Assistant's built-in `mqtt` integration to discover, this integration parses the
payload itself and creates or updates a native entity directly, through its own entity
platform, keyed by the payload's `unique_id`.

**Why this is safe to do without coordinating with the other two bridge instances**
(unlike the §8 Phase 3 redesign): this is purely a receiving-side, local decision. What a
bridge does with a message *after* the loop-guard check is never observable by the
instance that sent it — nothing about it is re-published onto the shared prefix. The
wire protocol, and every other instance's view of this bridge, is byte-for-byte
identical to before.

**What this fixes:** entities created this way are owned by this integration's config
entry, so removing the integration removes them automatically via Home Assistant's
standard config-entry cleanup — no separate depublish step needed for the receiving
side. It also means this integration no longer writes anything into
`local_discovery_prefix` (`homeassistant/` by default) for federated entities, removing
the collision risk with Zigbee2MQTT/ESPHome/Tasmota discovery that motivated the §8
redesign in the first place — for the receiving side, today, without waiting for Phase 3.

**What this does *not* fix:** neither of the two §2 known limitations (object_id/domain
collision, hardcoded `sensor` component) — both originate on the far side, in what the
*sending* bridge publishes, before this instance ever sees the message. Also unresolved:
cleanup of *this* bridge's own entities as seen by the *other* two instances (§3's
outbound side) — that still requires this bridge to depublish its own retained messages
on removal, independent of this amendment.

`local_discovery_prefix` remains listed in §1 as a historical note (it's still what the
*blueprint* does, and still relevant if you're comparing against another instance running
the blueprint unmodified) but is no longer part of this integration's config — see
MIGRATION_PLAN.md's Phase 1b for the implementation.

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

## 8. Forward compatibility: Phase 3 target design (named, not implemented)

Phase 1 reproduces the blueprint's MQTT-Discovery-emulation protocol exactly, as specified
above, with no wire changes. However, a target design for a future protocol generation has
been identified and is documented here so it doesn't need to be rediscovered later. It is
**not implemented in Phase 1 or Phase 2**, and is gated on coordinating a rollout with the
other two bridge instances — do not build it unprompted.

**Problem it solves:** the current protocol emulates MQTT Discovery by writing into
`local_discovery_prefix` (`homeassistant/` by default) — a namespace shared with
Zigbee2MQTT/ESPHome/Tasmota discovery. Combined with the §2 object_id/domain collision
known limitation, this is a real risk of a bridged entity colliding with, or being
overwritten by, an unrelated device's discovery message.

**Target design:** each bridge instance publishes its own retained JSON "manifest" —
a list of `{bridge_id, object_id, domain, name, device_class, unit, state_topic}` per
bridged entity — under a dedicated, bridge-only topic tree:
`ha_bridge/{bridge_id}/manifest`. Other instances subscribe only to the manifests of
bridges they explicitly opt into (a config-flow "follow list", not a blanket subscribe to
everything on the shared prefix). Each instance diffs the manifest against the native HA
entities it has already instantiated for that remote bridge, and creates/removes native
entities directly through its own entity platform. There is no MQTT Discovery emulation
in this design, no writes to the local discovery root, and no forwarding/echo-prevention
logic (§5) — a bridge just reads its followed peers' manifests and reconciles entities
against them. As a side effect, this eliminates both §2 known limitations: entities carry
their real domain and no longer collide on a shared `sensor/{object_id}` topic.

**Migration path — `protocol_version`:** every own-payload JSON this integration
publishes carries a `protocol_version` integer field (§3; Phase 1 sets it to `1`). Once a
future manifest-based payload exists, it will carry its own `protocol_version` (2+). This
lets any instance inspect `protocol_version` per bridge partner on incoming messages and
decide, per partner, whether to speak the legacy discovery protocol or the manifest
protocol — enabling a gradual, partner-by-partner rollout instead of a synchronized
cutover across all three instances on one day.

See `MIGRATION_PLAN.md` for the internal `ProtocolAdapter` abstraction that keeps Phase 1's
implementation swappable when this design is eventually built.

**Relationship to §5a:** §5a already brought the *local materialization* half of this
design forward — incoming messages become native entities, not forwarded discovery. What
Phase 3 still owns exclusively is the *outbound* half (own entities as a manifest instead
of MQTT Discovery emulation) and the follow-list/opt-in subscription model — both
wire-protocol changes requiring the cross-instance coordination described above. When
Phase 3 lands, its manifest-diffing logic is expected to feed the same entity
materialization layer §5a introduced, rather than building a second one.
