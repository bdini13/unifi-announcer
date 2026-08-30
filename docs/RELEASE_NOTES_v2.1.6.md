# v2.1.6 — Home Assistant playback reliability

v2.1.6 is a focused reliability patch for the normal Home Assistant playback path. It does not add a second playback implementation or change the two-slot ownership model introduced in stable v2.1.

## Fixed

- Prevent normal Home Assistant playback from timing out solely because Protect continues to report the previous `speakerTrackList` fingerprint after a successful direct overwrite of an already proven UniFi Announcer slot.
- Continue to prefer fresh Protect fingerprint evidence, but after a short bounded wait allow playback when Protect still reports the **same proven physical slot and exact owned filename** and only the content fingerprint is stale.
- Continue to fail closed when the physical slot is ambiguous, the filename changes, ownership evidence disappears, or another positive ownership mismatch is observed.
- Update Home Assistant's **Last playback result** immediately after user actions instead of waiting for the next coordinator poll.
- Report successful playback as `success` and command/transport failures as `failure`; queue outcomes such as `suppressed`, `deduped`, `dropped`, and `partial` remain visible as their canonical dispositions.
- Apply the same result-state behavior to buttons, `media_player.play_media`, `notify.send_message`, and `unifi_announcer.announce`.

## Build provenance

The Docker build accepts the exact source commit through `GIT_SHA`. v2.1.6 documentation supplies `git rev-parse HEAD` during normal build/upgrade commands so `/version` and the image's OCI revision label identify the code that produced the running container.

## Validation

Automated release evidence includes:

- core Python 3.12 regression suite;
- Home Assistant custom-component tests, including immediate success/failure result-state coverage;
- Ruff and Python compile checks;
- JSON metadata and Docker Compose validation;
- Docker image build with an injected git SHA;
- HACS validation and Hassfest.

The release must not be published until the live single-device Home Assistant gate also passes on the exact release candidate: the normal HA playback action returns successfully, Protect `play-speaker` returns HTTP 200, the announcement is audible on the physical Smart Chime, and **Last playback result** becomes `success`. A deliberate failed HA playback must also produce `failure`.

## Compatibility and safety

The v2.1 safety boundary is unchanged. Dynamic TTS still uses exactly two persistent service-owned slots, rechecks ownership before writes, never guesses a physical slot, and never treats built-in/user-created/preset tracks as dynamic overwrite candidates.

Multi-chime/group behavior remains covered by automated tests but has not yet been physically validated on multiple Smart Chimes. No synchronized microphone benchmark is claimed.
