"""Capture payload shapes (TS-mirror contract) + broadcast hub fan-out.

The UI's TypeScript mirror validates these exact key sets — a drifted key
is a breaking protocol change, so shapes are pinned with exact-set
assertions. The hub tests pin failure isolation: one broken subscriber
never starves the rest.
"""

import pytest
from pydantic import ValidationError

from engine.protocol import (
    CaptureStartCommandPayload,
    CaptureStopCommandPayload,
    Envelope,
    EventBroadcastHub,
    build_capture_device_changed_payload,
    build_capture_started_payload,
    build_capture_stopped_payload,
    build_transcript_final_payload,
    build_transcript_partial_payload,
)


def test_transcript_partial_payload_has_the_exact_pinned_keys() -> None:
    payload = build_transcript_partial_payload(
        "them", "hello world", 1.0, 2.5, 7, speaker_id="1", speaker_label="Speaker 1"
    )
    assert set(payload.keys()) == {
        "stream", "text", "t_start", "t_end", "seq", "speaker_id", "speaker_label",
    }
    assert payload == {
        "stream": "them",
        "text": "hello world",
        "t_start": 1.0,
        "t_end": 2.5,
        "seq": 7,
        "speaker_id": "1",
        "speaker_label": "Speaker 1",
    }


def test_transcript_final_payload_has_the_exact_pinned_keys() -> None:
    payload = build_transcript_final_payload(
        "me", "done", 1.0, 2.0, 9, "seg-1", 850.5, speaker_id="me", speaker_label="Alex"
    )
    assert set(payload.keys()) == {
        "stream",
        "text",
        "t_start",
        "t_end",
        "seq",
        "segment_id",
        "lag_ms",
        "speaker_id",
        "speaker_label",
    }
    assert payload["segment_id"] == "seg-1"
    assert payload["lag_ms"] == 850.5


def test_capture_lifecycle_payloads_have_the_exact_pinned_keys() -> None:
    assert build_capture_started_payload("m-1", "command") == {
        "meeting_id": "m-1", "reason": "command",
    }
    assert build_capture_stopped_payload("m-1", "error") == {
        "meeting_id": "m-1", "reason": "error",
    }
    assert build_capture_device_changed_payload("Headset", 412.0) == {
        "device_name": "Headset", "recovered_ms": 412.0,
    }


def test_capture_start_command_payload_validates_strictly() -> None:
    assert CaptureStartCommandPayload.model_validate({}).title is None
    assert CaptureStartCommandPayload.model_validate({"title": "Standup"}).title == "Standup"
    with pytest.raises(ValidationError):  # Unknown fields: deny by default.
        CaptureStartCommandPayload.model_validate({"title": "x", "evil": True})
    with pytest.raises(ValidationError):  # Type confusion.
        CaptureStartCommandPayload.model_validate({"title": 123})


def test_capture_start_title_length_bound_is_exact() -> None:
    CaptureStartCommandPayload.model_validate({"title": "x" * 512})  # At the bound.
    with pytest.raises(ValidationError):
        CaptureStartCommandPayload.model_validate({"title": "x" * 513})  # Just over.


def test_capture_stop_payload_rejects_any_fields() -> None:
    CaptureStopCommandPayload.model_validate({})
    with pytest.raises(ValidationError):
        CaptureStopCommandPayload.model_validate({"anything": 1})


async def test_hub_broadcasts_a_valid_event_envelope_to_all_subscribers() -> None:
    hub = EventBroadcastHub()
    received_a: list[Envelope] = []
    received_b: list[Envelope] = []

    async def send_a(envelope: Envelope) -> None:
        received_a.append(envelope)

    async def send_b(envelope: Envelope) -> None:
        received_b.append(envelope)

    hub.subscribe(send_a)
    hub.subscribe(send_b)
    await hub.broadcast_event("transcript.partial", {"stream": "me", "text": "hi"})
    for received in (received_a, received_b):
        assert len(received) == 1
        envelope = received[0]
        assert envelope.v == 1
        assert envelope.kind.value == "event"
        assert envelope.name == "transcript.partial"
        assert envelope.payload == {"stream": "me", "text": "hi"}
        assert envelope.id  # Fresh correlatable id.


async def test_unsubscribe_stops_delivery_and_is_idempotent() -> None:
    hub = EventBroadcastHub()
    received: list[Envelope] = []

    async def send(envelope: Envelope) -> None:
        received.append(envelope)

    unsubscribe = hub.subscribe(send)
    await hub.broadcast_event("e", {})
    unsubscribe()
    unsubscribe()  # Second call must be harmless.
    await hub.broadcast_event("e", {})
    assert len(received) == 1
    assert hub.subscriber_count == 0


async def test_failing_subscriber_is_dropped_and_others_still_receive() -> None:
    """Failure isolation: a dead socket must never block the live ones."""
    hub = EventBroadcastHub()
    received: list[Envelope] = []

    async def broken(envelope: Envelope) -> None:
        raise ConnectionError("client vanished")

    async def healthy(envelope: Envelope) -> None:
        received.append(envelope)

    hub.subscribe(broken)
    hub.subscribe(healthy)
    await hub.broadcast_event("transcript.final", {"n": 1})
    assert len(received) == 1  # Healthy subscriber unaffected.
    assert hub.subscriber_count == 1  # Broken one evicted.
    await hub.broadcast_event("transcript.final", {"n": 2})
    assert len(received) == 2  # And stays evicted.
