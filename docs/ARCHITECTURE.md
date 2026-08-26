# Architecture

UniFi Announcer is a local adapter around undocumented UniFi Protect / Smart Chime behavior. Runtime dependencies are explicit in `AppServices` and are published through `app.state.services`; network resources are started and stopped by the application lifespan.

```text
Home Assistant ─┐
REST routes ────┤
local rules ────┼─> AnnouncementCommand -> AnnouncementDispatcher
MQTT ───────────┤     validate -> profile -> quiet hours -> targets/groups
MCP ────────────┘                         -> per-chime arbitration

preset/default/buzzer --------------------------> Protect playback

dynamic text
  -> bounded content-addressed host MP3 cache
  -> DynamicTtsSlotManager
  -> verify exact owned physical slot(s)
  -> direct overwrite UA-TTS-1 or UA-TTS-2
  -> persistent Protect ringtone identity
  -> Protect play-speaker
  -> Smart Chime
```

## Fixed-slot invariant

Starting in `v2.1.0-beta.3`, arbitrary TTS may consume exactly two service-owned dynamic ringtone identities per persistent Announcer installation. A UUID generated once under `/data` names the two identities. Each logical identity is mapped to an exact physical slot independently for every configured Smart Chime.

New unique phrases overwrite those two physical slots in a lease-protected ping-pong pattern. They do not create new Protect ringtone identities after provisioning.

Presets remain separate persistent ringtone identities.

## Why direct write and Protect playback are both used

The Smart Chime exposes an undocumented slot-overwrite route, but playback itself has no verified direct HTTP equivalent. The production dynamic path therefore deliberately splits responsibilities:

- **direct device HTTPS:** overwrite only an exact, proven `unifi_announcer`-owned slot;
- **Protect/NVR:** retain the persistent ringtone identity and issue `play-speaker`.

This is not an arbitrary direct-upload path. Before every write, the manager revalidates the persisted physical binding. Unknown, built-in, preset, user-created, and ownership-ambiguous tracks are excluded.

If ownership cannot be proven, dynamic TTS fails closed rather than reverting to the beta.2 per-phrase allocation model.

## Slot leasing

Two logical slots avoid overwriting bytes that may still be needed by a previous playback. The slot manager:

1. acquires logical slot 1 or 2;
2. verifies every target's physical binding;
3. skips the write if that slot already contains the requested content hash;
4. otherwise overwrites each target's corresponding physical slot;
5. issues playback through the existing per-chime queues;
6. holds the slot until encoded-audio duration × repeats plus a conservative safety margin has elapsed.

## Modules

- `app/config.py`: typed environment settings.
- `app/chime/{credentials,capabilities}.py`: direct-device credential and firmware gates.
- `app/protect/{client,events}.py`: lazy HTTP transport, protocol notes, and runtime frame decoding.
- `app/audio/tts.py`: TTS encoding and normalized content keys.
- `app/audio/cache.py`: in-memory Protect `RingtoneIndex`.
- `app/audio/bounded_cache.py`: bounded host-side MP3 cache policy.
- `app/playback/dynamic_slots.py`: slot data model, ownership proof, overwrite, lease, migration primitives.
- `app/playback/fixed_slots.py`: fail-closed production startup ordering and migration-first provisioning.
- `app/playback/arbitration.py`: bounded per-chime priority queues and dispositions.
- `app/rules/engine.py`: local rule action contracts.
- `app/integrations/mqtt.py`: MQTT lifecycle, discovery, events, and command adapter.
- `app/integrations/mcp.py`: optional thin MCP adapter.
- `app/routes/commands.py`: HTTP-to-command adapter.
- `app/dispatcher.py`: the only command execution path.
- `app/observability.py`: timings and in-memory metrics.
- `app/server.py`: production composition and ASGI lifespan.

## Persistence

The `/data` volume contains the durable ownership evidence required by beta.3:

```text
installation.json
  persistent Announcer installation UUID

dynamic_tts_slots.json
  two slot identities + per-chime physical bindings

track_registry.json
  presets / beta.2 legacy ownership evidence

cache/tts/*.mp3
  bounded content-addressed host TTS cache
```

Do not discard registry data casually during a beta.2 -> beta.3 migration. Ambiguous physical artifacts are intentionally retained/reported instead of being claimed without evidence.

## Reverse-engineered protocol boundary

Direct chime endpoints are **undocumented**, verified against UP Chime firmware **v1.7.20**. Read-only device info/support behavior and the exact owned-slot overwrite primitive are isolated behind capability and ownership gates. Unknown firmware fails closed. Destructive endpoints remain blocked before network I/O.

Credential-retrieval procedures and raw authentication research are intentionally excluded from the public repository.

REST, Home Assistant, local rules, MQTT, and MCP all produce `AnnouncementCommand` values for the same dispatcher. Group fanout uses the existing independent per-chime queues and common disposition semantics.
