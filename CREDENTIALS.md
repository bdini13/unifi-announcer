# Smart Chime credential setup

Arbitrary text-to-speech requires UniFi Announcer to make a narrowly scoped direct HTTPS request to the adopted Smart Chime so it can replace the bytes in one of the two proven service-owned TTS slots. Normal playback still goes through UniFi Protect.

The direct-device path uses username `ubnt` plus the Smart Chime credential provisioned during adoption. Treat that credential as a high-value secret. UniFi Announcer accepts an existing credential but does **not** retrieve it from Protect automatically.

## Important limitation on the validated stack

The current physically validated stack is:

- UniFi Protect `7.2.105`;
- Smart WiFi Chime / UP Chime;
- Smart Chime firmware `1.7.20`.

On that Protect version, live validation found **no Device Password or equivalent device-authentication field in the Protect web UI**, including **Settings → General → Advanced** and the other visible Protect Settings sections.

Therefore, a fresh installation on Protect `7.2.105` cannot bootstrap credential-backed arbitrary TTS through this project's supported onboarding procedure unless the operator already possesses and maintains the current Smart Chime credential through an authorized external process.

Credential-free preset, assigned-default, and hardware-buzzer playback remains available with `TTS_ENGINE=none`.

## Historical / version-dependent Protect UI references

Older UniFi community guidance has described a **Device Password** setting in Protect. Its location has varied between releases, including historical references to:

- **Settings → General → Advanced → Device Password**;
- **Settings → System → Advanced → Device Password**.

These locations are **not validated for Protect 7.2.105** and should not be read as a promise that a current Protect installation exposes the credential.

Historical references:

- [Ubiquiti staff/community discussion of Protect Device Password](https://community.ui.com/questions/username-and-password/3b29ebb4-cd18-4cfe-8ed0-7a96f6f96aac?page=1)
- [Ubiquiti community discussion of newer device-authentication navigation](https://community.ui.com/questions/How-to-find-Unifi-device-username-and-password-in-Unifi-OS-2-5/f2e51ba9-34a3-40ca-bd98-1126373b7715)

If your Protect version exposes an existing Device Password through its normal web UI, you may verify that value with the non-destructive procedure below before configuring it in UniFi Announcer. Do not rotate or reset device credentials solely for this project.

A **Recovery Code** is not assumed to be interchangeable with the direct-device credential. Do not put a recovery code into `CHIME_DIRECT_PASSWORD` unless a non-destructive verification proves that the target Smart Chime accepts it.

## Verify an existing credential without changing anything

If you already possess the current Smart Chime credential, verify it against the chime's read-only `/api/info` endpoint before saving it in `.env`.

The following probe uses Python `getpass`, so the credential is not placed in shell history or exported into the process environment. It prints only the HTTP status and does not display the response body.

```bash
python3 - <<'PY'
import getpass
import json
import ssl
import urllib.error
import urllib.request

ip = input("Smart Chime IP: ").strip()
password = getpass.getpass("Existing Smart Chime credential: ")
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
- `HTTP 401` — the value is not the current direct-device credential for that chime. Do not keep retrying rapidly and do not rotate device credentials just to make the test pass.
- connection/timeout error — verify the Smart Chime IP, LAN reachability, firewall policy, and firmware compatibility before assuming the credential is wrong.

This exact `ubnt` + `/api/info` verification path returned `HTTP 200` during live validation on Protect `7.2.105` with Smart Chime firmware `1.7.20` using an already configured credential.

The Smart Chime presents a self-signed certificate, so the verification probe deliberately disables certificate verification for this local check. Run it only from a trusted LAN/VPN.

## Configure UniFi Announcer

Once the verification returns `HTTP 200`, place the credential in your private `.env` and keep that file mode `0600`:

```env
CHIME_DIRECT_USER=ubnt
CHIME_DIRECT_PASSWORD=<verified-device-password>
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

If the adopted-device credential rotates, a static `CHIME_DIRECT_PASSWORD` must be updated and the container recreated. UniFi Announcer also supports `CHIME_CREDENTIAL_FILE` for operators who already maintain the credential in a mounted local secret file; that provider rereads the file when it changes and after a direct-device HTTP 401.

UniFi Announcer does **not** retrieve or refresh the password from Protect itself.

## If you do not already have the credential

If your Protect UI does not expose an existing Device Password and you do not already possess the current Smart Chime credential, credential-backed arbitrary TTS cannot be newly configured through this project's supported onboarding path.

Do not enable SSH on the console, query Protect's internal database, scrape backups, or publish raw authentication/support data as an onboarding workaround. Those methods are version-sensitive, broaden the security boundary, and are not supported by this project.

Use `TTS_ENGINE=none` for credential-free preset/default/buzzer playback and open a GitHub issue with only the following non-sensitive information:

- Protect version;
- Smart Chime model and firmware;
- whether **Device Password** is present anywhere in the Protect web settings;
- whether you already possess a credential and, if tested, whether the `/api/info` verification returned `200`, `401`, timed out, or could not connect.

Never post the password, private IPs/hostnames, device IDs, certificate fingerprints, recovery codes, or raw support logs.
