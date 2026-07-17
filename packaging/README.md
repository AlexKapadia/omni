# Omni packaging — how the product ships

This folder turns the dev checkout into an installable Windows product:
a **PyInstaller-frozen engine sidecar** wrapped by a **Tauri 2 bundle**
(NSIS `.exe` + `.msi`), auto-updated from **GitHub Releases** with
signature-verified artifacts.

---

## 1. What the installer contains (and deliberately does not)

| Piece | Ships in installer? | Size | How it arrives |
|---|---|---|---|
| Tauri shell (`Omni.exe`, WebView2 UI) | yes | ~15 MB | installer |
| Frozen engine (`omni-engine/`, PyInstaller onedir) | yes | ~133 MB on disk | installer (bundle resource) |
| SQL migrations | yes (inside the engine bundle) | ~KB | installer |
| sqlite-vec loadable extension (`vec0.dll`) | yes (inside `_internal/sqlite_vec/`) | 0.3 MB | installer |
| STT model weights (Silero VAD 2.3 MB, Parakeet-TDT `.nemo` 2.47 GB) | **no** | ~2.5 GB | engine downloads to `%LOCALAPPDATA%\Omni\models` with SHA256 verification against `packaging/model-manifest.json` (`engine/stt/model_weights_downloader.py`) |
| STT Python runtime (torch CUDA 12.8 + NeMo) | **no** | ~8 GB installed | first-run install into `%LOCALAPPDATA%\Omni\pyenv` via `install-stt-runtime.ps1` (below) |

The engine boots and serves `/health`, notes, vault, RAG, router, and
approval features **without** the STT stack; `stt_ready` in the WS
heartbeat stays honestly `false` until models + runtime are present
(fail closed, never a crash).

### Installed layout (NSIS/MSI, per-user)

```
<install dir>\
  Omni.exe                      # Tauri shell
  omni-engine\                  # bundle resource (PyInstaller onedir)
    omni-engine.exe             # spawned by the shell's sidecar supervisor
    _internal\...               # frozen python + deps + migrations + vec0.dll
  stt-runtime\
    install-stt-runtime.ps1     # first-run STT installer (wizard invokes)
    stt-runtime-requirements.txt# locked versions (exported from uv.lock)
```

`resolve_engine_command()` in `apps/ui/src-tauri/src/engine_sidecar.rs`
is THE one dev/prod seam: dev runs `uv run python -m engine.server`,
release runs `<exe dir>\omni-engine\omni-engine.exe`.

---

## 2. Heavy STT dependencies — chosen strategy and why

**Chosen: (a) first-run install into a private, per-user environment at
`%LOCALAPPDATA%\Omni\pyenv`, driven by `packaging/install-stt-runtime.ps1`.**

How it works:

1. The script resolves `uv` (an existing one on PATH, else downloads the
   pinned release and **verifies its published SHA256** before running it).
2. `uv venv --python 3.11 %LOCALAPPDATA%\Omni\pyenv` — uv fetches a
   managed CPython 3.11 (same minor as the frozen engine, so binary
   wheels are ABI-compatible).
