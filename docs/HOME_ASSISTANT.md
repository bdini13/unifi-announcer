# Home Assistant integration

UniFi Announcer includes a HACS-compatible custom integration under `custom_components/unifi_announcer` for Home Assistant 2026.3+.

> [!IMPORTANT]
> The HACS integration is a **client for the UniFi Announcer Docker service**. Run and configure the Docker backend first; installing HACS alone does not provide Smart Chime playback or TTS.

> [!WARNING]
> Use the latest stable v2.1 release for new installations. `v2.1.0-beta.2` and earlier can leave device-side ringtone artifacts when many unique phrases are spoken. Stable v2.1 uses exactly two fixed service-owned dynamic TTS slots instead.

## Install

### HACS custom repository

1. Install and start the UniFi Announcer Docker service using the repository Quick Start.
2. In HACS, add `https://github.com/bdini13/unifi-announcer` as an **Integration** custom repository.
3. Select the latest stable release.
4. Install **UniFi Announcer**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration → UniFi Announcer**.
7. Enter the Announcer URL, for example `http://announcer.local:8095`.
8. Enter the required `APP_API_KEY` configured on the Announcer service.

### Manual installation

Copy `custom_components/unifi_announcer` into Home Assistant's `/config/custom_components/` directory and restart Home Assistant. The Docker backend is still required.

Backend and Home Assistant integration versions should be upgraded together. For candidate testing, copy the component from the exact candidate commit rather than mixing a candidate backend with an older HACS component.

## Announcer-side requirement for arbitrary TTS

Stable v2.1 uses exactly two persistent service-owned Smart Chime slots for dynamic speech. The Announcer container must be able to prove and overwrite those exact slots, which requires a current per-device Smart Chime credential supplied on the Announcer host through `CHIME_DIRECT_PASSWORD` or `CHIME_CREDENTIAL_FILE`.

Home Assistant never receives that credential. On the validated Protect stack, obtain it through Protect's authenticated **Manual Recovery → Reveal** flow documented in [`CREDENTIALS.md`](../CREDENTIALS.md).

Verify the Announcer host before troubleshooting Home Assistant:

```bash
export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")
curl -fsS http://<announcer-host>:8095/version
curl -fsS "${AUTH[@]}" http://<announcer-host>:8095/tts/slots/status
```

Arbitrary TTS requires `"ready": true` and `"slot_count": 2`. Buzzer/default/preset behavior can remain available when fixed-slot dynamic TTS is not ready.

If `/version` reports `git_sha: unknown`, rebuild the backend with exact checkout provenance:

```bash
export GIT_SHA="$(git rev-parse HEAD)"
docker compose up -d --build
```

## Config flow

The UI validates the service with:

- `GET /health`
- `GET /version`
- `GET /auth/check`

No playback occurs during setup.

If the application API key is rejected while Home Assistant loads the integration, the entry transitions to Home Assistant's reauthentication flow. If the Announcer service is temporarily unreachable, setup is retried instead of treating the outage as invalid configuration.

The v2.1 integration deliberately supports one UniFi Announcer config entry. This avoids ambiguous routing for the global `unifi_announcer.announce` action.

## Options

Use **Settings → Devices & services → UniFi Announcer → Configure** to set:

- poll interval;
- default target;
- default volume;
- default repeat count.

Changing options reloads the integration. Volume `0` is valid and remains `0` rather than falling back to a default.

## Devices and entities

Physical Smart Chimes and explicitly configured compatible camera speakers are represented as Ubiquiti devices using stable Protect IDs. Logical groups attach to the UniFi Announcer service device rather than pretending to be physical hardware.

For each configured physical Chime the integration creates:

- `notify` entity for standard text announcements;
- `media_player` for text and preset `play_media`;
- buzzer button;
- assigned-default button;
- preset selector;
- play-selected-preset button;
- queue-depth sensor;
- **Last playback result** sensor.

Logical groups get the same playback controls and Last playback result sensor, but no queue-depth sensor. Queue depth belongs to physical Chimes; v2.1 intentionally avoids a fake aggregate group value.

Experimental camera targets get only capability-safe entities:

- `notify` for text announcements;
- text-only `media_player` playback;
- queue-depth sensor;
- **Last playback result** sensor.

