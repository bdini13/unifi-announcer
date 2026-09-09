# Compatibility

## Evidence matrix

| Component / capability | Evidence level | Status |
|---|---|---|
| UniFi Protect 7.2.105 private session API | Existing implementation + live use + mocked tests | Protect auth, persistent ringtone identity and playback backend |
| Smart Chime firmware 1.7.20 `/api/info` | Existing recorded/live evidence | Capability gate, device identity, uptime/boot-epoch evidence |
| Smart Chime firmware 1.7.20 `/api/support` | Existing recorded evidence | Sensitive diagnostic read; not part of normal playback |
| Exact owned ringtone-slot overwrite | Controlled local research on fw 1.7.20 + v2.1 ownership gates | Used only for two proven service-owned dynamic TTS slots |
| Same-boot resident content reuse | Physical single-Chime v2.1.8 validation + automated tests | Supported when content, ownership, device identity, and boot continuity all match |
| Reboot/reconnect resident invalidation | Physical single-Chime reboot validation + automated lifecycle/concurrency tests | Supported; next request safely rewrites when continuity is broken |
| Generic arbitrary direct staging | Insufficient safe ownership model | Disabled |
| Direct HTTP playback | No verified route | Unsupported; playback remains Protect `play-speaker` |
| Protect camera AAC talkback WebSocket | Integrated physical validation on one UVC G3 Instant + automated transport/dispatcher/HA tests | Experimental prerelease; the exact validated G3 Instant AAC-LC 22.05 kHz mono profile is production-eligible |
| Exact AAC protocol-profile opt-in | G4 metadata + automated gates + clear normal/repeat/serialization observations + unavailable/available recovery | Draft beta.3 only; empty by default and labeled `experimental_opt_in`; post-recovery playback and restart validation pending |
| Other AAC camera model/sample-rate profiles | No integrated physical evidence or explicit exact opt-in | Unsupported for playback; remain visible as unavailable |
| Protect camera Opus/RTP talkback | Advertised by some camera bootstrap profiles but not physically validated in this service | Unsupported; fails closed |
| Direct slot deletion | Semantics not proven | Unsupported; v2.1 migration overwrites proven legacy bytes with silence rather than guessing deletion |
| Protect-internal UCP4 transport/trust | No supported transport or trust path found | Unsupported; disconnected research interface only |
| Python | 3.12 container target; HA validation uses its pinned environment | Supported by CI |
| aiomqtt | 2.3.0 | Optional MQTT path |
| MCP Python SDK | 2.0.0 | Optional Streamable HTTP MCP path |

## Stable v2.1 fixed-slot compatibility boundary

Dynamic TTS in stable `v2.1` releases requires all of the following:

- a compatible Smart Chime firmware whose direct info capability permits custom ringtone storage;
- a current adopted-device credential supplied locally to the Announcer host and accepted by the target Smart Chime;
- exactly two persistent service-owned Protect ringtone identities;
- an exact, persisted physical slot binding for each configured target;
- ownership evidence that still matches immediately before each overwrite.

If any write precondition fails, arbitrary TTS fails closed. The service never falls back to the beta.2 per-phrase ringtone allocation model because that can accumulate device-side artifacts under high-cardinality workloads.

Buzzer/default/persistent preset operations can remain available independently when their existing Protect paths are healthy.

## v2.1.8 resident-content boundary

v2.1.8 may skip a physical Smart Chime write when requested content is already resident, but application cache state alone is not sufficient. A resident hit requires:

- source MP3 identity to match;
- the exact persisted physical slot and owned filename to match;
- the same configured physical device identity;
- a persisted write generation that has not been invalidated by a later write/lifecycle event;
- an uptime-derived boot epoch that still matches the currently observed Smart Chime boot;
- all requested targets to satisfy the same trust requirements.

Direct-device uptime is deliberately part of the trust model because physical validation showed that static MAC/serial/firmware and slot metadata can remain unchanged across a Smart Chime reboot even when the playable slot bytes do not survive correctly.

The first v2.1.8 candidate failed this gate and produced wrong audio after a physical Smart Chime reboot. It was not released. The corrected implementation invalidates resident proof on boot discontinuity, observed reconnect, and guarded lifecycle operations. The fixed candidate was physically retested: the first post-reboot request performed one safe rewrite and the next same-boot request reused resident content correctly.

If boot continuity is missing, malformed, or outside the configured tolerance, resident reuse is rejected and the phrase is rewritten.

## Experimental camera-speaker compatibility boundary

`v2.2.0-beta.2` is the current published prerelease. The integrated camera path was physically validated on one **UVC G3 Instant**. Production camera playback is therefore evidence-gated to the exact observed profile:

```text
model: UVC G3 Instant
codec: AAC-LC
transport: serverudp
sample rate: 22050 Hz
channels: 1
bits per sample: 16
```

A camera is not enabled merely because Protect reports `hasSpeaker=true` or an AAC talkback profile. Draft beta.3 adds an empty-by-default `EXPERIMENTAL_CAMERA_PROFILES` list for explicit exact wire-profile testing. A matching configured camera reports `experimental_opt_in`; it is not added to the physically validated model table. Opus/RTP, partial, malformed, or non-matching profiles remain unavailable and fail closed.

