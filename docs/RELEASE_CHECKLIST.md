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

## v2.1.7 release gate — PASS

v2.1.7 changed documentation, release identity, packaging, and credential-onboarding guidance only. Runtime playback behavior and the two-slot ownership model remained unchanged from physically validated v2.1.6, so this patch did not require another audible-playback gate before publication.

Credential-onboarding evidence:

- [x] Protect UI path verified as **Devices → Smart WiFi Chime → Settings → Manage → Manual Recovery → Reveal**.
- [x] The value returned by Reveal exactly matched the already working `CHIME_DIRECT_PASSWORD` without displaying or persisting either value.
- [x] Username `ubnt` plus that revealed value returned HTTP 200 against the Smart Chime's read-only `/api/info` endpoint.
- [x] Only `/api/info` was invoked; its response body was not read or displayed.
- [x] Reveal was confirmed to use a read-only GET operation, while Edit uses a credential-changing PATCH operation.
- [x] No credential, Protect setting, Smart Chime setting, ringtone slot, or running deployment was changed.
- [x] Validation scope is disclosed as UniFi OS `5.1.31`, Protect `7.2.105`, Smart WiFi Chime firmware `1.7.20`, and an already adopted device; fresh-adoption behavior was not independently repeated.

Release identity and publication:

- [x] `APP_VERSION`, HA `INTEGRATION_VERSION`, and HA manifest version all equal `2.1.7`.
- [x] Release script targets `v2.1.7` and `docs/RELEASE_NOTES_v2.1.7.md`.
- [x] README Quick Start/upgrade commands pinned `v2.1.7` at publication and injected `git rev-parse HEAD` into the build.
- [x] Release publisher was bound to the trusted `main` commit that transitions `APP_VERSION` from `2.1.6` to `2.1.7`.
- [x] HACS and Hassfest ran in a read-only job with checkout credentials disabled; only the publishing job received `contents: write`.
- [x] Focused release/documentation tests, full core tests, Ruff, compile, JSON, diff, and privacy scans passed.
- [x] Exact branch-head and merge-ref GitHub CI passed.
- [x] Trusted post-merge `main` CI and the v2.1.7 publisher passed.
- [x] Published tag and immutable release both target `6384ae4132ef677303b07232ce443cf66029efbf`.
- [x] The completed version-specific publisher was retired after publication.

## v2.1.8 release gate — PASS

v2.1.8 adds content-aware resident-slot reuse and therefore required fresh physical playback, restart, and Smart Chime reboot validation. The detailed record intentionally retains both the first candidate's blocking reboot failure and the corrected implementation's passing remediation evidence: [v2.1.8 live validation report](validation/v2.1.8-live-latency-validation.md).

Safety and latency evidence:

- [x] Normal repeated speech uses a zero-write resident path and plays the requested phrase correctly.
- [x] Ten resident HA request-path samples measured p95 approximately 663 ms with zero direct upload/sync/settle work; this is not an acoustic microphone benchmark.
- [x] A/B/A content reuse and two-slot eviction retain exactly two service-owned dynamic identities.
- [x] Announcer-process restart preserves correct same-boot resident reuse.
- [x] The initial static-identity-only candidate failed physical Smart Chime reboot safety and was not released.
- [x] The remediation ties resident proof to direct-device uptime/boot epoch and invalidates proof across lifecycle breaks.
- [x] Smart Chime reboot invalidates all resident content proof before post-reboot playback.
- [x] Direct-device uptime/boot epoch resets are detected even when static identity and slot metadata remain unchanged.
- [x] First post-reboot request performs exactly one safe rewrite and plays the correct phrase.
- [x] Second request during the same new boot performs zero writes and plays the correct phrase.
- [x] Reconnect invalidation, controlled reboot ordering, cancellation cleanup, multi-target isolation, write-ahead failure safety, and concurrent leases have automated regression coverage.
- [x] Independent focused review reports no blocking correctness or security findings.

Release identity and publication:

- [x] `APP_VERSION`, HA `INTEGRATION_VERSION`, and HA manifest version all equal `2.1.8`.
- [x] Release script targets `v2.1.8` and `docs/RELEASE_NOTES_v2.1.8.md`.
- [x] Release workflow was bound to trusted post-merge `main` CI and the `2.1.7` → `2.1.8` version transition.
- [x] Existing v2.1.7 release artifacts remain immutable historical records.
- [x] The candidate was built with exact Git SHA provenance while preserving `.env` and persistent `/data`.
- [x] Exact final branch-head and merge-ref GitHub CI passed after release-preparation changes.
- [x] Trusted post-merge `main` pytest, Home Assistant, HACS/Hassfest release validation, and publisher checks passed.
- [x] Published `v2.1.8` tag and immutable release both target `a7873e8a38e7f8c319680073a47d5d4856466560`.
- [x] `main` and the `v2.1.8` tag resolved to the same release commit at publication.
- [x] The completed version-specific v2.1.8 publisher is retired by the post-release cleanup PR.
- [ ] Final local deployment of the immutable `v2.1.8` tag reports matching app/HA versions, `/version.git_sha`, OCI image revision, and passes one audible new/repeated-text smoke test.

