"""Decision table for the auto-start rules engine.

Pins deny-by-default (unknown sources NEVER auto-start, even when listed in
auto_start_sources), the three-gate auto-start rule, one-suggestion-per-app-
session dedup with grace, dismissal cooldowns, mic corroboration (exact-name
mapping — TeamSpeak must not corroborate Teams), quiet-while-capturing, and
the SuggestStop grace flow.
"""

import pytest

from engine.detect.auto_start_rules_engine import AutoStartRulesEngine, DetectionRuleSettings
from engine.detect.detection_signal_types import (
    SOURCE_ADHOC_LOOPBACK,
    SOURCE_BROWSER_MEET,
    SOURCE_DISCORD,
    SOURCE_TEAMS,
    SOURCE_ZOOM,
    AdHocCallSuspected,
    AutoStart,
    MeetingAppDetected,
    MicrophoneInUse,
    SuggestCapture,
    SuggestStop,
)


def mad(source: str, confidence: float, evidence: str = "window_title") -> MeetingAppDetected:
    return MeetingAppDetected(
        source=source,
        app=f"{source}.exe",
        window_title_hint=None,
        confidence=confidence,
        evidence=evidence,
    )


def mic(app_name: str) -> MicrophoneInUse:
    return MicrophoneInUse(app_name=app_name, is_packaged=False)


def adhoc(confidence: float = 0.7) -> AdHocCallSuspected:
    return AdHocCallSuspected(
        source=SOURCE_ADHOC_LOOPBACK,
        speech_seconds_in_window=15.0,
        rolling_window_s=30.0,
        confidence=confidence,
    )


# --- suggestion basics --------------------------------------------------------


def test_strong_signal_suggests_with_source_dedupe_key() -> None:
    engine = AutoStartRulesEngine()
    decisions = engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], capture_active=False)
    assert decisions == [
        SuggestCapture(
            reason=f"{SOURCE_ZOOM} meeting activity detected",
            source=SOURCE_ZOOM,
            confidence=0.9,
            dedupe_key=SOURCE_ZOOM,
        )
    ]


def test_suggest_threshold_is_boundary_exact() -> None:
    at = AutoStartRulesEngine()
    assert len(at.update(0.0, [mad(SOURCE_ZOOM, 0.6)], False)) == 1  # == threshold fires
    under = AutoStartRulesEngine()
    assert under.update(0.0, [mad(SOURCE_ZOOM, 0.59)], False) == []


def test_one_suggestion_per_app_session_across_repeated_polls() -> None:
    engine = AutoStartRulesEngine()
    assert len(engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], False)) == 1
    for t in (3.0, 6.0, 9.0, 300.0):  # continuous presence: still one session
        assert engine.update(t, [mad(SOURCE_ZOOM, 0.9)], False) == []


def test_enumeration_flicker_within_grace_does_not_retrigger() -> None:
    engine = AutoStartRulesEngine()  # session_end_grace_s = 10
    assert len(engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], False)) == 1
    assert engine.update(5.0, [], False) == []  # blip: absent < grace
    assert engine.update(8.0, [mad(SOURCE_ZOOM, 0.9)], False) == []  # same session


def test_new_session_after_grace_expiry_suggests_again() -> None:
    engine = AutoStartRulesEngine()
    assert len(engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], False)) == 1
    assert engine.update(11.0, [], False) == []  # 11s absent > 10s grace: session over
    assert len(engine.update(12.0, [mad(SOURCE_ZOOM, 0.9)], False)) == 1  # new meeting


def test_multiple_sources_decide_in_deterministic_sorted_order() -> None:
    engine = AutoStartRulesEngine()
    decisions = engine.update(
        0.0, [mad(SOURCE_ZOOM, 0.9), mad(SOURCE_BROWSER_MEET, 0.65)], False
    )
    assert [d.source for d in decisions if isinstance(d, SuggestCapture)] == [
        SOURCE_BROWSER_MEET,
        SOURCE_ZOOM,
    ]


