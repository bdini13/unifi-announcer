# Smart Chime credential setup

Arbitrary text-to-speech requires UniFi Announcer to make a narrowly scoped direct HTTPS request to the adopted Smart Chime so it can replace the bytes in one of the two proven service-owned TTS slots. Normal playback still goes through UniFi Protect.

This direct-device path uses username `ubnt` plus the Smart Chime password provisioned during adoption. Treat that password as a high-value secret. Depending on Protect version, the same adopted-device password may be used by more than one Protect device.

## Preferred way to obtain the password

Use the UniFi Protect **web** interface first. Ubiquiti has historically exposed the adopted-device password as **Device Password** in Protect settings. Its location has moved between releases; common locations have included:

- **Settings → General → Advanced → Device Password**
- **Settings → System → Advanced → Device Password**

Use settings search if your Protect version provides it. Reveal and copy the existing value rather than changing it solely for UniFi Announcer.

Ubiquiti community references:

- [Ubiquiti staff: Protect device password is in Settings → General → Device Password](https://community.ui.com/questions/username-and-password/3b29ebb4-cd18-4cfe-8ed0-7a96f6f96aac?page=1)
- [Ubiquiti community: newer navigation may place device authentication under Settings → System → Advanced](https://community.ui.com/questions/How-to-find-Unifi-device-username-and-password-in-Unifi-OS-2-5/f2e51ba9-34a3-40ca-bd98-1126373b7715)

A **Recovery Code** is not assumed to be interchangeable with the direct-device password. Do not put a recovery code into `CHIME_DIRECT_PASSWORD` unless the non-destructive verification below confirms that the Smart Chime accepts it.

## Verify the credential without changing anything

Before saving the password in `.env`, verify it against the Smart Chime's read-only `/api/info` endpoint. This test sends the password through stdin-generated JSON so it does not appear in shell history, and it discards the device-info response body.

```bash
read -r -p "Smart Chime IP: " CHIME_IP
read -r -s -p "Protect Device Password: " CHIME_DEVICE_PASSWORD
echo
export CHIME_DEVICE_PASSWORD

python3 -c 'import json,os; print(json.dumps({"username":"ubnt","password":os.environ["CHIME_DEVICE_PASSWORD"]}))' | \
  curl -ksS -o /dev/null -w 'HTTP %{http_code}\n' \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    "https://${CHIME_IP}:8080/api/info"

unset CHIME_DEVICE_PASSWORD CHIME_IP
```

Interpret the result:

- `HTTP 200` — the Smart Chime accepted the credential; it is suitable for `CHIME_DIRECT_PASSWORD`.
- `HTTP 401` — the value is not the current direct-device credential for that chime. Do not keep retrying rapidly and do not rotate device credentials just to make the test pass.
- connection/timeout error — verify the Smart Chime IP, LAN reachability, firewall policy, and firmware compatibility before assuming the password is wrong.

The Smart Chime presents a self-signed certificate, which is why the verification example uses `-k`. Keep this test on a trusted LAN/VPN.

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

If Protect rotates the adopted-device password, a static `CHIME_DIRECT_PASSWORD` must be updated and the container recreated. UniFi Announcer also supports `CHIME_CREDENTIAL_FILE` for operators who already maintain the credential in a mounted local secret file; that provider rereads the file when it changes and after a direct-device HTTP 401.

UniFi Announcer does **not** retrieve the password from Protect automatically.

## If Device Password is not available in your Protect UI

Do not enable SSH on the console, query Protect's internal database, scrape backups, or publish raw authentication/support data as an onboarding workaround. Those methods are version-sensitive, broaden the security boundary, and are not supported by this project.

Use `TTS_ENGINE=none` for credential-free preset/default/buzzer playback and open a GitHub issue with only the following non-sensitive information:

- Protect version;
- Smart Chime model and firmware;
- whether **Device Password** is present anywhere in the Protect web settings;
- whether the `/api/info` verification returned `401`, timed out, or could not connect.

Never post the password, private IPs/hostnames, device IDs, certificate fingerprints, or raw support logs.