# Track ownership, reconciliation, and garbage collection

The registry models three separate identities: the caller's `logical_key`, the
Protect/NVR ringtone object, and an optional device-flash slot. A `TrackRecord`
contains provenance (`owner`), kind, NVR id/name, device slot/filename/hash,
local MP3 path, creation/update/use timestamps, and a `pinned` flag.

## Ownership invariant

Only records created by this service use `owner: unifi_announcer`. Records
upgraded from the old schema become `owner: unknown`; discovery never imports or
claims built-in, unknown, or user-created tones. Presets should be pinned.

At startup the service loads the registry, takes read-only NVR ringtone and chime
`speakerTrackList` snapshots, and marks each registered identity present,
missing, or untracked. Snapshot entries absent from the registry remain absent.

## Conservative GC

`MAX_DYNAMIC_TRACKS` applies only to unpinned `dynamic_tts` records owned by the
service. Oldest-use records over the cap are handled in this order:

1. delete the NVR object only when the registry proves service ownership;
2. delete the recorded local MP3;
3. remove the registry entry;
4. **never delete device flash directly**. Slot deletion semantics have not been
   proven, so the result records `skipped: semantics unproven`.

If an NVR or disk deletion fails, the registry entry is retained for a later
reconciliation. This avoids losing ownership evidence. Built-ins, unknown
snapshot entries, non-owned records, and pinned records are never GC candidates.

`MAX_TOTAL_RINGTONES` (default 6) also reserves space against the complete
Protect ringtone inventory before each new TTS upload. If the total would cross
that ceiling, the service deletes only the least-recently-used unpinned
`dynamic_tts` record it owns. Presets, built-ins, pinned records, and unknown or
user-created tones are never selected. A capacity-style HTTP 400 triggers one
additional owned-dynamic eviction and one upload retry; it never broadens the
deletion boundary.

No direct-slot experiment is required for, or run by, reconciliation.

## Direct overwrite boundary

Generic direct staging is disabled. The explicit research method requires a
positive physical slot, an exact MP3 filename, `owner: unifi_announcer`, and
non-built-in metadata; it is not wired to production. Registry ownership and a
retained rollback artifact are mandatory before any separately approved use.
Deletion semantics remain unproven and no direct deletion is permitted.

Controlled tests also showed that a successful direct save is not enough to
prove that Protect's `speakerTrackList` has reconciled. Registry reconciliation
must therefore never treat an NVR snapshot as proof of newly staged direct bytes.
Deployment-specific evidence is intentionally excluded from the public repo.