def test_adhoc_loopback_signal_suggests() -> None:
    engine = AutoStartRulesEngine()
    decisions = engine.update(0.0, [adhoc()], False)
    assert len(decisions) == 1
    assert isinstance(decisions[0], SuggestCapture)
    assert decisions[0].source == SOURCE_ADHOC_LOOPBACK


# --- dismissal ---------------------------------------------------------------


def test_dismissed_key_is_suppressed_for_cooldown_then_recovers() -> None:
    engine = AutoStartRulesEngine()  # dismissed_cooldown_s = 1800
    assert len(engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], False)) == 1
    engine.dismiss(SOURCE_ZOOM, 0.0)
    assert engine.update(5.0, [mad(SOURCE_ZOOM, 0.9)], False) == []  # same session
    assert engine.update(16.0, [], False) == []  # session expires
    # New session while still inside the dismissal cooldown: stays quiet.
    assert engine.update(20.0, [mad(SOURCE_ZOOM, 0.9)], False) == []
    assert engine.update(31.0, [], False) == []  # that session expires too
    # New session after the cooldown: suggestion allowed again.
    assert len(engine.update(1801.0, [mad(SOURCE_ZOOM, 0.9)], False)) == 1


# --- mic corroboration ---------------------------------------------------------


def test_weak_process_signal_alone_stays_silent() -> None:
    engine = AutoStartRulesEngine()
    assert engine.update(0.0, [mad(SOURCE_DISCORD, 0.3, "process")], False) == []


def test_mic_corroboration_lifts_weak_signal_to_suggestion() -> None:
    engine = AutoStartRulesEngine()  # boost 0.4: 0.3 + 0.4 = 0.7 >= 0.6
    decisions = engine.update(
        0.0, [mad(SOURCE_DISCORD, 0.3, "process"), mic("Discord.exe")], False
    )
    assert len(decisions) == 1
    assert isinstance(decisions[0], SuggestCapture)
    assert decisions[0].confidence == pytest.approx(0.7)


def test_teamspeak_mic_use_does_not_corroborate_teams() -> None:
    """Exact-name mapping: the substring near-miss must stay silent."""
    engine = AutoStartRulesEngine()
    decisions = engine.update(
        0.0, [mad(SOURCE_TEAMS, 0.3, "process"), mic("TeamSpeak.exe")], False
    )
    assert decisions == []


def test_browser_mic_corroborates_browser_source_capped() -> None:
    engine = AutoStartRulesEngine()
    decisions = engine.update(
        0.0, [mad(SOURCE_BROWSER_MEET, 0.65), mic("chrome.exe")], False
    )
    assert isinstance(decisions[0], SuggestCapture)
    assert decisions[0].confidence == pytest.approx(0.95)  # 0.65+0.4 capped at 0.95


def test_mic_in_use_alone_is_never_a_meeting() -> None:
    engine = AutoStartRulesEngine()
    assert engine.update(0.0, [mic("Zoom.exe")], False) == []  # corroboration-only
    assert engine.update(3.0, [mic("dictation-app.exe")], False) == []


# --- auto-start: deny by default ----------------------------------------------


def test_auto_start_denied_by_default_even_at_full_confidence() -> None:
    engine = AutoStartRulesEngine()  # default settings: auto_start_sources empty
    decisions = engine.update(0.0, [mad(SOURCE_ZOOM, 1.0)], False)
    assert len(decisions) == 1
    assert isinstance(decisions[0], SuggestCapture)  # suggest, never auto-start


def test_opted_in_known_source_auto_starts_at_boundary() -> None:
    settings = DetectionRuleSettings(auto_start_sources=frozenset({SOURCE_ZOOM}))
    engine = AutoStartRulesEngine(settings)
    decisions = engine.update(0.0, [mad(SOURCE_ZOOM, 0.85)], False)  # == threshold
    assert decisions == [
        AutoStart(
            reason=f"{SOURCE_ZOOM} meeting detected (user-enabled auto-start)",
            source=SOURCE_ZOOM,
            confidence=0.85,
        )
    ]


