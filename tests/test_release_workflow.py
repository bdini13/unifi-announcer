from pathlib import Path


def test_release_workflow_runs_behavioral_release_script():
    workflow = Path(".github/workflows/release.yml").read_text()
    assert "python scripts/release_v2_1.py" in workflow
    assert 'VALIDATED_SHA="${{ github.event.workflow_run.head_sha }}"' in workflow
    assert "GITHUB_REPOSITORY: ${{ github.repository }}" in workflow
    assert "EXPECTED_VERSION: 2.1.6" in workflow
    assert "Publish v2.1.6 release" in workflow
    assert "test -s docs/RELEASE_NOTES_v2.1.6.md" in workflow
