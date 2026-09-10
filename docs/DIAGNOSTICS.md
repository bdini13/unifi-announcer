# Diagnostics and support bundle

The diagnostics follow-up adds an authenticated, shareable support snapshot without serializing raw UniFi/Protect objects or support logs.

> [!IMPORTANT]
> This work is currently stacked on the unreleased `v2.2.0-beta.4` media-ingestion candidate. Its eventual release version will be assigned only after beta.4 lands. Do not treat the development branch as a published release.

## Backend endpoint

```text
GET /diagnostics/support
X-API-Key: <APP_API_KEY>
```

The response is JSON and uses:

```text
Content-Disposition: attachment; filename="unifi-announcer-diagnostics.json"
```

Example:

```bash
export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
curl -fsS \
  -H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}" \
  -o unifi-announcer-diagnostics.json \
  http://<announcer-host>:8095/diagnostics/support
```

The endpoint refreshes configured camera capability state before building the snapshot, then reads the remaining state from local runtime structures. It does not request support logs or expose raw Protect bootstrap data.

## Redaction model

The bundle is assembled from an explicit allowlist rather than by serializing internal objects and deleting selected fields afterward.

It intentionally omits:

- UniFi Protect device IDs and camera UUIDs;
- Smart Chime direct-device identifiers;
- real configured target names and group names;
- application/Protect/device credentials;
- cookies and authorization headers;
- controller, camera, or signed talkback URLs;
- IP/MAC/serial identifiers;
- dynamic-slot Protect ringtone IDs;
- dynamic-slot filenames;
- TTS/media content hashes and fingerprints;
- cache filesystem paths;
- raw exception text;
- support-log contents and raw Protect responses.

Targets and groups are pseudonymized as `target_1`, `target_2`, `group_1`, and so on. Group membership is preserved only through those aliases so topology can still be understood without sharing room/device names.

Because diagnostics are produced by software and new fields can introduce mistakes, review a bundle before posting it publicly even though automated regressions enforce the current redaction contract.

## Included release/build state

The snapshot includes safe build evidence:

- semantic application version;
- `GIT_SHA` build revision;
- protocol-mode labels already exposed by `/version`;
- the repository's documented physically tested Protect/Smart Chime firmware evidence.

A missing build revision produces `build_revision_unknown` instead of inventing provenance.

The `tested_firmware` values are evidence records, **not** claims that the currently connected controller/device is running those versions. Runtime firmware comparison remains a separate compatibility task and must use read-only capability/identity discovery rather than version guessing.

## Included health and queue state

Health output is reduced to component names and coarse `status`. Component detail strings are deliberately omitted because they may contain private host or device information.

Per-target output includes only:

- pseudonymized target label;
- type (`chime` or `camera`);
- queue depth;
- boolean capability map;
- for cameras only, safe model name, availability, and evidence label when present.

Groups include only pseudonymized membership and the boolean capability intersection.

## Dynamic Smart Chime slot state

The support bundle exposes enough information to diagnose fixed-slot state without revealing Protect identities:

- ready state;
- fixed-slot mode;
- slot count;
- logical busy-slot numbers;
- legacy-orphan count;
- whether an error exists, but not its text;
- binding count per logical slot;
- trusted resident-content binding count;
- aggregate safe `last_prepare` timing/count fields.

It intentionally drops:

- target/device IDs;
- Protect ringtone IDs and names;
- direct device-slot mappings;
- filenames;
- content MD5/cache-key prefixes;
- boot-epoch details tied to individual devices;
- raw errors.

## Cache and media-ingestion state

The bundle includes only numeric host-cache totals/limits and beta.4 media-ingestion limits. Cache paths and file names are not included.

## Latency stages

The bundle exposes allowlisted process-local histogram summaries from the existing metrics registry:

- `announce_total_ms`
- `tts_ms`
- `pcm_process_ms`
- `encode_ms`
- `upload_ms`
- `play_request_ms`
- `queue_wait_ms`
- `slot_acquire_ms`
- `slot_preflight_ms`
- `slot_direct_upload_ms`
- `slot_sync_ms`
- `slot_settle_ms`
- `slot_prepare_ms`
- `camera_prepare_ms`

Each histogram can contain `count`, `sum`, `min`, `max`, and `avg` numeric values.

`camera_prepare_ms` already existed as a dispatcher timing stage but was previously lost because `AnnouncementTiming` did not declare it. The diagnostics follow-up makes that field persistent and exports it through the same metrics path as the other real measured stages.

`play_request_ms` remains the current acceptance/request-path timing. The project does not label it as acoustic latency, and it does not invent a separate camera-play timing until that stage has dedicated runtime instrumentation.

## Compatibility warnings

Warnings are machine-readable objects with a stable-style `code` plus `severity`. The first slice derives them only from state that the application actually knows:

- `build_revision_unknown`
- `service_health_degraded`
- `dynamic_tts_not_ready`
- `legacy_orphans_present`
- `camera_unavailable`
- `camera_experimental_opt_in`
- `camera_compatibility_unproven`

Camera warnings are based on the same capability/physical-evidence labels used by playback gating. An AAC speaker is not upgraded to validated merely because its metadata resembles a known profile.

Runtime firmware-version comparison is deliberately **not** implemented by this first slice because the current service does not yet retain a sanitized, authoritative runtime firmware identity for every path. That should be added only through read-only discovery with explicit evidence semantics.

## Home Assistant diagnostics

The HACS integration requests the backend support bundle when Home Assistant diagnostics are generated and embeds it under `backend_support`.

If that request fails, Home Assistant stores only:

```json
{
  "available": false,
  "error_type": "CannotConnect"
}
```

It intentionally does not copy exception text into the shareable diagnostic output because transport errors can include private addresses or other deployment details.

The pre-existing Home Assistant diagnostic fields remain available for integration-local troubleshooting, with the existing API-key redaction and camera signed-URL/token filtering.

## Remaining diagnostics roadmap

After this support-bundle slice is green, the remaining diagnostics/compatibility work is:

1. add sanitized runtime firmware identity discovery for Protect and Smart Chime;
2. compare runtime versions to physical-evidence records without implying support from version ordering alone;
3. add explicit camera send/drain timing only after real instrumentation exists;
4. add synchronized acoustic measurement tooling separately from request-path metrics;
5. validate the support bundle against real degraded/offline/reboot states and confirm the output remains safe to share.