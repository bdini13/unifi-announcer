# Reliability and native media: single-Chime listening test

## Candidate and scope

This session began on **2026-10-30 EDT** (**2026-10-31 UTC**) and continued on **2026-10-31 EDT** after an interruption. A temporary backend candidate was tested on one physical Smart Chime with a listener in the room. The results below apply to this exact backend build:

**Immediate post-reconnect playback remains an open release gate.** The October 31 repeat reached Protect `CONNECTED`, but the first announcement failed: Protect returned HTTP 500 from `play-speaker`, and Announcer returned HTTP 502 with disposition `failed`. After the durable uncertainty guard expired, an explicit delayed retry succeeded and the listener confirmed clear speech exactly once. That recovery does not erase the earlier failure; its cause remains unproven. Separately, the listener corrected the original check's “no audio” response; that response is superseded and does not establish a silent-success defect.

| Item | Observed value |
| --- | --- |
| Source revision | `998eb0926c1a20b5a90462795978a12353ad54a2` |
| Local Docker image ID (not a registry digest) | `sha256:2c4c860171572ba422311b6842bf0d427c94ca97681e79ae94a62e3d7ee52dcd` |
| Provenance | Image OCI revision and running `/version.git_sha` both matched the source revision |
| Device count/model | One UniFi Protect Smart Chime |
| Chime firmware | `1.7.20` |
| Protect | `7.3.70` |
| UniFi OS | `5.1.34` |
| Installed Home Assistant | `2026.9.1` |
| Installed HA integration | `2.2.0-beta.4`; existing installation, not the exact candidate source |

The original backend was stopped while the candidate used its persistent data mount and existing two service-owned slot identities. The original container, image, and configuration were retained, and the stopped data directory was archived and checksum-verified. Camera targets, groups, MQTT, and MCP were disabled for the candidate; the Protect event stream remained enabled. No firmware, adoption, credentials, or installed HA component were changed.

**Restoration status: VERIFIED.** After active playback and uncertainty guards expired, the candidate stopped with exit code 0 and the original service was restarted. Its original image and environment were unchanged: source `ecf2d8e35228ad48ed6874dd6f14a208d0c32fda`, local Docker image ID `sha256:719e7750606df48745d1ac7db54cc41a7fcfed46c25d9b1817c594602979e038`. Health was `ok`, both slots were ready, and their owned identities matched the baseline. Current shared data was preserved; the old content-state backup was not restored over the audio written during this session. No additional playback was sent after restoration.

## Playback checks

REST speech used Piper and an explicit volume of 30. Each listening result was supplied by the user; API success alone was not treated as audible proof.

| Check | Device/API evidence | Listening result |
| --- | --- | --- |
| Initial distinct phrase | Alpha phrase returned HTTP 200/played | Clear, exactly once, comfortable volume. |
| Second phrase followed by first phrase | Bravo then alpha returned HTTP 200/played; the alpha request waited for admission | Both complete, in order, without overlap or an unexpected tone. |
| Raw WAV upload | A 4.54-second, 22,050 Hz mono WAV (200,236 bytes) was normalized to MP3 (36,824 bytes); `/media/announce` returned HTTP 200 | The expected media-test phrase was clear and played once. |
| Native HA TTS | HA `tts.speak` with Piper targeted `media_player.default`; the backend received `POST /media/announce` and returned HTTP 200 | “October Home Assistant test. This message came through native text to speech” was clear and played once. |
| Backend restart during repeated speech | The longer phrase requested two plays. Container restart completed in 0.505 seconds while about 30.4 seconds remained on the durable guard. The guard survived restart, readiness stayed false during recovery, and readiness returned after 36.54 seconds. A follow-up request then returned played | The longer message played exactly twice and completely, followed by “October restart complete. Playback has recovered,” without overlap or cut-off. |
| Concurrent text and media requests | Both returned HTTP 200; media waited about 17.7 seconds in the queue | Both complete, in order, without overlap or wrong audio. |
| Physical Chime reboot, original check | Reboot returned HTTP 200; direct uptime reset from 437,036 to 17 seconds. Protect reported disconnection at 22.41 seconds and `CONNECTED` at 25.9 seconds, with direct uptime then 22 seconds. A fresh unique phrase returned HTTP 200/played in 6.894 seconds | **UNCERTAIN:** the earlier “no audio” response was corrected by the listener. It is superseded and is not a confirmed failure. The repeat is recorded separately below. |
| Physical Chime reboot, October 31 repeat | Direct uptime reset from 54,500 to 18 seconds, and Protect reported `CONNECTED` at 21.43 seconds. The immediate fresh-phrase request completed in 6.978 seconds with HTTP 502/disposition `failed`, following Protect HTTP 500 from `play-speaker` | **FAILED at the API:** no successful playback is claimed for this request. The failure remains an open release gate. |
| Delayed playback after the October 31 reboot | After the durable uncertainty guard reached zero, direct device uptime was 152 seconds. An explicit retry returned HTTP 200/played in 4.144 seconds | **PASSED:** clear speech, exactly once. This establishes delayed recovery, not reliable immediate playback after reconnect. |
| Existing virtual TTS preset | `package-delivered` returned HTTP 200/played in 8.492 seconds using slot 2 | **Not acoustically validated:** no listener confirmation was recorded. This is not a saved Protect recording. |