They do not get buzzer/default/preset buttons or a preset selector. Camera volume is device-managed, and Home Assistant does not send its configured default volume to a camera target. The backend still rejects any explicit camera volume/profile override before playback.

If `CHIMES_CONFIG`, `CAMERAS_CONFIG`, or `GROUPS_CONFIG` changes after Home Assistant has loaded the integration, reload/restart the integration so entity topology is rebuilt.

## Standard announcements

Select the actual notify entity from Home Assistant's UI; generated entity IDs can vary with device names.

```yaml
action: notify.send_message
target:
  entity_id: notify.unifi_announcer_kitchen_announcements
data:
  message: "Dinner is ready"
```

The notify entity uses the integration's configured default volume/repeat behavior. The Announcer backend synthesizes/caches text and manages the fixed slots; Home Assistant does not create or manage ringtone objects.

## Advanced announcement action

Use the native action when an automation needs per-call controls:

```yaml
action: unifi_announcer.announce
data:
  message: "Dinner is ready"
  target: kitchen
  volume: 45
  repeat_times: 1
  priority: 50
  dedupe_key: dinner-ready
```

Supported fields are `message`, `target`, `volume`, `repeat_times`, `profile`, `priority`, and `dedupe_key`. Camera targets support `message`, `target`, `repeat_times`, `priority`, and `dedupe_key`; explicit `volume` and `profile` are intentionally rejected.

## Media player

The media player intentionally advertises only `PLAY_MEDIA`. Smart Chimes and camera talkback sessions are not normal streaming speakers: there is no honest pause, seek, playback position, or persistent transport state.

### Text

```yaml
action: media_player.play_media
target:
  entity_id: media_player.kitchen_announcer
data:
  media_content_type: text
  media_content_id: "The laundry is finished"
```

### Preset

```yaml
action: media_player.play_media
target:
  entity_id: media_player.kitchen_announcer
data:
  media_content_type: unifi-announcer/preset
  media_content_id: package-delivered
```

Internal `UA-TTS-*` slot identities are filtered from the user-facing preset list.

Camera media players accept `media_content_type: text` only. Preset playback remains a Chime capability and fails clearly on camera or mixed targets.

Native `tts.speak` / `media-source://` binary ingestion is intentionally deferred to a later v2.2 prerelease. The beta.1 camera path remains a thin client over the existing dispatcher.

## Last playback result

The per-target **Last playback result** sensor is local action state, not a delayed status poll. Starting with v2.1.6 the integration updates it immediately after an HA playback action completes or fails.

Values are intentionally simple at the success/failure boundary while preserving meaningful queue policy outcomes:

| Value | Meaning |
|---|---|
| `success` | Backend returned canonical dispatcher disposition `played` |
| `failure` | Announcer request failed, timed out, or returned a client/transport error |
| `suppressed` | Quiet-hours/policy intentionally prevented playback |
| `deduped` | Duplicate request was intentionally coalesced |
| `dropped` | Queue policy intentionally dropped the request |
| `partial` | Multi-target dispatch produced mixed outcomes |
| `unknown` | No playback action has completed since this HA runtime loaded |

A successful HTTP request alone does not make HA invent acoustic confirmation. Physical audibility is part of release/device validation, while the sensor reports the dispatcher/client result visible to Home Assistant.

## v2.1.8 resident reuse and stale Protect inventory

A Smart Chime slot overwrite can succeed while Protect's `speakerTrackList` continues to report the previous content fingerprint. v2.1.6 introduced a narrow stale Protect inventory fallback; v2.1.8 keeps that safety boundary and adds application-authoritative resident-content reuse.

For **new content**:

1. exact slot ownership is preflighted;
2. the direct overwrite must succeed;
3. Protect is briefly polled for fresh content evidence;
4. if the fingerprint remains stale, playback may continue only when Protect still identifies the same proven physical slot and exact UniFi Announcer-owned filename;
5. ambiguity, filename drift, missing ownership evidence, or other positive mismatches fail closed.

For **resident repeated content**, v2.1.8 may skip the write/sync/settle path entirely, but only while all requested targets have matching trusted content and the current Smart Chime boot remains proven. Trusted state is tied to direct-device uptime/boot epoch. A reboot, reconnect, device change, lifecycle invalidation, failed write, or unprovable boot continuity forces a safe rewrite rather than trusting stale bytes.

