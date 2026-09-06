from types import SimpleNamespace

import pytest

from scripts.release_v2_1_8 import (
    NOTES_FILE,
    TAG,
    TITLE,
    ReleaseError,
    publish_release,
)

REPOSITORY = "owner/repository"
VALIDATED_SHA = "1" * 40


def test_release_identity_targets_v2_1_8():
    assert TAG == "v2.1.8"
    assert TITLE.startswith("v2.1.8 ")
    assert NOTES_FILE == "docs/RELEASE_NOTES_v2.1.8.md"


class FakeRunner:
    def __init__(
        self,
        *,
        tag_returncode: int,
        release_status: int,
        release_returncode: int | None = None,
        push_returncode: int = 0,
        initial_tag_sha: str = VALIDATED_SHA,
        initial_tag_output: str | None = None,
        post_push_sha: str | None = None,
        final_tag_sha: str | None = None,
        post_push_output: str | None = None,
        final_release_status: int = 200,
        create_returncode: int = 0,
    ):
        self.tag_returncode = tag_returncode
        self.release_status = release_status
        self.release_returncode = (
            0
            if release_status == 200
            else 1
            if release_returncode is None
            else release_returncode
        )
        self.push_returncode = push_returncode
        self.initial_tag_sha = initial_tag_sha
        self.initial_tag_output = initial_tag_output
        self.post_push_sha = post_push_sha
        self.final_tag_sha = final_tag_sha
        self.post_push_output = post_push_output
        self.final_release_status = final_release_status
        self.create_returncode = create_returncode
        self.calls = []
        self.tag_checks = 0
        self.release_checks = 0
        self.pushed_sha = None
        self.release_created = False

    def __call__(self, command):
        command = tuple(command)
        self.calls.append(command)
        if command[:3] == ("git", "ls-remote", "--exit-code"):
            self.tag_checks += 1
            if self.tag_checks == 1:
                output = self.initial_tag_output
                if output is None:
                    output = (
                        f"{self.initial_tag_sha}\trefs/tags/{TAG}\n"
                        if self.tag_returncode == 0
                        else ""
                    )
                return SimpleNamespace(
                    returncode=self.tag_returncode,
                    stdout=output,
                    stderr=(
                        "network failure"
                        if self.tag_returncode not in (0, 2)
                        else ""
                    ),
                )
            output = self.post_push_output
            if output is None:
                sha = (
                    self.final_tag_sha
                    if self.tag_checks >= 3 and self.final_tag_sha is not None
                    else self.post_push_sha or self.pushed_sha
                )
                output = f"{sha}\trefs/tags/{TAG}\n"
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        if command[:4] == ("gh", "api", "--method", "POST"):
            self.pushed_sha = command[-1].split("=", 1)[1]
            return SimpleNamespace(
                returncode=self.push_returncode,
                stdout="tag created" if self.push_returncode == 0 else "",
                stderr="tag conflict" if self.push_returncode else "",
            )
        if command[:3] == ("gh", "api", "--include"):
            self.release_checks += 1
            status = (
                self.final_release_status if self.release_created else self.release_status
            )
            returncode = (
                0
                if self.release_created and status == 200
                else self.release_returncode
            )
            return SimpleNamespace(
                returncode=returncode,
                stdout=f"HTTP/2.0 {status} Status\n\n{{}}\n",
                stderr=("API failure" if status not in (200, 404) else ""),
            )
        if command[:3] == ("gh", "release", "create"):
            self.release_created = self.create_returncode == 0
            return SimpleNamespace(
                returncode=self.create_returncode,
                stdout="created" if self.create_returncode == 0 else "",
                stderr="creation denied" if self.create_returncode else "",
            )
        raise AssertionError(f"unexpected command: {command}")


def tag_create_command(validated_sha=VALIDATED_SHA):
    return (
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{REPOSITORY}/git/refs",
        "--field",
        f"ref=refs/tags/{TAG}",
        "--field",
        f"sha={validated_sha}",
    )


def create_command():
    return (
        "gh",
        "release",
        "create",
        TAG,
        "--repo",
        REPOSITORY,
        "--verify-tag",
        "--title",
        TITLE,
        "--notes-file",
        NOTES_FILE,
    )


