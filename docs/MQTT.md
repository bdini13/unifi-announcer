# MQTT integration

Set `MQTT_URL=mqtt://broker:1883`. `MQTT_USERNAME` and `MQTT_PASSWORD` are
optional. The bridge owns one `aiomqtt.Client` for the full connected session;
inbound subscriptions, discovery, state, events, and command dispositions all
use that client. Broker loss is retried with exponential backoff and does not
affect REST or SSE.

## Topics

| Direction | Topic | Payload / behavior |
|---|---|---|
| publish, retained | `unifi-announcer/status` | `online`; the broker Last Will publishes `offline`. |
| subscribe | `unifi-announcer/announce` | Announcement command JSON. |
| subscribe | `unifi-announcer/chime/<name>/play` | Buzzer, default, preset, or announcement command JSON; `<name>` supplies `target` when the payload omits it. |
| publish | `unifi-announcer/event` | Normalized Protect event JSON. |
| publish | `unifi-announcer/disposition` | `{action, disposition, ...result}` for each accepted MQTT command. |
| publish, retained | `unifi-announcer/chime/<name>/direct_health` | Direct-path capability/health state. |
| publish, retained | `unifi-announcer/chime/<name>/queue_depth` | Current queue depth at publication. |
| publish, retained | `unifi-announcer/chime/<name>/firmware` | Firmware version or `unknown`. |
| publish, retained | `unifi-announcer/chime/<name>/last_ring` | Most recent ring value or `unknown`; live ring events update it. |

## Command payloads

```json
{"text":"Dinner is ready","volume":55,"repeat_times":1,"profile":"day","priority":50,"target":"kitchen"}
{"preset":"package","profile":"day","priority":20,"target":"downstairs"}
{"default":true,"volume":30,"repeat_times":2,"priority":10}
{"buzzer":true}
```

`volume`, `repeat_times`, `profile`, `priority`, and `target` have the same
meaning and validation as REST. See [POLICY.md](POLICY.md). A topic target is
used only when the JSON has no explicit `target`.

## Home Assistant discovery

For every configured chime name, retained discovery is published for:

- buttons: buzzer and assigned default ringtone;
- sensors: direct health, queue depth, firmware, and last ring.

Discovery topics follow:

```text
homeassistant/button/unifi_announcer/<name>_buzzer/config
homeassistant/button/unifi_announcer/<name>_default/config
homeassistant/sensor/unifi_announcer/<name>_direct_health/config
homeassistant/sensor/unifi_announcer/<name>_queue_depth/config
homeassistant/sensor/unifi_announcer/<name>_firmware/config
homeassistant/sensor/unifi_announcer/<name>_last_ring/config
```

The buzzer button publishes exactly
`{"buzzer":true,"target":"<name>"}` and the default button publishes exactly
`{"default":true,"target":"<name>"}` to
`unifi-announcer/chime/<name>/play`.
