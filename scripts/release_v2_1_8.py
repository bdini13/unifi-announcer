"""Idempotently publish the fixed v2.1.8 GitHub release.

The release workflow calls this only after the exact main commit has passed the
core test lane plus HACS and Hassfest validation. Existing tags/releases are
never moved or replaced: inconsistent states fail closed for manual review.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Protocol

TAG = "v2.1.8"
TITLE = "v2.1.8 — Safe resident Smart Chime TTS reuse"
NOTES_FILE = "docs/RELEASE_NOTES_v2.1.8.md"


class Result(Protocol):
    returncode: int
    stdout: str
    stderr: str


class ReleaseError(RuntimeError):
    """Release state is inconsistent or publishing failed."""


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _detail(result: Result) -> str:
    return (result.stderr or result.stdout or "unknown command failure").strip()


def _release_exists(result: Result) -> bool:
    statuses = re.findall(r"^HTTP/\S+\s+(\d{3})\b", result.stdout, re.MULTILINE)
    if not statuses:
        raise ReleaseError(f"{TAG} release lookup returned no HTTP status: {_detail(result)}")
    status = int(statuses[-1])
    if status == 200 and result.returncode == 0:
        return True
    if status == 404:
        return False
    raise ReleaseError(f"{TAG} release lookup failed with HTTP {status}: {_detail(result)}")


def _tag_lookup_command() -> list[str]:
    return [
        "git",
        "ls-remote",
        "--exit-code",
        "--tags",
        "origin",
        f"refs/tags/{TAG}",
        f"refs/tags/{TAG}^{{}}",
    ]


def _tag_sha(result: Result) -> str:
    expected_ref = f"refs/tags/{TAG}"
    dereferenced_ref = f"{expected_ref}^{{}}"
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[1] not in (expected_ref, dereferenced_ref):
            raise ReleaseError(f"{TAG} tag verification returned unexpected output")
        if fields[1] in refs:
            raise ReleaseError(f"{TAG} tag verification returned duplicate refs")
        refs[fields[1]] = fields[0]
    if result.returncode != 0 or expected_ref not in refs:
        raise ReleaseError(f"{TAG} tag verification failed: {_detail(result)}")
    return refs.get(dereferenced_ref, refs[expected_ref])


def publish_release(
    validated_sha: str,
    repository: str,
    *,
    runner: Callable[[Sequence[str]], Result] = _run,
) -> str:
    """Publish exactly ``TAG`` at ``validated_sha`` without mutating old releases."""
    tag = runner(_tag_lookup_command())
    if tag.returncode not in (0, 2):
        raise ReleaseError(f"{TAG} tag lookup failed: {_detail(tag)}")

    release = runner(
        ["gh", "api", "--include", f"repos/{repository}/releases/tags/{TAG}"]
    )
    tag_exists = tag.returncode == 0
    release_exists = _release_exists(release)

    if tag_exists and release_exists:
        if _tag_sha(tag) != validated_sha:
            raise ReleaseError(f"{TAG} existing tag does not match validated SHA")
        print(f"{TAG} already exists; leaving its tag and release unchanged.")
        return "unchanged"
    if tag_exists:
        raise ReleaseError(f"{TAG} tag exists without a release")
    if release_exists:
        raise ReleaseError(f"{TAG} release exists without a matching remote tag")

    # Reserve the immutable tag name through GitHub's atomic create-ref API.
    # A concurrent publisher receives HTTP 422 and publication stops without
    # ever attaching a release to an unverified tag.
    pushed = runner(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repository}/git/refs",
            "--field",
            f"ref=refs/tags/{TAG}",
            "--field",
            f"sha={validated_sha}",
        ]
    )
    if pushed.returncode != 0:
        raise ReleaseError(f"{TAG} atomic tag creation failed: {_detail(pushed)}")

    verified = runner(_tag_lookup_command())
    if _tag_sha(verified) != validated_sha:
        raise ReleaseError(f"{TAG} remote tag does not match validated SHA")

    command = [
        "gh",
        "release",
        "create",
        TAG,
        "--repo",
        repository,
        "--verify-tag",
        "--title",
        TITLE,
        "--notes-file",
        NOTES_FILE,
    ]
    created = runner(command)
    if created.returncode != 0:
        raise ReleaseError(f"release creation failed: {_detail(created)}")

    final_tag = runner(_tag_lookup_command())
    if _tag_sha(final_tag) != validated_sha:
        raise ReleaseError(f"{TAG} post-release tag does not match validated SHA")
    final_release = runner(
        ["gh", "api", "--include", f"repos/{repository}/releases/tags/{TAG}"]
    )
    if not _release_exists(final_release):
        raise ReleaseError(f"{TAG} release missing after successful creation")
    return "created"


if __name__ == "__main__":
    publish_release(os.environ["VALIDATED_SHA"], os.environ["GITHUB_REPOSITORY"])
