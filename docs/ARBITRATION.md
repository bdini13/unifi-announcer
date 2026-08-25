# Playback arbitration

Each chime owns an independent priority heap and an immediately scheduled asyncio worker; there is no fixed-interval polling. A submission waits for a final target disposition: `played`, `deduped`, `dropped`, or `failed` (`queued` is reserved for asynchronous adapters).

Priority values are lower-is-stronger:

- `0` emergency: never dropped. It displaces queued non-emergency work or is admitted temporarily above capacity when the only slot is in flight.
- `10` doorbell: may displace queued informational (`100`) work.
- `50` normal: admitted only while capacity remains.
- `100` info: dropped when full.

In-flight audio is never interrupted. Dedupe keys map to monotonic expiry times and expired entries are pruned on submission, bounding long-running memory use. Dispatch fanout reports each target's final disposition and queue wait.
