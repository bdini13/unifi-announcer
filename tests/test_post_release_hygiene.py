from pathlib import Path


def test_completed_v2_1_7_publisher_is_retired():
    assert not Path(".github/workflows/release.yml").exists()
    guide = Path("docs/POST_RELEASE.md").read_text()
    assert "Stable `v2.1.7` has already been published" in guide
    assert "Publish v2.1.7 release" in guide


def test_maintainer_guide_requires_retiring_fixed_publishers():
    guide = Path("docs/MAINTAINERS.md").read_text()
    assert "retire any completed version-specific automatic publishing workflow" in guide
    assert "ordinary post-release `main` commits" in guide
    assert "new release PR" in guide
