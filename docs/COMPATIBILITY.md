# Compatibility

## Evidence matrix

| Component / capability | Evidence level | Status |
|---|---|---|
| UniFi Protect 4.x/5.x private session API | Existing implementation + mocked tests | NVR auth, ringtone identity and playback are the production backend |
| Smart Chime firmware 1.7.20 `/api/info` | Existing recorded evidence | Experimental read; capability-gated with NVR fallback |
| Smart Chime firmware 1.7.20 `/api/support` | Existing recorded evidence | Experimental sensitive read; redacted |
| Direct ringtone-slot staging | Controlled local research on fw 1.7.20 | Experimental and unpublished; Protect metadata did not reliably reconcile, so generic direct staging remains disabled |
| Direct HTTP playback/deletion | No verified route | Unsupported; do not infer from UCP4 command strings |
| Protect-internal UCP4 transport/trust | No supported transport or trust path found | Unsupported; disconnected default-off research interface only |
| Python | 3.12 container target; CI also runs project Python | Supported by tests |
| aiomqtt | 2.3.0 | Optional MQTT path |

Direct-device endpoints are undocumented and experimental. Unknown firmware
fails closed for writes. Direct staging is optional; Protect/NVR ringtone
identity remains mandatory and playback uses the NVR route.

## Firmware evidence levels

- **Level 1 — strings signature:** `scripts/fw_signature.py` extracts printable
  clues, exact/normalized full-phrase matches, offsets, and bounded contexts.
  String presence does not prove a route is registered or a function is called.
- **Level 2 — private analyst notes:** deployment-specific evidence is kept out
  of the public repository.
- Dynamic tests, auth probes, uploads, playback, deletion, and flash writes were
  not run in this checkpoint.

After a firmware update, run the signature tool only against an authorized
local image and compare JSON. Signature changes require review; they do not by
themselves enable direct writes. Leave experiments off and rely on the NVR path
until compatibility and auth are separately approved and proven.

## Protect WebSocket framing

The existing sanitized fixture covers one/two linked frames with an 8-byte
header and JSON or zlib payload. It contains no live IDs, addresses, or auth.
