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

For arbitrary TTS, the operator may supply an existing Protect web-UI **Device
Password** only after the non-destructive `/api/info` check in
[`CREDENTIALS.md`](CREDENTIALS.md) confirms that the target Smart Chime accepts
it. Treat this adopted-device password as a high-value secret; depending on the
Protect release it may be shared by multiple managed devices.

The project does not retrieve Smart Chime credentials automatically and does not
support enabling SSH, querying internal Protect databases, scraping backups, or
publishing raw authentication material as onboarding methods.

Before sharing diagnostics, remove secrets, hostnames, IP addresses, device IDs,
certificate fingerprints, audio content, and deployment-specific paths.
