# Release checklist

This file defines the evidence required before a UniFi Announcer release is tagged. CI success is necessary but does not replace release-specific physical validation when a patch changes playback behavior.

## Automated gates for the exact release commit

- [ ] Core lane uses Python 3.12 and runs `python -W error -m pytest -q tests` with sanitized non-live environment values.
- [ ] Home Assistant lane uses the pinned HA test requirements and runs `python -m pytest -q tests_ha`.
- [ ] `ruff check .` passes.
- [ ] `python -m compileall -q app custom_components` passes.
- [ ] JSON metadata validation passes for HA/HACS files.
- [ ] `docker compose config` succeeds.
- [ ] Docker image builds with the exact release commit supplied through `GIT_SHA`.
- [ ] HACS validation passes against the exact release commit.
- [ ] Hassfest validation passes against the exact release commit.
- [ ] Application modules import without contacting live UniFi equipment.
- [ ] Public test fixtures and docs contain no private credentials, private device data, or deployment-specific secrets.

## Stable v2.1 architecture evidence

These checks establish the playback architecture that patch releases must preserve:

- [x] Fixed-slot overwrite exercised on a physical Smart Chime with both alternating service-owned slots producing distinct speech.
- [x] Preset, assigned-default, hardware buzzer, and post-restart TTS playback exercised on the physical single-device setup.
- [x] Concurrent three-message behavior covered by automated regression tests.
- [x] Duplicate-request deduplication covered by automated regression tests.
- [x] A 100-unique-message automated regression preserves exactly two service-owned dynamic identities and synthetic per-device mappings.
- [x] Live single-device health/version/slot/cache/metrics/rules/events checks have been exercised during v2.1 development.

## v2.1.6 release gate — PASS

The exact candidate physical gate passed before merge/publication and is recorded in [PR #23](https://github.com/bdini13/unifi-announcer/pull/23). The immutable GitHub release body retained an earlier future-tense sentence, but the release itself was not published with an uncleared hardware gate. The final tagged smoke test is recorded in [v2.1.6 release notes](RELEASE_NOTES_v2.1.6.md).

v2.1.6 fixes the normal Home Assistant playback path when Protect's ringtone inventory remains stale after the Smart Chime already accepted an owned-slot overwrite. It also makes the HA Last playback result sensor update immediately and adds exact build provenance to the documented deployment path.

The candidate preserved these safety conditions:

- [x] Fresh Protect fingerprint evidence is preferred when it becomes available within the bounded synchronization wait.
- [x] Stale fingerprint fallback is allowed only for the exact previously proven physical slot and exact persisted UniFi Announcer-owned filename.
- [x] Filename drift fails closed.
- [x] Ambiguous physical-slot evidence fails closed.
- [x] Missing ownership evidence fails closed.
- [x] No new dynamic Protect ringtone identity is created for each phrase.
- [x] Exactly two persistent dynamic TTS slots remain owned by the installation.

Home Assistant behavior on the exact candidate:

- [x] Normal HA button/action reaches the Announcer endpoint and receives HTTP 200.
- [x] Protect `play-speaker` returns HTTP 200 for the same request.
- [x] The expected announcement is audible on the physical Smart Chime.
- [x] Last playback result changes immediately to `success` after successful playback.
- [x] A deliberate failed playback path changes Last playback result immediately to `failure`.
- [x] Other canonical queue outcomes (`suppressed`, `deduped`, `dropped`, `partial`) remain distinct rather than being flattened to success/failure.

Build/release identity:

- [x] `APP_VERSION`, HA `INTEGRATION_VERSION`, and HA manifest version all equal `2.1.6`.
- [x] Release script targets `v2.1.6` and `docs/RELEASE_NOTES_v2.1.6.md`.
- [x] Release workflow checks the exact validated `main` SHA and expects version `2.1.6` before publishing.
- [x] Candidate Docker image is built with `GIT_SHA=<candidate SHA>`.
- [x] `/version` reports the candidate/release SHA rather than `unknown`.
- [x] OCI image label `org.opencontainers.image.revision` matches that same SHA.
- [x] README Quick Start/upgrade commands pin `v2.1.6` and inject `git rev-parse HEAD` into the build.

## Publish/deploy sequence

Do not merge/tag until every required release-specific physical gate is satisfied.

1. Freeze an exact candidate SHA and run all automated gates.
2. Back up `.env` and persistent `/data` state on the live host.
3. Deploy that exact candidate SHA with `GIT_SHA` embedded.
4. Install/reload the matching HA candidate component.
5. Complete the live HA success/failure gate and record evidence on the release PR.
6. Update release notes/checklist so they explicitly record the live gate result before merge.
7. Before publication, verify the release notes contain no unresolved future-tense blocker such as `must not be published until` and no unchecked release-specific gate that has actually passed.
8. Merge only the validated candidate code/docs into `main`.
9. Let trusted `main` CI complete successfully.
10. Release workflow reruns HACS/Hassfest against `workflow_run.head_sha` and publishes the release at that exact SHA.
11. Deploy the immutable release tag/source using `GIT_SHA="$(git rev-parse HEAD)"` and repeat the HA audible playback smoke test.
12. Verify GitHub tag/release, app version, HA manifest version, `/version`, and deployed image revision all agree.

## Rollback gate

Before live candidate or release deployment:

- [ ] `.env` is backed up with restrictive permissions.
- [ ] Actual `/data` mount source is discovered from the running container and backed up.
- [ ] Backup archive lists successfully with `tar -tzf`.
- [ ] Backup checksum is recorded.
- [ ] `track_registry.json` is preserved as ownership evidence.
- [ ] Previous known-good release tag is known and available.

If any candidate gate fails, restore the previous code/HA component first. Do not delete or hand-edit slot ownership registries to make a failing candidate appear healthy.

## Validation limitations that must remain public

- Multi-chime behavior is covered by automated tests but has not been physically validated on multiple Smart Chimes.
- No synchronized microphone benchmark is available; do not claim measured acoustic latency.
- Public CI uses sanitized fixtures and cannot prove physical audibility.
- Generic arbitrary raw upload, unknown-route probing, controller identity reuse, direct slot deletion, and direct UCP4 transport remain unsupported and outside stable v2.1.
- The project does not retrieve Smart Chime credentials automatically and does not support SSH/database extraction as onboarding. Live validation on Protect `7.2.105` found no Device Password or equivalent field in the normal Protect web UI. An operator may configure arbitrary TTS only when they already possess a credential that the non-destructive `/api/info` verification in [`CREDENTIALS.md`](../CREDENTIALS.md) confirms the target Smart Chime accepts.

These limitations do not block the validated single-device fixed-slot implementation, but they must not be rewritten as broader physical validation claims.
