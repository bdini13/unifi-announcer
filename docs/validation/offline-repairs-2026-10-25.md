# Offline reliability repairs — 2026-10-25

These unreleased changes follow the [REA audit](rea-audit-2026-10-24.md). Work used local source, retained controller artifacts, synthetic inventories, and fake transports. No live device requests, playback, uploads, service restart, or deployment were performed in this repair pass. Passing tests establish software behavior; they do not establish audible correctness on a Chime.

## Implemented repairs

| Audit finding | Change and regression coverage |
| --- | --- |
| STATE-5: Protect restores canonical content without a reboot | Resident reuse now requires matching current inventory bytes as well as boot/ownership evidence. Inventory/catalog/lifecycle changes revoke leases; exact feedback matching an in-progress Announcer write does not revoke it. If preparation obtained fresh inventory proof, the final playback check rejects fingerprint drift even when its event was missed. Tests cover restoration, conflicting/missing/malformed inventory, own-write feedback, and cancellation. The post-write stale-inventory fallback remains a limit below. |
| CTRL-1: HTTP success can conceal built-in fallback | Public playback checks current catalog identity, connectivity, and resident content before posting. Dynamic playback additionally requires an active prepared lease and its proven filename/physical slot. Missing-record HTTP 400/404 is classified for stale-ID handling. **Partial mitigation:** ordinary presets still lack complete filename-to-slot proof; see limits below. |
| STATE-1: interrupted initial provisioning | A durable journal retains the original inventory and operation evidence. Recovery can reuse a proven completed staging operation after a lost response. Ambiguous/transformed inventory still fails closed rather than guessing ownership. |
| STATE-2: restart loses active reservations | Durable per-target deadlines are written before playback and uncertain slot writes. Restarts retain the acoustic hold; Linux/macOS boot changes conservatively rebase it once. Cancellation and failed journal writes are covered. Startup and preset mutation acquire the same target reservations. |
| C1: destructive preset replacement | Upload and verify a new identity, persist registry state, then retire the previous recording. A journal reconciles interrupted commits and rolls back only a response-proven new ID. Full capacity is rejected before deleting the previous recording. |
| C2: duration belongs to an old identity | Use duration only when the registry ID matches the selected recording. A stale-ID retry clears old duration and extends the hold conservatively. |
| STATE-3: malformed optional content cache | Validate the complete optional cache structure; discard invalid optimization state without discarding the ownership registry. |
| STATE-4: premature readiness | Publish readiness only after migration, binding recovery, and production content restoration finish. |
| C3: preset retains dynamic eviction eligibility | Explicit conversion sets preset classification and pins it. Same-name identity replacement cannot inherit a physical binding. |
| C4: shared HA service has singleton routing | Optional `config_entry_id` selects an instance; ambiguous routing and unloaded targets fail explicitly. Unloading another instance preserves the global service. The manifest continues to restrict normal setup to a single entry. |

Additional corrections distinguish manual built-in track 1 from a camera's assigned doorbell tone, reserve up to ten plays when Protect's repeat setting is inherited, and use reported physical track numbers rather than list offsets. Explicit Announcer repeat overrides remain limited to 1–6. Legacy cleanup refuses ambiguous slot numbering.

## Recovery and capacity

Keep the mounted data directory persistent. `playback_guards.json`, `dynamic_tts_provisioning.json`, `preset_update.json`, and the ownership registry contain recovery evidence. Deleting them is not a general recovery procedure. Invalid safety journals stop the affected operation; invalid optional content-cache state merely disables reuse. A lost upload response with a newly discovered same-name ID remains an explicit reconciliation case because the service cannot prove that it owns that object.

Preset replacement needs one spare catalog entry while both identities exist. `MAX_TOTAL_RINGTONES` counts every returned catalog record, including built-ins; its conservative default remains six. On the inspected controller, four built-ins plus two service slots consume that default allowance. Persistent presets require deliberately configured headroom, and replacement needs another spare entry. Controller definitions of six custom physical slots and twelve custom catalog records do not prove that all those records can be resident on a particular device. This repair does not silently expand the configured limit.

## Validation

The backend suite includes focused regressions for the failure paths above, using fake controllers, deterministic barriers, and short scheduler delays. A redundant long admission-test sleep was shortened while retaining separate assertions for the production duration calculation. Both minimum and current HA compatibility environments remain valuable and are retained.

Final primary-branch local checks:

| Check | Result |
| --- | --- |
| Backend, Python 3.12.14, warnings as errors | 555 passed in 4.42 seconds |
| HA 2026.3.2, Python 3.14.7 | 28 passed in 0.37 seconds |
| HA 2026.10.0, Python 3.14.7 | 28 passed in 0.66 seconds |
| Ruff, Python compilation, JSON metadata, whitespace | Passed |

The pinned minimum test helper requires HA **2026.3.2**; older descriptions incorrectly called it 2026.3.4. Local timings exclude dependency installation and container build. Docker/FFmpeg are unavailable locally, so Compose, image build, and the codec smoke require the GitHub CI jobs.

The separate native-media candidate also defers normalization until dispatcher admission and target/policy checks, bounds pending uploads and decoders, shares a deadline across waiting/probing/encoding, and terminates subprocesses on cancellation. Its CI performs a short silent WAV-to-MP3 check in the existing built container, without a second image build or network access. Integration with this reliability branch is validated separately.

## Remaining limits and later checks

- Ordinary-preset canonical MP3 hashes prove that matching bytes exist somewhere in inventory. They do not prove which filename/physical slot the controller will select when distinct identities contain identical bytes. Exact public identity mapping still needs a verified contract before implementation.
- Inventory observation, a direct write, and Protect-mediated playback are separate operations. A controller write after the final check remains possible; event invalidation narrows the window but is not an atomic device transaction.
- Protect inventory can lag an acknowledged direct upload. The existing bounded synchronization fallback still allows playback through an exactly owned slot after that timeout. In that fallback, stale metadata and a same-filename canonical restoration cannot be distinguished if the corresponding controller event is missed. This is weaker than proof of current playback bytes and still needs device investigation; it never permits skipping a new write based on conflicting inventory.
- Upload cancellation may outlive a client request. The durable uncertainty hold uses the configured command timeout; firmware completion timing has not been proven to obey that bound. REA did not complete native Xtensa analysis.
- Failed startup and maintenance retain their uncertainty deadline, even when failure may have preceded a write. Recovery can therefore wait the command timeout plus its polling interval; successful confirmed completion clears the maintenance hold.
- Guards estimate duration rather than observe acoustic completion. Host boot identity is supported on Linux and macOS; other platforms have only clock-based fallback behavior.
- New provisioning recovery, controller resynchronization after preset mutation, restart during active playback, and end-to-end HA playback require a reachable Chime and a listener before release. No new multi-Chime physical validation is claimed.
