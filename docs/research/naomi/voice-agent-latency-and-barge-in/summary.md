# Voice-agent latency budgets & barge-in — engineering literature

**Sources (surveyed 2026-07-06; professional engineering write-ups — treated as practitioner
evidence, cross-checked against vendor docs, not peer-reviewed):**
- Retell AI. "How Real-Time Voice AI Actually Works (STT → LLM → TTS, Explained)."
  https://www.retellai.com/blog/how-real-time-voice-ai-works-stt-llm-tts
- Chanl. "Voice AI pipeline: STT, LLM, TTS and the 300ms budget."
  https://www.channel.tel/blog/voice-ai-pipeline-stt-tts-latency-budget
- Sayna AI. "Sub-Second Voice Agent Latency: A Practical Architecture Guide."
  https://sayna.ai/blog/sub-second-voice-agent-latency-practical-architecture-guide
- ByondLabs. "Voice Agent Latency: The Sub-Second Tuning Playbook."
  https://byondlabs.tech/blog/voice-agent-latency-the-sub-second-tuning-playbook
- Groq. "Understanding and Optimizing Latency." GroqDocs.
  https://console.groq.com/docs/production-readiness/optimizing-latency
- Artificial Analysis provider benchmarks: https://artificialanalysis.ai/providers/groq

## Consensus findings

1. **The clock starts at end-of-speech.** Perceived latency = user stops talking → first
   audible reply. Chained pipelines that don't stream at every stage land at 1-2s+;
   streaming everywhere gets ~690ms typical (worked example: 120ms end-of-speech detection
   + 450ms LLM time-to-first-token + 120ms TTS time-to-first-byte). Pauses beyond ~300ms
   already feel non-instant; sub-second is the credibility line for "millisecond feel".
2. **End-of-utterance detection is the hidden cost.** Naive silence timeouts wait
   1000-1500ms; tuned VAD-based end-pointing achieves 150-250ms at a false-trigger cost
   that must be tested. (Omni advantage: Silero VAD gating already runs locally in
   `engine/stt/vad_gating_state_machine.py` — the budget line is a config knob, not new
   work.)
3. **LLM TTFT dominates the remote share.** Groq is the fastest mainstream provider class:
   sub-300ms TTFT for most models on GroqCloud (Groq docs), with deterministic latency
   (no GPU scheduling variance) and 300-800+ tokens/s output (Artificial Analysis) —
   output speed matters because the first *sentence* (not token) gates TTS start.
4. **TTS TTFB:** 40-120ms across modern streaming TTS; Cartesia Sonic at the low end
   (see cartesia-sonic-realtime-tts/).
5. **Barge-in discipline:** on user speech onset while the agent talks — stop playback
   within one audio frame (~20ms), drop pending audio, cancel TTS generation, abort the
   LLM stream, return to listening. Reported achievable pipeline-clear latency: ~25ms.
   Asymmetry matters: false-positive interruptions (agent stops when it shouldn't) are
   *more* disruptive than brief overlap — require sustained speech (~2-3 VAD frames,
   ~60-100ms) before triggering, and ignore the agent's own output (Omni advantage:
   loopback vs mic are already separate labelled streams, so echo-triggered barge-in is
   structurally impossible when playback is on loopback and VAD runs on mic).

## Retrieval note (local)

Local hybrid retrieval (M3: bge-small embeddings in sqlite-vec + keyword) is on-box and
measured in the tens of milliseconds — it belongs inside the LLM-call critical path budget
but is negligible next to network TTFT.
