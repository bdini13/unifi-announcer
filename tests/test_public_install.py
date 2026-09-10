from pathlib import Path


def test_compose_uses_named_volume_for_writable_default_data():
    compose = Path("docker-compose.yml").read_text()
    assert "- ${DATA_PATH:-unifi-announcer-data}:/data" in compose
    assert "name: unifi-announcer-data" not in compose
    assert "${DATA_PATH:-./data}:/data" not in compose
    assert "watchtower.enable" not in compose.lower()


def test_readme_keeps_stable_install_and_identifies_published_beta():
    readme = Path("README.md").read_text()
    stable_clone = readme.split(
        "### 1. Clone the stable release and create private configuration", 1
    )[1].split("### 2. Start the service", 1)[0]
    ha_setup = readme.split("## Home Assistant — recommended setup", 1)[1].split(
        "### Standard announcement", 1
    )[0]
    assert "git checkout v2.1.8" in stable_clone
    assert "v2.2.0-beta.1" not in stable_clone
    assert "Select the latest stable release" in ha_setup
    assert "img.shields.io/github/v/release/bdini13/unifi-announcer" in readme
    assert "releases/latest" in readme
    assert "**Stable:** `v2.1.8`" in readme
    assert "**Prerelease:** `v2.2.0-beta.3`" in readme
    assert "**Previous prerelease:** `v2.2.0-beta.2`" in readme
    assert "**Release candidate:** `v2.2.0-beta.3`" not in readme
    assert "physically validated on one UVC G3 Instant" in readme
    assert 'AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")' in readme
    assert "$UNIFI..." not in readme
    assert "scheduled for `v2.1.1`" not in readme
    assert "**Next release:** `v2.1.1`" not in readme
    assert Path("docs/RELEASE_NOTES_v2.1.8.md").exists()
    assert Path("docs/RELEASE_NOTES_v2.2.0-beta.2.md").exists()
    assert Path("docs/validation/v2.1.8-live-latency-validation.md").exists()
    checklist = Path("docs/RELEASE_CHECKLIST.md").read_text()
    assert "## v2.1.8 release gate" in checklist


def test_quick_start_handles_secrets_and_temporary_login_safely():
    readme = Path("README.md").read_text()
    quick_start = readme.split("### 2. Start the service", 1)[0]
    assert "install -m 600 .env.example .env" in quick_start
    assert 'read -r -s -p "Local UniFi password: " UNIFI_PASSWORD' in quick_start
    assert 'COOKIE_JAR="$(mktemp)"' in quick_start
    assert "--data-binary @-" in quick_start
    assert "export UNIFI_USERNAME UNIFI_PASSWORD" in quick_start
    assert 'rm -f "$COOKIE_JAR"' in quick_start
    assert "trap - EXIT" in quick_start
    assert "unset UNIFI_USERNAME UNIFI_PASSWORD" in quick_start
    assert "chmod 600 .env" in quick_start


def test_documented_builds_embed_source_revision():
    readme = Path("README.md").read_text()
    dockerfile = Path("Dockerfile").read_text()
    compose = Path("docker-compose.yml").read_text()
    assert 'export GIT_SHA="$(git rev-parse HEAD)"' in readme
    assert "GIT_SHA: ${GIT_SHA:-unknown}" in compose
    assert "ARG GIT_SHA=unknown" in dockerfile
    assert 'org.opencontainers.image.revision="${GIT_SHA}"' in dockerfile
    assert "git_sha: unknown" in readme


def test_readme_documents_bind_mount_ownership_when_data_path_is_used():
    readme = Path("README.md").read_text()
    assert "sudo chown -R 1000:1000 /srv/unifi-announcer/data" in readme