This distinction matters for latency: in live single-Chime validation, 10 same-boot resident HA requests measured roughly 0.54–0.66 seconds request round-trip with zero slot writes. These were request-path measurements, not synchronized acoustic benchmarks.

## Availability

The integration polls lightweight service state. A temporary Piper outage does not make buzzer/default/preset controls unavailable when Protect itself remains reachable.

Fixed-slot readiness is an Announcer runtime concern. If `/tts/slots/status` is not ready, text announcement actions fail clearly rather than reverting to old per-phrase allocation behavior.

## Diagnostics

Home Assistant diagnostics include safe service version, health, target/group names and capabilities, preset names, queue depths, and configuration metadata. API keys and credentials are redacted; raw Protect responses, signed talkback URLs, session cookies, physical-slot credentials, and private support logs are not included.

The Version sensor reports the semantic UniFi Announcer version. Its attributes include the container `git_sha`, allowing a deployed image to be compared with the expected release commit when the image was built with `GIT_SHA`.

For backend detail, authenticated `/tts/slots/status` exposes sanitized v2.1.8 resident-content/last-prepare state and `/metrics/json` exposes process-local counters/histograms.

## Stable v2.1.8 verification

For a v2.1.8 deployment, verify the backend and matching HA component together:

1. `/version` reports semantic version `2.1.8` and the expected build SHA rather than `unknown`;
2. `/tts/slots/status` reports exactly two ready slots when arbitrary TTS is configured;
3. a normal HA text announcement completes without timeout;
4. Protect playback succeeds and the expected phrase is audibly heard;
5. Last playback result becomes `success` immediately;
6. repeat the same phrase on the same Chime boot and confirm it remains correct;
7. the repeated request should normally show a resident content hit with zero direct upload when boot continuity is still trusted;
8. if the Chime has rebooted/reconnected, the first safe request may rewrite once before later same-boot reuse.

The release-specific physical evidence, including discovery and remediation of an earlier reboot-safety defect, is retained in [`validation/v2.1.8-live-latency-validation.md`](validation/v2.1.8-live-latency-validation.md).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Integration not offered after HACS install | Docker backend not running or older integration installed | Start backend; select latest stable release; reinstall/restart HA |
| Invalid API key / reauthentication requested | `APP_API_KEY` changed or mismatches | Enter the current application key in the reauth flow |
| Cannot connect | HA cannot reach Docker host/port | Verify Announcer URL, port, and LAN routing |
| No preset options | `/presets` failed or state is stale | Verify `/presets`, then reload the integration |
| HA playback times out while direct slot tests work | Backend/client mismatch or non-stale slot-sync failure | Verify `/version`, update backend/client together, inspect slot timing/status and backend logs |
| Last playback result stays `unknown` after an action | Action never reached the integration or old component is loaded | Update/restart the custom integration and retry |
| Last playback result is `failure` | Backend/client action failed | Inspect the HA error plus Announcer logs; verify Protect and slot status |
| Text TTS fails but preset/buzzer works | Fixed slots not ready or direct credential stale | Check `/tts/slots/status` with `X-API-Key` |
| Repeated text performs a write | Resident proof was missing/invalidated by lifecycle or boot change | Usually safe/expected; inspect `content_reuse` state and lifecycle counters |
| First text after Chime reboot rewrites once | v2.1.8 correctly invalidated old resident bytes | Expected; the next same-boot replay can become a zero-write hit |
| Slot status reports ownership drift | Binding no longer matches persisted proof | Stop dynamic TTS and reconcile; never force an unknown slot |
| `/version` shows `git_sha: unknown` | Container built without `GIT_SHA` | Rebuild with `export GIT_SHA="$(git rev-parse HEAD)"` |
| TTS synthesis fails | Piper/Edge TTS unavailable | Check the configured TTS service separately |
| Group has no queue sensor | Intentional in v2.1 | Inspect member-Chime queue sensors |
| Newly configured Chime/group is absent | Entity topology predates config change | Reload/restart the integration |

Keep UniFi Announcer on a trusted LAN/VPN or behind a deliberately configured authenticated reverse proxy. Do not expose it directly to the public internet.
