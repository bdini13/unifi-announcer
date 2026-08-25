# Playback policy

Every REST, MQTT, and local-rule playback request is converted to one
`AnnouncementCommand` and sent through the canonical dispatcher.

## Request fields

| Field | Meaning |
|---|---|
| `text` | Required for TTS announcements. |
| `volume` | Explicit volume, `0..100`. |
| `repeat_times` | Explicit repeat count, `1..6`. MQTT uses the same spelling. |
| `profile` | Optional name from `VOLUME_PROFILES`. |
| `priority` | `0..100`; lower numbers are more urgent. Default `50`. |
| `target` | One chime name, group name, or `default`. |

The applicable fields are accepted by `POST /announce`,
`POST /play-default`, and `POST /presets/{name}/play`. Buzzer commands only
use `target` because volume, repeats, profiles, and quiet-hour suppression do
not apply to the piezo buzzer.

## Resolution order

The dispatcher resolves volume and repeats deterministically:

1. explicit request value;
2. named profile value;
3. `VOLUME_DEFAULT` / `REPEAT_DEFAULT`.

An explicit volume of `0` is preserved. Unknown profiles contribute no values,
so defaults apply.

## Quiet hours

`QUIET_HOURS=22:00-06:30` supports both same-day and midnight-crossing windows.
Priority is resolved before the quiet-hours decision. Priorities `0..49` pass;
priorities `50..100` are suppressed. Buzzer requests always pass.

Suppression is a successful no-sound disposition:

- dispatcher: `SuppressedResult` with `disposition: suppressed`;
- REST: HTTP `202` with the disposition and detail;
- MQTT: JSON on `unifi-announcer/disposition` and an informational log line;
- rules: increments both `rules_fired` and `rules_suppressed`.

## Examples

```http
POST /announce
{"text":"Laundry is done","profile":"night","priority":50,"target":"default"}

POST /presets/package/play?profile=day&priority=20&target=downstairs
POST /play-default?volume=30&repeat_times=2&priority=10&target=default
```

MQTT command payloads use the same values:

```json
{"preset":"package","profile":"day","priority":20,"target":"downstairs"}
```
