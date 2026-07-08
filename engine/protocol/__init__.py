"""WebSocket protocol v1 between the engine sidecar and the UI shell.

Purpose: the pinned wire contract — envelope shape, message names, error
codes, and payload models. The UI is built against these exact shapes;
changes here are breaking protocol changes and require a version bump.
Pipeline position: sits between ``engine.server`` (transport) and every
feature module that emits events or answers commands.

Security invariant: every inbound frame is treated as untrusted input and
must pass through ``parse_envelope`` (size cap + strict validation) before
any handler sees it — fail closed, never crash the socket.
"""

from engine.protocol.ask_query_payloads import AskQueryCommandPayload
from engine.protocol.capture_event_payloads import (
    COMMAND_CAPTURE_START,
    COMMAND_CAPTURE_STOP,
    EVENT_CAPTURE_DEVICE_CHANGED,
    EVENT_CAPTURE_STARTED,
    EVENT_CAPTURE_STOPPED,
    EVENT_TRANSCRIPT_FINAL,
    EVENT_TRANSCRIPT_PARTIAL,
    CaptureStartCommandPayload,
    CaptureStopCommandPayload,
    build_capture_device_changed_payload,
    build_capture_started_payload,
    build_capture_stopped_payload,
    build_transcript_final_payload,
    build_transcript_partial_payload,
)
from engine.protocol.detection_event_payloads import (
    COMMAND_DETECTION_DISMISS,
    EVENT_CAPTURE_SUGGEST_STOP,
    EVENT_MEETING_DETECTED,
    DetectionDismissCommandPayload,
    build_capture_suggest_stop_payload,
    build_meeting_detected_payload,
)
from engine.protocol.device_listing_payloads import (
    COMMAND_DEVICES_LIST,
    AudioDeviceDescription,
    DevicesListCommandPayload,
    build_devices_list_payload,
)
from engine.protocol.event_broadcast_hub import EventBroadcastHub
from engine.protocol.google_connect_payloads import (
    COMMAND_GOOGLE_CONNECT,
    EVENT_GOOGLE_CONNECT_COMPLETED,
    GoogleConnectCommandPayload,
    build_google_connect_completed_payload,
)
from engine.protocol.heartbeat_payload import build_heartbeat_payload
from engine.protocol.ledger_summary_payloads import (
    COMMAND_LEDGER_SUMMARY,
    DEFAULT_RECENT_ENTRIES_LIMIT,
    LedgerSummaryCommandPayload,
)
from engine.protocol.meeting_finalization_payloads import (
    COMMAND_IMPORT_MEDIA,
    COMMAND_MEETING_RETRANSCRIBE,
    COMMAND_MEETING_EXPORT,
    COMMAND_MEETING_FINALIZE,
    COMMAND_MEETING_GET,
    COMMAND_MEETINGS_LIST,
    COMMAND_TRANSCRIPT_SEGMENT_UPDATE,
    EVENT_ENHANCE_FAILED,
    EVENT_ENHANCE_READY,
    EVENT_ENHANCE_STARTED,
    ImportMediaCommandPayload,
    MeetingRetranscribeCommandPayload,
    MeetingExportCommandPayload,
    MeetingFinalizeCommandPayload,
    MeetingGetCommandPayload,
    MeetingsListCommandPayload,
    TranscriptSegmentUpdatePayload,
    build_enhance_failed_payload,
    build_enhance_ready_payload,
    build_enhance_started_payload,
)
from engine.protocol.models_download_payloads import (
    COMMAND_MODELS_DOWNLOAD,
    EVENT_MODELS_DOWNLOAD_COMPLETED,
    EVENT_MODELS_DOWNLOAD_FAILED,
    EVENT_MODELS_DOWNLOAD_PROGRESS,
    ModelsDownloadCommandPayload,
    build_models_download_completed_payload,
    build_models_download_failed_payload,
    build_models_download_progress_payload,
)
from engine.protocol.provider_keys_payloads import (
    COMMAND_KEYS_SAVE,
    COMMAND_KEYS_VALIDATE,
    KeysSaveCommandPayload,
    KeysValidateCommandPayload,
)
from engine.protocol.settings_command_payloads import (
    COMMAND_SETTINGS_GET,
    COMMAND_SETTINGS_UPDATE,
    COMMAND_SETUP_STATUS,
    SettingsGetCommandPayload,
    SettingsUpdateCommandPayload,
    SetupStatusCommandPayload,
)
from engine.protocol.websocket_envelope import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    Envelope,
    EnvelopeKind,
    ProtocolError,
    ProtocolErrorCode,
    error_reply,
    parse_envelope,
)