The unchecked final tagged deployment is an operational post-publication smoke check. It does not change the immutable GitHub release contents or the fact that the shipped runtime blobs match the physically validated remediation code, but it should be completed before broad public promotion.

## v2.2.0-beta.1 release gate — PASS / PUBLISHED PRERELEASE

v2.2.0-beta.1 introduced explicit, capability-gated Protect camera-speaker TTS while preserving stable v2.1.8 Smart Chime behavior. Its integrated camera path was physically validated on one UVC G3 Instant before publication. The immutable prerelease tag/release targets merge SHA `4bc0f6cea06f65f971de80e8f618413c1cea1fab`. Stable `v2.1.8` remains the recommended public release.

Automated and review evidence:

- [x] Backend, Home Assistant, Ruff, compile, JSON, Compose, Docker build, HACS, and Hassfest checks passed for the implementation before release preparation.
- [x] Independent compatibility/API/Home Assistant review reported no findings.
- [x] Independent security review reported no blocking P0/P1 findings after adversarial cookie, deadline, ADTS, ffmpeg, cancellation, and mixed-group tests.
- [x] Camera targets remain explicit opt-in and absent from implicit `default` resolution.
- [x] Legacy `/chimes`, Smart Chime slots, and existing Home Assistant identifiers remain unchanged.
- [x] `APP_VERSION`, HA `INTEGRATION_VERSION`, and HA manifest version all equal `2.2.0-beta.1` for the immutable beta.1 release.
- [x] Stable install instructions remain pinned to immutable `v2.1.8`.
- [x] Exact release-preparation branch-head and merge-ref CI passed.
- [x] Trusted post-merge `main` pytest, Home Assistant, HACS, and Hassfest checks passed at merge SHA `4bc0f6cea06f65f971de80e8f618413c1cea1fab`.
- [x] Immutable GitHub prerelease `v2.2.0-beta.1` was published at that exact merge SHA.

Physical beta gate:

- [x] Back up `.env` and the actual `/data` mount with restrictive permissions and verify the archive/checksum.
- [x] Build and deploy the exact candidate SHA with `GIT_SHA` provenance and an immutable image digest.
- [x] Install/reload the matching Home Assistant candidate.
- [x] Confirm the expected phrase is audible and intelligible on the explicitly configured G3 Instant at the approved test volume.
- [x] Confirm repeats do not overlap; cancellation does not replay; and the tested post-send uncertain transport failure performs one negotiation, connection, and send attempt without retry.
- [x] Confirm camera-only playback performs no Smart Chime slot write through instrumented dispatcher coverage; live slot state also remained unchanged.
- [x] Confirm an unavailable camera prevents mixed-group Smart Chime playback before any physical effect.
- [x] Confirm Home Assistant exposes only capability-supported camera controls.
- [x] Confirm service restart followed by a camera announcement remains safe.
- [x] Record exact candidate SHA, app/HA versions, image revision/digest, sanitized target capability, and model-scoped outcome without private topology or credentials in [the G3 Instant validation report](validation/v2.2.0-beta.1-g3-instant-camera-validation.md).

The beta.1 gate passed, but that evidence remains scoped to one UVC G3 Instant and its observed AAC-LC / 22.05 kHz / mono / 16-bit `serverudp` profile. Beta.1 remains a prerelease and must not be generalized to other camera models or talkback profiles.

## v2.2.0-beta.2 release gate — PASS / PUBLISHED PRERELEASE

Hardening after beta.1 was released as immutable prerelease `v2.2.0-beta.2` at merge SHA `9d8e8f845201cf8de1223cc7d5fc31c192194a5d`. Stable `v2.1.8` remains the recommended public release.

- [x] Production compatibility uses an explicit physically validated model/profile table rather than broad AAC/sample-rate inference.
- [x] The actual prepared talkback session is rechecked against the approved model/profile before any audio frame can be sent.
- [x] At most one prepared talkback session exists per physical camera while separate cameras remain independent.
- [x] Authenticated `/targets` polling refreshes transient camera availability without requiring Home Assistant entity recreation.
- [x] Home Assistant entity availability requires both coordinator health and current target capability.
- [x] Production `GROUPS_CONFIG` rejects unknown/duplicate members, empty groups, reserved/colliding names, and malformed JSON instead of silently omitting targets.
- [x] README, compatibility, Home Assistant, environment examples, and roadmap retain the exact G3 Instant compatibility boundary.
- [x] Exact beta.2 branch-head, merge-ref, trusted `main`, and release-tag backend/HA/HACS/Hassfest/Docker checks passed.
- [x] Candidate physical Gates 1–5 and 7–8 passed; Gate 6 was explicitly owner-waived and remains documented as not empirically run.
- [x] Immutable GitHub prerelease and tag both target the exact merge SHA.
- [x] The tagged Docker backend and matching HA integration reported beta.2 with exact build provenance.
- [x] Separate tagged smoke tests played clearly once on the G3 Instant and once on the Smart Chime at volume 50.

