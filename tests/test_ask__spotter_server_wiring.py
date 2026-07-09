"""Live-answers spotter server wiring: capture events -> feed/flush -> hits.

Drives ``LiveAnswersSpotterWiring`` over a real ``EventBroadcastHub`` with
a fake spotter and a temp database: session construction on
``capture.started``, per-``transcript.final`` feeding (off the broadcast
path, in order), ``flush()`` + connection close on ``capture.stopped``,
``answers.hit`` broadcast on emit, malformed-frame tolerance, and session
replacement when a new capture starts.
"""

import asyncio
from pathlib import Path

import aiosqlite

from engine.ask import ANSWERS_HIT_EVENT_NAME
from engine.ask.ask_answer_contracts import LiveAnswerHit, LiveAnswerSource
from engine.protocol import (
    EVENT_CAPTURE_STARTED,
    EVENT_CAPTURE_STOPPED,
    EVENT_TRANSCRIPT_FINAL,
    Envelope,
    EventBroadcastHub,
    build_capture_started_payload,
    build_capture_stopped_payload,
    build_transcript_final_payload,
)
from engine.wiring.live_answers_spotter_wiring import HitEmitter, LiveAnswersSpotterWiring

HIT = LiveAnswerHit(
    question="what is the Q3 budget?",
    asked_by="them",
    spotted_to_hit_ms=640,
    sources=(
        LiveAnswerSource(
            note_path="Projects/budget.md",
            line_start=4,
            line_end=9,
            heading_path="Q3",
            snippet="The Q3 budget is 40k.",
            score=0.031,
        ),
    ),
)


class FakeSpotter:
    """Records the feed; emits one scripted hit on demand."""

    def __init__(self, emit: HitEmitter) -> None:
        self.emit = emit
        self.segments: list[tuple[str, str]] = []
        self.flushes = 0
        self.emit_on_segment = False

    async def on_final_segment(self, stream: str, text: str) -> None:
        self.segments.append((stream, text))
        if self.emit_on_segment:
            await self.emit(HIT)

    async def flush(self) -> None:
        self.flushes += 1


async def drain_tasks() -> None:
    """Let the wiring's worker task consume everything queued so far."""
    for _ in range(10):
        await asyncio.sleep(0)


def make_wiring(
    hub: EventBroadcastHub, tmp_path: Path, real_migrations_dir: Path
) -> tuple[LiveAnswersSpotterWiring, list[FakeSpotter]]:
    created: list[FakeSpotter] = []

    def factory(connection: aiosqlite.Connection, emit: HitEmitter) -> FakeSpotter:
        spotter = FakeSpotter(emit)
        created.append(spotter)
        return spotter

    wiring = LiveAnswersSpotterWiring(
        hub, db_path=tmp_path / "spotter.db", migrations_dir=real_migrations_dir,
        spotter_factory=factory,
    )
    return wiring, created


