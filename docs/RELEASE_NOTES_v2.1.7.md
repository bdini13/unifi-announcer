# v2.1.7 — Smart Chime credential onboarding

v2.1.7 is a documentation and packaging patch that adds a validated, non-destructive onboarding path for the Smart Chime device password required by arbitrary TTS. Runtime playback behavior and the two-slot ownership model are unchanged from v2.1.6.

## Added

- Document the validated Protect web UI path: **Devices → Smart WiFi Chime → Settings → Manage → Manual Recovery → Reveal**.
- Clearly distinguish read-only **Reveal** from credential-changing **Edit**.
- Add a `getpass`-based `/api/info` verification procedure that does not place the password in shell history or print the response body.
- Align the README, environment example, compatibility guidance, security guidance, release checklist, and bug-report intake with the verified onboarding flow.

## Validation boundary

The onboarding path was validated on:

- UniFi OS `5.1.31`;
- Protect `7.2.105`;
- Smart WiFi Chime / UP Chime;
- Smart Chime firmware `1.7.20`.

On that installation, the exact value returned by **Reveal** matched the already working `CHIME_DIRECT_PASSWORD` and returned `HTTP 200` with username `ubnt` against the Smart Chime's read-only `/api/info` endpoint. Only `/api/info` was invoked during the credential check; its response body was not read or displayed. No credential, Protect setting, Smart Chime setting, ringtone slot, or running deployment was changed.

This validation used an already adopted Smart Chime. A fresh adoption was not independently repeated because no spare device was available. Other Protect and firmware versions may present different navigation or behavior.

## Security

Treat the revealed value as a high-value device password. Do not post it, include it in screenshots, export it into shell history, or expose UniFi Announcer outside a trusted LAN/VPN. Use **Reveal**, not **Edit**, for onboarding. SSH, internal Protect database access, backup scraping, and credential reset are neither required nor supported by this flow.

## Upgrade

No configuration or data migration is required from v2.1.6. Existing deployments may upgrade the backend and Home Assistant integration together using the normal tagged-release procedure in the README.