__all__ = [
    "COMMAND_CAPTURE_START",
    "COMMAND_CAPTURE_STOP",
    "COMMAND_DETECTION_DISMISS",
    "COMMAND_DEVICES_LIST",
    "COMMAND_GOOGLE_CONNECT",
    "COMMAND_KEYS_SAVE",
    "COMMAND_KEYS_VALIDATE",
    "COMMAND_LEDGER_SUMMARY",
    "COMMAND_MEETINGS_LIST",
    "COMMAND_MEETING_FINALIZE",
    "COMMAND_MEETING_GET",
    "COMMAND_MEETING_EXPORT",
    "COMMAND_TRANSCRIPT_SEGMENT_UPDATE",
    "COMMAND_IMPORT_MEDIA",
    "COMMAND_MEETING_RETRANSCRIBE",
    "COMMAND_MODELS_DOWNLOAD",
    "COMMAND_SETTINGS_GET",
    "COMMAND_SETTINGS_UPDATE",
    "COMMAND_SETUP_STATUS",
    "DEFAULT_RECENT_ENTRIES_LIMIT",
    "EVENT_CAPTURE_DEVICE_CHANGED",
    "EVENT_CAPTURE_STARTED",
    "EVENT_CAPTURE_STOPPED",
    "EVENT_CAPTURE_SUGGEST_STOP",
    "EVENT_ENHANCE_FAILED",
    "EVENT_ENHANCE_READY",
    "EVENT_ENHANCE_STARTED",
    "EVENT_GOOGLE_CONNECT_COMPLETED",
    "EVENT_MEETING_DETECTED",
    "EVENT_MODELS_DOWNLOAD_COMPLETED",
    "EVENT_MODELS_DOWNLOAD_FAILED",
    "EVENT_MODELS_DOWNLOAD_PROGRESS",
    "EVENT_TRANSCRIPT_FINAL",
    "EVENT_TRANSCRIPT_PARTIAL",
    "MAX_MESSAGE_BYTES",
    "PROTOCOL_VERSION",
    "AskQueryCommandPayload",
    "AudioDeviceDescription",
    "CaptureStartCommandPayload",
    "CaptureStopCommandPayload",
    "DetectionDismissCommandPayload",
    "DevicesListCommandPayload",
    "Envelope",
    "EnvelopeKind",
    "EventBroadcastHub",
    "GoogleConnectCommandPayload",
    "KeysSaveCommandPayload",
    "KeysValidateCommandPayload",
    "LedgerSummaryCommandPayload",
    "MeetingFinalizeCommandPayload",
    "MeetingGetCommandPayload",
    "MeetingsListCommandPayload",
    "ModelsDownloadCommandPayload",
    "ProtocolError",
    "ProtocolErrorCode",
    "SettingsGetCommandPayload",
    "SettingsUpdateCommandPayload",
    "SetupStatusCommandPayload",
    "build_capture_device_changed_payload",
    "build_capture_started_payload",
    "build_capture_stopped_payload",
    "build_capture_suggest_stop_payload",
    "build_devices_list_payload",
    "build_enhance_failed_payload",
    "build_enhance_ready_payload",
    "build_enhance_started_payload",
    "build_google_connect_completed_payload",
    "build_heartbeat_payload",
    "build_meeting_detected_payload",
    "build_models_download_completed_payload",
    "build_models_download_failed_payload",
    "build_models_download_progress_payload",
    "build_transcript_final_payload",
    "build_transcript_partial_payload",
    "error_reply",
    "parse_envelope",
]
