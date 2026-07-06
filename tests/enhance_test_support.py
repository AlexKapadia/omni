"""Shared deterministic doubles + environment builders for the enhance suite.

``ScriptedRouter`` replays pre-scripted per-task outcomes (a completion text
or a typed RouterError) and RECORDS every call, so tests can prove the
injection-defence posture (untrusted content in ``messages``, never in the
``system_frame``) by inspecting exactly what would have gone over the wire.
``build_finalization_env`` assembles a real SQLite DB (real migrations), a
real tmp vault, and an event collector around the real finalization service.
No network anywhere (unit-test discipline)."""

from dataclasses import dataclass
from pathlib import Path

from engine.protocol import Envelope, EventBroadcastHub
from engine.router import (
    ChatMessage,
    MisconfiguredRouteError,
    Provider,
    ProviderCompletion,
    ProviderRouter,
    RoutedCompletion,
    RouterError,
    ToolSpec,
)
from engine.router.router_ledger_repository import RouterLedgerEntry
from engine.storage.meetings_repository import (
    insert_meeting,
    mark_meeting_ended,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.storage.transcript_segments_repository import insert_transcript_segment


async def record_nothing(entry: RouterLedgerEntry) -> None:
    """A LedgerRecorder that discards entries (unit tests, no DB)."""


@dataclass(frozen=True)
class RecordedRouteCall:
    """One route() invocation exactly as the pipeline issued it."""

    task_type: str
    system_frame: str
    messages: tuple[ChatMessage, ...]
    json_schema: dict[str, object] | None
    max_tokens: int


class ScriptedRouter(ProviderRouter):
    """Deterministic ProviderRouter double: scripted outcomes, recorded calls.

    ``script`` maps task_type -> ordered outcomes; each call pops the next.
    A ``str`` outcome becomes a successful completion; a ``RouterError``
    outcome is raised. An exhausted/missing script raises
    ``MisconfiguredRouteError`` so an unexpected extra call fails loudly.
    """

    def __init__(self, script: dict[str, list[str | RouterError]]) -> None:
        super().__init__({}, record_nothing)
        self._script = {task: list(outcomes) for task, outcomes in script.items()}
        self.calls: list[RecordedRouteCall] = []

    async def route(
        self,
        task_type: str,
        system_frame: str,
        messages: tuple[ChatMessage, ...],
        *,
        tools: tuple[ToolSpec, ...] = (),
        json_schema: dict[str, object] | None = None,
        max_tokens: int = 4096,
    ) -> RoutedCompletion:
        self.calls.append(
            RecordedRouteCall(task_type, system_frame, messages, json_schema, max_tokens)
        )
        queue = self._script.get(task_type)
        if not queue:
            raise MisconfiguredRouteError(task_type)
        outcome = queue.pop(0)
        if isinstance(outcome, RouterError):
            raise outcome
        return RoutedCompletion(
            completion=ProviderCompletion(
                text=outcome,
                provider=Provider.GROQ,
                model="scripted-model",
                prompt_tokens=10,
                completion_tokens=20,
            ),
            provider=Provider.GROQ,
            model="scripted-model",
            latency_ms=12,
        )

    def calls_for(self, task_type: str) -> list[RecordedRouteCall]:
        return [call for call in self.calls if call.task_type == task_type]


class EventCollector:
    """Collects every hub broadcast so tests assert the event story."""

    def __init__(self, hub: EventBroadcastHub) -> None:
        self.events: list[Envelope] = []
        hub.subscribe(self._collect)

    async def _collect(self, envelope: Envelope) -> None:
        self.events.append(envelope)

    def named(self, name: str) -> list[Envelope]:
        return [event for event in self.events if event.name == name]


# A small, realistic two-stream conversation used across the suite.
DEFAULT_SEGMENTS: tuple[tuple[str, str], ...] = (
    ("them", "Thanks for joining, let's review the renewal."),
    ("me", "Sure, I have my notes ready."),
    ("them", "We need the security review done by Friday."),
    ("me", "I will own the security review."),
)


async def seed_meeting(
    db_path: Path,
    migrations_dir: Path,
    meeting_id: str,
    title: str = "Vendor sync",
    started_at: str = "2026-07-06T10:00:00+00:00",
    ended_at: str | None = "2026-07-06T10:30:00+00:00",
    segments: tuple[tuple[str, str], ...] = DEFAULT_SEGMENTS,
) -> None:
    """Create one ended meeting + its transcript rows on a real schema."""
    await apply_migrations(db_path, migrations_dir)
    connection = await open_sqlite_connection(db_path)
    try:
        await insert_meeting(connection, meeting_id, title, started_at)
        if ended_at is not None:
            await mark_meeting_ended(connection, meeting_id, ended_at)
        for index, (stream, text) in enumerate(segments):
            await insert_transcript_segment(
                connection,
                segment_id=f"{meeting_id}-seg-{index}",
                meeting_id=meeting_id,
                stream=stream,
                text=text,
                t_start=float(index),
                t_end=float(index) + 0.9,
                created_at_iso=started_at,
            )
        await connection.commit()
    finally:
        await connection.close()


VALID_EXTRACTION_JSON = (
    '{"actions": [{"title": "Finish the security review", "owner": "Me",'
    ' "due_hint": "Friday"}],'
    ' "contacts": [{"name": "Dana Vendor", "phone": null, "email": "dana@example.test",'
    ' "company": "Northwind"}],'
    ' "dates": [{"when": "Friday", "what": "security review due"}],'
    ' "open_questions": ["Who signs the renewal?"],'
    ' "commitments": [{"who": "Me", "what": "own the security review", "when": "Friday"}]}'
)

VALID_ENHANCED_MARKDOWN = (
    "Renewal call with Northwind.\n\n## Summary\nWe agreed the security review "
    "lands by Friday.\n\n## Next Steps\n- I own the security review."
)
