# v2.2.0-beta.1 — Experimental Protect camera-speaker TTS

## Why this beta exists

v2.2.0-beta.1 adds explicitly configured UniFi Protect camera speakers as experimental text-announcement targets without changing the stable Smart Chime playback architecture. The beta exists to validate the exact integrated Announcer path on representative hardware before any stable compatibility claim.

Stable `v2.1.8` remains the recommended public release while this gate is open.

## Added

- Explicit `CAMERAS_CONFIG` allowlisting by user-facing name and Protect camera ID. Cameras are never auto-enabled and never join the implicit `default` target.
- Capability-gated camera text announcements through a fresh controller-minted talkback WebSocket.
- Authenticated, versioned `GET /targets` discovery with sanitized per-target and group capabilities while preserving the legacy `GET /chimes` response.
- Capability-safe Home Assistant camera and mixed-group entities using stable Protect IDs.
- Mixed Smart Chime/camera groups through the existing dispatcher, quiet-hours policy, priority, dedupe, and independent per-target queues.

## Fail-closed transport and security model

Camera playback accepts only a connected camera with a speaker and the physically researched AAC-LC, 22.05 kHz, mono, 16-bit `serverudp` profile. Unsupported or incomplete profiles fail before playback.

The implementation:

- converts bounded MP3 input through a cancellable ffmpeg subprocess with streaming output limits;
- validates complete ADTS frames, AAC-LC profile, sample rate, channel count, and one raw-data block per frame;
- confines controller-minted URLs to the configured controller host, expected secure scheme, exact talkback path, and verified port `7443`;
- rejects URL userinfo, fragments, malformed negotiation payloads, and unscoped authentication;
- forwards exactly one cookie-jar-approved `TOKEN`, honoring domain, path, expiry, and secure-cookie policy;
- uses one absolute deadline across bootstrap, transcoding, negotiation, socket arming, transmission, and drain;
- cancels and reaps active ffmpeg and playback work;
- does not reconnect or replay after uncertain delivery;
- never persists, returns, or logs signed talkback URLs or session cookies.

For mixed groups, every camera is revalidated, transcoded, negotiated, WebSocket-opened, and armed before any Smart Chime slot mutation or playback request. A camera preparation failure therefore prevents partial Chime effects.

## Compatibility

Existing Smart Chime behavior remains unchanged:

- exactly two service-owned dynamic TTS slots;
- same-boot resident-content reuse and reboot/reconnect invalidation;
- preset, assigned-default, and buzzer behavior;
- legacy `/chimes` schema and existing Home Assistant entity/device identifiers.

Camera targets currently support text announcements and repeats only. Camera volume remains device-managed. Per-request volume/profile overrides, preset/default/buzzer actions, Opus/RTP talkback, and generic camera-model compatibility claims remain unsupported.

Native Home Assistant `tts.speak` and `media-source://` binary ingestion remain deferred to a later v2.2 prerelease.

## Automated validation

The merged camera-speaker implementation passed:

- 375 backend tests with warnings treated as errors;
- 18 Home Assistant custom-component tests under the pinned Python 3.14 environment;
- Ruff, Python compilation, JSON metadata, Docker Compose, Docker image build, HACS, and Hassfest checks;
- a real in-memory ffmpeg MP3-to-AAC/ADTS smoke test;
- changed-file privacy and credential-leak scanning with zero findings;
- independent compatibility/API/Home Assistant review with no findings;
- independent security review with no blocking P0/P1 findings.

The draft release-preparation PR has separately passed 376 backend tests, 18 Home Assistant tests, Ruff, Python compilation, JSON metadata, diff validation, Docker Compose, Docker image build, HACS, Hassfest, and an added-line privacy scan. Final PR CI must remain green after evidence-only updates, and post-merge checks must pass against their exact commit before any tag or publication decision.

## Physical validation boundary

Integrated audible camera playback was physically confirmed on one G3 Instant using exact candidate `65954f29ac1996fde5dd470b95acb3bc6b38fd43`. Two separately authorized single-play requests returned success without Smart Chime slot-state changes; the listener confirmed clear and correct speech on the replay. See the [sanitized validation report](validation/v2.2.0-beta.1-g3-instant-camera-validation.md).

The required beta.1 validation gates have now confirmed, on the exact candidate and model:

- `repeat_times` requests do not overlap or replay unexpectedly;
- cancellation does not replay, and the tested post-send uncertain transport failure does not trigger an automatic retry;
- camera-only playback does not touch Smart Chime slots;
- a deliberately unavailable camera prevents mixed-group Chime playback;
- Home Assistant exposes only the supported camera controls;
- service restart and a subsequent announcement remain safe.

A passing test on this one G3 Instant must not be generalized to other models or Opus/RTP profiles. Completion of the beta.1 validation gate does not authorize merge, tagging, publication, deployment as a release, stable promotion, or broader compatibility claims.

## Upgrade and rollback

Upgrade the Docker backend and Home Assistant integration together. `CAMERAS_CONFIG` is optional, so existing Smart Chime-only installations require no configuration or data migration. Preserve `.env`, the actual `/data` mount, and all ownership/content-state files.

Any later candidate deployment must use an exact commit with `GIT_SHA` embedded and an immutable image digest. Back up `.env` and `/data`, verify `/health`, `/version`, `/targets`, and `/tts/slots/status`, and retain stable `v2.1.8` as the rollback target.

## Release-preparation boundary

This release-preparation PR changes version identity, release documentation, and contract tests only. It must remain draft and must not be merged until the physical beta gate passes and merge is separately approved. Opening the PR authorizes **no tag, GitHub release, image publication, deployment, or audible test**. Physical testing, merge, publication, and release deployment each require their own approval after the applicable gate is satisfied.
