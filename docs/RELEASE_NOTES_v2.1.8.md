# v2.1.8 — Safe resident Smart Chime TTS reuse

v2.1.8 reduces repeated-announcement latency by reusing content already written to the two service-owned Smart Chime slots, while tying that trust to the current physical Chime boot. It preserves the bounded two-slot ownership model and fails closed whenever content continuity cannot be proven.

## Added

- Content-aware selection across the two existing dynamic TTS slots for repeated and recently used phrases.
- Persistent, application-authoritative content assignments validated against device identity, owned-slot metadata, and an uptime-derived boot epoch.
- Detailed slot-path metrics for acquisition, preflight, direct upload, synchronization, settle delay, total preparation, content hits/misses, overwrite skips, and lifecycle invalidations.
- Chime reconnect tracking through the Protect event stream.
- Regression coverage for restart reuse, reboot invalidation, write-ahead failure safety, cancellation cleanup, multi-target isolation, concurrent leases, and third-content eviction.

## Changed

- Repeated text on the same proven Chime boot can skip direct upload, synchronization, and settle work.
- Announcer-initiated reboot invalidates resident content proof before issuing the reboot and holds a per-target lifecycle barrier through the request.
- An observed Chime reconnect invalidates all resident proof for that Chime.
- Active leases record their actual target set so unrelated Chime traffic cannot starve lifecycle invalidation.
- Cancelled preparations release both slot and target metadata.
- Boot-epoch tolerance must be finite and nonnegative.

## Safety model

Static MAC, serial, firmware, logical slot, physical slot, and filename values do not prove that playable ringtone bytes survived a hardware reboot. v2.1.8 therefore estimates a boot epoch from direct-device uptime and stores it with each trusted content assignment. If the current epoch changes, is malformed, or cannot be read safely, the fast path is rejected and the phrase is rewritten before playback.

Content proof is revoked durably before physical writes and lifecycle operations. A failed or partial multi-target write remains untrusted and must be rewritten later. The release continues to use exactly two persistent UniFi Announcer-owned dynamic ringtone identities; arbitrary speech does not create additional Protect ringtone objects.

## Validation

The exact pre-release implementation passed:

- 323 backend tests;
- 12 Home Assistant custom-component tests;
- Ruff, Python compilation, JSON metadata, Docker Compose, Docker image build, HACS, and Hassfest checks;
- targeted secret/injection scanning;
- 200 repeated concurrency checks covering cancellation cleanup and unrelated-target invalidation;
- independent focused review with no blocking correctness or security findings.

Physical single-Chime validation confirmed:

- normal same-boot repeated speech used a zero-write resident path and played correctly;
- Announcer-process restart preserved same-boot reuse and played the correct phrase;
- physical Smart Chime reboot cleared both content proofs before playback;
- the first post-reboot request performed exactly one safe overwrite and played the correct phrase;
- the second request during the new boot performed zero writes and played the correct phrase.

The validation intentionally retains the earlier candidate's reboot failure and the subsequent remediation evidence. See the [complete v2.1.8 live validation record](https://github.com/bdini13/unifi-announcer/blob/v2.1.8/docs/validation/v2.1.8-live-latency-validation.md).

## Upgrade

Upgrade the backend and Home Assistant integration together. Preserve the existing `.env`, the actual `/data` mount, `track_registry.json`, and dynamic-slot content state. Build with the exact release SHA supplied through `GIT_SHA`, then verify `/version`, `/health`, and `/tts/slots/status` before audible playback.

No manual data migration is required from v2.1.7. Existing pre-v2.1.8 content assignments that lack boot-epoch evidence are intentionally treated as untrusted and rewritten once before reuse.

## Validation boundary

Physical validation covered one Smart Chime. Multi-Chime behavior is covered by automated fixtures and concurrency tests but has not been physically validated on multiple devices. No synchronized microphone benchmark was used, so this release does not claim measured acoustic latency.
