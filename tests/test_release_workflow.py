from pathlib import Path


def test_release_workflow_runs_behavioral_release_script():
    workflow = Path(".github/workflows/release-v2.1-beta.yml").read_text()
    assert "python scripts/release_v2_1.py" in workflow
    assert 'VALIDATED_SHA="${{ github.event.workflow_run.head_sha }}"' in workflow
    assert "GITHUB_REPOSITORY: ${{ github.repository }}" in workflow
