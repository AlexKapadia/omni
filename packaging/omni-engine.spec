# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: the Omni engine sidecar (onedir, lean, console hidden).

What ships: the FULL `engine` package (collected generically, so moving
modules inside the package — e.g. the engine/wiring/ reshuffle — needs no
spec change), the SQL migrations, and every LIGHT runtime dependency from
pyproject.toml (fastapi/uvicorn/aiosqlite/pydantic, onnxruntime for VAD +
bge-small, sqlite-vec incl. its vec0 loadable extension DLL, provider
SDKs, tokenizers, watchdog, audio capture).

What deliberately does NOT ship: the heavy STT stack (torch CUDA + NeMo,
multi-GB). It installs at first run into %LOCALAPPDATA%/Omni/pyenv (see
packaging/install-stt-runtime.ps1); the runtime hook
pyi_rth_omni_stt_pyenv.py attaches it, and the engine's lazy imports +
stt_ready heartbeat handle absence honestly (fail closed, never crash).
Model weights (Silero VAD, Parakeet .nemo) are ALSO not bundled — the
engine downloads them to %LOCALAPPDATA%/Omni/models with SHA256
verification against packaging/model-manifest.json.

Build (repo root):
    uv run --with pyinstaller pyinstaller packaging/omni-engine.spec \
        --noconfirm --distpath packaging/dist --workpath packaging/build

Security invariants:
- console=False: no console window flashes at the user (the Tauri
  supervisor pipes stdout/stderr into the app log regardless).
- No secrets are read or embedded at build time.
"""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    copy_metadata,
)

SPEC_DIR = Path(SPECPATH).resolve()  # packaging/
REPO_ROOT = SPEC_DIR.parent

# --- Application code --------------------------------------------------------
# Collect the engine package GENERICALLY: every submodule becomes a hidden
# import so dynamically-reached modules (factory seams, wiring) are included
# no matter how files move inside the package.
hiddenimports = collect_submodules("engine")

# uvicorn selects its event-loop / http / websocket implementations from
# strings at runtime — static analysis cannot see them.
hiddenimports += collect_submodules("uvicorn")

# --- Data files ---------------------------------------------------------------
# Migrations ship next to the code. Two destinations on purpose:
# engine code resolves the dir relative to a module __file__
# (Path(__file__).parent.parent/"migrations"); today that lands at
# _internal/migrations, and after the queued engine/wiring/ package move it
# would resolve one level deeper (_internal/engine/migrations). Seven tiny
# SQL files duplicated beat a boot-time crash on the pending merge.
datas = [
    (str(REPO_ROOT / "migrations"), "migrations"),
    (str(REPO_ROOT / "migrations"), "engine/migrations"),
]
binaries = []

# sqlite-vec ships its loadable extension (vec0.dll) as package data — the
# vector store loads it via the sqlite_vec python package at runtime.
vec_datas, vec_binaries, vec_hidden = collect_all("sqlite_vec")
datas += vec_datas
binaries += vec_binaries
hiddenimports += vec_hidden

# Provider SDKs read their own version via importlib.metadata at import time.
for dist_name in ("google-genai", "groq", "anthropic"):
    datas += copy_metadata(dist_name)

a = Analysis(
    # Entry: engine/server.py run as a top-level script == the
    # `python -m engine.server` dev semantics (its __main__ guard calls
    # main()); pathex makes the `engine` package importable from source.
    [str(REPO_ROOT / "engine" / "server.py")],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    # Attaches the optional first-run STT runtime (torch+NeMo) from
    # %LOCALAPPDATA%/Omni/pyenv — appended to sys.path, bundle always wins.
    runtime_hooks=[str(SPEC_DIR / "pyi_rth_omni_stt_pyenv.py")],
    # Lean-bundle guarantee: even when the build venv has the `stt` extra
    # installed, the heavy stack must NEVER be frozen in.
    excludes=[
        "torch",
        "torchaudio",
        "torchvision",
        "nemo",
        "nemo_toolkit",
        "pytorch_lightning",
        "lightning",
        "matplotlib",
        "IPython",
        "jupyter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="omni-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Console hidden: never flash a window. Piped stdout/stderr from the
    # Tauri supervisor still reach Python's logging (handles are inherited).
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPEC_DIR / "omni-engine.ico"),
    version=str(SPEC_DIR / "omni-engine-version-info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="omni-engine",
)
