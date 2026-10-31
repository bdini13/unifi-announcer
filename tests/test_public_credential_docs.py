from pathlib import Path


def test_public_credential_guide_is_safe_and_discoverable():
    guide = Path("CREDENTIALS.md").read_text()
    env_example = Path(".env.example").read_text()
    security = Path("SECURITY.md").read_text()
    compatibility = Path("docs/COMPATIBILITY.md").read_text()
    checklist = Path("docs/RELEASE_CHECKLIST.md").read_text()

    assert "Protect `7.2.105`" in guide
    assert "Manual Recovery → Reveal" in guide
    assert "GET /devices/password/{deviceType}/{deviceId}" in guide
    assert "Edit" in guide
    assert "PATCH" in guide
    assert "exactly matched the already known working `CHIME_DIRECT_PASSWORD`" in guide
    assert "returned `HTTP 200`" in guide
    assert "incorrectly captured UI text" in guide
    assert "/api/info" in guide
    assert "getpass.getpass" in guide
    assert "export CHIME_DEVICE_PASSWORD" not in guide
    assert "does **not** retrieve" in guide
    assert 'AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")' in guide
    assert "SSH" in guide
    assert "database" in guide
    assert "backup" in guide

    assert "Manual Recovery -> Reveal" in env_example
    assert "Do not click Edit" in env_example
    assert "See CREDENTIALS.md" in env_example
    assert "CREDENTIALS.md" in security
    assert "Manual Recovery → Reveal" in security
    assert "Use **Reveal**, not **Edit**" in security
    assert "CREDENTIALS.md" in compatibility
    assert "Manual Recovery → Reveal" in compatibility
    assert "returned **HTTP 200**" in compatibility
    assert "incorrectly captured UI text" in compatibility
    assert "Manual Recovery → Reveal" in checklist
    assert "Use Reveal, not Edit" in checklist


def test_public_credential_guide_does_not_publish_extraction_workarounds():
    guide = Path("CREDENTIALS.md").read_text().lower()

    assert "query protect's internal database" in guide
    assert "scrape backups" in guide
    assert "not supported by this project" in guide
    assert "psql -u" not in guide
    assert "devicepassword\" from" not in guide


def test_bug_report_collects_safe_credential_and_lifecycle_diagnostics():
    template = Path(".github/ISSUE_TEMPLATE/bug_report.yml").read_text()

    assert "placeholder: v2.1.8" in template
    assert "id: tts_mode" in template
    assert "id: credential_check" in template
    assert "Manual Recovery → Reveal" in template
    assert "Use Reveal, not Edit" in template
    assert "Reveal available; /api/info returned HTTP 200" in template
    assert "Reveal available; /api/info returned HTTP 401" in template
    assert "Never paste the revealed credential" in template
    assert "CREDENTIALS.md" in template
    assert "id: lifecycle_context" in template
    assert "Smart Chime rebooted or lost power" in template
    assert "Protect reported a Chime disconnect/reconnect" in template
    assert "id: slot_status" in template
    assert "content hit/miss" in template
