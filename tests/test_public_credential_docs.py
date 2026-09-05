from pathlib import Path


def test_public_credential_guide_is_safe_and_discoverable():
    guide = Path("CREDENTIALS.md").read_text()
    env_example = Path(".env.example").read_text()
    security = Path("SECURITY.md").read_text()
    compatibility = Path("docs/COMPATIBILITY.md").read_text()

    assert "Protect `7.2.105`" in guide
    assert "no Device Password or equivalent" in guide
    assert "not validated for Protect 7.2.105" in guide
    assert "/api/info" in guide
    assert "getpass.getpass" in guide
    assert "export CHIME_DEVICE_PASSWORD" not in guide
    assert "Recovery Code" in guide
    assert "not assumed to be interchangeable" in guide
    assert "does **not** retrieve" in guide
    assert 'AUTH=(-H "X-API-Key: ${UNIFI_ANNOUNCER_API_KEY}")' in guide

    assert "Protect 7.2.105 did not expose Device Password" in env_example
    assert "See CREDENTIALS.md" in env_example
    assert "does not support SSH/database extraction as onboarding" in env_example
    assert "CREDENTIALS.md" in security
    assert "Protect `7.2.105` found no Device Password" in security
    assert "CREDENTIALS.md" in compatibility
    assert "no Device Password or equivalent field" in compatibility


def test_public_credential_guide_does_not_publish_extraction_workarounds():
    guide = Path("CREDENTIALS.md").read_text().lower()

    assert "query protect's internal database" in guide
    assert "scrape backups" in guide
    assert "not supported by this project" in guide
    assert "psql -u" not in guide
    assert "devicepassword\" from" not in guide


def test_bug_report_collects_safe_credential_diagnostics():
    template = Path(".github/ISSUE_TEMPLATE/bug_report.yml").read_text()

    assert "placeholder: v2.1.6" in template
    assert "id: tts_mode" in template
    assert "id: credential_check" in template
    assert "HTTP 200" in template
    assert "HTTP 401" in template
    assert "I do not already possess a credential" in template
    assert "Protect 7.2.105 may not expose a Device Password" in template
    assert "Never paste the credential" in template
    assert "CREDENTIALS.md" in template


def test_v2_1_6_release_gate_is_recorded_as_passed():
    checklist = Path("docs/RELEASE_CHECKLIST.md").read_text()
    notes = Path("docs/RELEASE_NOTES_v2.1.6.md").read_text()

    assert "## v2.1.6 release gate — PASS" in checklist
    assert "PR #23" in checklist
    assert "- [x] The expected announcement is audible on the physical Smart Chime." in checklist
    assert "- [x] Protect `play-speaker` returns HTTP 200 for the same request." in checklist
    assert "passed before merge and publication" in notes
    assert "canonical post-publication verification record" in notes
    assert "must not be published until" not in notes


def test_future_release_process_rejects_stale_gate_language():
    checklist = Path("docs/RELEASE_CHECKLIST.md").read_text()

    assert "contain no unresolved future-tense blocker" in checklist
    assert "must not be published until" in checklist
