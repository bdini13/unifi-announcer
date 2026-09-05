from pathlib import Path

import yaml


def test_v2_1_7_publisher_is_present_until_release_completes():
    workflow = yaml.safe_load(Path(".github/workflows/release.yml").read_text())
    jobs = workflow["jobs"]
    validate = jobs["validate"]
    publish = jobs["publish"]

    assert set(jobs) == {"validate", "publish"}
    assert workflow["permissions"] == {"contents": "read"}
    assert validate.get("permissions") is None
    assert publish["permissions"] == {"contents": "write"}
    assert all(
        job.get("permissions") != {"contents": "write"}
        for name, job in jobs.items()
        if name != "publish"
    )
    assert publish["needs"] == "validate"

    validate_steps = validate["steps"]
    publish_steps = publish["steps"]
    validate_actions = [step.get("uses", "") for step in validate_steps]
    publish_actions = [step.get("uses", "") for step in publish_steps]
    assert any(action.startswith("hacs/action@") for action in validate_actions)
    assert any(
        action.startswith("home-assistant/actions/hassfest@")
        for action in validate_actions
    )
    assert not any(action.startswith("hacs/action@") for action in publish_actions)
    assert not any(
        action.startswith("home-assistant/actions/hassfest@")
        for action in publish_actions
    )

    checkouts = [
        step
        for step in validate_steps + publish_steps
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkouts) == 2
    for checkout in checkouts:
        assert checkout["with"]["ref"] == "${{ github.event.workflow_run.head_sha }}"
        assert checkout["with"]["persist-credentials"] is False

    publish_step = next(
        step for step in publish_steps if step.get("name") == "Publish v2.1.7 release"
    )
    assert publish_step["env"]["EXPECTED_VERSION"] == "2.1.7"
    assert (
        publish_step["env"]["VALIDATED_SHA"]
        == "${{ github.event.workflow_run.head_sha }}"
    )
    script_lines = [
        line.strip()
        for line in publish_step["run"].splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert script_lines == [
        "set -euo pipefail",
        'test "$(git rev-parse HEAD)" = "$VALIDATED_SHA"',
        'test "$(python -c \'from app.version import APP_VERSION; print(APP_VERSION)\')" = "$EXPECTED_VERSION"',
        'test "$(git show HEAD^:app/version.py | python -c \'import re, sys; print(re.search(r"APP_VERSION = \\"([^\\"]+)\\"", sys.stdin.read()).group(1))\')" = "2.1.6"',
        'test "$(python -c \'import json; print(json.load(open("custom_components/unifi_announcer/manifest.json"))["version"])\')" = "$EXPECTED_VERSION"',
        'test "$(python -c \'import ast; tree=ast.parse(open("custom_components/unifi_announcer/const.py").read()); print(next(node.value.value for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "INTEGRATION_VERSION" for target in node.targets)))\')" = "$EXPECTED_VERSION"',
        "test -s docs/RELEASE_NOTES_v2.1.7.md",
        "python scripts/release_v2_1.py",
    ]


def test_maintainer_guide_requires_retiring_fixed_publishers():
    guide = Path("docs/MAINTAINERS.md").read_text()
    assert "retire any completed version-specific automatic publishing workflow" in guide
    assert "ordinary post-release `main` commits" in guide
    assert "new release PR" in guide