def test_opted_in_source_below_auto_threshold_falls_back_to_suggest() -> None:
    settings = DetectionRuleSettings(auto_start_sources=frozenset({SOURCE_ZOOM}))
    engine = AutoStartRulesEngine(settings)
    decisions = engine.update(0.0, [mad(SOURCE_ZOOM, 0.84)], False)
    assert len(decisions) == 1
    assert isinstance(decisions[0], SuggestCapture)


def test_unknown_source_never_auto_starts_even_if_opted_in() -> None:
    """THE deny-by-default case: an unrecognised source string, explicitly
    listed in auto_start_sources at confidence 0.99, may only SUGGEST."""
    settings = DetectionRuleSettings(auto_start_sources=frozenset({"holo_deck"}))
    engine = AutoStartRulesEngine(settings)
    decisions = engine.update(
        0.0,
        [
            MeetingAppDetected(
                source="holo_deck",
                app="holodeck.exe",
                window_title_hint=None,
                confidence=0.99,
                evidence="window_title",
            )
        ],
        False,
    )
    assert len(decisions) == 1
    assert isinstance(decisions[0], SuggestCapture)


def test_disabled_source_yields_no_decisions_at_all() -> None:
    settings = DetectionRuleSettings(
        source_enabled={SOURCE_ZOOM: False},
        auto_start_sources=frozenset({SOURCE_ZOOM}),
    )
    engine = AutoStartRulesEngine(settings)
    assert engine.update(0.0, [mad(SOURCE_ZOOM, 1.0)], False) == []


# --- capture interplay: quiet rules + suggest-stop ------------------------------


def test_capturing_suppresses_all_suggestions_and_marks_sessions_handled() -> None:
    engine = AutoStartRulesEngine()
    assert engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], capture_active=True) == []
    # Capture stops while the same meeting continues: still no suggestion —
    # the session was covered by the capture the user already ran.
    assert engine.update(3.0, [mad(SOURCE_ZOOM, 0.9)], capture_active=False) == []


def test_suggest_stop_after_grace_once_then_silent() -> None:
    engine = AutoStartRulesEngine()  # suggest_stop_grace_s = 60
    assert engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], True) == []
    assert engine.update(10.0, [mad(SOURCE_ZOOM, 0.9)], True) == []  # last seen 10
    assert engine.update(30.0, [], True) == []  # absent 20s < 60s grace
    assert engine.update(69.0, [], True) == []  # absent 59s: just under
    decisions = engine.update(70.0, [], True)  # absent exactly 60s: fires
    assert decisions == [SuggestStop(reason="meeting app closed while capture is still running")]
    assert engine.update(120.0, [], True) == []  # one hint per capture, not a nag


def test_meeting_reappearing_during_capture_rearms_suggest_stop() -> None:
    engine = AutoStartRulesEngine()
    engine.update(0.0, [mad(SOURCE_ZOOM, 0.9)], True)
    assert engine.update(61.0, [], True) != []  # first stop hint
    engine.update(100.0, [mad(SOURCE_ZOOM, 0.9)], True)  # meeting is back
    assert engine.update(161.0, [], True) != []  # its ending hints again


def test_no_suggest_stop_without_meeting_evidence_or_capture() -> None:
    engine = AutoStartRulesEngine()
    assert engine.update(0.0, [], True) == []  # capturing, never saw a meeting
    assert engine.update(100.0, [], True) == []
    engine2 = AutoStartRulesEngine()
    engine2.update(0.0, [mad(SOURCE_ZOOM, 0.9)], True)
    engine2.update(5.0, [], False)  # capture ended -> per-capture state resets
    assert engine2.update(120.0, [], True) == []  # new capture: no stale hint


# --- settings validation ---------------------------------------------------------


@pytest.mark.parametrize(
    "bad_settings_kwargs",
    [
        {"suggest_min_confidence": 0.0},
        {"suggest_min_confidence": 1.1},
        {"auto_start_min_confidence": -0.5},
        {"mic_corroboration_boost": 1.5},
        {"dismissed_cooldown_s": -1.0},
        {"session_end_grace_s": -0.1},
        {"suggest_stop_grace_s": -5.0},
    ],
)
def test_degenerate_settings_rejected(bad_settings_kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        DetectionRuleSettings(**bad_settings_kwargs)  # type: ignore[arg-type]
