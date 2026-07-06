"""Payload model for the ``ask.query`` command (WS protocol v1, M3 wiring).

Purpose: the pinned, strictly-validated shape of the Ask-Omni question
command. The command/reply NAMES are pinned in ``engine.ask`` (the feature
package that documents the deferred wiring spec); this module owns only the
inbound payload validation, mirroring how ``capture_event_payloads`` owns
the capture command shapes.
Pipeline position: between ``engine.websocket_connection_handler`` (inbound
frame) and ``engine.ask.ask_query_command_dispatcher`` (handler).

Security invariant: the query is UNTRUSTED input — strictly validated
(unknown fields rejected, hard length bound) before it may reach retrieval
or any model call (deny by default).
"""

from pydantic import BaseModel, ConfigDict, Field

# Hard bound on one question. WHY 4000: far above any real question, far
# below anything that could stress the retriever or smuggle bulk content.
MAX_ASK_QUERY_CHARS = 4000


class AskQueryCommandPayload(BaseModel):
    """Payload of the ``ask.query`` command (client -> engine)."""

    model_config = ConfigDict(extra="forbid")

    # Non-empty, bounded: an empty question has no honest answer path and a
    # megabyte "question" is an abuse attempt, not a query.
    query: str = Field(min_length=1, max_length=MAX_ASK_QUERY_CHARS)