One UVC G4 Instant reported AAC-LC, `serverudp`, 22,050 Hz, mono, 16-bit metadata. On the exact beta.3 candidate, normal speech, repeat-times-two, and rapid A→B serialization were heard correctly from that representative device. An approved camera reboot produced a clean unavailable → available transition, while G3/Smart Chime queues and Smart Chime slot proof remained unchanged. Post-recovery playback and Announcer restart testing remain pending; this partial evidence does not establish broad G4 or generic camera compatibility.

Configured cameras are re-inspected through authenticated `/targets` polling. Temporary offline state therefore changes target capability/availability without removing the configured target from Home Assistant. A reconnect can recover on the next poll without entity recreation.

Only one prepared talkback session may exist per configured camera at a time. The per-camera preparation lease is held from capability/profile revalidation through prepared-session playback/close, preventing overlapping controller-minted WebSockets for the same physical camera. Different cameras remain independent.

`GROUPS_CONFIG` is validated fail-closed in production. Unknown members, empty groups, duplicate members, reserved/colliding names, and malformed JSON are rejected at startup instead of being silently omitted.

Camera targets currently support text announcements and repeats only. Camera volume remains device-managed. Per-request volume/profile overrides, preset/default/buzzer actions, generic raw media, and unsupported transport profiles remain blocked.

## Protect + direct responsibilities

The v2.1 path intentionally uses both sides:

```text
Direct Smart Chime HTTPS
  -> read device info/uptime for capability + boot evidence
  -> replace bytes only in a proven UA-TTS slot when needed

Protect/NVR
  -> retain the persistent ringtone identity
  -> issue play-speaker
  -> provide event/reconnect observations used for lifecycle invalidation
```

A successful direct save is not itself enough to claim an arbitrary physical slot. Generic staging remains disabled.

The experimental camera path remains Protect-mediated as well: Protect bootstrap supplies current camera capability state and the controller mints the short-lived talkback WebSocket. UniFi Announcer confines that URL back to the configured controller and never persists or returns its signed query or session cookie.

## Firmware evidence levels

- **Level 1 — strings signature:** `scripts/fw_signature.py` extracts printable clues, exact/normalized full-phrase matches, offsets, and bounded contexts. String presence does not prove a route is registered or safe.
- **Level 2 — controlled device evidence:** sanitized tests can prove exact slot/hash/size/lifecycle behavior without publishing deployment credentials.
- **Level 3 — production enablement:** requires explicit ownership evidence, capability gating, lifecycle/boot safety where relevant, and fail-closed behavior in code.

After a Smart Chime firmware update, treat fixed-slot writes and resident reuse as unverified until compatibility is retested. Signature changes alone must never enable direct writes. Likewise, camera metadata similarity is not sufficient to add another camera/profile to the compatibility table.

## Credential handling

The direct Smart Chime client uses username `ubnt` plus the unique device password provisioned for the adopted device. UniFi Announcer accepts that secret through `CHIME_DIRECT_PASSWORD` or `CHIME_CREDENTIAL_FILE`; the latter supports an external local refresher without requiring container restarts.

Live validation on UniFi OS `5.1.31`, Protect `7.2.105`, and Smart Chime firmware `1.7.20` confirmed the normal authenticated UI onboarding path:

**Protect → Devices → Smart WiFi Chime → Settings → Manage → Manual Recovery → Reveal**

Live inspection of the Protect frontend showed that **Reveal** performs `GET /devices/password/{deviceType}/{deviceId}`, while **Edit** uses `PATCH` on the same resource. The value returned by Reveal exactly matched the known working `CHIME_DIRECT_PASSWORD` and returned **HTTP 200** with username `ubnt` against the Smart Chime's read-only `/api/info` check.

The earlier `HTTP 401` result attributed to a recovery value was traced to incorrectly captured UI text rather than the actual value returned by Reveal. That result is superseded by the verified Reveal flow.

For onboarding, use **Reveal**, not **Edit**. Edit is a credential-changing operation and is not required to configure UniFi Announcer. The validated flow requires no SSH, Protect database access, backup scraping, credential reset, or exploit. See [`CREDENTIALS.md`](../CREDENTIALS.md).

The project does not retrieve the credential automatically. MCP and Home Assistant receive only the Announcer application/API surfaces and never receive the physical device credential.

Camera talkback uses the existing authenticated Protect session. The short-lived `TOKEN` cookie is selected through the HTTP cookie jar for the configured controller host and is never exposed through the public API or Home Assistant.

## Protect WebSocket framing

The existing sanitized fixture covers one/two linked frames with an 8-byte header and JSON or zlib payload. It contains no live IDs, addresses, or auth. In v2.1.8, observed Smart Chime reconnect state is also used to revoke resident content proof before later playback trusts it.

## Physical validation boundary

Stable v2.1.8 physical validation covers one Smart Chime on Protect `7.2.105` / firmware `1.7.20`. Multiple Chimes/groups are covered by automated fixtures and concurrency tests but have not been physically validated on multiple devices. Request-path timing was measured, but no synchronized microphone benchmark was used; do not generalize the single-device timing numbers into a universal acoustic-latency claim.

The `v2.2.0-beta.1` integrated camera path was physically validated on one UVC G3 Instant with the exact AAC-LC / 22.05 kHz / mono / 16-bit `serverudp` profile. Repeat behavior, restart behavior, Home Assistant entity exposure, camera-only Smart Chime slot isolation, mixed-group fail-closed behavior, and no-retry uncertain-send behavior were included in the beta gate. This result must not be generalized to another camera model or talkback profile.
