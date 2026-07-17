# Fable engine sweep — confirmed findings (2026-07-17)

1. BLOCKER — engine/microsoft/graph_api_gateway.py:21-37 (+ graph_session.py:75-101, oauth_desktop_flow.py) — entire Microsoft Graph surface has no kill-switch check; list_upcoming_outlook_events and token-refresh POST fire every 300s from calendar_poll_service.py:97-109 even with egress kill switch engaged, while the Google gateway checks it before every call (google_api_gateway.py:36-39). Fix: add kill_switch_engaged() refusal at the top of every Graph call and in MicrosoftSession.request_json/refresh, mirroring the Google gateway.

2. MAJOR — websocket_connection_handler.py:139-140 + detect/detection_service.py:115-122 + detect/auto_start_rules_engine.py:156-167 — rearm_suggestions_for_ui() runs on EVERY WS connect; four windows each with reconnect backoff means duplicate meeting.detected broadcasts per connecting window, resurrecting ignored toasts. Fix: rearm only on the hub's 0->1 subscriber transition (or debounce rearm per source), not per connection.

3. MAJOR — same rearm path re-fires AutoStart: rearm clears `handled` for sessions marked handled by _observe_capture (auto_start_rules_engine.py:293-295), and auto-start decisions never set a dismiss cooldown; after manual stop with Zoom still open, any reconnect re-emits meeting.detected{auto_start:true} and the UI restarts capture against the user's explicit stop. Fix: exclude auto-start-eligible sources from rearm (or add per-source auto-start cooldown after a manual stop).

4. MAJOR — stt/live_capture_service.py:160-239 — start() checks self._meeting_id at line 162 but assigns at 210 with many awaits between; two near-simultaneous capture.start produce two controllers/meetings, second clobbers state, first leaks streams. Fix: serialize start()/stop() under an asyncio.Lock (or set sentinel before first await).

5. MAJOR — google/calendar_poll_service.py:111-133 — _broadcast_new assigns self._last_broadcast_ids = current_ids per provider, so Microsoft pass overwrites the Google id set; with both providers every event re-broadcasts every 300s tick. Fix: per-provider dedupe sets, or replace only that provider's prefixed keys in the merged set.

6. MAJOR — enhance/meeting_retranscription_service.py:84 — decode_kept_audio() runs blocking ffmpeg subprocess.run on the event loop, freezing the whole engine during decode; import path does it right via asyncio.to_thread (import_/media_import_service.py:63). Fix: samples = await asyncio.to_thread(decode_kept_audio, audio_path).

7. MAJOR — wiring/models_download_command_dispatcher.py:104-125 + wiring/models_lifecycle_ops.py:22-29 — models.cancel cancels only the awaiting task; the to_thread download keeps running, keeps emitting progress, and a second models.download opens a second writer on the same .partial file (model_weights_downloader.py:196-204) — corruption. Fix: pass a threading.Event into the fetch loop checked per 256KB block; keep single-flight guard until the thread actually exits.

8. MAJOR — websocket_connection_handler.py:142-144 — frames processed serially per connection; meeting.finalize / meeting.retranscribe / import.media awaited inline for minutes, blocking capture.stop and all other commands on that socket. Fix: run these long commands in a spawned task and send the reply on completion (progress events already exist).

9. MINOR — websocket_connection_handler.py:147-152,159-181 — run()'s finally suppresses only CancelledError when awaiting heartbeat task; a raced send-on-closed-socket exception re-raises in finally as unhandled ASGI error on ordinary disconnects. Fix: suppress/log Exception too.

10. MINOR — wiring/detection_server_wiring.py:138 — _on_decision fires create_task without keeping a reference; broadcast task can be GC'd mid-flight and an event silently dropped (repo keeps refs elsewhere: server.py:179-182). Fix: task set with done-callback discard.

11. MINOR — server.py:174-184 — vault_rebind_tasks grows unboundedly and pending rebind tasks are neither cancelled nor awaited at shutdown. Fix: done-callback discard + cancel/await stragglers in shutdown.

12. MINOR — wiring/live_meeting_enrichment_wiring.py:225-233 vs :251 — after _FLUSH_AND_STOP the worker closes the sqlite connection but _tick_task can still enter session.tick() against the closed connection; raise escapes as unretrieved task exception. Fix: cancel _tick_task from the worker's stop path (or re-check queue None before tick + try/except).

13. MINOR — stt/live_capture_service.py:241-274 — stop() unguarded and not exception-safe: concurrent stops double-run teardown/capture.stopped, and an exception in finalize aborts before state nulling, wedging capture until restart. Fix: share the start() lock; move state-nulling into finally.

Refuted/clean: command names and event kinds between UI and engine fully aligned; no dispatch or parser mismatches.