async def test_started_final_stopped_feeds_in_order_then_flushes(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    hub = EventBroadcastHub()
    wiring, created = make_wiring(hub, tmp_path, real_migrations_dir)
    await hub.broadcast_event(
        EVENT_CAPTURE_STARTED, build_capture_started_payload("m-1", "command")
    )
    await hub.broadcast_event(
        EVENT_TRANSCRIPT_FINAL,
        build_transcript_final_payload(
            "them", "what is the Q3 budget?", 1.0, 2.5, 0, "s-1", 400.0,
            speaker_id="1", speaker_label="Speaker 1",
        ),
    )
    await hub.broadcast_event(
        EVENT_TRANSCRIPT_FINAL,
        build_transcript_final_payload(
            "me", "let me check", 2.6, 3.4, 0, "s-2", 380.0,
            speaker_id="me", speaker_label="Me",
        ),
    )
    await drain_tasks()
    assert len(created) == 1
    assert created[0].segments == [
        ("them", "what is the Q3 budget?"),
        ("me", "let me check"),
    ]  # spoken order preserved through the queue
    assert created[0].flushes == 0  # nothing flushed while the meeting runs
    await hub.broadcast_event(
        EVENT_CAPTURE_STOPPED, build_capture_stopped_payload("m-1", "command")
    )
    await drain_tasks()
    assert created[0].flushes == 1  # meeting end: whatever is buffered spots now
    await wiring.shutdown()


async def test_emitted_hits_broadcast_the_pinned_answers_hit_payload(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    hub = EventBroadcastHub()
    received: list[Envelope] = []

    async def subscriber(envelope: Envelope) -> None:
        received.append(envelope)

    hub.subscribe(subscriber)
    wiring, created = make_wiring(hub, tmp_path, real_migrations_dir)
    await hub.broadcast_event(
        EVENT_CAPTURE_STARTED, build_capture_started_payload("m-1", "command")
    )
    await drain_tasks()
    created[0].emit_on_segment = True
    await hub.broadcast_event(
        EVENT_TRANSCRIPT_FINAL,
        build_transcript_final_payload(
            "them", "what is the Q3 budget?", 1.0, 2.5, 0, "s-1", 400.0,
            speaker_id="1", speaker_label="Speaker 1",
        ),
    )
    await drain_tasks()
    hits = [e for e in received if e.name == ANSWERS_HIT_EVENT_NAME]
    assert len(hits) == 1
    assert hits[0].payload == {
        "question": "what is the Q3 budget?",
        "asked_by": "them",
        "spotted_to_hit_ms": 640,
        "hits": [
            {
                "note_path": "Projects/budget.md",
                "line_start": 4,
                "line_end": 9,
                "heading_path": "Q3",
                "snippet": "The Q3 budget is 40k.",
                "score": 0.031,
            }
        ],
    }
    await wiring.shutdown()


async def test_malformed_final_payloads_and_out_of_session_finals_are_ignored(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    hub = EventBroadcastHub()
    wiring, created = make_wiring(hub, tmp_path, real_migrations_dir)
    # A final with no session open: nothing to feed, nothing crashes.
    await hub.broadcast_event(
        EVENT_TRANSCRIPT_FINAL,
        build_transcript_final_payload(
            "them", "orphan", 0.0, 1.0, 0, "s-0", 10.0,
            speaker_id="1", speaker_label="Speaker 1",
        ),
    )
    await hub.broadcast_event(
        EVENT_CAPTURE_STARTED, build_capture_started_payload("m-1", "command")
    )
    # Malformed shapes: wrong types and whitespace-only text contribute nothing.
    for payload in (
        {"stream": 3, "text": "typed wrong"},
        {"stream": "them"},  # text missing
        {"stream": "them", "text": "   "},  # nothing to spot
        {},
    ):
        await hub.broadcast_event(EVENT_TRANSCRIPT_FINAL, payload)
    await drain_tasks()
    assert len(created) == 1 and created[0].segments == []
    await wiring.shutdown()


async def test_a_second_capture_start_replaces_the_previous_session(
    tmp_path: Path, real_migrations_dir: Path
) -> None:
    hub = EventBroadcastHub()
    wiring, created = make_wiring(hub, tmp_path, real_migrations_dir)
    await hub.broadcast_event(
        EVENT_CAPTURE_STARTED, build_capture_started_payload("m-1", "command")
    )
    await hub.broadcast_event(
        EVENT_CAPTURE_STARTED, build_capture_started_payload("m-2", "command")
    )
    await drain_tasks()
    assert len(created) == 2  # fresh spotter per meeting; the old one is gone
    await hub.broadcast_event(
        EVENT_TRANSCRIPT_FINAL,
        build_transcript_final_payload(
            "me", "new meeting line", 0.5, 1.0, 0, "s-9", 90.0,
            speaker_id="me", speaker_label="Me",
        ),
    )
    await drain_tasks()
    assert created[0].segments == []  # the replaced session never sees new finals
    assert created[1].segments == [("me", "new meeting line")]
    await wiring.shutdown()
