# Maintainer guide

This guide records repository and release settings that live outside the source tree. They should be reviewed before a public launch and after material GitHub configuration changes.

## Repository presentation

Recommended GitHub repository metadata:

- Description: `Self-hosted TTS and programmable announcements for UniFi Protect Smart Chimes, with Home Assistant, REST, MQTT, and MCP.`
- Topics: `unifi`, `unifi-protect`, `smart-chime`, `home-assistant`, `home-automation`, `tts`, `piper`, `mqtt`, `mcp`, `docker`, `self-hosted`, `smart-home`.
- Issues: enabled.
- Discussions: optional but recommended once public support traffic begins; use Q&A for setup/help and Issues for reproducible bugs or focused feature requests.
- Wiki: optional; canonical technical documentation should remain version-controlled under `docs/`.

Do not add a homepage or support link that bypasses the security/redaction guidance in `SECURITY.md`.

## Main branch protection

Prefer a GitHub ruleset targeting `main` with these protections:

- require changes through a pull request;
- require the repository `test` workflow to pass;
- require Home Assistant validation (`hacs` and `hassfest`) for integration/release changes;
- require the branch to be up to date before merge when practical;
- block force pushes;
- block branch deletion;
- require conversation resolution if review threads are used;
- retain administrator bypass only for genuine recovery, not routine releases.

The source release workflow intentionally validates the exact trusted `main` SHA before creating a tag. Branch protection should reinforce that flow, not be bypassed to accelerate a release.

## Tag protection

Prefer a ruleset matching `v*` tags that blocks tag updates and deletion after creation. New tag creation must remain possible for the trusted release workflow.

A release tag is a historical identity. Never move an existing `vX.Y.Z` tag to a new commit to repair a release. Publish a new patch version instead.

## Release immutability

In **Settings → General → Releases**, enable GitHub release immutability for future releases when available for the repository/account.

After publishing a release, verify the release API/UI reports it as immutable. Enabling the setting does not retroactively make older releases immutable, so do not describe an older release as immutable unless GitHub itself reports that state.

## Merge policy

For this single-maintainer repository, squash merge is the preferred default for release/fix PRs because it keeps `main` readable while preserving detailed development history in the PR.

Recommended repository options:

- allow squash merge: on;
- optionally disable merge commits and rebase merges once the workflow is established;
- automatically delete head branches after merge: on;
- allow update branch: on if it fits the required-check workflow;
- auto-merge: optional, but do **not** use it for a PR that still has an external physical-device release gate.

Physical Smart Chime evidence is not represented by GitHub CI, so release PRs that require hardware validation must remain explicitly gated until that evidence is recorded.

## Release procedure

1. Prepare a focused release PR with version, docs, tests, and release workflow aligned.
2. Keep the PR draft while any physical-device release gate is pending.
3. Freeze an exact candidate branch-head SHA.
4. Require the exact-head push CI to pass, including the Docker build with that SHA embedded.
5. Deploy the exact candidate SHA and matching Home Assistant component when hardware validation is required.
6. Record physical PASS/FAIL evidence on the PR without posting credentials, private addresses, device IDs, or private logs.
7. Update release notes/checklist to reflect only evidence actually observed.
8. Mark ready and squash-merge only after all required gates pass.
9. Require trusted `main` CI to pass.
10. Let the release workflow publish the tag at the exact validated `main` SHA.
11. Verify tag target, GitHub release target, application version, HA manifest version, `/version.git_sha`, and OCI image revision agree.
12. Deploy the release tag and repeat the minimal physical smoke test.

See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the release-specific evidence matrix.

## GitHub Actions provenance

Two different SHAs may appear while a PR is open:

- **branch-head SHA** — the exact candidate commit suitable for live candidate deployment;
- **pull-request merge-ref SHA** — GitHub's synthetic merge of the candidate into current `main`, useful for compatibility CI but not the source identity to deploy as the candidate.

Do not substitute the merge-ref SHA for the branch-head SHA in physical validation notes. After merge, the release workflow must use the trusted `main` commit SHA that actually passed the push workflow.

## Public support hygiene

Issue and discussion replies should request only the minimum diagnostic information needed:

- UniFi Announcer semantic version and git SHA;
- Protect version;
- Smart Chime model and firmware;
- sanitized error text/reproduction steps;
- whether the behavior was observed on physical hardware or a fixture/test.

Never request users to post UniFi passwords, API keys, Smart Chime adoption credentials, private addresses, device IDs, certificate material, authentication cookies/tokens, private audio, or unredacted support archives.
