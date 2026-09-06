# Architecture

UniFi Announcer is a local adapter around undocumented UniFi Protect / Smart Chime behavior. Runtime dependencies are explicit in `AppServices` and are published through `app.state.services`; network resources are started and stopped by the application lifespan.

```text
Home Assistant ─┐
REST routes ────┤
local rules ────┼─> AnnouncementCommand -> AnnouncementDispatcher
MQTT ───────────┤     validate -> profile -> quiet hours -> targets/groups
MCP ────────────┘                         -> per-target arbitration

preset/default/buzzer --------------------------> Protect playback

dynamic text
  -> bounded content-addressed host MP3 cache
  -> Chime: DynamicTtsSlotManager -> owned slot -> Protect play-speaker
  -> camera: capability gate -> AAC/ADTS -> controller-minted talkback WSS
```

## Fixed-slot invariant

Starting in `v2.1.0-beta.3`, arbitrary TTS may consume exactly two service-owned dynamic ringtone identities per persistent Announcer installation. A UUID generated once under `/data` names the two identities. Each logical identity is mapped to an exact physical slot independently for every configured Smart Chime.

New unique phrases overwrite those two physical slots instead of creating new Protect ringtone identities. v2.1.8 adds content-aware selection: when a free slot already contains the requested content for every requested target and that content remains trusted for the current Chime boot, the write can be skipped entirely.

Persistent presets remain separate Protect ringtone identities. Slot-backed spoken preset behavior still uses the same dynamic two-slot manager; v2.1.8 does not add pinned/non-evictable preset slots.

## Why direct write and Protect playback are both used

The Smart Chime exposes an undocumented slot-overwrite route, but playback itself has no verified direct HTTP equivalent. The production dynamic path therefore deliberately splits responsibilities:

- **direct device HTTPS:** overwrite only an exact, proven `unifi_announcer`-owned slot;
- **Protect/NVR:** retain the persistent ringtone identity and issue `play-speaker`.

This is not an arbitrary direct-upload path. Before every write, the manager revalidates the persisted physical binding. Unknown, built-in, preset, user-created, and ownership-ambiguous tracks are excluded.

If ownership cannot be proven, dynamic TTS fails closed rather than reverting to the beta.2 per-phrase allocation model.

## Resident-content trust in v2.1.8

Protect `speakerTrackList` content fingerprints can remain stale after the physical Chime has accepted new bytes, so repeated-content reuse cannot depend exclusively on that control-plane fingerprint. v2.1.8 therefore maintains a separate application-owned content record for each logical-slot / Chime binding.

Trusted resident state includes:

- source MP3 hash and size;
- exact physical slot and owned filename;
- device identity;
- monotonically advancing write generation;
- write/use timestamps;
- an uptime-derived Smart Chime boot epoch.

A fast-path hit is allowed only when all requested targets have matching trusted resident state. If any requested target is missing or mismatched, the selected slot is rewritten for the required targets.

## Boot/lifecycle invalidation

Static MAC/serial/firmware and slot metadata do not prove that playable audio survived a hardware reboot. v2.1.8 therefore estimates the current physical boot epoch from direct-device uptime.

Resident proof is rejected or invalidated when:

- direct-device uptime cannot be read safely;
- the observed boot epoch differs beyond the configured tolerance;
- device identity changes;
- a Smart Chime reconnect is observed through Protect events;
- an Announcer-controlled lifecycle operation begins;
- ownership or filename evidence drifts;
- a physical write is about to occur;
- a write fails or only part of a multi-target operation completes.

The invalidation is persisted before a physical overwrite or guarded lifecycle action so a process crash cannot resurrect stale content proof.

## Slot and target leasing

Two logical slots avoid overwriting bytes that may still be needed by a previous playback. v2.1.8 also tracks the actual target set for active leases so lifecycle invalidation for one Chime does not incorrectly wait on unrelated Chime traffic.

The production manager:

1. refreshes boot continuity for the requested targets;
2. acquires a free logical slot, preferring one with matching trusted resident content;
3. records the actual requested target set for the lease;
4. verifies every requested target's physical ownership binding;
5. skips a write only for an exact trusted resident match;
6. otherwise durably revokes old content proof and overwrites the owned physical slot;
7. waits for bounded synchronization/settle evidence for new content;
8. commits the new content assignment only after all requested writes succeed;
9. issues playback through the existing per-Chime queues;
10. holds the slot until encoded-audio duration × repeats plus a conservative safety margin has elapsed.

