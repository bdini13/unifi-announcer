# Track ownership, fixed TTS slots, reconciliation, and migration

UniFi Announcer models three separate identities: the caller's logical object, the Protect/NVR ringtone identity used by `play-speaker`, and the physical Smart Chime flash slot. These identities must never be treated as interchangeable ownership proof.

## Ownership invariant

Only artifacts explicitly created and persisted by this service use `owner: unifi_announcer`. Records upgraded from an older schema become `owner: unknown`; discovery never imports or claims built-in, unknown, or user-created tones. Presets remain persistent and should be pinned.

## Dynamic TTS in v2.1.0-beta.3

Arbitrary TTS no longer creates one Protect ringtone per unique phrase.

Each Announcer `/data` installation owns exactly two persistent logical TTS slots:

```text
UA-TTS-1-<installation-suffix>
UA-TTS-2-<installation-suffix>
```

The installation UUID is generated once in `/data/installation.json`. Slot identities and per-chime physical bindings are persisted in `/data/dynamic_tts_slots.json`.

For each configured Smart Chime, a slot binding records the exact physical slot and filename plus the fingerprints used to prove ownership. Before every overwrite, the service rechecks that physical location. If the proof no longer matches, dynamic TTS fails closed; it never guesses another slot.

### Runtime flow

```text
text
  -> content-addressed host MP3 cache
  -> acquire logical slot 1 or 2
  -> verify each target's physical binding
  -> overwrite only that owned physical slot
  -> Protect play-speaker with persistent ringtone ID
  -> hold slot lease through conservative playback guard
  -> release slot
```

Two slots are used rather than one so a later announcement does not overwrite bytes while an earlier announcement may still be starting or playing. Slot reuse accounts for encoded audio duration, repeat count, and a safety margin.

When the selected slot already contains the same content fingerprint, the device write is skipped.

## Provisioning

A clean beta.3 installation:

1. loads or creates the persistent installation UUID;
2. proves the direct-device write capability for every configured target before allocation;
3. creates two distinct short silent MP3 bootstrap artifacts;
4. creates the two Protect ringtone identities once;
5. plays each bootstrap at volume 0 so Protect stages it to each target;
6. maps each bootstrap fingerprint to exactly one physical `speakerTrackList` position;
7. persists the proven mapping.

An exact-looking `UA-TTS-*` name is **not** enough to claim ownership if the local registry is missing. Such a collision fails closed.

## Presets

Presets remain normal persistent Protect ringtone identities. They are separate from the two dynamic slots and are never selected for dynamic overwrite.

The user-facing `/presets` and MCP `list_presets` responses hide internal `UA-TTS-*` identities.

## Migration from beta.2 and earlier

Beta.2 represented every unique spoken phrase as an owned `dynamic_tts` record. NVR garbage collection could delete the Protect object, but direct device deletion was intentionally prohibited because deletion semantics were unproven. High-cardinality workloads could therefore leave physical flash artifacts.

Beta.3 preserves the legacy registry through startup and performs migration before allocating new slot identities.

For each proven legacy dynamic record:

1. inspect the old Protect ringtone fingerprint;
2. look for an exact, unique physical match on each configured chime;
3. when ownership can be proved, overwrite that old physical artifact with a tiny silent bootstrap artifact rather than using unproven deletion semantics;
4. delete the old service-owned Protect ringtone identity;
5. remove the old registry record only when cleanup evidence is complete.

If ownership cannot be proved, the record becomes `legacy_orphan` and remains available as evidence. Unknown, user-created, preset, and built-in artifacts are never modified automatically.

This is intentionally conservative: ambiguous orphaned flash entries may require manual review rather than automatic deletion.

## Host-side TTS cache

The host MP3 cache is independent from Smart Chime slot count. It remains content-addressed so repeated phrases can bypass synthesis and encoding, but beta.3 bounds it with:

```text
TTS_CACHE_MAX_FILES=256
TTS_CACHE_MAX_BYTES=268435456
```

Pruning is least-recently-used by file timestamp and occurs at startup and after cache use.

## Protect capacity

`MAX_TOTAL_RINGTONES` remains a conservative capacity guard for initial fixed-slot provisioning and persistent preset creation.

Routine arbitrary TTS after provisioning creates **zero new Protect ringtone identities**.

`MAX_DYNAMIC_TRACKS` is deprecated in beta.3. It is retained temporarily only for compatibility with legacy registry/startup behavior; physical dynamic TTS usage is fixed at exactly two slots.

## Direct overwrite boundary

Generic direct staging remains disabled. Production dynamic TTS may call the existing owned-slot overwrite primitive only after the manager has persisted and revalidated exact service ownership.

The write boundary requires:

- a positive exact physical slot;
- an exact expected filename;
- `owner: unifi_announcer`;
- non-built-in status;
- compatible device capability;
- a current device credential;
- a persisted binding whose physical fingerprint still matches approved ownership evidence.

No direct deletion is performed. Destructive device endpoints remain blocked.

Credential-retrieval procedures and raw authentication research are intentionally excluded from the public repository.

## Status and diagnostics

Beta.3 exposes:

```text
GET /tts/slots/status
GET /tts/cache/status
```

MCP `get_status` also includes dynamic-slot and host-cache status.

A healthy fixed-slot system reports:

```json
{
  "mode": "two_slot_overwrite",
  "ready": true,
  "slot_count": 2
}
```

A stream of unique messages must not increase `slot_count` or the number of service-owned dynamic Protect identities beyond the initial two.
