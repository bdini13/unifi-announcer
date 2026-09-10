from pathlib import Path


def test_camera_setup_guide_matches_beta3_runtime_contract():
    guide = Path("docs/CAMERAS.md").read_text()
    env_example = Path(".env.example").read_text()
    release_notes = Path("docs/RELEASE_NOTES_v2.2.0-beta.3.md").read_text()

    assert "Stable `v2.1.8` remains the recommended release" in guide
    assert "`v2.2.0-beta.3`" in guide
    assert "CAMERAS_CONFIG" in guide
    assert "EXPERIMENTAL_CAMERA_PROFILES" in guide
    assert "physically_validated" in guide
    assert "experimental_opt_in" in guide
    assert "/proxy/protect/api/bootstrap" in guide
    assert "/targets" in guide
    assert '"codec":"aac","transport":"serverudp","sample_rate":22050,"channels":1,"bits_per_sample":16' in guide
    assert "Cameras never join the implicit `default` target" in guide
    assert "text and repeats" in guide
    assert "does not retry after uncertain camera delivery" in guide

    first_playback = guide.split("## 6. First camera announcement", 1)[1].split(
        "## Home Assistant behavior", 1
    )[0]
    assert '"target":"family_room_camera"' in first_playback
    assert '"repeat_times":1' in first_playback
    assert '"volume":' not in first_playback
    assert '"profile":' not in first_playback

    assert "See docs/CAMERAS.md" in env_example
    assert "[Protect camera-speaker setup guide](CAMERAS.md)" in release_notes
