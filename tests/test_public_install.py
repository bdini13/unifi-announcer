from pathlib import Path


def test_compose_uses_named_volume_for_writable_default_data():
    compose = Path("docker-compose.yml").read_text()
    assert "- ${DATA_PATH:-unifi-announcer-data}:/data" in compose
    assert "name: unifi-announcer-data" not in compose
    assert "${DATA_PATH:-./data}:/data" not in compose
    assert "watchtower.enable" not in compose.lower()


def test_readme_targets_v2_1_2_and_has_no_stale_launch_banner():
    readme = Path("README.md").read_text()
    assert "git checkout v2.1.2" in readme
    assert "stable-v2.1.2" in readme
    assert "**Stable:** `v2.1.2`" in readme
    assert 'AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")' in readme
    assert "$UNIFI..." not in readme
    assert "scheduled for `v2.1.1`" not in readme
    assert "**Next release:** `v2.1.1`" not in readme
    assert Path("docs/RELEASE_NOTES_v2.1.2.md").exists()


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


def test_readme_documents_bind_mount_ownership_when_data_path_is_used():
    readme = Path("README.md").read_text()
    assert "sudo chown -R 1000:1000 /srv/unifi-announcer/data" in readme


def test_public_docs_do_not_claim_unsupported_credential_onboarding():
    readme = Path("README.md").read_text()
    env_example = Path(".env.example").read_text()
    assert "Make a Smart Chime speak (advanced)" in readme
    assert "Arbitrary text announcements | ⚠️ Advanced" in readme
    assert "There is no supported public retrieval workflow" in readme
    quick_start = readme.split("### 2. Start the service", 1)[0]
    assert "\nCHIME_DIRECT_PASSWORD=<current-device-adoption-credential>" not in quick_start
    assert "# CHIME_DIRECT_PASSWORD=<current-device-adoption-credential>" in quick_start
    assert "TTS_ENGINE=none" in readme
    assert "CHIME_DIRECT_PASSWORD=" in env_example


def test_hacs_docs_make_backend_requirement_explicit():
    readme = Path("README.md").read_text()
    ha_docs = Path("docs/HOME_ASSISTANT.md").read_text()
    assert "HACS integration is a client for the Docker service" in readme
    assert "HACS integration is a **client for the UniFi Announcer Docker service**" in ha_docs
    assert "HACS does not replace or run the backend" in readme


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
    assert "restore" in rollback.lower()
    assert "track_registry.json" in rollback


def test_public_configuration_fails_closed_without_api_key():
    readme = Path("README.md").read_text()
    env_example = Path(".env.example").read_text()
    assert "APP_API_KEY` is required" in readme
    assert "APP_API_KEY=REPLACE_ME" in env_example
    assert "If APP_API_KEY is configured" not in readme
    assert "REPLACE_ME" in env_example
    assert "backups/" in Path(".gitignore").read_text()
    assert "chmod 600" in readme


def test_upgrade_docs_preserve_legacy_default_bind_data():
    readme = Path("README.md").read_text()
    assert "./data" in readme
    assert "DATA_PATH=./data" in readme
    assert "docker compose config" in readme


def test_release_identity_is_v2_1_2():
    assert 'APP_VERSION = "2.1.2"' in Path("app/version.py").read_text()
    assert 'INTEGRATION_VERSION = "2.1.2"' in Path(
        "custom_components/unifi_announcer/const.py"
    ).read_text()
    assert '"version": "2.1.2"' in Path(
        "custom_components/unifi_announcer/manifest.json"
    ).read_text()


def test_stable_claims_disclose_physical_validation_boundary():
    readme = Path("README.md").read_text()
    notes = Path("docs/RELEASE_NOTES_v2.1.0.md").read_text()
    assert "Multiple chimes and named groups | 🧪" in readme
    assert "only one physical Smart Chime" in readme
    assert "100-unique-message live soak" not in readme
    assert "100-unique-message automated regression" in readme
    assert "physical playback matrix" not in notes
    assert "100-unique-message automated regression" in notes
    assert "Multi-chime behavior is covered by automated tests" in notes


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
    assert "## Support" in readme
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
