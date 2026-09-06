from pathlib import Path


WORKFLOW = Path(".github/workflows/release.yml")


def test_v2_1_8_release_workflow_is_exact_sha_and_transition_bound():
    workflow = WORKFLOW.read_text()
    assert 'ref: ${{ github.event.workflow_run.head_sha }}' in workflow
    assert 'github.event.workflow_run.event == \'push\'' in workflow
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in workflow
    assert 'APP_VERSION; print(APP_VERSION)\')\" = \"2.1.8\"' in workflow
    assert ')\')\" = \"2.1.7\"' in workflow
    assert 'test "$(git rev-parse HEAD)" = "$VALIDATED_SHA"' in workflow


def test_v2_1_8_release_workflow_uses_least_privilege_and_fixed_publisher():
    workflow = WORKFLOW.read_text()
    assert workflow.count("contents: write") == 1
    assert "persist-credentials: false" in workflow
    assert "python scripts/release_v2_1_8.py" in workflow
    assert "python scripts/release_v2_1.py" not in workflow
    assert "gh release create" not in workflow
