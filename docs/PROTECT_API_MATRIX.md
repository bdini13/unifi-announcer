# Protect API backend matrix

The runtime now exposes three explicit boundaries: `ProtectStateBackend`,
`PlaybackBackend`, and `RingtoneBackend`. The dispatcher receives only the
playback boundary; startup reconciliation reads through state/ringtone
boundaries. Existing legacy routes still delegate to the same private client.

| Capability | Current backend | Official local API status |
|---|---|---|
| Chime/ringtone state reads | Verified private console session API | No verified endpoint/schema configured in this repository |
| `play-speaker`, `play-buzzer`, default play | Verified private Protect routes | No verified official equivalent mapped |
| Ringtone list/upload/delete | Verified private Protect routes | No verified official equivalent mapped |
| Bootstrap WebSocket auth | Private console session/cookie | Not migrated |
| API-key configuration | `PROTECT_API_KEY` + `PROTECT_API_BASE_URL` readiness fields | Optional/planned only; never logged |

`select_protect_backends` intentionally keeps all three boundaries on the current
private implementation. Supplying an official key/base URL records
`configured-but-no-verified-endpoint-mapping`; it does not invent paths, construct
an official client, or make a request. Migration requires documented local API
paths and mocked contract tests before any backend can be selected.

This checkpoint therefore improves replaceability without falsely claiming an
official Protect API migration.
