# MCP server

UniFi Announcer can expose an optional Streamable HTTP Model Context Protocol endpoint from the same process as the REST API.

The MCP layer is deliberately thin: every playback tool submits the same `AnnouncementCommand` to the existing `AnnouncementDispatcher`. It does not create a second Protect client, TTS engine, cache, queue, or playback path.

## Dynamic TTS and conversational workloads

`v2.1.0-beta.3` specifically hardens MCP/conversational use. Beta.2 created a distinct Protect ringtone identity for each new phrase, which could leave device-side artifacts even after safe NVR cleanup. Beta.3 provisions exactly two persistent service-owned TTS slots and overwrites them in place.

After initial provisioning, 1 or 100 unique `announce` tool calls create **zero additional Protect ringtone identities**.

The Announcer host still keeps a bounded content-addressed MP3 cache so repeated phrases can skip synthesis/encoding. Check the runtime before enabling a high-volume agent:

```bash
curl -fsS http://<announcer-host>:8095/tts/slots/status
curl -fsS http://<announcer-host>:8095/tts/cache/status
```

Dynamic MCP announcements require fixed-slot status `ready: true`. The direct overwrite path needs the current Smart Chime per-device credential on the Announcer host; MCP never receives or exposes that credential.

## Enable

Add to `.env`:

```env
MCP_ENABLED=true
MCP_API_KEY=<generate-a-dedicated-secret>
MCP_ALLOWED_HOSTS=announcer.local,192.0.2.10
```

Recreate the container. The endpoint is:

```text
http://<announcer-host>:8095/mcp
```

The MCP key is intentionally separate from `APP_API_KEY`, although an operator may choose to assign them the same value.

Requests authenticate with:

```text
Authorization: Bearer <MCP_API_KEY>
```

`MCP_ALLOWED_HOSTS` is required for non-localhost names/IPs because the MCP SDK's DNS-rebinding protection rejects unexpected `Host` headers. Include the exact LAN hostname/IP clients will use.

## Tools

Read-only:

- `get_status`
- `list_chimes`
- `list_presets`
- `get_recent_events`
- `get_queue_status`

Playback:

- `announce`
- `play_preset`
- `play_default`
- `buzzer`

`get_status` includes `dynamic_tts` and `tts_cache` data in beta.3. Internal `UA-TTS-*` identities are omitted from `list_presets`.

Playback results return canonical dispositions such as `played`, `suppressed`, `deduped`, `partial`, or `failed`. Quiet-hours suppression and deduplication are application outcomes rather than generic MCP protocol failures.

An `announce` response may include `dynamic_tts_slot: 1` or `2` in its details. That number identifies the logical ping-pong slot, not a user preset.

## Not exposed

The MCP surface deliberately excludes preset mutation, rule editing, chime setting changes, reboot/reset/adoption, arbitrary cache mutation, direct support logs, firmware research, arbitrary direct staging, credential retrieval, and arbitrary URL/file playback.

The fixed-slot manager's internal direct write operation is not an MCP tool and accepts only previously proven service-owned slots.

## Hermes

Use the current Hermes MCP configuration syntax for the installed Hermes release. Conceptually:

```yaml
mcp_servers:
  unifi_announcer:
    url: "http://<announcer-host>:8095/mcp"
    transport: streamable_http
    headers:
      Authorization: "Bearer ${UNIFI_ANNOUNCER_MCP_KEY}"
    timeout: 120
    connect_timeout: 30
    enabled: true
```

Verify the exact field names with the Hermes version in use, then run its MCP connection/tool-discovery test before enabling playback tools in normal agent workflows.

For beta.3 acceptance, send a high-cardinality sequence (for example 100 unique messages) and verify the service-owned Protect dynamic identity count remains exactly two and device storage remains stable.

## Architecture notes

The service pins the stable MCP Python SDK 2.0.0. The MCP ASGI app is mounted at `/mcp` with `streamable_http_path="/"`, avoiding an accidental `/mcp/mcp` path. Because mounted ASGI application lifespans do not run automatically, the parent server lifespan explicitly owns the MCP session manager.

MCP, Home Assistant, REST, MQTT, and local rules all share the same fixed-slot dispatcher path for arbitrary text.

Keep MCP LAN-only unless protected by a deliberate VPN/reverse-proxy design. Do not expose it directly to the public internet.
