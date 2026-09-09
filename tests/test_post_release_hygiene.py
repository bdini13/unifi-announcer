from pathlib import Path


def test_completed_v2_1_8_publisher_is_retired():
    assert not Path(".github/workflows/release.yml").exists()
    guide = Path("docs/POST_RELEASE.md").read_text()
    assert "Stable `v2.1.8` has been published as an immutable release" in guide
    assert "Publish v2.1.8 release" in guide
    assert "intentionally retired" in guide


def test_beta2_post_release_state_is_recorded_without_a_publisher():
    guide = Path("docs/POST_RELEASE.md").read_text()
    assert "v2.2.0-beta.2" in guide
    assert "9d8e8f845201cf8de1223cc7d5fc31c192194a5d" in guide
    assert "published manually" in guide
    assert "No persistent version-specific publisher was introduced" in guide


def test_maintainer_guide_requires_retiring_fixed_publishers():
    guide = Path("docs/MAINTAINERS.md").read_text()
    assert "retire any completed version-specific automatic publishing workflow" in guide
    assert "ordinary post-release `main` commits" in guide
    assert "new release PR" in guide