Publication and deployment did not promote beta.2 to stable or expand compatibility beyond the validated G3 Instant profile.

## v2.2.0-beta.3 candidate gate — PARTIAL PHYSICAL VALIDATION

- [x] Read-only Protect/bootstrap discovery found one connected G4 Instant with a speaker and AAC-LC / `serverudp` / 22,050 Hz / mono / 16-bit metadata.
- [x] Discovery did not prepare a talkback session, send audio, or change Protect/camera settings.
- [x] `EXPERIMENTAL_CAMERA_PROFILES` defaults to empty and fails closed on malformed, duplicate, partial, extra-key, unsupported, or type-coerced entries.
- [x] Exact opt-in matches all five wire-profile dimensions and labels unvalidated models `experimental_opt_in`.
- [x] The validated G3 model/profile remains `physically_validated` and default behavior remains unchanged.
- [x] Exact beta.3 backend/HA identity, focused/full tests, Ruff, compile, JSON, Compose, Docker build, HACS, and Hassfest pass at the frozen draft-PR SHA.
- [x] The exact candidate was deployed after separate approval and complete verified rollback backups.
- [ ] One-device-at-a-time G4 physical validation is completed with an immediate room-readiness prompt before every audible action.
- [x] Gate 1 normal speech was heard clearly once from the representative G4; queues drained, no other target was engaged, and Smart Chime slot proof remained unchanged.
- [x] Further audible testing was paused before the repeat request; repeat, serialization, recovery, and restart gates remain pending.
- [x] Sanitized partial evidence is recorded without private identifiers, credentials, signed URLs, or topology.

The candidate must remain draft. One successful normal-speech observation does not complete the physical gate or establish broad G4/generic camera compatibility.

## Approval-gated candidate, publish, and deploy sequence

Opening a draft release-preparation PR is allowed before physical validation. Do not mark it ready, merge it, tag it, publish it, or deploy it without the gate and approval required for that step.

1. Prepare version identity, release notes, checklist, and contract tests on a dedicated branch without adding publication automation.
2. Open a **draft** release-preparation PR and freeze its exact head SHA.
3. Run branch-head and merge-ref automated checks. CI success does not authorize physical testing or merge.
4. With separate deployment/test approval, back up `.env` and persistent `/data`, then deploy that exact candidate SHA with `GIT_SHA` and immutable image-digest provenance.
5. Install/reload the matching HA candidate component and complete the release-specific physical gate.
6. Record sanitized evidence on the draft PR, update the release notes/checklist, and rerun exact-SHA CI.
7. Before merge or publication, verify the release notes contain no unresolved future-tense blocker such as `must not be published until` and no release-specific gate remains unchecked after actually passing.
8. Only after every required physical item passes and merge is separately approved, mark the draft ready and merge it into `main`.
9. Let trusted post-merge `main` CI complete successfully and verify the merge SHA still carries the approved candidate content.
10. With separate publication approval, create the immutable prerelease tag/GitHub release at that exact `main` SHA, either manually or through a newly reviewed one-version publisher. No publisher exists by default.
11. Verify the tag, GitHub release, app version, HA manifest version, and source commit all agree.
12. With separate release-deployment approval, deploy the immutable tag/image digest and repeat the minimal approved smoke test.
13. Verify `/version`, deployed image revision/digest, and HA version agree; retire any one-version publisher introduced for publication.

## Rollback gate

Before live candidate or release deployment:

- [ ] `.env` is backed up with restrictive permissions.
- [ ] Actual `/data` mount source is discovered from the running container and backed up.
- [ ] Backup archive lists successfully with `tar -tzf`.
- [ ] Backup checksum is recorded.
- [ ] `track_registry.json`, `dynamic_tts_slots.json`, `dynamic_tts_content_state.json` when present, and `installation.json` are preserved.
- [ ] Previous known-good release tag is known and available.

If any candidate gate fails, restore the previous code/HA component first. Do not delete or hand-edit slot ownership registries to make a failing candidate appear healthy.

## Validation limitations that must remain public

- Multi-Chime behavior is covered by automated tests but has not been physically validated on multiple Smart Chimes.
- No synchronized microphone benchmark is available; do not claim measured acoustic latency.
- Public CI uses sanitized fixtures and cannot prove physical audibility.
- Generic arbitrary raw upload, unknown-route probing, controller identity reuse, direct slot deletion, and direct UCP4 transport remain unsupported and outside stable v2.1.
- Credential onboarding is UI-assisted rather than automatic. On validated Protect `7.2.105`, **Devices → Smart WiFi Chime → Settings → Manage → Manual Recovery → Reveal** exposes the existing unique device password; that exact revealed value returned HTTP 200 with username `ubnt` against `/api/info`. Use Reveal, not Edit. The service does not retrieve this credential automatically and does not support SSH/database extraction as onboarding.
- Camera prerelease compatibility is scoped to exact physically validated model/profile records; generic speaker/AAC metadata must never be treated as sufficient compatibility evidence.

These limitations do not block the validated single-device fixed-slot implementation or the published G3 Instant beta evidence, but they must not be rewritten as broader physical validation claims.
