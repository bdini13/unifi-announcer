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

Dynamic speech and newly saved presets carry MP3 duration estimates. Preset duration belongs to its exact Protect identity; replacement by another ID discards the old estimate. Older or externally created presets, built-in default tones, and the buzzer use `CHIME_PLAYBACK_FALLBACK_SECONDS` (default 30 seconds per play). Set this value at least as long as the longest recording without known duration. `/play-default` selects built-in track 1, independently of camera assignments. When it leaves repeats to the device, the reservation covers up to 10 plays; explicit API repeat counts remain 1–6. Unknown recordings longer than the configured fallback can still overlap; these guards are estimates, not microphone-confirmed completion.

`/data/playback_guards.json` persists per-target deadlines before any request that may start sound, including a conservative network interval until the outcome is known. Admission and slot startup respect these deadlines after a process restart. A detected host reboot retains a full recorded hold rather than assuming remote audio stopped. Wall-clock and monotonic deadlines prevent a same-host clock correction from shortening the reservation. Malformed guard state fails closed: retain it for recovery instead of deleting it to bypass a wait.

Preset creation/replacement acquires the Chime admission reservation and slot lifecycle guard before changing controller ringtones. This prevents Announcer's own mutations from overlapping active announcements. External controller synchronization remains asynchronous; observed changes invalidate content proof and in-progress preparation, but the service cannot make an external write and a subsequent play request atomic.

The backend command deadline is 120 seconds, including admission wait and preparation. Camera preparation has its own 30-second default deadline. HA command requests wait up to 150 seconds; polling remains 15 seconds. A timeout stops waiting/preparation while preserving any already-established Chime guard. Long guards or sustained traffic can cause later requests to reach their deadline without playback.

The lower-level `app.main` compatibility path retains its original queue worker; production must run `app.server:app` to get preparation admission and duration reservations.
