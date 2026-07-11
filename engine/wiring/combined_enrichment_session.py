"""Combined live-enrichment session: summary + vault poll + optional translation."""

from __future__ import annotations

from engine.ask.live_summary_service import LiveSummaryService
from engine.ask.live_translation_service import LiveTranslationService
from engine.ask.proactive_vault_poller import ProactiveVaultPoller


class CombinedEnrichmentSession:
    """One meeting's enrichment fan-out; translation may attach mid-session."""

    def __init__(
        self,
        summary: LiveSummaryService,
        vault: ProactiveVaultPoller,
        translation: LiveTranslationService | None = None,
    ) -> None:
        self._summary = summary
        self._vault = vault
        self._translation = translation

    async def on_final_segment(self, stream: str, text: str) -> None:
        await self._summary.on_final_segment(stream, text)
        await self._vault.on_final_segment(stream, text)
        if self._translation is not None:
            await self._translation.on_final_segment(stream, text)

    async def tick(self) -> None:
        await self._summary.tick()
        await self._vault.tick()
        if self._translation is not None:
            await self._translation.tick()

    async def flush(self) -> None:
        await self._summary.flush()
        await self._vault.flush()
        if self._translation is not None:
            await self._translation.flush()


__all__ = ["CombinedEnrichmentSession"]
