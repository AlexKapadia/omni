"""Round-trip and exact-shape tests for the pinned WS protocol v1 envelope.

The UI is built against this exact wire shape; these tests pin it so any
accidental change to field names, kinds, or serialisation fails loudly.
"""

import json

from engine.protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    parse_envelope,
)


def test_envelope_roundtrips_bytewise_through_the_wire_format() -> None:
    """serialise → parse → serialise must be a fixed point (determinism)."""
    original = Envelope(
        v=1,
        kind=EnvelopeKind.COMMAND,
        name="ping",
        id="abc-123",
        payload={"nested": {"deep": [1, 2.5, "three", None, True]}},
    )
    wire = original.to_wire()
    reparsed = parse_envelope(wire)
    assert reparsed == original
    assert reparsed.to_wire() == wire  # exact fixed point, not just equality


def test_wire_format_has_exactly_the_pinned_top_level_keys() -> None:
    """The contract is {"v","kind","name","id","payload"} — nothing else."""
    wire = Envelope(v=1, kind=EnvelopeKind.EVENT, name="e", id="i", payload={}).to_wire()
    decoded = json.loads(wire)
    assert set(decoded.keys()) == {"v", "kind", "name", "id", "payload"}
    assert decoded["v"] == PROTOCOL_VERSION
    assert isinstance(decoded["kind"], str)
    assert isinstance(decoded["payload"], dict)


def test_all_three_kinds_serialise_to_their_exact_wire_strings() -> None:
    """Kind values are pinned strings: event / command / reply."""
    for kind, expected in [
        (EnvelopeKind.EVENT, "event"),
        (EnvelopeKind.COMMAND, "command"),
        (EnvelopeKind.REPLY, "reply"),
    ]:
        wire = Envelope(v=1, kind=kind, name="n", id="i", payload={}).to_wire()
        assert json.loads(wire)["kind"] == expected


def test_roundtrip_preserves_unicode_payloads_exactly() -> None:
    """Non-ASCII content (names, notes) must survive the wire unmangled."""
    payload = {"text": "naïve café — 会議メモ 🎙️", "path": "C:\\Users\\alexa"}
    envelope = Envelope(v=1, kind=EnvelopeKind.REPLY, name="r", id="i", payload=payload)
    assert parse_envelope(envelope.to_wire()).payload == payload


def test_boundary_exact_payload_size_is_accepted_at_the_limit() -> None:
    """A frame at exactly MAX_MESSAGE_BYTES parses; one byte over is tested
    in the rejection suite — boundary-exact on both sides of the cutoff."""
    skeleton = Envelope(v=1, kind=EnvelopeKind.COMMAND, name="ping", id="i", payload={"pad": ""})
    overhead = len(skeleton.to_wire().encode("utf-8"))
    padding = "x" * (MAX_MESSAGE_BYTES - overhead)
    wire = Envelope(
        v=1, kind=EnvelopeKind.COMMAND, name="ping", id="i", payload={"pad": padding}
    ).to_wire()
    assert len(wire.encode("utf-8")) == MAX_MESSAGE_BYTES  # exactly at the limit
    assert parse_envelope(wire).payload["pad"] == padding


def test_max_length_name_and_id_are_accepted_at_the_boundary() -> None:
    """128-char name/id are legal (limit is inclusive)."""
    long_string = "a" * 128
    frame = {"v": 1, "kind": "command", "name": long_string, "id": long_string, "payload": {}}
    envelope = parse_envelope(json.dumps(frame))
    assert envelope.name == long_string
    assert envelope.id == long_string
