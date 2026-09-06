from pathlib import Path


def test_completed_v2_1_8_publisher_is_retired():
    assert not Path(".github/workflows/release.yml").exists()
    guide = Path("docs/POST_RELEASE.md").read_text()
    assert "Stable `v2.1.8` has been published as an immutable release" in guide
    assert "Publish v2.1.8 release" in guide
    assert "intentionally retired" in guide


def test_maintainer_guide_requires_retiring_fixed_publishers():
    guide = Path("docs/MAINTAINERS.md").read_text()
    assert "retire any completed version-specific automatic publishing workflow" in guide
    assert "ordinary post-release `main` commits" in guide
    assert "new release PR" in guide
