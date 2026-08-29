from pathlib import Path

import yaml


def test_compose_uses_named_volume_for_writable_default_data():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    mount = compose["services"]["unifi-announcer"]["volumes"][0]
    assert mount == "unifi-announcer-data:/data"
    assert compose["volumes"]["unifi-announcer-data"]["name"] == "unifi-announcer-data"


def test_readme_uses_immutable_release_checkout_and_valid_auth_example():
    readme = Path("README.md").read_text()
    assert "git checkout v2.1.0" in readme
    assert 'AUTH=(-H "X-API-Key: $UNIFI_ANNOUNCER_API_KEY")' in readme
    assert "$UNIFI..." not in readme


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


def test_source_comments_match_the_configured_credential_providers():
    source = Path("app/main.py").read_text()
    assert "We read it once via the NVR API bootstrap" not in source
    assert "We fetch it lazily through the NVR client" not in source
    assert "see README \"Direct device API\" for" not in source


def test_readme_documents_backup_and_rollback_for_named_volume():
    readme = Path("README.md").read_text()
    rollback = readme.split("## Roll back", 1)[1].split("## Troubleshooting", 1)[0]
    assert "docker compose stop unifi-announcer" in rollback
    assert "unifi-announcer-data" in rollback
    assert "backup" in rollback.lower()
    assert "git checkout <previous-tag>" in rollback
    assert "restore" in rollback.lower()
    assert "track_registry.json" in rollback
