# Multi-Chime physical validation

Status: **not yet physically validated**

The software supports multiple explicitly configured Smart Chimes and named groups, but the project must not promote that to a physical compatibility claim until at least two real Smart Chimes have completed the gate below on one exact software candidate.

## Purpose

Prove the properties that unit/API tests cannot establish acoustically:

- each named Chime routes to the intended physical device;
- a two-Chime group delivers the same intended content to both devices;
- repeated content remains correct across both devices;
- different physical Chimes can make progress independently;
- two concurrent requests to one physical Chime serialize rather than overlap;
- one Chime becoming unavailable does not silently convert a group request into a false full success;
- reboot/reconnect invalidates resident-content trust for only the affected device;
- no additional dynamic ringtone identities are created beyond the fixed two service-owned slots.

## Required setup

Use an exact candidate that has already passed automated CI. Record:

- source SHA;
- semantic version;
- Docker image digest and OCI revision;
- Protect version under test;
- firmware of Chime A;
- firmware of Chime B;
- Home Assistant integration version when HA is part of the test.

Configure two distinct Chime targets and one group containing both, for example:

```env
CHIMES_CONFIG='[
  {"name":"chime_a","id":"<uuid-a>","direct_ip":"<ip-a>"},
  {"name":"chime_b","id":"<uuid-b>","direct_ip":"<ip-b>"}
]'
GROUPS_CONFIG='{"two_chimes":["chime_a","chime_b"]}'
```

Do not commit or publish the real IDs, IPs, device passwords, API key, slot filenames, or support logs.

Before sound testing:

1. Back up the persistent Announcer data directory/volume.
2. Confirm rollback image/tag is locally available.
3. Confirm both Chimes are online in Protect.
4. Confirm direct `/api/info` succeeds for each Chime through normal Announcer startup/preflight.
5. Confirm authenticated `/tts/slots/status` reports `ready=true` and exactly two logical service-owned slots.
6. Confirm authenticated `/targets` lists both configured targets and the intended group.
7. Warn occupants that the harness produces several audible announcements.

## Automated audible harness

The repository includes `scripts/validate_multi_chime.py` to exercise the normal REST/dispatcher path. It does not determine whether sound was heard; a human must record the acoustic outcome.

Set the API key in the environment rather than a command-line argument:

```bash
export UNIFI_ANNOUNCER_API_KEY='<your-api-key>'
python scripts/validate_multi_chime.py \
  --url 'http://<announcer-host>:8095' \
  --target-a 'chime_a' \
  --target-b 'chime_b' \
  --group 'two_chimes' \
  --confirm-sound
```

The script first performs a no-sound `/targets` preflight and refuses to continue unless:

- target A and target B are different;
- both are `type=chime`;
- both advertise `announce`;
- the named group exists;
- the group contains both targets;
- the group advertises `announce`.

It then runs these audible phases:

1. target A only;
2. target B only;
3. group once;
4. exact same group content again;
5. simultaneous requests to A and B;
6. simultaneous submissions of two different phrases to A, which must serialize through A's per-target queue.

The JSON output intentionally pseudonymizes the target/group labels and records only HTTP status, canonical disposition, and request-path timing. It is not acoustic proof.

## Acoustic observation sheet

Record the result while standing where both Chimes can be distinguished.

| Phase | Expected acoustic result | Result |
|---|---|---|
| Target A only | Exact A phrase from A only | PENDING |
| Target B only | Exact B phrase from B only | PENDING |
| Group once | Same group phrase from A and B | PENDING |
| Group repeat | Same phrase again from A and B; no stale prior content | PENDING |
| Different targets concurrent | A and B both play their own unique concurrent phrase | PENDING |
| Same target serialized first/second | A plays first phrase then second; no overlap/cross-content | PENDING |

Any wrong-device sound, stale phrase, missing device, overlap on the same Chime, duplicate playback, or unexpected extra device is a failure.

## Fixed-slot invariants

Immediately before and after the harness, capture authenticated `/tts/slots/status` locally and compare the safe invariants:

- exactly two logical slots;
- no new service-owned ringtone identity allocated per phrase;
- both configured Chimes have bindings to the established logical slots;
- no ownership drift;
- no unresolved legacy orphans introduced by the test.

Do not publish raw slot bindings because they contain physical/device identifiers and filenames.

## Partial failure gate

This step requires deliberate temporary unavailability of one test Chime.

1. Make Chime B unavailable in a reversible way, such as powering only that test Chime off.
2. Wait until the service/Protect path observes it unavailable.
3. Submit one group announcement.
4. Record the canonical result and what A does physically.
5. Restore B and wait for recovery.

Pass criteria:

- the system must not report a false full `played` result for both members when B is unavailable;
- any playback on A must be represented consistently with the group failure/partial semantics;
- no retry should later produce stale/duplicate sound on B merely because it reconnects.

If current preflight semantics intentionally fail the whole mixed request before any side effect, record that as the observed behavior rather than forcing a partial-play expectation.

## Reboot/reconnect gate

After both Chimes have trusted resident content:

1. Reboot only Chime B.
2. Leave Chime A online.
3. Wait for B to return to Protect/direct access.
4. Repeat a phrase that was previously resident on both Chimes.
5. Inspect sanitized counters/status and listen to both devices.

Pass criteria:

- B's pre-reboot resident-content trust is invalidated and it safely rewrites/revalidates before reuse;
- A does not lose trusted same-boot resident content merely because B rebooted, unless group-slot selection legitimately requires a rewrite for shared correctness;
- both devices ultimately play the requested phrase correctly;
- subsequent same-boot repeats can reuse trusted resident content again;
- no stale pre-reboot bytes are heard from B.

## Home Assistant group smoke

After REST testing passes, run one Home Assistant announcement to the two-Chime group using the matching integration version.

For beta.4 or later, also run one native `tts.speak` group request. Both physical Chimes must receive the intended content and Home Assistant Last playback result must match the canonical backend disposition.

## Evidence record

Create a release-specific validation record after the run containing only sanitized evidence:

- exact source SHA and image digest;
- semantic/backend/HA versions;
- exact firmware version for each Chime;
- Protect version;
- harness JSON with pseudonymous targets;
- acoustic PASS/FAIL per phase;
- safe fixed-slot counts/state summary;
- partial-failure behavior;
- reboot/reconnect behavior;
- any deviations or required fixes.

Do not mark the roadmap item physically validated until every required phase has direct evidence. A successful harness API response by itself is insufficient.