3. `uv pip install -r stt-runtime-requirements.txt` — the requirements
   file is **exported from the repo's `uv.lock`** (`uv export --frozen
   --extra stt --no-dev --no-emit-project --no-hashes`), so users get the
   EXACT versions the engine was tested against (e.g. `torch==2.11.0+cu128`,
   `nemo-toolkit==2.7.3`, `numpy==2.4.6` — identical to the version frozen
   into the bundle). The PyTorch CUDA 12.8 index is passed explicitly.
4. A real `import torch; import nemo.collections.asr` verification runs in
   the new environment; only then is the completion marker
   `pyenv\.stt-runtime-complete` written (**marker last — fail closed**).
5. The frozen engine's runtime hook (`pyi_rth_omni_stt_pyenv.py`)
   **appends** `pyenv\Lib\site-packages` to `sys.path` at boot **only when
   the marker exists**. Appended, never prepended: bundled (tested)
   modules always win; the side environment only supplies what the bundle
   deliberately omits. The engine's existing lazy imports then find
   torch/NeMo and `stt_ready` flips true on next engine start.

Why (a) beat (b) (a second downloadable bundle):

- **GitHub Releases caps single assets at 2 GB** — a torch-CUDA bundle
  cannot ship as one asset; we'd have to build, split, hash, host and
  re-assemble multi-part archives ourselves, and rebuild them for every
  torch/NeMo bump.
- pip/uv already solve download-resume, wheel verification, dependency
  closure, and caching; re-implementing that is pure liability.
- Locked requirements give **the same determinism a frozen bundle would**
  (versions pinned from `uv.lock`) without redistributing NVIDIA's CUDA
  binaries ourselves.
- Cost: first-run needs Python-ecosystem downloads (~4 GB download,
  ~8 GB on disk) — the same order as the unavoidable model weights, and
  it happens once, with progress surfaced.

### Interface for the onboarding wizard (first-run lane)

- **Invoke:** `powershell -ExecutionPolicy Bypass -File "<install dir>\stt-runtime\install-stt-runtime.ps1"`
  (no admin required; everything lands under `%LOCALAPPDATA%\Omni`).
- **Progress:** one JSON object per stdout line:
  `{"phase":"preflight|uv|venv|install|verify|complete|error","message":"...","percent":0-100|null}`.
  `install`-phase lines relay uv's own output with `percent: null`.
- **Result:** exit `0` = installed + verified (idempotent — re-running
  exits 0 fast). Non-zero = not installed, marker absent, safe to retry.
- **Model weights** are a separate, existing surface: the engine's
  `model_weights_downloader` pulls to `%LOCALAPPDATA%\Omni\models` with
  SHA256 checks against `packaging/model-manifest.json`.
- **After success:** restart the engine (the sidecar supervisor restarts
  it automatically if killed) — the runtime hook attaches the venv at
  process start.

---

## 3. Build locally

Prereqs (this repo's dev box already has all of them): `uv`, Node 22 +
pnpm 10, Rust (MSVC target — use the portable MSVC env), WebView2.

```powershell
# 0) icons (only when the logo geometry changes)
uv run --no-project --with pillow python packaging/generate_omni_icon.py

# 1) engine sidecar (onedir -> packaging/dist/omni-engine/)
uv sync    # lean: the stt extra is NOT installed and NOT bundled
uv run --with pyinstaller pyinstaller packaging/omni-engine.spec --noconfirm --distpath packaging/dist --workpath packaging/build

# 2) boot-test the frozen engine (the true gate)
#    run it with OMNI_ENGINE_PORT/OMNI_DB_PATH/OMNI_MODELS_DIR pointing at a
#    scratch dir and assert GET /health -> 200 {"status":"ok",...}

# 3) installer (NSIS .exe + .msi). Cargo needs the MSVC env; never Git Bash.
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
# TAURI_SIGNING_PRIVATE_KEY accepts a file path OR the key content (Tauri v2
# has no separate _PATH variable).
$env:TAURI_SIGNING_PRIVATE_KEY = "$env:LOCALAPPDATA\Omni\updater-signing-key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
cmd /c "call %LOCALAPPDATA%\portable-msvc\msvc\setup_x64.bat && cd /d <repo>\apps\ui && pnpm tauri build"
```

Artifacts land in `apps/ui/src-tauri/target/release/bundle/`
(`nsis/Omni_<version>_x64-setup.exe`, `msi/Omni_<version>_x64_en-US.msi`,
plus `.sig` updater signatures for each).

Note: `pnpm tauri build` bundles the **current contents of
`packaging/dist/omni-engine`** — rebuild the sidecar first when engine
code changed.

---

## 4. Auto-update (tauri-plugin-updater + GitHub Releases)

- **Endpoint** (in `tauri.conf.json` → `plugins.updater.endpoints`):
  `https://github.com/bhaskaraanjana/omni/releases/latest/download/latest.json`
- **Signing:** every installer is minisign-signed at build time; the
  public key is pinned in `tauri.conf.json` and the app **refuses any
  unsigned/mis-signed update** (fail closed).
- **Private key location (this box):** `%LOCALAPPDATA%\Omni\updater-signing-key`
  (+ `.pub`). **NEVER in the repo** — `.gitignore` carries a
  belt-and-braces `*updater-signing-key*` pattern. Losing this key means
  installed apps can never auto-update again: back it up to a password
  manager.
- **Check cadence:** once per launch, release builds only
  (`updater_launch_check::spawn_launch_check`). Offline → a single
  `updater:error` event, never a startup failure.

### Event/command surface (for Settings + onboarding UI)

Events emitted by the shell (stable names):

| Event | Payload |
|---|---|
| `updater:checking` | — |
| `updater:update-available` | `{ version, currentVersion, notes }` |
| `updater:up-to-date` | — |
| `updater:error` | `{ message }` |
| `updater:download-progress` | `{ downloadedBytes, totalBytes\|null }` |
| `updater:installed` | — (then invoke `updater_restart_app`) |

Commands (Tauri `invoke`): `updater_download_and_install` (re-checks,
downloads, verifies, installs; emits progress) and `updater_restart_app`.

---

## 5. Release via tag (CI)