Both original owned slot identities remained in use. No zero-write resident hit was observed in the initial October 30 checks: replaying alpha uploaded it again. Protect inventory lagged acknowledged direct writes, so successful playback also exercised the bounded stale-inventory fallback after a fresh write. These observations establish the heard results for those requests; they do not resolve the fallback's controller-race limitation described in the [offline repair record](offline-repairs-2026-10-25.md#remaining-limits-and-later-checks).

Request, restart, readiness, and queue timings are application measurements. They are not synchronized microphone measurements of acoustic latency or completion. Durable guards estimate completion from duration and repeat count.

## Rejected requests

Nine invalid requests returned the expected errors. A before/after comparison found the complete slot state unchanged throughout this batch.

| Input | HTTP result |
| --- | --- |
| Empty media body | 400 |
| Invalid WAV data | 400 |
| Unsupported media MIME type | 415 |
| Gzip content encoding | 415 |
| Upload exceeding 4 MiB | 413 |
| 31-second WAV exceeding the duration bound | 400 |
| Unknown target | 400 |
| Repeat count 7 | 400 |
| Volume 101 | 400 |

## Follow-up correction

A follow-up review identified a recovery delay: requests submitted while slots were unready could renew an uncertainty guard even though no write began. A follow-up change now rejects that path before creating the write hold. Focused regressions cover announcement and preset requests. After the correction, the combined media branch passed **591 backend tests in 4.54 seconds**, and Ruff passed; the primary reliability branch passed **557 backend tests in 4.51 seconds**.

The live image above predates this correction, which was not deployed during this session. Its acoustic results must not be presented as physical validation of the later source revision. This unready-slot guard correction is separate from the unresolved Protect HTTP 500 after reconnect; it does not establish a fix for that failure.

## Remaining validation

- **OPEN RELEASE GATE:** determine the cause of the Protect HTTP 500 during the immediate post-reconnect announcement and establish reliable recovery on the final candidate. Announcer reported this request as failed. The delayed retry passed audibly, but that does not erase the immediate failure. The separate original “no audio” response was corrected and must not be treated as a confirmed silent-success defect.
- The virtual preset returned a successful API result without listener confirmation, so its audible behavior was not validated in this session. The original service has been restored and verified.
- The HA test establishes compatibility between the existing installed beta.4 integration and this backend. The exact candidate HA component was not installed or physically exercised.
- No camera or multi-device playback was tested. Distinct Chime credentials, mixed/reversed camera groups, and synchronized multi-device playback remain outside this evidence.
- No destructive ownership/provisioning experiment, forced controller resynchronization, preset replacement, interrupted synthesis, or physical power-loss test was performed. The installed preset is a virtual TTS preset; no genuine saved Protect recording is available to test saved-recording playback.
- Freshly acknowledged writes can still race controller restoration. Ordinary-preset fingerprint checks do not prove the controller's exact filename-to-slot selection. Native Xtensa upload-completion analysis remains incomplete.

These results supplement the [October 25 offline repair tests](offline-repairs-2026-10-25.md) and the [beta.4 media validation record](v2.2.0-beta.4-media-ingestion-validation.md). The candidate remains unreleased; the immediate post-reconnect failure and other release gates remain open. Private raw evidence, configuration, and identifiers are retained outside the repository.
