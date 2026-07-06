# Naomi conversation loop — progress tracker (feature/naomi-loop)

**North Star:** talk to Naomi like Jarvis — mic → VAD endpoint → verbatim STT →
retrieval-first answer → affect-tagged reply spoken through a WARM persistent
Cartesia socket, automatic barge-in, actions via approval cards (never executed
directly), latency instrumented per stage and shown live in the UI.

**Resume here:** build the engine/voice persistent connection, then engine/naomi.

## Checklist

- [x] Read foundation (brief §7, engine/voice, engine/ask, engine/stt, wiring, apps/ui/src/naomi)
- [x] Branch `feature/naomi-loop` created off main (baseline: 1413 pytest)
- [ ] ENGINE: persistent Cartesia connection (multiplexed context_id, reconnect+backoff, kill-switch at (re)connect, continuation framing)
- [ ] ENGINE: engine/naomi package — protocol names, affect parser, clause chunker, latency breakdown, state machine, onset detector, mic session, answer service, action-intent flow, speaker, orchestrator
- [ ] ENGINE: wiring — naomi_turn_command_dispatcher + handler/server/factory edits
- [ ] TESTS: state machine, endpoint 699/701, barge-in races, retrieval-empty honesty, action-card never-execute, persistent socket reconnect/kill-switch, latency arithmetic exact, affect fallback, clause chunker, WS commands
- [ ] UI: naomi-turn-protocol, socket extension, conversation state, controls, captions w/ word highlight, citations chips, error states, latency readout
- [ ] UI TESTS: protocol parsers, conversation reducer, word highlight
- [ ] GATES: pytest (expect 1413+new), ruff, mypy, tsc, vitest
- [ ] LIVE TEST: seeded vault fact → spoken answer via real Cartesia (warm socket) + barge-in; record real latency table vs budget (p50 620 ms)
- [ ] Commit + push at each gate

## Decisions & evidence

- Router has NO streaming surface → clause-level chunking of the completed
  synthesis text into Cartesia `continue:true` frames; streaming-router noted
  as an honest follow-up.
- Naomi endpoint profile: VAD min_silence = 0.7 s (task-pinned; boundary
  tested at 699/701 ms).
- Action intents: deterministic leading-verb/wake-word gate → dictation
  INTENT_PARSING task → dictation-intents row → existing card builder →
  PENDING card + spoken confirmation. Executor is never reachable from this
  path (deny by default).
- Voice answers: live-tier structured-first retrieval (ms-fast, no graph
  expansion, no rerank); empty/below-floor ⇒ exact "I don't have that in your
  notes." with ZERO provider calls.
- Latency contract: total_ms = endpoint+retrieval+llm+ttfa BY CONSTRUCTION
  (sum of rounded spans), tested exact to the unit.

## Agent ledger

Single build agent (this lane). No sub-fan-out.
