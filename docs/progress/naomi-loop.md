# Naomi conversation loop — progress tracker (feature/naomi-loop)

**North Star:** talk to Naomi like Jarvis — mic → VAD endpoint → verbatim STT →
retrieval-first answer → affect-tagged reply spoken through a WARM persistent
Cartesia socket, automatic barge-in, actions via approval cards (never executed
directly), latency instrumented per stage and shown live in the UI.

**Resume here:** engine core modules being built by orchestrator; UI lane
dispatched to a scoped agent. Next: wiring + tests + gate + live test.

## Seam map (confirmed 2026-07-07 via Explore agent)
- STT mic-only: compose `PerStreamTranscriptionPipeline(stream=ME, vad_probability=SileroOnnxVoiceActivityDetector, transcribe=ParakeetNemoTranscriber.transcribe_window, on_partial, on_final, gate=VadGatingStateMachine(VadGateConfig(min_silence_s=0.7)))`. on_final(words,t_open,t_close) = verbatim utterance on end-of-speech. Audio: AudioFrame(stream, float32@16k, t_start_monotonic); PIPELINE_SAMPLE_RATE=16000. Feed via session.feed(frame) seam (live test injects PCM here).
- Retrieval (live tier): `retrieve_structured_first(conn, retriever, query, tier=TIER_LIVE, top_n=5, enable_graph_expansion=False)`; empty chunks ⇒ no-answer, ZERO provider calls. Retriever: HybridRrfRetriever(conn, None, None) (BM25 until vec).
- Router: `ProviderRouter.route("ask_synthesis", system_frame, (ChatMessage(role,content),...), max_tokens=...) -> RoutedCompletion`; NO streaming; kill-switch first; ledger per attempt. TaskType.ASK_SYNTHESIS/INTENT_PARSING confirmed.
- Action intent: `route("intent_parsing", INTENT_PARSING_SYSTEM_FRAME, ..., json_schema=DICTATION_INTENT_JSON_SCHEMA)` → `parse_intent_completion_text` → insert dictation_intents → `build_card_from_dictation_intent(conn, record=..., created_at=...)` → PENDING card id. Executor (`execute_approved_card`) unreachable from pending (claim requires approved→executing) = deny by default.
- Speaker: PersistentCartesiaConnection.speak_utterance(chunks, context_id, affect) yields CartesiaMessage; relay to hub via existing naomi.audio.* builders; cancel(context_id) = barge-in wire.
- Hub: `await hub.broadcast_event(name, payload)`. WS register in websocket_connection_handler._dispatch_command; factory in wiring/server_default_service_factories.py + server.create_app.

## Checklist
- [x] Read foundation + full seam map
- [x] Predecessor partials verified (import+ruff): persistent_cartesia_connection, affect_self_tag_parser, naomi_turn_protocol_names — kept; fixed one ruff S110 in reader pump
- [ ] ENGINE naomi core: turn_state_machine, clause_chunker, turn_latency_breakdown, mic_stt_session, voice_answer_service, action_intent_flow, turn_speaker, turn_orchestrator (+runner split if >300)
- [ ] ENGINE wiring: naomi_turn_command_dispatcher + naomi_turn_gateway/factory + handler/server/factory edits
- [x] ENGINE wiring: naomi_turn_command_dispatcher + naomi_turn_gateway + naomi_mic_capture_source + server.py/handler/factory edits (factory-gated; hermetic tests refuse honestly)
- [x] TESTS (98 naomi, all green): state machine + illegal (full matrix), endpoint 699/701 boundary + 0.7s profile + onset, barge-in races, retrieval-empty honesty (zero provider calls), action-card never-execute (executor refuses pending), persistent socket warm-reuse/reconnect/kill-switch/multiplex, latency arithmetic exact (seeded fuzz), affect fallback (fuzz, never leaks tag), clause chunker (join==text fuzz), voice answer service, WS listen commands, full-turn orchestrator sequence
- [x] UI (agent): naomi-turn-protocol, socket extension, conversation store, NaomiView controls (PTT + open-mic), state→affect, latency table, captions, citation chips, error states (+68 UI tests)
- [x] GATES GREEN: ruff clean, mypy clean (310 files), pytest 1510 passed/1 skip, pnpm tsc clean, vitest 713 passed
- [ ] LIVE TEST: seeded vault fact → PCM at session seam → verbatim + retrieval hit + REAL warm-socket Cartesia + affect; latency table vs 620ms p50; barge-in interrupt
- [x] Commit + push at each gate (checkpoints db1241a, 198474f; gate commit pending)

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
