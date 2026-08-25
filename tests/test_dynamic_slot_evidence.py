from scripts.dynamic_slot_evidence import (
    added_occurrences,
    classify_verdict,
    staged_device_proof_matches,
    staged_slot_matches,
)


def test_added_occurrences_preserves_new_duplicate_lines():
    before = ["same", "same", "old"]
    after = ["same", "same", "same", "old", "new"]

    assert added_occurrences(before, after) == ["same", "new"]


def test_staged_slot_matches_exact_hash_and_size():
    tracks = [{"md5": "first", "size": 10}, {"md5": "target", "size": 42}]

    assert staged_slot_matches(tracks, slot=2, md5="target", size=42)
    assert not staged_slot_matches(tracks, slot=2, md5="target", size=41)
    assert not staged_slot_matches(tracks, slot=3, md5="target", size=42)


def test_staged_device_proof_accepts_logs_when_protect_metadata_is_stale():
    tone = {"size": 11536, "md5": "tone-md5", "sha256": "tone-sha256"}
    proof = {
        "logged_save_track": 7,
        "logged_bytes": 11536,
        "logged_route": "/api/uploadRingtone/7/owned.mp3",
        "local_mp3_md5": "tone-md5",
        "local_mp3_sha256": "tone-sha256",
        "protect_metadata_stale": True,
    }

    assert staged_device_proof_matches(proof, tone)
    assert not staged_device_proof_matches({**proof, "logged_save_track": 6}, tone)
    assert not staged_device_proof_matches({**proof, "logged_bytes": 4223}, tone)


def test_classify_validated_requires_success_and_new_play_start():
    assert classify_verdict(200, ["audio_spk: playSpeaker start track[7]"]) == "validated"
    assert classify_verdict(204, ["audio_spk: playSpeaker start track[7]"]) == "validated"
    assert classify_verdict(200, ["save file into track[7]"]) == "inconclusive"


def test_classify_rejected_for_http_or_explicit_mapping_failure():
    assert classify_verdict(400, []) == "rejected"
    assert classify_verdict(200, ["UCP4 ringtone mapping failed for track 7"]) == "rejected"
    assert classify_verdict(200, ["playSpeaker load error for track[7]"]) == "rejected"
