# v2.2.0-beta.2 — Camera-speaker hardening candidate

## Purpose

v2.2.0-beta.2 hardens the experimental Protect camera-speaker path first published in `v2.2.0-beta.1`. Stable `v2.1.8` remains the recommended public release. This candidate does not broaden camera compatibility: production camera playback remains limited to the single physically validated UVC G3 Instant talkback profile until additional models are separately tested.

## Camera compatibility boundary

Production playback is now evidence-gated by an explicit compatibility table. The only enabled profile is:

- model: `UVC G3 Instant`;
- codec: AAC-LC;
- transport: `serverudp`;
- sample rate: 22,050 Hz;
- channels: mono;
- sample depth: 16-bit.

Other camera models, sample rates, transports, and Opus/RTP profiles remain configured/discoverable but are reported unavailable and fail closed before playback. Matching only `hasSpeaker` or a generic AAC capability is no longer sufficient.

The prepared talkback session is checked again before any audio frame can be sent. If the camera model/profile changes while preparation is in progress, the socket is closed and playback fails closed.

## Session and concurrency hardening

A per-camera preparation lease now covers the physical talkback session from preparation through playback/close. This prevents two announcements from arming competing talkback WebSockets to the same physical camera. Separate cameras retain independent concurrency.

The existing no-retry boundary remains unchanged: cancellation and uncertain post-send transport failure do not reconnect or replay audio.

## Dynamic camera availability

Authenticated `GET /targets` refreshes configured camera state from Protect on each poll. Home Assistant keeps explicitly configured camera and mixed-group announcement entities registered when a camera becomes unavailable; entity availability follows the refreshed target capability and coordinator health so a reconnect can recover without recreating the integration.

A camera that disappears from Protect inventory is normalized to sanitized `unavailable` state rather than leaking transport details.

## Group configuration safety

Production `GROUPS_CONFIG` now fails closed at startup for:

- malformed JSON or non-object configuration;
- empty groups;
- unknown target names;
- duplicate members;
- reserved `default` or colliding group names.

Unknown members are no longer silently omitted from mixed camera/Smart Chime groups.

## Smart Chime compatibility

The stable Smart Chime architecture is intentionally unchanged:

- exactly two service-owned dynamic TTS slots;
- same-boot resident-content reuse from v2.1.8;
- reboot/reconnect invalidation;
- Protect-mediated `play-speaker` playback;
- preset/default/buzzer behavior;
- legacy `/chimes` compatibility.

Camera-only playback continues to avoid Smart Chime dynamic-slot preparation.

## Home Assistant

Backend, HA integration, and manifest identity are aligned at `2.2.0-beta.2` for this candidate. Camera announcement entities now remain present through transient camera outages and report unavailable until the target becomes valid again. Camera targets still expose only supported text/repeat behavior; per-request camera volume/profile, presets, assigned-default and buzzer remain unsupported.

## Automated validation

The beta.2 candidate must pass, on the exact frozen branch head and merge-ref:

- backend pytest with warnings as errors;
- Home Assistant custom-component tests;
- Ruff and Python compilation;
- HA/HACS JSON validation;
- Docker Compose rendering;
- exact-SHA Docker image build;
- HACS validation;
- Hassfest;
- focused camera hardening regressions for exact model/profile gating, profile changes during preparation, same-camera serialization, independent cameras, missing cameras, strict group validation, dynamic `/targets` refresh, and HA availability recovery.

## Required physical validation before merge/publication

Because beta.2 changes live camera playback/session behavior, automated CI is not sufficient. Before this candidate may be merged or published, physically validate the exact frozen candidate on the previously tested UVC G3 Instant and record sanitized evidence that:

1. `/version` semantic version and Git SHA match the candidate and OCI revision.
2. Normal Home Assistant → Announcer → camera speech is clear and correct.
3. `repeat_times=2` produces exactly two sequential, non-overlapping repetitions.
4. Two rapid/concurrent announcements to the same camera do not overlap, produce wrong audio, or create competing talkback behavior.
5. A camera outage changes `/targets` and HA availability to unavailable.
6. Camera recovery restores `/targets` and the existing HA entities without an integration restart.
7. A valid mixed Smart Chime + camera group plays correctly.
8. An unavailable camera causes a mixed group to fail before Smart Chime slot mutation or playback.
9. Camera-only playback leaves Smart Chime slot state unchanged.
10. An Announcer restart revalidates the camera and subsequent playback remains correct.

See `docs/validation/v2.2.0-beta.2-camera-hardening-validation.md` for the evidence template.

## Release boundary

This branch is a candidate only. Passing CI or physical validation does not itself authorize merge, tagging, GitHub release publication, image publication, deployment as a release, stable promotion, or broader camera compatibility claims. Those actions remain separately approval-gated.

If beta.2 is later published, it must be an immutable **prerelease**. Stable install guidance must remain pinned to `v2.1.8` until a separate stable promotion is approved.