1. Bump the version in `apps/ui/src-tauri/tauri.conf.json` **and**
   `pyproject.toml` **and** `packaging/omni-engine-version-info.txt`.
2. `git tag v<version> && git push origin v<version>`.
3. `.github/workflows/release.yml` runs a **matrix** on `windows-latest`,
   `macos-latest`, and `ubuntu-latest`: verifies the tag matches the app
   version → builds the lean sidecar → **boot-tests `/health` for real** →
   builds + signs platform bundles (NSIS/MSI on Windows; DMG/app on macOS;
   deb/AppImage on Linux via tauri-action) → creates a **draft** GitHub Release
   with installers, `.sig` files, and the `latest.json` updater manifest.
4. Inspect the draft, then **publish** — publishing is what makes
   `releases/latest/download/latest.json` live, which is when installed
   apps start updating.

### STT runtime on macOS/Linux

Windows uses `stt-runtime/install-stt-runtime.ps1`. macOS and Linux use
`packaging/install-stt-runtime.sh` with the same locked requirements
exported from `uv.lock`. The private venv lands under the platform
equivalent of `%LOCALAPPDATA%\Omni\pyenv`.

### One-time repo secret setup (manual — an agent must never do this)

Create the repo secret `TAURI_SIGNING_PRIVATE_KEY` with the **contents**
of `%LOCALAPPDATA%\Omni\updater-signing-key`:

```powershell
gh secret set TAURI_SIGNING_PRIVATE_KEY --repo bhaskaraanjana/omni --body (Get-Content "$env:LOCALAPPDATA\Omni\updater-signing-key" -Raw)
```

The key has an empty password (generated with `--ci`), so
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` is set to `""` in the workflow.

---

## 6. First-run flow (what the onboarding wizard orchestrates)

1. Installer finishes → app launches → sidecar supervisor spawns the
   frozen engine → `/health` 200, heartbeat reports `stt_ready: false`.
2. Wizard: vault path, API keys → DPAPI, Google connect (existing engine
   surfaces).
3. Wizard: **model download** — engine downloads Silero VAD (2.3 MB) +
   Parakeet (2.47 GB) with SHA256 verification and progress.
4. Wizard: **STT runtime install** — run `stt-runtime\install-stt-runtime.ps1`,
   render the JSON progress stream (~4 GB download / ~8 GB disk), then
   restart the engine (kill it; the supervisor respawns with the venv
   attached).
5. Heartbeat flips `stt_ready: true` → capture unlocked.

---

## 7. What a contributor needs

- **Windows 10/11** (full capture), or **macOS / Linux** for shell + mic work
  (loopback may need BlackHole or PipeWire monitor).
- `uv`, Node 22 + pnpm 10, Rust stable (MSVC on Windows), WebView2 (Windows).
- No secrets: dev builds run unsigned locally (set
  `TAURI_SIGNING_PRIVATE_KEY` only when you need updater artifacts,
  or generate your own key with `pnpm tauri signer generate --ci -w <path>`).
- NSIS/WiX are fetched by the Tauri bundler automatically on first build.
- Regenerate `stt-runtime-requirements.txt` whenever `uv.lock` changes
  the stt extra: `uv export --frozen --extra stt --no-dev
  --no-emit-project --no-hashes -o packaging/stt-runtime-requirements.txt`.

## 8. Known gaps / honest notes

- **Installer language:** the brief asked for en-GB; NSIS ships a single
  "English" language pack (no en-GB variant) and the MSI uses WiX's
  en-US culture strings. Copy is English; a true en-GB locale would need
  custom NSI/WXL locale files.
- **CPU-only boxes:** the STT runtime installs the CUDA 12.8 torch build
  (per the lock). It imports and runs on machines without an NVIDIA GPU
  (engine falls back to CPU float32), but carries CUDA-sized downloads;
  a slimmer CPU-only flavour is a follow-up.
- **Code signing (Authenticode):** installers are minisign-signed for the
  updater but not Authenticode-signed — SmartScreen will warn on first
  download until a certificate is bought and wired into the bundler.
- **Cosmetic exe name:** the Cargo package is `omni-ui`, so the raw build
  artifact is `omni-ui.exe`; the installed launcher is `Omni.exe`
  (`productName`). Sidecar resolution is name-independent, so this is
  purely cosmetic — left as-is.
- The engine bundles `migrations/` at BOTH `_internal/migrations` and
  `_internal/engine/migrations` as a belt-and-braces margin for the
  `engine/wiring/` package move (now landed, path pinned to repo root in
  `server_default_service_factories.py` + regression test). The dual copy
  is harmless; a follow-up can drop the redundant one.
