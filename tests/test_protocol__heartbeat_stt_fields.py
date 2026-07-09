"""Heartbeat optional STT status fields."""

from engine.protocol.heartbeat_payload import build_heartbeat_payload


def test_heartbeat_includes_optional_stt_fields() -> None:
    payload = build_heartbeat_payload(
        0.0,
        stt_ready=True,
        stt_engine="parakeet",
        stt_model_id="parakeet-tdt-0.6b-v2",
        stt_device="cuda",
    )
    assert payload["stt_ready"] is True
    assert payload["stt_engine"] == "parakeet"
    assert payload["stt_model_id"] == "parakeet-tdt-0.6b-v2"
    assert payload["stt_device"] == "cuda"


def test_heartbeat_omits_empty_optional_stt_fields() -> None:
    payload = build_heartbeat_payload(0.0, stt_ready=False)
    assert "stt_engine" not in payload
    assert "stt_device" not in payload
