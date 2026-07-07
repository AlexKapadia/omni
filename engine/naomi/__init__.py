"""Naomi conversation loop: mic → retrieval → router → warm-socket speech.

The turn-loop layer that sits above ``engine.stt`` (mic-only STT),
``engine.ask``/``engine.index`` (live-tier retrieval), ``engine.router``
(synthesis), ``engine.agents`` (prepare-only approval cards), and
``engine.voice`` (persistent Cartesia socket). The orchestrator conducts one
turn at a time, instruments every stage, and speaks Naomi's reply — never
executing actions, only preparing approval cards (approval-before-execute).

Submodules import each other directly (mirroring ``engine.ask``); this
package init deliberately re-exports nothing to avoid import cycles at boot.
"""
