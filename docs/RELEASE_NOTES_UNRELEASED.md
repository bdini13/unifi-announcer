# Unreleased reliability fixes

This source candidate fixes cancelled Piper stream reuse, saved-preset selection, camera-group lock ordering and deadlines, per-Chime credential selection, playback-duration reservations, admission before audio preparation, automatic fixed-slot startup recovery, and HA command/polling timeout separation. HA device registry compatibility is tested at the supported 2026.3.4 minimum and at 2026.10.0.

`PIPER_VOICE=default` retains the Piper server's voice; an explicit voice name is sent in the Wyoming request. `TTS_RATE` accepts a speed multiplier from 0.5 to 2.0: Piper uses FFmpeg tempo adjustment, while Edge receives a rate percentage. Cache keys include a new synthesis revision so older audio generated while these settings were ignored is not reused. The host cache remains bounded; the two device slot identities are unchanged.

Slot registry and resident-content state now flush file data before atomic replacement and flush the parent directory afterward. This strengthens write-ahead invalidation across host crashes; actual power-loss durability still depends on the storage/filesystem and requires physical validation.

Unavailable slots retry startup every `TTS_SLOT_RECOVERY_INTERVAL` seconds (default 30), with each attempt limited to 90 seconds. All configured Chimes must pass the existing identity, ownership, and mapping checks before dynamic TTS becomes ready. Readiness is degraded while recovery is needed. No ownership checks are relaxed and failed recovery never guesses a physical slot.

## Validation required before release

Automated regressions cover cancellation, preset precedence, reversed camera groups, bounded urgent overload, per-target dedupe before preparation, acoustic guards, recovery after failure, credential isolation/rotation, persistence failure, and minimum/current HA compatibility. These are synthetic tests, not new device-validation claims.

Before deployment or release, build the image and validate Compose, HACS, and Hassfest. On hardware, verify consecutive different phrases, interrupted synthesis, saved audio whose content differs from its name, long audio with repeats, two Chimes with distinct credentials, mixed/reversed camera groups, and startup with a temporarily unreachable device followed by recovery. Test through HA as well as REST. Record the exact candidate revision, device count, and observed audible result.

## Rollback

Back up `.env` and the entire mounted `/data` directory before testing. Retain the currently deployed backend image and matching HA component. Stop the candidate before restoring the prior backend/component and, if necessary, its matching data backup. Added preset duration metadata is optional and older track-registry readers ignore it; fixed slot ownership/schema remains unchanged. Reverting code removes the new guards and retries.

No release tag, running deployment, or published version is changed by this working branch. Security vulnerability remediation is outside this change set.

## Reliability validation before CI cleanup — 2026-10-10

- Main reliability branch: 453 backend tests passed with interpreter warnings treated as errors.
- HA integration: 23 tests passed on each of HA 2026.3.4 and 2026.10.0.
- The separate PR43 compatibility worktree: 436 backend tests and 28 HA tests on each supported test version passed.
- Ruff, Python compilation, JSON metadata, workflow YAML parsing, and whitespace checks passed.
- FFmpeg 7.1 encoded a synthetic two-second tone at 0.5×, 1×, and 2× into approximately 4.05, 2.06, and 1.07 seconds respectively; no speaker playback was involved.
- Docker/Compose, HACS/Hassfest CI execution, and physical device validation remain pending. No live deployment or GitHub branch was modified.

The subsequent [CI review](CI.md) removed redundant tests and eliminated fake-device waits; the current main backend suite has 436 tests and runs in approximately 6.5 seconds.

## Single-Chime candidate test — 2026-10-10

[Physical test results](validation/reliability-single-chime-2026-10-10.md) confirm distinct phrases, resident replay, repeats without interruption, and playback after a service restart on one Chime. The session also exposed stale capability health after a failed startup probe; failed probes now retry read-only device information every 30 seconds until success, with shutdown cancellation. Other release gates remain outstanding.