def test_public_docs_document_supported_credential_onboarding():
    readme = Path("README.md").read_text()
    env_example = Path(".env.example").read_text()
    assert "Arbitrary text announcements | ✅ Supported" in readme
    assert "does **not** retrieve the credential automatically" in readme
    assert "Manual Recovery → Reveal" in readme
    assert "Do **not** click **Edit**" in readme
    assert "fresh install cannot bootstrap" not in readme
    assert "no Device Password or equivalent field" not in readme
    assert "[Smart Chime credential setup](CREDENTIALS.md)" in readme
    quick_start = readme.split("### 2. Start the service", 1)[0]
    assert "\nCHIME_DIRECT_PASSWORD=<revealed-and-verified-device-password>" not in quick_start
    assert "# CHIME_DIRECT_PASSWORD=<revealed-and-verified-device-password>" in quick_start
    assert "# CHIME_CREDENTIAL_FILE=/run/secrets/unifi_chime_password" in quick_start
    assert "TTS_ENGINE=none" in readme
    assert "CHIME_DIRECT_PASSWORD=" in env_example
    assert "CHIME_CREDENTIAL_FILE" in env_example
    assert "Manual Recovery -> Reveal" in env_example
    assert "Do not click Edit" in env_example


def test_readme_top_callouts_are_focused_on_runtime_risks():
    readme = Path("README.md").read_text()
    intro = readme.split("## Why this exists", 1)[0]
    assert "> [!IMPORTANT]" in intro
    assert "> [!CAUTION]" in intro
    assert "> [!NOTE]" not in intro
    assert "undocumented UniFi Protect and Smart Chime interfaces" in intro
    assert "CHIME_DIRECT_PASSWORD" in intro
    assert "CHIME_CREDENTIAL_FILE" in intro
    assert "Protect `7.2.105`" in intro
    assert "firmware `1.7.20`" in intro
    assert "Manual Recovery → Reveal" in intro
    assert "CREDENTIALS.md" in intro


def test_readme_documents_v2_1_8_resident_reuse_and_boot_safety():
    readme = Path("README.md").read_text()
    env_example = Path(".env.example").read_text()
    assert "Content-aware resident TTS reuse | ✅ v2.1.8" in readme
    assert "Smart Chime reboot/reconnect invalidation | ✅ v2.1.8" in readme
    assert "boot epoch" in readme
    assert "direct-device uptime" in readme
    assert "write-ahead invalidation" in readme
    assert "TTS_SLOT_BOOT_EPOCH_TOLERANCE" in readme
    assert "TTS_SLOT_BOOT_EPOCH_TOLERANCE=5.0" in env_example
    assert "v2.1.8 candidate" not in env_example


def test_readme_latency_claims_remain_bounded_to_request_path():
    readme = Path("README.md").read_text()
    assert "## Observed v2.1.8 latency" in readme
    assert "p95:     663 ms" in readme
    assert "request round-trip measurements" in readme
    assert "not synchronized microphone/acoustic-onset measurements" in readme
    assert "does not claim measured acoustic latency" in readme


def test_hacs_docs_make_backend_requirement_explicit():
    readme = Path("README.md").read_text()
    ha_docs = Path("docs/HOME_ASSISTANT.md").read_text()
    assert "HACS integration is a client for the Docker service" in readme
    assert "HACS integration is a **client for the UniFi Announcer Docker service**" in ha_docs
    assert "HACS does not replace or run the backend" in readme


def test_ha_docs_define_immediate_playback_result_semantics():
    readme = Path("README.md").read_text()
    ha_docs = Path("docs/HOME_ASSISTANT.md").read_text()
    assert "Last playback result" in readme
    assert "Last playback result" in ha_docs
    assert "`success`" in ha_docs
    assert "`failure`" in ha_docs
    assert "updates it immediately" in ha_docs
    assert "stale Protect inventory" in ha_docs


def test_source_comments_match_the_configured_credential_providers():
    source = Path("app/main.py").read_text()
    assert "We read it once via the NVR API bootstrap" not in source
    assert "We fetch it lazily through the NVR client" not in source
    assert "see README \"Direct device API\" for" not in source


def test_readme_documents_backup_and_rollback_for_named_volume():
    readme = Path("README.md").read_text()
    rollback = readme.split("## Roll back", 1)[1].split("## Troubleshooting", 1)[0]
    assert "docker compose stop unifi-announcer" in rollback
    assert "DATA_SOURCE" in rollback
    assert "backup" in rollback.lower()
    assert "umask 077" in rollback
    assert "tar -tzf" in rollback
    assert "sha256sum" in rollback
    assert "restore-test" in rollback
    assert "git checkout <previous-tag>" in rollback


