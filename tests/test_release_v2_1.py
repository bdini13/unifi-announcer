from types import SimpleNamespace

import pytest

from scripts.release_v2_1 import NOTES_FILE, TAG, TITLE, ReleaseError, publish_release

REPOSITORY = "owner/repository"


def test_release_identity_targets_v2_1_6():
    assert TAG == "v2.1.6"
    assert TITLE.startswith("v2.1.6 ")
    assert NOTES_FILE == "docs/RELEASE_NOTES_v2.1.6.md"


class FakeRunner:
    def __init__(
        self,
        *,
        tag_returncode: int,
        release_status: int,
        release_returncode: int | None = None,
        create_returncode: int = 0,
    ):
        self.tag_returncode = tag_returncode
        self.release_status = release_status
        self.release_returncode = (
            0 if release_status == 200 else 1
            if release_returncode is None
            else release_returncode
        )
        self.create_returncode = create_returncode
        self.calls = []

    def __call__(self, command):
        command = tuple(command)
        self.calls.append(command)
        if command[:3] == ("git", "ls-remote", "--exit-code"):
            return SimpleNamespace(
                returncode=self.tag_returncode,
                stdout=(f"f18a180e\trefs/tags/{TAG}\n" if self.tag_returncode == 0 else ""),
                stderr="network failure" if self.tag_returncode not in (0, 2) else "",
            )
        if command[:3] == ("gh", "api", "--include"):
            return SimpleNamespace(
                returncode=self.release_returncode,
                stdout=f"HTTP/2.0 {self.release_status} Status\n\n{{}}\n",
                stderr=("API failure" if self.release_status not in (200, 404) else ""),
            )
        if command[:3] == ("gh", "release", "create"):
            return SimpleNamespace(
                returncode=self.create_returncode,
                stdout="created" if self.create_returncode == 0 else "",
                stderr="creation denied" if self.create_returncode else "",
            )
        raise AssertionError(f"unexpected command: {command}")


def create_command(validated_sha):
    return (
        "gh",
        "release",
        "create",
        TAG,
        "--target",
        validated_sha,
        "--title",
        TITLE,
        "--notes-file",
        NOTES_FILE,
    )


def test_neither_tag_nor_release_creates_exact_release():
    runner = FakeRunner(tag_returncode=2, release_status=404)
    assert publish_release("validated-sha", REPOSITORY, runner=runner) == "created"
    assert runner.calls[-1] == create_command("validated-sha")


def test_existing_tag_and_release_are_left_unchanged():
    runner = FakeRunner(tag_returncode=0, release_status=200)
    assert publish_release("newer-main-sha", REPOSITORY, runner=runner) == "unchanged"
    assert create_command("newer-main-sha") not in runner.calls


def test_tag_without_release_fails_closed():
    runner = FakeRunner(tag_returncode=0, release_status=404)
    with pytest.raises(ReleaseError, match="tag exists without a release"):
        publish_release("validated-sha", REPOSITORY, runner=runner)


def test_release_without_tag_fails_closed():
    runner = FakeRunner(tag_returncode=2, release_status=200)
    with pytest.raises(ReleaseError, match="release exists without a matching remote tag"):
        publish_release("validated-sha", REPOSITORY, runner=runner)


def test_tag_lookup_operational_error_fails_closed():
    runner = FakeRunner(tag_returncode=128, release_status=404)
    with pytest.raises(ReleaseError, match="tag lookup failed: network failure"):
        publish_release("validated-sha", REPOSITORY, runner=runner)
    assert create_command("validated-sha") not in runner.calls


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_release_lookup_operational_http_error_fails_closed(status):
    runner = FakeRunner(tag_returncode=2, release_status=status)
    with pytest.raises(ReleaseError, match=rf"release lookup failed with HTTP {status}"):
        publish_release("validated-sha", REPOSITORY, runner=runner)
    assert create_command("validated-sha") not in runner.calls


def test_release_lookup_without_http_status_fails_closed():
    def runner(command):
        if command[:3] == ["git", "ls-remote", "--exit-code"]:
            return SimpleNamespace(returncode=2, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="transport failed")

    with pytest.raises(ReleaseError, match="returned no HTTP status: transport failed"):
        publish_release("validated-sha", REPOSITORY, runner=runner)


def test_create_failure_reports_stderr():
    runner = FakeRunner(
        tag_returncode=2,
        release_status=404,
        create_returncode=1,
    )
    with pytest.raises(ReleaseError, match="release creation failed: creation denied"):
        publish_release("validated-sha", REPOSITORY, runner=runner)
