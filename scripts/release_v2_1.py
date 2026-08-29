"""Idempotently publish the fixed v2.1.1 GitHub release."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Protocol

TAG = "v2.1.1"
TITLE = "v2.1.1 — Secure public installation hardening"
NOTES_FILE = "docs/RELEASE_NOTES_v2.1.1.md"


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


def publish_release(
    validated_sha: str,
    repository: str,
    *,
    runner: Callable[[Sequence[str]], Result] = _run,
) -> str:
    tag = runner(
        ["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{TAG}"]
    )
    if tag.returncode not in (0, 2):
        raise ReleaseError(f"{TAG} tag lookup failed: {_detail(tag)}")

    release = runner(
        ["gh", "api", "--include", f"repos/{repository}/releases/tags/{TAG}"]
    )
    tag_exists = tag.returncode == 0
    release_exists = _release_exists(release)

    if tag_exists and release_exists:
        print(f"{TAG} already exists; leaving its tag and release unchanged.")
        return "unchanged"
    if tag_exists:
        raise ReleaseError(f"{TAG} tag exists without a release")
    if release_exists:
        raise ReleaseError(f"{TAG} release exists without a matching remote tag")

    command = [
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
    ]
    created = runner(command)
    if created.returncode != 0:
        raise ReleaseError(f"release creation failed: {_detail(created)}")
    return "created"


if __name__ == "__main__":
    publish_release(os.environ["VALIDATED_SHA"], os.environ["GITHUB_REPOSITORY"])
