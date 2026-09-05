# Compatibility

## Evidence matrix

| Component / capability | Evidence level | Status |
|---|---|---|
| UniFi Protect 7.2.105 private session API | Existing implementation + live use + mocked tests | Protect auth, persistent ringtone identity and playback backend |
| Smart Chime firmware 1.7.20 `/api/info` | Existing recorded/live evidence | Used to capability-gate fixed-slot TTS writes |
| Smart Chime firmware 1.7.20 `/api/support` | Existing recorded evidence | Sensitive diagnostic read; not part of normal playback |
| Exact owned ringtone-slot overwrite | Controlled local research on fw 1.7.20 + v2.1 ownership gates | Used only for two proven service-owned dynamic TTS slots |
| Generic arbitrary direct staging | Insufficient safe ownership model | Disabled |
| Direct HTTP playback | No verified route | Unsupported; playback remains Protect `play-speaker` |
| Direct slot deletion | Semantics not proven | Unsupported; v2.1 migration overwrites proven legacy bytes with silence rather than guessing deletion |
| Protect-internal UCP4 transport/trust | No supported transport or trust path found | Unsupported; disconnected research interface only |
| Python | 3.12 container target; HA validation uses its pinned environment | Supported by CI |
| aiomqtt | 2.3.0 | Optional MQTT path |
| MCP Python SDK | 2.0.0 | Optional Streamable HTTP MCP path |

## v2.1 fixed-slot compatibility boundary

Dynamic TTS in stable `v2.1` releases requires all of the following:

- a compatible Smart Chime firmware whose direct info capability permits custom ringtone storage;
- a current adopted-device credential supplied locally to the Announcer host and accepted by the target Smart Chime;
- exactly two persistent service-owned Protect ringtone identities;
- an exact, persisted physical slot binding for each configured target;
- ownership evidence that still matches immediately before each overwrite.

If any write precondition fails, arbitrary TTS fails closed. The service never falls back to the beta.2 per-phrase ringtone allocation because that can accumulate device-side artifacts under high-cardinality workloads.

Buzzer/default/persistent preset operations can remain available independently when their existing Protect paths are healthy.

## Protect + direct responsibilities

The v2.1 path intentionally uses both sides:

```text
Direct Smart Chime HTTPS
  -> replace bytes only in a proven UA-TTS slot

Protect/NVR
  -> retain the persistent ringtone identity
  -> issue play-speaker
```

A successful direct save is not itself enough to claim an arbitrary physical slot. Generic staging remains disabled.

## Firmware evidence levels

- **Level 1 — strings signature:** `scripts/fw_signature.py` extracts printable clues, exact/normalized full-phrase matches, offsets, and bounded contexts. String presence does not prove a route is registered or safe.
- **Level 2 — controlled device evidence:** sanitized tests can prove exact slot/hash/size behavior without publishing deployment credentials.
- **Level 3 — production enablement:** requires explicit ownership evidence, capability gating, and fail-closed behavior in code.

After a Smart Chime firmware update, treat fixed-slot writes as unverified until compatibility is retested. Signature changes alone must never enable direct writes.

## Credential handling

The direct Smart Chime client uses username `ubnt` plus the password provisioned for the adopted device. UniFi Announcer accepts that secret through `CHIME_DIRECT_PASSWORD` or `CHIME_CREDENTIAL_FILE`; the latter supports an external local refresher without requiring container restarts.

For public onboarding, first use the Protect web interface's existing **Device Password** value when that setting is available, then verify it non-destructively against the target Smart Chime's `/api/info` endpoint before configuring arbitrary TTS. See [`CREDENTIALS.md`](../CREDENTIALS.md) for the exact procedure and version-dependent UI locations.

The project does not retrieve the password automatically and does not support enabling SSH, querying Protect's internal database, scraping backups, or publishing raw authentication material as onboarding methods. MCP and Home Assistant receive only the Announcer application/API surfaces and never receive the physical device credential.

## Protect WebSocket framing

The existing sanitized fixture covers one/two linked frames with an 8-byte header and JSON or zlib payload. It contains no live IDs, addresses, or auth.
