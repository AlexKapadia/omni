"""Typed error taxonomy for the Naomi voice pipeline.

Purpose: the three ways voice can refuse or fail, as distinct types so the
command dispatcher maps each to an honest, structured reply — and so tests
can assert the EXACT failure mode (never a bare Exception).
Pipeline position: raised by ``engine.voice`` modules; caught only by the
command dispatcher and the streamer's supervision.

Security invariant: messages carried by these errors are already redacted
by the raiser — no key material ever rides an exception (claude.md §5.6).
"""


class VoiceEgressBlockedError(Exception):
    """The kill switch is engaged: no external voice call may be made.

    Fail closed on egress only — capture, transcription and the pool visual
    keep working; the UI surfaces this message verbatim.
    """

    def __init__(self) -> None:
        super().__init__(
            "The kill switch is engaged, so Naomi's voice is paused. "
            "Everything local keeps working on this device."
        )


class VoiceNotConfiguredError(Exception):
    """Cartesia credentials are missing — refuse rather than guess.

    The message names the env var, NEVER any value (secrets discipline).
    """


class VoiceProviderError(Exception):
    """The provider connection/stream failed. Message is pre-redacted."""