Cancelled preparations release both slot and target metadata.

## Modules

- `app/config.py`: typed environment settings.
- `app/chime/{credentials,capabilities}.py`: direct-device credential and firmware gates.
- `app/protect/{client,events}.py`: lazy HTTP transport, protocol notes, runtime frame decoding, and reconnect observation.
- `app/audio/tts.py`: TTS encoding and normalized content keys.
- `app/audio/cache.py`: in-memory Protect `RingtoneIndex`.
- `app/audio/bounded_cache.py`: bounded host-side MP3 cache policy and host-cache metrics.
- `app/playback/dynamic_slots.py`: slot data model, ownership proof, overwrite, lease, migration primitives.
- `app/playback/fixed_slots.py`: fail-closed production provisioning followed by conservative legacy migration.
- `app/playback/production_slots.py`: v2.1.8 resident-content trust, boot epochs, lifecycle invalidation, content-aware acquisition, and slot-path timings.
- `app/playback/camera_talkback.py`: experimental camera capability, AAC/ADTS, URL-confinement, and talkback transport boundary.
- `app/playback/arbitration.py`: bounded per-Chime priority queues and dispositions.
- `app/rules/engine.py`: local rule action contracts.
- `app/integrations/mqtt.py`: MQTT lifecycle, discovery, events, and command adapter.
- `app/integrations/mcp.py`: optional thin MCP adapter.
- `app/routes/commands.py`: HTTP-to-command adapter.
- `app/dispatcher.py`: the only command execution path.
- `app/observability.py`: timings and in-memory metrics.
- `app/server.py`: production composition, reconnect invalidation wiring, and ASGI lifespan.

## Persistence

The `/data` volume contains durable ownership and reuse evidence:

```text
installation.json
  persistent Announcer installation UUID

dynamic_tts_slots.json
  two slot identities + per-Chime physical bindings

dynamic_tts_content_state.json
  v2.1.8 resident content assignments, write generations, device/boot evidence

track_registry.json
  presets / beta.2 legacy ownership evidence

cache/tts/*.mp3
  bounded content-addressed host TTS cache
```

Do not discard registry data casually during upgrades. Ambiguous physical artifacts are intentionally retained/reported instead of being claimed without evidence. Missing or pre-v2.1.8 content state is safe: the optimization is treated as untrusted and content is rewritten before later reuse.

## Reverse-engineered protocol boundary

Direct Chime endpoints are **undocumented**, verified against UP Chime firmware **1.7.20**. Read-only device info/support behavior and the exact owned-slot overwrite primitive are isolated behind capability and ownership gates. Unknown firmware fails closed. Destructive endpoints remain blocked before network I/O.

Credential retrieval is not implemented by UniFi Announcer. The supported onboarding path is Protect's authenticated Manual Recovery → Reveal UI flow documented in [`CREDENTIALS.md`](../CREDENTIALS.md).

REST, Home Assistant, local rules, MQTT, and MCP all produce `AnnouncementCommand` values for the same dispatcher. Group fanout uses the existing independent per-Chime queues and common disposition semantics.

## Experimental camera talkback targets

Camera targets are explicitly configured by name and Protect ID; bootstrap discovery never opts cameras in automatically. The dispatcher partitions mixed groups before preparing audio. Smart Chime members continue through fixed slots unchanged, while camera members receive the same synthesized MP3 through a separately injected talkback backend and their own arbitration queues.

Before each camera session, the backend re-reads Protect bootstrap and requires a connected camera with `hasSpeaker=true` plus the physically verified AAC, mono, 16-bit, `serverudp` profile. It converts MP3 to AAC-LC ADTS with a cancellable, streaming output bound; validates every frame's profile/rate/channel/single-block metadata; obtains a fresh controller-minted talkback URL; confines that URL to the configured controller host and verified talkback port `7443`; sends only the single scoped `TOKEN` cookie; opens and arms the socket before mixed-group Chime slot/playback effects; then sends complete frames at `1024 / sample_rate`, drains, and closes. It does not reconnect or replay after uncertain delivery.

The first implementation excludes Opus/RTP profiles and camera ringtone semantics. Cameras support text announcements and repeats only; volume remains device-managed. Signed URLs and cookies are never persisted, returned, or logged.
