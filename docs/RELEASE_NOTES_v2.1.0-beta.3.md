# v2.1.0-beta.3 — Fixed-slot dynamic TTS

## Why this beta exists

Testing the beta.2 MCP interface with conversational AI exposed a device-storage flaw: each unique TTS phrase became a unique Protect ringtone identity. Beta.2 could safely remove old service-owned NVR identities, but it intentionally did not delete Smart Chime flash entries because direct deletion semantics were unproven. High-cardinality speech could therefore accumulate physical device artifacts.

Beta.3 changes the dynamic TTS storage model rather than weakening the safety boundary.

## Fixed two-slot architecture

Each persistent Announcer installation now provisions exactly two service-owned dynamic TTS identities:

```text
UA-TTS-1-<installation-suffix>
UA-TTS-2-<installation-suffix>
```

After provisioning, arbitrary TTS creates no new Protect ringtone identities. New speech is cached on the Announcer host, overwritten into one of the two proven device slots, and played through the persistent Protect ringtone ID.

The slots alternate and are leased through a conservative playback-duration guard so a later message cannot overwrite bytes that an earlier playback may still need.

## Fail-closed ownership

Direct writes are allowed only after the service proves and persists the exact physical device-slot mapping for its own Protect ringtone identity. The binding is rechecked before every overwrite.

If ownership evidence is missing or drifts, dynamic TTS fails closed. UniFi Announcer does not guess a slot and does not fall back to the beta.2 per-phrase allocation model.

Built-in, user-created, preset, and unknown tracks are never dynamic overwrite candidates.

## Migration

Beta.3 preserves beta.2 ownership records through startup and conservatively migrates legacy `dynamic_tts` records only after both new fixed slots are proven.

Where an old service-owned Protect fingerprint maps uniquely to a physical device track, beta.3 can replace the legacy audio bytes with a tiny silent artifact and delete the old NVR identity. Ambiguous device artifacts are retained as `legacy_orphan` evidence rather than modified automatically.

Do not delete `/data/track_registry.json` before upgrading from beta.2 if you want the migration to retain the strongest available ownership evidence.

## Bounded host cache

The content-addressed host TTS cache is now separately bounded. Defaults:

```env
TTS_CACHE_MAX_FILES=256
TTS_CACHE_MAX_BYTES=268435456
```

This prevents conversational workloads from moving the unbounded-growth problem from the Smart Chime to `/data/cache/tts`.

## New status endpoints

```text
GET /tts/slots/status
GET /tts/cache/status
```

MCP `get_status` includes the same fixed-slot/cache status, and internal `UA-TTS-*` identities are hidden from user-facing preset lists.

## Direct-device credential requirement

The fixed-slot overwrite path requires a current Smart Chime per-device adoption credential supplied through `CHIME_DIRECT_PASSWORD` or `CHIME_CREDENTIAL_FILE`.

Credential-retrieval procedures and raw authentication research remain intentionally excluded from the public repository.

If fixed-slot ownership cannot be established, arbitrary TTS is disabled rather than reverting to flash-growing behavior. Other safe functionality can remain available.

## Regression coverage

Beta.3 adds tests for:

- first-run creation of exactly two identities;
- restart without creating additional identities;
- 100 unique Hermes-style messages with the Protect ringtone count fixed at two;
- ping-pong slot selection;
- repeat-content overwrite skipping;
- slot ownership drift failing before device write;
- corrupt installation identity failing without allocation;
- dispatcher fixed-slot path never calling the legacy per-phrase uploader;
- host cache file-count and byte limits.

## Live validation required before stable

This beta should not be promoted to stable based only on mocked CI. Validate on a real Smart Chime with a high-cardinality workload and confirm:

- two service-owned dynamic slots after startup;
- no new dynamic identities after 10/25/50/100 unique messages;
- stable device storage/free space;
- correct speech on both alternating slots;
- no slot reuse/cross-talk under rapid announcements;
- presets, buzzer, default playback, groups, Home Assistant, and MCP remain functional.
