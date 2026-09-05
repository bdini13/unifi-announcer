# v2.1.6 — Home Assistant playback reliability

> **Release verification note:** the immutable GitHub release body preserves an earlier future-tense sentence saying publication must wait for the live gate. The live physical gate had already **passed before merge and publication** on the exact release candidate. [PR #23](https://github.com/bdini13/unifi-announcer/pull/23) records the candidate SHA, automated gate, physical audible-playback gate, HA success/failure result transitions, and two-slot preservation. This file is the canonical post-publication verification record.

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

The live single-device release gate also passed before publication on the exact release candidate. The normal Home Assistant path reached UniFi Announcer successfully, Protect `play-speaker` returned HTTP 200, the expected announcement was physically audible on the Smart Chime, and **Last playback result** changed immediately to `success`. A deliberate safe failed HA action produced `failure`, and a subsequent valid action returned the result to `success`. Multiple unique HA phrases preserved exactly two dynamic TTS identities without modifying built-in, user-created, preset, or unknown tracks.

After publication, the immutable `v2.1.6` tag was deployed at commit `11b2a318e49f57f5c53d5afd4f80a427dae7d618`. The final tagged smoke test confirmed `/version` and the Docker OCI revision matched that commit, runtime/cache health remained good, the HA component reported `2.1.6`, Protect playback returned HTTP 200, audible Smart Chime playback succeeded, and the two-slot ownership/cardinality invariant remained intact. Rollback was not required.

A usability observation from physical testing was low apparent volume while the Smart Chime's stored volume was 34; this was not treated as a release blocker.

## Compatibility and safety

The v2.1 safety boundary is unchanged. Dynamic TTS still uses exactly two persistent service-owned slots, rechecks ownership before writes, never guesses a physical slot, and never treats built-in/user-created/preset tracks as dynamic overwrite candidates.

Multi-chime/group behavior remains covered by automated tests but has not yet been physically validated on multiple Smart Chimes. No synchronized microphone benchmark is claimed.
