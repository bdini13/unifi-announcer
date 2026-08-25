
from scripts.fw_signature import extract


def test_watch_phrase_does_not_match_only_first_word(tmp_path):
    firmware = tmp_path / "up-chime-1.7.20.bin"
    firmware.write_bytes(b"xxxxDisablexxxx uploadRingtonexxxx")
    report = extract(str(firmware))
    phrase = "Disable ucp4_wss responst and trnafer to https client"
    assert report["watch_strings"][phrase] is False


def test_exact_and_normalized_phrase_report_offsets_and_context(tmp_path):
    firmware = tmp_path / "up-chime-1.7.20.bin"
    phrase = b"Disable   ucp4_wss responst and trnafer to HTTPS client"
    firmware.write_bytes(b"\0prefix-context " + phrase + b" suffix-context\0")
    report = extract(str(firmware))
    key = "Disable ucp4_wss responst and trnafer to https client"
    assert report["watch_strings"][key] is True
    evidence = next(item for item in report["watch_evidence"] if item["phrase"] == key)
    assert evidence["match"] == "normalized"
    assert evidence["offsets"] == [1]
    assert "prefix-context" in evidence["contexts"][0]


def test_level1_endpoint_signature_uses_synthetic_binary_strings(tmp_path):
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"AAAA/api/info\0BBBBsupportCustomRingtone\0CCCCplaySpeaker\0")
    report = extract(str(firmware))
    assert report["analysis_level"] == "level1-strings"
    assert "/api/info" in report["http_endpoints_confirmed"]
    assert report["string_evidence"]["/api/info"]["offsets"] == [4]
    assert report["feature_flags"]["supportCustomRingtone"] is True
    assert report["direct_write_safe"] is False
