# Security policy

## Supported versions

Security fixes are provided for the latest stable release. Upgrade to the latest
published release before reporting an issue unless the issue prevents upgrading.

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities or include credentials,
console addresses, device identifiers, support logs, or other private deployment
data in public reports.

Use GitHub's **Report a vulnerability** flow under the repository Security tab.
If private vulnerability reporting is unavailable, open a minimal public issue
that asks the maintainer to establish a private contact channel; include no
technical exploit details until that channel exists.

Include the affected version, impact, reproduction conditions using synthetic or
redacted data, and any proposed mitigation. Reports should receive an initial
response within seven days, but this community project provides no response-time
guarantee.

## Security boundary

UniFi Announcer uses undocumented local UniFi interfaces. Keep it on a trusted
LAN or behind a VPN/authenticated reverse proxy. Never expose REST or MCP directly
to the public internet. Use a dedicated least-privilege local UniFi account and
separate REST and MCP keys.

For arbitrary TTS, use Protect's normal authenticated web UI to reveal the Smart
Chime's existing unique device password as documented in [`CREDENTIALS.md`](CREDENTIALS.md).
On the validated UniFi OS `5.1.31` / Protect `7.2.105` stack the path is
**Devices → Smart WiFi Chime → Settings → Manage → Manual Recovery → Reveal**. The value produced by Reveal
matched the known working direct-device credential and returned HTTP 200 with
username `ubnt` against `/api/info`.

Use **Reveal**, not **Edit**, for onboarding. Live inspection of the Protect
frontend showed that Reveal reads the existing per-device password, while Edit
uses the corresponding credential-changing operation. Do not rotate a device
credential merely to configure UniFi Announcer.

Treat the revealed password as a high-value secret. The project does not retrieve
Smart Chime credentials automatically and does not support enabling SSH, querying
internal Protect databases, scraping backups, or publishing raw authentication
material as onboarding methods; those methods are unnecessary for the validated
UI flow.

Before sharing diagnostics, remove secrets, hostnames, IP addresses, device IDs,
certificate fingerprints, screenshots containing revealed credentials, audio
content, and deployment-specific paths.
