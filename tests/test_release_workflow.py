from pathlib import Path


def test_existing_stable_tag_does_not_fail_on_later_main_commits():
    workflow = Path(".github/workflows/release-v2.1-beta.yml").read_text()
    assert 'test "$existing_sha" = "${{ github.event.workflow_run.head_sha }}"' not in workflow
    assert 'echo "$TAG already exists at $existing_sha; leaving it unchanged."' in workflow
