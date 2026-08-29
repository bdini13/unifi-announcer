from pathlib import Path

import yaml


def test_compose_uses_named_volume_for_writable_default_data():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    mount = compose["services"]["unifi-announcer"]["volumes"][0]
    assert mount == "unifi-announcer-data:/data"
    assert compose["volumes"]["unifi-announcer-data"] is None


def test_readme_uses_immutable_release_checkout_and_valid_auth_example():
    readme = Path("README.md").read_text()
    assert "git checkout v2.1.0" in readme
    assert 'AUTH=(-H "X-API-Key: $UNIFI_ANNOUNCER_API_KEY")' in readme
    assert "$UNIFI..." not in readme


def test_readme_documents_bind_mount_ownership_when_data_path_is_used():
    readme = Path("README.md").read_text()
    assert "sudo chown -R 1000:1000 /srv/unifi-announcer/data" in readme
