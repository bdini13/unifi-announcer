# Unreleased reliability fixes

This source candidate fixes cancelled Piper stream reuse, saved-preset selection, camera-group lock ordering and deadlines, per-Chime credential selection, playback-duration reservations, admission before audio preparation, automatic fixed-slot startup recovery, and HA command/polling timeout separation. HA device registry compatibility is tested at the supported 2026.3.2 minimum and at 2026.10.0.

`PIPER_VOICE=default` retains the Piper server's voice; an explicit voice name is sent in the Wyoming request. `TTS_RATE` accepts a speed multiplier from 0.5 to 2.0: Piper uses FFmpeg tempo adjustment, while Edge receives a rate percentage. Cache keys include a new synthesis revision so older audio generated while these settings were ignored is not reused. The host cache remains bounded; the two device slot identities are unchanged.

Slot registry and resident-content state now flush file data before atomic replacement and flush the parent directory afterward. This strengthens write-ahead invalidation across host crashes; actual power-loss durability still depends on the storage/filesystem and requires physical validation.

Unavailable slots retry startup every `TTS_SLOT_RECOVERY_INTERVAL` seconds (default 30), with each attempt limited to 90 seconds. All configured Chimes must pass the existing identity, ownership, and mapping checks before dynamic TTS becomes ready. Readiness is degraded while recovery is needed. No ownership checks are relaxed and failed recovery never guesses a physical slot.

## Offline audit fixes — 2026-10-25

The [REA audit](validation/rea-audit-2026-10-24.md) identified Protect as a second writer to dynamic slots. Resident reuse now requires matching current inventory as well as local proof and device/boot continuity. Ringtone/inventory events and stream gaps revoke content proof, and events during preparation prevent a stale preparation from reaching play. Recently acknowledged direct writes retain the bounded same-slot/same-filename stale-inventory allowance. External synchronization can still race observed state; these changes do not establish an atomic device/controller guarantee.

Ordinary play now preflights catalog identity and connection state. Presets additionally fetch canonical audio and require its fingerprint in the target inventory. This adds controller reads compared with historical cached-play timings. Missing/ambiguous identities, disconnected targets, and absent fingerprint evidence fail before playback. Public Protect metadata does not expose its complete filename/physical-track lookup, so HTTP success remains acknowledgment rather than proof of correct audible output. Manual `/play-default` and the HA button are correctly described as built-in track 1, independently of camera assignments.

Playback deadlines are durably written to `playback_guards.json` before a potentially audible request or uncertain slot/maintenance write. They survive process restart; slot startup and ringtone mutation honor the same reservations. Unknown device repeat settings reserve up to 10 plays, while explicit API repeats remain 1–6. Malformed deadline state fails closed. Failed or cancelled startup/maintenance retains the command-timeout hold, which can delay retries beyond the 30-second polling interval; confirmed success clears it. These remain duration estimates, including a conservative allowance for uncertain network completion.

`dynamic_tts_provisioning.json` retains original before-snapshots through lost upload, staging, or inventory responses. Recovery requires positive identity or exact known-content evidence, commits each target separately, and refuses unrelated or unidentified transformed deltas. Same-name replacement IDs cannot inherit old physical bindings. Explicit sparse track numbers are used during binding, preflight, and legacy cleanup. Readiness remains false throughout migration/content restoration. Malformed optional resident cache state becomes a safe miss.

Forced preset replacement now needs spare capacity, verifies and durably records the replacement before retiring the old ID, and reconciles interrupted writes through `preset_update.json`. Unknown upload outcomes and unverified deletion remain errors; they never authorize deleting an unfamiliar same-name object. Duration metadata follows exact identity, saved presets cannot remain eligible for legacy dynamic eviction, and duplicate names fail lookup. HA's global announcement action supports explicit `config_entry_id` routing and remains registered while another entry is loaded; normal setup retains its existing single-entry restriction.

All October 25 changes were developed with the Chime offline. The later [October 30 single-Chime session](validation/reliability-single-chime-2026-10-30.md) adds temporary-deployment and audible evidence for the exact backend revision recorded there; it does not physically validate every repair.

## Single-Chime candidate test — 2026-10-30–31

Backend `998eb0926c1a20b5a90462795978a12353ad54a2` was temporarily tested on one Smart Chime running firmware `1.7.20`, with Protect `7.3.70` and UniFi OS `5.1.34`. Image provenance and the running version matched. The listener confirmed distinct REST phrases in order, a normalized WAV upload, native HA `tts.speak`, and two complete repetitions across a backend restart followed by a recovery phrase. The durable playback guard survived the restart, and readiness remained false until recovery. The same two owned identities were retained. Nine invalid media/parameter requests returned the expected errors without changing slot state.