def test_public_configuration_fails_closed_without_api_key():
    readme = Path("README.md").read_text()
    env_example = Path(".env.example").read_text()
    assert "`APP_API_KEY` is required" in readme
    assert "APP_API_KEY=REPLACE_ME" in env_example
    assert "If APP_API_KEY is configured" not in readme
    assert "REPLACE_ME" in env_example
    assert "backups/" in Path(".gitignore").read_text()
    assert "chmod 600" in readme


def test_upgrade_docs_preserve_legacy_default_bind_data_and_v218_state():
    readme = Path("README.md").read_text()
    assert "## Upgrade to v2.1.8" in readme
    assert "./data" in readme
    assert "DATA_PATH=./data" in readme
    assert "docker compose config" in readme
    assert "track_registry.json" in readme
    assert "dynamic_tts_slots.json" in readme
    assert "dynamic_tts_content_state.json" in readme
    assert "installation.json" in readme
    assert "No manual data migration is required from v2.1.7" in readme


def test_release_identity_is_v2_2_0_beta_3():
    assert 'APP_VERSION = "2.2.0-beta.3"' in Path("app/version.py").read_text()
    assert 'INTEGRATION_VERSION = "2.2.0-beta.3"' in Path(
        "custom_components/unifi_announcer/const.py"
    ).read_text()
    assert '"version": "2.2.0-beta.3"' in Path(
        "custom_components/unifi_announcer/manifest.json"
    ).read_text()


def test_beta1_release_notes_preserve_historical_physical_boundary():
    notes = Path("docs/RELEASE_NOTES_v2.2.0-beta.1.md").read_text()
    checklist = Path("docs/RELEASE_CHECKLIST.md").read_text()
    assert "Integrated audible camera playback was physically confirmed" in notes
    assert "one G3 Instant" in notes
    assert "does not authorize merge, tagging, publication" in notes
    assert "stable promotion" in notes
    assert "Opus/RTP" in notes
    assert "deliberately unavailable camera prevents mixed-group Chime playback" in notes
    assert Path(
        "docs/validation/v2.2.0-beta.1-g3-instant-camera-validation.md"
    ).exists()
    assert "no tag, github release, image publication, deployment, or audible test" in notes.lower()
    assert "must remain draft" in notes
    assert "No publisher exists by default" in checklist


def test_beta2_release_docs_record_publication_and_tagged_smoke_gate():
    notes = Path("docs/RELEASE_NOTES_v2.2.0-beta.2.md").read_text()
    validation = Path(
        "docs/validation/v2.2.0-beta.2-camera-hardening-validation.md"
    ).read_text()
    assert "v2.2.0-beta.2" in notes
    assert "Stable `v2.1.8` remains the recommended public release" in notes
    assert "UVC G3 Instant" in notes
    assert "22,050 Hz" in notes
    assert "per-camera preparation lease" in notes
    assert "Physical validation completed before publication" in notes
    assert "9d8e8f845201cf8de1223cc7d5fc31c192194a5d" in notes
    assert "published prerelease" in notes
    assert "RESULT: PASS" in validation
    assert "not empirically executed" in validation
    assert "offline → online" in validation
    assert "Same-camera concurrency/session serialization" in validation
    assert "Tagged release and deployment smoke test" in validation
    assert "volume 50" in validation


