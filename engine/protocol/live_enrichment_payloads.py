"""Event payloads for live meeting enrichment (summary + vault suggestions)."""

from __future__ import annotations

SUMMARY_UPDATED_EVENT_NAME = "summary.updated"
VAULT_SUGGESTION_EVENT_NAME = "vault.suggestion"
TRANSLATION_UPDATED_EVENT_NAME = "translation.updated"


def summary_updated_payload(
    meeting_id: str, summary_md: str, updated_at_ms: int
) -> dict[str, object]:
    return {
        "meeting_id": meeting_id,
        "summary_md": summary_md,
        "updated_at_ms": updated_at_ms,
    }


def vault_suggestion_payload(
    topic: str, sources: list[dict[str, object]], latency_ms: int
) -> dict[str, object]:
    return {
        "topic": topic,
        "latency_ms": latency_ms,
        "hits": sources,
    }


def translation_updated_payload(lines: list[dict[str, object]]) -> dict[str, object]:
    return {"lines": lines}
