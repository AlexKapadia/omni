<#
.SYNOPSIS
Omni first-run STT runtime installer: torch (CUDA 12.8) + NeMo into a
private per-user environment at %LOCALAPPDATA%\Omni\pyenv.

.DESCRIPTION
The shipped Omni engine is LEAN — the multi-GB STT stack is not bundled.
This script installs it once, from the EXACT versions the engine was
tested against (stt-runtime-requirements.txt, exported from the repo's
uv.lock), into %LOCALAPPDATA%\Omni\pyenv. The frozen engine attaches that
environment via its runtime hook (packaging/pyi_rth_omni_stt_pyenv.py)
and flips stt_ready=true on its next start.

Progress protocol (consumed by the onboarding wizard): one JSON object
per stdout line: {"phase":"preflight|uv|venv|install|verify|complete|error",
"message":"...","percent":0-100|null}. Exit 0 = installed and verified;
any other exit = not installed (and the completion marker is absent —
fail closed, a half-install is never attached).

Idempotent: exits 0 immediately if the completion marker already exists.

Security:
- uv (the installer tool) is downloaded PINNED to a version and verified
  against its published SHA256 before first use; an existing uv on PATH
  is preferred and nothing is downloaded.
- Installs only from pypi.org + download.pytorch.org over TLS, versions
  pinned by the requirements file.
- Everything lands under the per-user %LOCALAPPDATA%\Omni — no admin, no
  machine-wide writes.
#>
[CmdletBinding()]
param(
    # Directory this script + stt-runtime-requirements.txt live in.
    [string]$ResourceDir = $PSScriptRoot,
    [string]$OmniDir = (Join-Path $env:LOCALAPPDATA "Omni")
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Pinned uv release (matches the version the build box validated).
$UvVersion = "0.11.6"
$UvZipUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"
$UvShaUrl = "$UvZipUrl.sha256"
$PythonVersion = "3.11"   # Must match the frozen engine's interpreter ABI.

$PyenvDir = Join-Path $OmniDir "pyenv"
$ToolsDir = Join-Path $OmniDir "tools"
$Marker = Join-Path $PyenvDir ".stt-runtime-complete"
$Requirements = Join-Path $ResourceDir "stt-runtime-requirements.txt"

function Emit([string]$Phase, [string]$Message, $Percent = $null) {
    # Single-line JSON progress protocol for the wizard.
    $obj = [ordered]@{ phase = $Phase; message = $Message; percent = $Percent }
    Write-Output ($obj | ConvertTo-Json -Compress)
}

function Fail([string]$Message) {
    # Fail closed: never leave a marker implying a working install.
    if (Test-Path $Marker) { Remove-Item $Marker -Force -Confirm:$false }
    Emit "error" $Message
    exit 1
}

function Resolve-Uv {
    # Prefer an existing uv (dev boxes); otherwise download pinned+verified.
    $existing = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $existing) { return $existing.Source }
    $uvExe = Join-Path $ToolsDir "uv.exe"
    if (Test-Path $uvExe) { return $uvExe }

    Emit "uv" "downloading uv $UvVersion" 5
    New-Item -ItemType Directory -Force $ToolsDir | Out-Null
    $zip = Join-Path $ToolsDir "uv.zip"
    Invoke-WebRequest -Uri $UvZipUrl -OutFile $zip -UseBasicParsing
    $expected = ((Invoke-WebRequest -Uri $UvShaUrl -UseBasicParsing).Content -split "\s+")[0].Trim().ToLower()
    $actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        Remove-Item $zip -Force -Confirm:$false
        Fail "uv download SHA256 mismatch (expected $expected, got $actual) - refusing to run it"
    }
    Expand-Archive -Path $zip -DestinationPath $ToolsDir -Force
    Remove-Item $zip -Force -Confirm:$false
    if (-not (Test-Path $uvExe)) { Fail "uv.exe missing after extraction" }
    return $uvExe
}

# --- preflight ----------------------------------------------------------------
if (Test-Path $Marker) {
    Emit "complete" "STT runtime already installed" 100
    exit 0
}
if (-not (Test-Path $Requirements)) {
    Fail "requirements file not found: $Requirements"
}
Emit "preflight" "installing STT runtime (torch CUDA 12.8 + NeMo, ~8 GB) to $PyenvDir" 0

try {
    $uv = Resolve-Uv

    # --- venv (uv fetches a managed CPython 3.11 if the box has none) --------
    Emit "venv" "creating Python $PythonVersion environment" 10
    & $uv venv --python $PythonVersion --allow-existing $PyenvDir
    if ($LASTEXITCODE -ne 0) { Fail "uv venv failed (exit $LASTEXITCODE)" }
    $pyenvPython = Join-Path $PyenvDir "Scripts\python.exe"

    # --- install (locked versions; torch +cu128 needs the PyTorch index) -----
    Emit "install" "downloading + installing pinned packages (largest step; several GB)" 20
    & $uv pip install --python $pyenvPython -r $Requirements `
        --extra-index-url "https://download.pytorch.org/whl/cu128" `
        --index-strategy unsafe-best-match 2>&1 | ForEach-Object {
        Emit "install" ([string]$_) $null
    }
    if ($LASTEXITCODE -ne 0) { Fail "package install failed (exit $LASTEXITCODE)" }

    # --- verify (real imports in the venv's own interpreter) ------------------
    Emit "verify" "verifying torch + NeMo import" 90
    & $pyenvPython -c "import torch; import nemo.collections.asr; print(torch.__version__)"
    if ($LASTEXITCODE -ne 0) { Fail "verification import failed (exit $LASTEXITCODE)" }

    # Marker written LAST: the engine's runtime hook only attaches a
    # verified-complete environment (fail closed).
    Set-Content -Path $Marker -Value ("installed " + (Get-Date -Format o)) -Encoding utf8
    Emit "complete" "STT runtime installed - restart the Omni engine to enable transcription" 100
    exit 0
}
catch {
    Fail "unexpected failure: $($_.Exception.Message)"
}
