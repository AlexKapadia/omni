"""PyInstaller runtime hook: attach the optional STT runtime (torch + NeMo).

Purpose: the installer ships a LEAN frozen engine — the multi-GB STT
stack (torch CUDA + NeMo) is NOT bundled. The first-run wizard installs
it into a private, per-user environment at %LOCALAPPDATA%/Omni/pyenv
(see packaging/install-stt-runtime.ps1). This hook runs before any
application import inside the frozen engine and APPENDS that
environment's site-packages to sys.path, so the engine's existing lazy
imports (engine/stt/parakeet_nemo_transcriber.py) find torch/nemo when
installed and honestly report stt_ready=false when not.

Ordering invariant: the path is APPENDED, never prepended — every module
frozen into the bundle (the tested versions) always wins over anything
in the side environment; the side environment only supplies modules the
bundle deliberately omits.

Security: reads a fixed per-user directory only (no env-var override in
the frozen app, so a hostile environment variable cannot inject a search
path); nothing is imported here, no network, fail-open to "STT absent".
"""

import os
import sys
from pathlib import Path


def _attach_stt_runtime() -> None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return
    pyenv = Path(local_app_data) / "Omni" / "pyenv"
    # The installer writes this marker LAST, after a verified install —
    # a half-installed environment is never attached (fail closed).
    if not (pyenv / ".stt-runtime-complete").is_file():
        return
    site_packages = pyenv / "Lib" / "site-packages"
    if site_packages.is_dir():
        sys.path.append(str(site_packages))


_attach_stt_runtime()
