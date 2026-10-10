# Playback arbitration

The unreleased production dispatcher admits requests before synthesis, slot writes, or camera preparation. Every physical target has a hard `PLAY_QUEUE_MAX_DEPTH` cap (default 16), counting waiting requests, active preparation, and ongoing audio guards. Dedupe and overload decisions therefore consume no audio preparation work. Group responses retain each target's `played`, `deduped`, `dropped`, or `failed` disposition; a mix can return `partial`.

Priority values are lower-is-stronger:

- `0` emergency displaces queued non-emergency work when full.
- `10` doorbell can displace queued informational (`100`) work.
- `50` normal and `100` info are dropped when full.
- All priorities obey the hard cap. If no eligible waiting request can be displaced, even an emergency is dropped. In-flight audio is never interrupted to make room.

Waiting groups acquire their accepted physical targets together. Overlapping groups cannot hold one target while waiting for another, and queued priority orders contested targets. Disjoint groups remain concurrent. Camera preparation also orders locks by camera ID, and its lock wait is covered by the camera preparation deadline.

Dedupe applies independently to each target, starting at admission. Expired keys are pruned on submission. A group can therefore skip a recently served member while playing on another. Queue-depth sensors include active reservations and guard intervals even after the command response has returned.

## Playback duration and deadlines

Protect's successful HTTP response acknowledges a Chime play request; it does not report sound completion. The dispatcher keeps the target reserved for estimated MP3 duration × repeats + 1.25 seconds, with a minimum 1.75-second guard. This reservation is separate from the two fixed TTS slot leases and survives caller cancellation or an ambiguous play-request failure.

Dynamic speech and newly saved presets carry MP3 duration estimates. Older or externally created presets, assigned-default tones, and the buzzer use `CHIME_PLAYBACK_FALLBACK_SECONDS` (default 30 seconds per play). Set this value at least as long as the longest recording without known duration. Assigned-default requests that leave repeat settings to the device conservatively reserve six plays. Unknown recordings longer than the configured fallback can still overlap; these guards are estimates, not microphone-confirmed completion.

The backend command deadline is 120 seconds, including admission wait and preparation. Camera preparation has its own 30-second default deadline. HA command requests wait up to 150 seconds; polling remains 15 seconds. A timeout stops waiting/preparation while preserving any already-established Chime guard. Long guards or sustained traffic can cause later requests to reach their deadline without playback.

The lower-level `app.main` compatibility path retains its original queue worker; production must run `app.server:app` to get preparation admission and duration reservations.
