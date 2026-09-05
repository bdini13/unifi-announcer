# Smart Chime credential setup

Arbitrary text-to-speech requires UniFi Announcer to make a narrowly scoped direct HTTPS request to the adopted Smart Chime so it can replace the bytes in one of the two proven service-owned TTS slots. Normal playback still goes through UniFi Protect.

The direct-device path uses username `ubnt` plus the Smart Chime's unique device password. Treat that password as a high-value secret. UniFi Announcer accepts the credential through `CHIME_DIRECT_PASSWORD` or `CHIME_CREDENTIAL_FILE`; the service itself does **not** retrieve the password from Protect.

## Validated Protect UI onboarding

The current physically validated stack is:

- UniFi OS `5.1.31`;
- Protect `7.2.105`;
- Smart WiFi Chime / UP Chime;
- Smart Chime firmware `1.7.20`.

On this stack, the credential can be obtained through Protect's normal authenticated web UI:

**Protect → Devices → Smart WiFi Chime → Settings → Manage → Manual Recovery → Reveal**

Use **Reveal** to display the existing value. Do **not** click **Edit** just to configure UniFi Announcer: Edit is a credential-changing operation and is not required for onboarding.

Live inspection of the Protect frontend confirmed the distinction:

- **Reveal** calls `GET /devices/password/{deviceType}/{deviceId}`;
- **Edit** uses `PATCH` on that same resource.

The value returned by **Reveal** exactly matched the already known working `CHIME_DIRECT_PASSWORD` on the validated installation and returned `HTTP 200` with username `ubnt` against the Smart Chime's `/api/info` endpoint.

The Manual Recovery area may present surrounding recovery-oriented UI text. Copy the actual value displayed by **Reveal**, not labels or other text from the page. An earlier `HTTP 401` test was traced to incorrectly captured UI text rather than the revealed credential; it is not evidence that the Reveal value is incompatible.

This onboarding path uses only Protect's normal authenticated UI. It does not require SSH, database access, backup scraping, credential reset, or an exploit.

## Verify the revealed credential without changing anything

After revealing the value, you may verify it against the chime's read-only `/api/info` endpoint before saving it in `.env`.

The following probe uses Python `getpass`, so the credential is not placed in shell history or exported into the process environment. It prints only the HTTP status and does not display the response body.

```bash
python3 - <<'PY'
import getpass
import json
import ssl
import urllib.error
import urllib.request

ip = input("Smart Chime IP: ").strip()
password = getpass.getpass("Revealed Smart Chime device password: ")
body = json.dumps({"username": "ubnt", "password": password}).encode()
request = urllib.request.Request(
    f"https://{ip}:8080/api/info",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
context = ssl._create_unverified_context()

try:
    with urllib.request.urlopen(request, context=context, timeout=8) as response:
        print(f"HTTP {response.status}")
except urllib.error.HTTPError as exc:
    print(f"HTTP {exc.code}")
except urllib.error.URLError as exc:
    print(f"Connection error: {exc.reason}")
PY
```

Interpret the result:

- `HTTP 200` — the Smart Chime accepted username `ubnt` plus the supplied credential; it is suitable for `CHIME_DIRECT_PASSWORD`.
- `HTTP 401` — the supplied value was not accepted. Re-open Protect and use the exact value produced by **Reveal**; do not retry rapidly and do not click Edit merely to force a new credential.
- connection/timeout error — verify the Smart Chime IP, LAN reachability, firewall policy, and firmware compatibility before assuming the credential is wrong.

On Protect `7.2.105` with Smart Chime firmware `1.7.20`, the exact value produced by **Reveal** returned `HTTP 200` through this `ubnt` + `/api/info` check.

The Smart Chime presents a self-signed certificate, so the verification probe deliberately disables certificate verification for this local check. Run it only from a trusted LAN/VPN.

## Configure UniFi Announcer

Once the verification returns `HTTP 200`, place the credential in your private `.env` and keep that file mode `0600`:

```env
CHIME_DIRECT_USER=ubnt
CHIME_DIRECT_PASSWORD=<revealed-and-verified-device-password>
TTS_ENGINE=piper
```

Then recreate the service:

```bash
chmod 600 .env
export GIT_SHA="$(git rev-parse HEAD)"
docker compose up -d --build
```

Verify that the dynamic slots are ready:

```bash
export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"
AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")
curl -fsS "${AUTH[@]}" http://<announcer-host-or-ip>:8095/tts/slots/status
```

A healthy arbitrary-TTS setup reports `"mode":"two_slot_overwrite"`, `"slot_count":2`, and `"ready":true`.

## Credential rotation

If the device password is intentionally changed in Protect, a static `CHIME_DIRECT_PASSWORD` must be updated and the container recreated. UniFi Announcer also supports `CHIME_CREDENTIAL_FILE` for operators who maintain the credential in a mounted local secret file; that provider rereads the file when it changes and after a direct-device HTTP 401.

Do not use Protect's **Edit** action merely as an Announcer setup step. If you intentionally rotate the credential for another reason, update every authorized consumer that depends on it.

UniFi Announcer does **not** retrieve or refresh the password from Protect automatically.

## Security notes

- Use the normal authenticated Protect UI and **Reveal** the existing value.
- Do not publish the revealed password, screenshots containing it, recovery UI contents, private IPs/hostnames, device IDs, certificate fingerprints, or raw support logs.
- Do not enable SSH on the console, query Protect's internal database, or scrape backups for credential onboarding; those methods are unnecessary for the validated flow and are not supported by this project.
- Keep UniFi Announcer and the verification probe on a trusted LAN/VPN.