def test_neither_tag_nor_release_reserves_exact_tag_then_creates_release():
    runner = FakeRunner(tag_returncode=2, release_status=404)
    assert publish_release(VALIDATED_SHA, REPOSITORY, runner=runner) == "created"
    assert tag_create_command() in runner.calls
    assert create_command() in runner.calls
    assert "--target" not in create_command()
    assert runner.tag_checks == 3
    assert runner.release_checks == 2


def test_existing_tag_and_release_are_left_unchanged():
    runner = FakeRunner(tag_returncode=0, release_status=200)
    assert publish_release(VALIDATED_SHA, REPOSITORY, runner=runner) == "unchanged"
    assert tag_create_command() not in runner.calls
    assert create_command() not in runner.calls


def test_existing_tag_and_release_at_wrong_sha_fail_closed():
    runner = FakeRunner(
        tag_returncode=0,
        release_status=200,
        initial_tag_sha="2" * 40,
    )
    with pytest.raises(ReleaseError, match="existing tag does not match validated SHA"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)


def test_existing_annotated_tag_resolves_to_validated_commit():
    runner = FakeRunner(
        tag_returncode=0,
        release_status=200,
        initial_tag_output=(
            f"{'a' * 40}\trefs/tags/{TAG}\n"
            f"{VALIDATED_SHA}\trefs/tags/{TAG}^{{}}\n"
        ),
    )
    assert publish_release(VALIDATED_SHA, REPOSITORY, runner=runner) == "unchanged"


def test_tag_without_release_fails_closed():
    runner = FakeRunner(tag_returncode=0, release_status=404)
    with pytest.raises(ReleaseError, match="tag exists without a release"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)
    assert tag_create_command() not in runner.calls


def test_release_without_tag_fails_closed():
    runner = FakeRunner(tag_returncode=2, release_status=200)
    with pytest.raises(ReleaseError, match="release exists without a matching remote tag"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)
    assert tag_create_command() not in runner.calls


def test_tag_lookup_operational_error_fails_closed():
    runner = FakeRunner(tag_returncode=128, release_status=404)
    with pytest.raises(ReleaseError, match="tag lookup failed: network failure"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)
    assert tag_create_command() not in runner.calls


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_release_lookup_operational_http_error_fails_closed(status):
    runner = FakeRunner(tag_returncode=2, release_status=status)
    with pytest.raises(ReleaseError, match=rf"release lookup failed with HTTP {status}"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)
    assert tag_create_command() not in runner.calls


def test_release_lookup_without_http_status_fails_closed():
    def runner(command):
        if command[:3] == ["git", "ls-remote", "--exit-code"]:
            return SimpleNamespace(returncode=2, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="transport failed")

    with pytest.raises(ReleaseError, match="returned no HTTP status: transport failed"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)


def test_atomic_tag_creation_conflict_fails_before_release_creation():
    runner = FakeRunner(
        tag_returncode=2,
        release_status=404,
        push_returncode=1,
    )
    with pytest.raises(ReleaseError, match="atomic tag creation failed: tag conflict"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)
    assert create_command() not in runner.calls


def test_post_push_remote_tag_must_match_validated_sha():
    runner = FakeRunner(
        tag_returncode=2,
        release_status=404,
        post_push_sha="2" * 40,
    )
    with pytest.raises(ReleaseError, match="remote tag does not match validated SHA"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)
    assert create_command() not in runner.calls


def test_post_push_tag_verification_must_be_unambiguous():
    runner = FakeRunner(
        tag_returncode=2,
        release_status=404,
        post_push_output="",
    )
    with pytest.raises(ReleaseError, match="tag verification failed"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)
    assert create_command() not in runner.calls


def test_post_release_tag_is_verified_again():
    runner = FakeRunner(
        tag_returncode=2,
        release_status=404,
        final_tag_sha="2" * 40,
    )
    with pytest.raises(ReleaseError, match="post-release tag does not match"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)


def test_post_release_api_must_confirm_release_exists():
    runner = FakeRunner(
        tag_returncode=2,
        release_status=404,
        final_release_status=404,
    )
    with pytest.raises(ReleaseError, match="release missing after successful creation"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)


def test_create_failure_reports_stderr():
    runner = FakeRunner(
        tag_returncode=2,
        release_status=404,
        create_returncode=1,
    )
    with pytest.raises(ReleaseError, match="release creation failed: creation denied"):
        publish_release(VALIDATED_SHA, REPOSITORY, runner=runner)
