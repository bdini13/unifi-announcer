# Protect realtime updates

UniFi Announcer consumes `/proxy/protect/ws/updates` with the authenticated Protect session. Captured fixtures are sanitized and contain no controller address, cookie, token, or real device identifier.

## Observed frame format

Each websocket message contains one or two linked frames. Every frame starts with exactly eight bytes:

| Byte(s) | Meaning |
|---|---|
| 0 | packet type (`1` observed) |
| 1 | payload format (`1` = JSON observed) |
| 2 | compression (`0` plain, `1` zlib) |
| 3 | reserved |
| 4–7 | unsigned big-endian payload length |

The payload begins at byte 8. An action frame may be followed immediately by a data frame, or tests/callers may supply the two frames separately. Unsupported packet types or payload formats fail closed. MessagePack is not enabled because the captured fixture does not demonstrate it.

## Ring semantics

Both `event` and `camera` updates are retained for enrichment. A doorbell rule is gated only by a camera's `lastRing` value: the service remembers `lastRing` per camera and emits `doorbell_ring` only when it advances. Replayed camera updates and Protect history event objects cannot duplicate a ring.

The live client reconnects with capped exponential backoff and exposes sanitized recent data through `/events/recent` and SSE through `/events/stream`.
