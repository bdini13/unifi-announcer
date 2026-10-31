# CI scope and performance

## Measured bottlenecks

The 2026-10-10 review profiled the complete local backend suite and inspected recent GitHub Actions jobs. A [successful historical run](https://github.com/bdini13/unifi-announcer/actions/runs/34427988207) spent 89 seconds in backend tests, 75 seconds installing HA dependencies, and 35 seconds building Docker. The two jobs took 142 and 86 seconds overall. Another commit generated both [push](https://github.com/bdini13/unifi-announcer/actions/runs/34655204585) and [pull-request](https://github.com/bdini13/unifi-announcer/actions/runs/34655209241) runs for the same revision.

On the Mac mini, the reliability branch's full backend suite changed from **453 tests in 87.72 seconds** to **436 tests in 6.46 seconds** (about **93% less test time**). The separate PR43 worktree also passed all 419 retained backend tests in 4.39 seconds. These are local pytest measurements, not measured end-to-end GitHub Actions speedups.

The largest test, the 100-unique-message slot regression, spent 75.54 seconds waiting for 100 real 750 ms device-settle delays even though its fake device updates storage synchronously. Its fake manager now uses zero settle delay; all 100 writes and the two-identity/alternating-slot assertions remain. A separate test verifies that preparation awaits the configured settle delay. Four slot-binding failure tests now advance a local polling clock instead of waiting a real second for each synthetic failure. Production timing is unchanged. Real event-loop timeout, cancellation, lease, and acoustic-guard regressions remain.

## Checks retained

| Area | Decision |
|---|---|
| Playback, admission, cancellation, slot ownership, persistence, restart/reconnect | Keep all behavioral regressions; shorten only artificial hardware waits. |
| REST, rules, MQTT, MCP, targets, authentication, diagnostics | Keep contract and failure-path checks. |
| HA minimum and current versions | Keep both environments: the version boundary caught a real setup failure. |
| Release scripts | Keep publication, tag-conflict, wrong-revision, and operational-error tests while the scripts remain callable. |
| Installation documentation | Keep usable command, credentials, backup/rollback, mounted-data, and authentication examples. |
| JSON metadata, lint, compilation, Compose, Docker, HACS, Hassfest | Keep these distinct packaging/integration gates. Docker remains inside the required `pytest` job. |

## Low-value coverage removed

Eighteen tests were removed: three historical post-release prose snapshots, two release-process prose checks, nine README/comment/historical-release snapshots, three extraction/import-identity checks duplicated by behavior tests, and one mocked benchmark that merely asserted a hard-coded connection count. The unused mocked-benchmark helper was removed too; real Piper connection reuse is still tested.

The version test now compares backend, HA component, and manifest versions to each other instead of repeating a fixed release string. Historical validation reports remain in the repository; requiring their exact sentences, old commit hashes, or image digests in every future CI run did not establish current correctness. Test deletion reduces maintenance noise; eliminating fake-device waits provides almost all the pytest speedup.

## Workflow execution and caching

- Run both workflows on pull requests, pushes to `main`, version tags (`v*`), and manual dispatch. Ordinary feature-branch pushes are covered when a PR is open; use manual dispatch for a branch without a PR. This avoids duplicate push/PR suites.
- Cancel superseded runs per workflow and PR/ref. Required check names remain `pytest`, `home-assistant`, `hacs`, and `hassfest`; the additional `home-assistant-current` job is retained.
- Install the same requirements with pinned uv 0.12.5 and cache its downloads/wheels separately by requirements inputs. Python still comes from `actions/setup-python`.
- Build with Buildx and the GitHub Actions layer cache. Commit-specific `GIT_SHA` metadata is applied after expensive Docker layers so new commits can reuse those layers. `.dockerignore` includes only runtime build inputs.
- Run scheduled HACS/Hassfest validation weekly (Monday 04:17 UTC), instead of daily. PR/main/tag validation remains immediate; detection of upstream validator changes on an otherwise idle repository can now take up to a week.
- Report the ten slowest tests on every run. Do not introduce test sharding or broad path-based skips for a suite that now runs in seconds.

The caching/concurrency configuration follows [uv's GitHub Actions guide](https://docs.astral.sh/uv/guides/integration/github/), [Docker's GitHub cache guide](https://docs.docker.com/build/ci/github-actions/cache/), and [GitHub's concurrency documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency). Cache misses still perform a complete install/build; caches do not skip validation.

## Maintaining useful tests

The October 25 offline repairs add failure-path coverage for controller content replacement, interrupted provisioning and preset updates, durable restart guards, physical slot numbering, and HA service routing. The admission scheduler test now uses a short hold while separately asserting the production duration calculation, removing another artificial long wait. One exact-wording HA documentation test was removed because playback-result behavior already has executable coverage. Both HA version gates and the 100-message slot regression remain.

On the combined native-media candidate, a short silent WAV-to-MP3 smoke check runs inside the same image already built by CI, with networking disabled. It verifies that the shipped FFmpeg/ffprobe binaries and conversion path work, without another Docker build or a physical speaker.

Profile before removing or parallelizing tests:

```bash
.venv/bin/python -W error -m pytest -q tests --durations=20
.venv-ha/bin/python -m pytest -q tests_ha --durations=10
```

Prefer observable results, resource cleanup, and failure behavior over source-code identity or exact editorial wording. Fake hardware should not incur production settling delays. Keep a focused check for the timing contract whenever a fake skips the delay, and preserve real-clock tests where scheduling/cancellation itself is the behavior under test.

Actionlint validates the workflow syntax and expressions locally. Docker is unavailable on the review Mac, so container builds and end-to-end timings must be verified in GitHub Actions. Record cold and warm cache measurements in the candidate pull request before merging.