def test_beta3_candidate_docs_preserve_opt_in_and_physical_gate():
    readme = Path("README.md").read_text()
    env_example = Path(".env.example").read_text()
    notes = Path("docs/RELEASE_NOTES_v2.2.0-beta.3.md").read_text()
    checklist = Path("docs/RELEASE_CHECKLIST.md").read_text()
    validation = Path(
        "docs/validation/v2.2.0-beta.3-g4-instant-validation.md"
    ).read_text()

    roadmap = Path("ROADMAP.md").read_text()
    compatibility = Path("docs/COMPATIBILITY.md").read_text()
    ha_docs = Path("docs/HOME_ASSISTANT.md").read_text()
    post_release = Path("docs/POST_RELEASE.md").read_text()

    assert "**Prerelease:** `v2.2.0-beta.3`" in readme
    assert "**Previous prerelease:** `v2.2.0-beta.2`" in readme
    assert "EXPERIMENTAL_CAMERA_PROFILES=[]" in env_example
    assert "empty by default" in notes
    assert "experimental_opt_in" in notes
    assert "Published prerelease `v2.2.0-beta.3`" in notes
    assert "76fca7f25a8f3b43e73ffd0432d97e5ec3995ce4" in notes
    assert "G4 Instant" in validation
    assert "RESULT: PASS" in validation
    assert "device speaker volume `100`" in validation
    assert "No automatic retry was sent" in validation
    assert "representative G4 Instant only" in validation
    assert "do not promote beta.3 to stable" in validation
    assert "TAGGED RELEASE DEPLOYMENT: PASS" in validation
    assert "sha256:46b1af0a5a96a9b93d0c08884b7f07a6a669a59ac170cc713ee2173837dc1966" in validation
    assert "Tagged release publication and deployment" in checklist
    assert "Draft candidate `v2.2.0-beta.3`" not in roadmap
    assert "Draft beta.3" not in compatibility
    assert "Draft beta.3" not in ha_docs
    assert "latest published camera prerelease" not in notes
    assert "Current published prerelease: **v2.2.0-beta.2**" not in roadmap
    assert "next representative target is an opt-in G4 Instant" not in roadmap
    assert "`v2.2.0-beta.2` is the current published prerelease" not in compatibility
    assert "`v2.2.0-beta.3` is the current experimental camera-speaker release" in post_release
    assert "`v2.2.0-beta.2` is the current experimental camera-speaker release" not in post_release
    assert "Candidate-validation deployed prerelease rollback target at that time" in validation
    assert "Protect camera-speaker TTS | 🧪 `v2.2.0-beta.3`" in readme
    assert "`v2.2.0-beta.2` is published" not in readme
    assert "v2.2.0-beta.3 candidate notes" not in readme
    assert "v2.2.0-beta.3 G4 Instant validation plan" not in readme
    assert "Example beta.3 candidate opt-in" not in env_example
    assert "no G4 audio has been played" not in readme
    assert "Until that gate is completed" not in notes
    assert "PARTIAL PHYSICAL VALIDATION" not in checklist
    assert "Sanitized partial evidence" not in checklist
    assert "Physical gate — PARTIAL" not in validation


def test_fastapi_metadata_uses_release_identity(main_module):
    from app.version import APP_VERSION

    assert main_module.app.version == APP_VERSION


def test_stable_claims_disclose_physical_validation_boundary():
    readme = Path("README.md").read_text()
    release_notes = Path("docs/RELEASE_NOTES_v2.1.8.md").read_text()
    assert "Multiple chimes and named groups | 🧪" in readme
    assert "physically exercised on **one** Smart Chime" in readme
    assert "100-unique-message **automated** regression" in readme
    assert "Multi-Chime/group playback has **not** been physically validated" in readme
    assert "Physical validation covered one Smart Chime" in release_notes
    assert "No synchronized microphone benchmark" in release_notes


def test_community_health_and_support_files_exist():
    required = [
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/pull_request_template.md",
    ]
    for name in required:
        assert Path(name).is_file(), name
    readme = Path("README.md").read_text()
    assert "## Support and security" in readme
    assert "SECURITY.md" in readme


def test_v2_1_1_notes_carry_the_home_assistant_correction():
    notes = Path("docs/RELEASE_NOTES_v2.1.1.md").read_text()
    assert "pytest-homeassistant-custom-component" in notes
    assert "incorrectly" in notes
    assert "unavailable until that version is published" not in notes


def test_protected_diagnostic_examples_send_api_key():
    docs = [
        Path("README.md").read_text(),
        Path("docs/HOME_ASSISTANT.md").read_text(),
        Path("docs/MCP.md").read_text(),
    ]
    for text in docs:
        for line in text.splitlines():
            if line.startswith("curl -fsS") and (
                "/tts/slots/status" in line or "/tts/cache/status" in line
            ):
                assert '"${AUTH[@]}"' in line
    combined = "\n".join(docs)
    assert 'AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")' in combined


def test_readme_standalone_verification_blocks_define_auth_locally():
    readme = Path("README.md").read_text()
    quick = readme.split("Verify health, version, and fixed-slot readiness:", 1)[1]
    quick = quick.split("```", 2)[1]
    upgrade = readme.split("Then verify:", 1)[1].split("```", 2)[1]
    for block in (quick, upgrade):
        assert 'export UNIFI_ANNOUNCER_API_KEY="<your-api-key>"' in block
        assert 'AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")' in block
        assert block.index("AUTH=(-H") < block.index("/tts/slots/status")
