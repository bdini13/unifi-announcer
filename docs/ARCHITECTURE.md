# Architecture

UniFi Announcer is a FastAPI adapter around undocumented local UniFi protocols. Runtime dependencies are explicit in `AppServices` and are published through `app.state.services`; network resources are started and stopped by the FastAPI lifespan.

```text
REST routes ─┐
local rules ─┼─> AnnouncementCommand -> AnnouncementDispatcher
MQTT ────────┘     validate -> profile -> quiet hours -> targets/groups
                         -> audio/preset -> per-chime jobs -> arbitration
                         -> DispatchResult/dispositions

TTS -> locked audio cache -> direct chime storage (capability gated, optional)
                         └-> Protect/NVR ringtone identity (always required)
RingtoneIndex (RAM) -> Protect/NVR play-speaker
```

## Modules

- `app/config.py`: typed environment settings.
- `app/chime/{credentials,capabilities}.py`: direct-device auth and firmware gates.
- `app/protect/{client,events}.py`: lazy HTTP transport, protocol notes, and the runtime frame decoder.
- `app/audio/{tts,cache}.py`: normalized TTS keys and `RingtoneIndex`.
- `app/rules/engine.py`: rule action contracts.
- `app/playback/arbitration.py`: bounded per-chime priority queues and dispositions.
- `app/integrations/mqtt.py`: MQTT lifecycle, discovery, events, and command adapter.
- `app/routes/commands.py`: HTTP-to-command adapter.
- `app/dispatcher.py`: the only command execution path.
- `app/observability.py`: timings and in-memory metrics.

## Reverse-engineered protocol boundary

Direct chime endpoints are **undocumented**, verified against UP Chime firmware **v1.7.20**: read-only `POST /api/info` and `POST /api/support`, plus the experimental `POST /api/uploadRingtone/<slot>/<filename>.mp3` route. Unknown firmware fails closed. A direct write stores device audio but does not create the NVR ringtone ID needed for playback, so production uploads still use the Protect backend. Playback has no verified direct HTTP endpoint and always uses Protect/NVR `POST .../chimes/{id}/play-speaker`. The destructive endpoint denylist is checked before network I/O.

Extracted classes have one runtime source of truth in the modules above; `app.main`
only wires their instances into `AppServices`. REST, local rules, and MQTT all
produce `AnnouncementCommand` values for the same dispatcher. Group fanout uses
`asyncio.gather` across independent queues, while each individual chime remains
serialized.