No zero-write resident hit was observed in the initial October 30 checks; replay uploaded fresh audio and used the existing bounded stale-inventory fallback. Concurrent text/media requests also completed audibly in order without overlap. HA ran its existing beta.4 component on HA `2026.9.1`, so this is not an exact-source physical test of the candidate integration.

**Immediate post-reconnect playback remains an open release gate:** on the October 31 repeat with the same candidate, device uptime reset and Protect reported `CONNECTED`, but the first fresh announcement received Protect HTTP 500 from `play-speaker`. Announcer returned HTTP 502/disposition `failed`; this was not a false success. After the uncertainty guard expired, an explicit delayed retry returned HTTP 200/played, and the listener confirmed clear speech exactly once. That recovery does not erase the immediate failure; its cause remains unproven. The listener corrected the earlier “no audio” response from the original check; that response is superseded and does not establish a silent-success defect. The [session record](validation/reliability-single-chime-2026-10-30.md) preserves both results. The virtual preset's API result was not acoustically validated.

The candidate stopped cleanly, and the original service was restored with its unchanged image and environment. Health was `ok`, both original slot identities were ready, and current shared data was retained rather than replaced with an obsolete content-state backup.

A follow-up fix prevents unready announcement and preset requests from renewing an uncertain-write hold when no write began. The combined media branch passed 591 backend tests in 4.54 seconds and Ruff; the primary branch passed 557 backend tests in 4.51 seconds. This correction postdates the live image, was not deployed, and still needs validation on a rebuilt candidate. It is separate from the unresolved Protect HTTP 500 after reconnect and is not presented as a fix for that failure.

## Validation required before release

Automated regressions cover cancellation, preset transactions and identity, reversed camera groups, bounded urgent overload, per-target dedupe before preparation, durable acoustic guards, interrupted provisioning, controller-event races, malformed optional state, sparse slot numbering, credential isolation/rotation, persistence failure, and minimum/current HA compatibility. These are synthetic tests, not new device-validation claims.

Before release, validate the final image, Compose, HACS, and Hassfest against the final source revision. The October 30 session covers consecutive phrases, WAV and HA TTS playback, and long audio with repeats across an active-play backend restart for its recorded build. Outstanding hardware gates include interrupted synthesis, saved audio whose content differs from its name, controller ringtone synchronization, two Chimes with distinct credentials, mixed/reversed camera groups, and startup with a temporarily unreachable device followed by recovery. Recheck changed paths on the rebuilt candidate, including its exact HA component. Record the exact revision, device count, and observed audible result.

## Rollback

Back up `.env` and the entire mounted `/data` directory before testing. Preserve the installation, slot registry, provisioning journal, `preset_update.json`, and `playback_guards.json`; they contain ownership, transaction, or playback-safety evidence. Retain the currently deployed backend image and matching HA component. Let active playback holds expire before reverting to code that ignores the new durable deadlines. Stop the candidate before restoring the prior backend/component and, if necessary, its matching data backup. Added preset duration metadata is optional and older track-registry readers ignore it; fixed slot ownership/schema remains unchanged. Reverting code removes the new safeguards and retries.

No release tag or published version has changed. The October 30–31 candidate deployment was temporary; [restoration of the original service was verified](validation/reliability-single-chime-2026-10-30.md#candidate-and-scope). Security vulnerability remediation is outside this change set.

## Reliability validation before CI cleanup — 2026-10-10

- Main reliability branch: 453 backend tests passed with interpreter warnings treated as errors.
- HA integration: 23 tests passed in each minimum/current environment. The minimum was previously documented as 2026.3.4; the pinned test helper `0.13.318` actually requires HA 2026.3.2, confirmed during the October 25 verification.
- The separate PR43 compatibility worktree: 436 backend tests and 28 HA tests on each supported test version passed.
- Ruff, Python compilation, JSON metadata, workflow YAML parsing, and whitespace checks passed.
- FFmpeg 7.1 encoded a synthetic two-second tone at 0.5×, 1×, and 2× into approximately 4.05, 2.06, and 1.07 seconds respectively; no speaker playback was involved.
- At this checkpoint, Docker/Compose, HACS/Hassfest CI execution, and physical device validation were pending. No live deployment or GitHub branch had been modified.

The subsequent [CI review](CI.md) removed redundant tests and eliminated fake-device waits; that October 10 baseline had 436 tests and ran in approximately 6.5 seconds. The offline audit adds focused failure-path regressions rather than reinstating historical prose snapshots or fake-device delays.

## Single-Chime candidate test — 2026-10-10

[Physical test results](validation/reliability-single-chime-2026-10-10.md) confirm distinct phrases, resident replay, repeats without interruption, and playback after a service restart on one Chime. The session also exposed stale capability health after a failed startup probe; failed probes now retry read-only device information every 30 seconds until success, with shutdown cancellation. Other release gates remain outstanding.
