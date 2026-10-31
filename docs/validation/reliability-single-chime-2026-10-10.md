# Reliability candidate: single-Chime listening test

## Scope and recovery

On 2026-10-10, candidate `bc9aa2519bfa87e8fd09a59aa658802b8661b50b` from PR #46 was built and tested on one physical Smart Chime, with the user in the room. Playback used REST and Piper at 30% volume. The existing beta.4 service was stopped while a temporary candidate used its data mount; automatic event announcements, MQTT, cameras, and MCP were disabled on the candidate. Its API was bound only to server loopback.

The current image/container and environment were retained, and the stopped service's complete data directory was archived and checksum-verified before startup. Both original slot identities and their physical mappings were preserved throughout testing. The original beta.4 container (`ecf2d8e35228ad48ed6874dd6f14a208d0c32fda`) was restored after the final playback check. The shared state retained the candidate's correct content records; restoring an older content-proof backup after overwriting physical slots would incorrectly claim old audio was resident. The backup remains available, but was not restored over current records. After restoration, the original beta.4 service also reproduced the stale `direct_device: degraded / nvr_fallback` report; Protect, event streaming, and both TTS slots were ready. This establishes that the startup-probe defect also exists in the previously deployed code, rather than being introduced by this candidate.

## Observed results

| Check | Device/API evidence | Listening result |
|---|---|---|
| First distinct phrase | Slot 1; one overwrite; HTTP 200/played | User confirmed clear speech, once, comfortable volume. |
| Second distinct phrase | Slot 2; one overwrite; HTTP 200/played | User confirmed complete speech. |
| Replay of first phrase immediately after second request | Resident hit, zero overwrites; admission wait about 3.94 s | User confirmed both phrases in order, without overlap or unexpected tone. |
| Longer phrase with two repeats, followed immediately by another request | The next request waited about 17.86 s before audio preparation; both returned played | User confirmed exactly two complete repetitions before the final phrase, with no overlap or cut-off. |
| Candidate service restart and resident replay | Two slots ready after restart; resident hit and zero overwrites | User confirmed the expected final phrase clearly once. |

Request durations include synthesis, uploads, and scheduling; they are not microphone-measured acoustic latency. The same two slot identities remained in use; no extra dynamic ringtone identities were allocated for the different phrases.

## Finding: stale capability health after a failed startup probe

The initial per-Chime capability probe raised `RemoteProtocolError` on both candidate starts. A subsequent mandatory direct-info call during slot initialization succeeded, as did fixed-slot writes and playback. A fresh, separate read-only device-info request also succeeded. However, the one-shot runtime probe retained its failure, so the background health snapshot subsequently reported `direct_device: degraded / nvr_fallback`. An early `health: ok` response reflected the background snapshot before that failed capability status was sampled, not proof that the issue had resolved.

The follow-up fix retries failed read-only capability probes every 30 seconds until one succeeds, replaces the stale unavailable state with fresh capability data, and cancels pending retries during shutdown. Successful probes stop retrying. A regression reproduces a protocol error followed by recovery; the independent-target test also verifies that stopping a failed probe cancels its pending wait. This follow-up changes capability probing only; the listening results above remain tied to the exact original candidate revision.

## Remaining validation

This session did not validate HA-initiated playback, saved-preset precedence, interrupted Piper synthesis, Chime reboot/power loss, an unreachable device during startup followed by recovery, distinct credentials on multiple Chimes, or mixed/reversed camera groups. No release or merge is justified solely by these single-device results. No firmware or Home Assistant component was changed.
