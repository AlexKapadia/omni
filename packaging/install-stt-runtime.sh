#!/usr/bin/env bash
# First-run STT runtime installer for macOS/Linux.
# Mirrors packaging/install-stt-runtime.ps1: private venv at ~/.local/share/Omni/pyenv
set -euo pipefail

PYENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/Omni/pyenv"
MARKER="${PYENV_DIR}/.stt-runtime-complete"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ_FILE="${SCRIPT_DIR}/stt-runtime-requirements.txt"

if [[ -f "${MARKER}" ]]; then
  echo "STT runtime already installed at ${PYENV_DIR}"
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to install the STT runtime. Install uv first: https://docs.astral.sh/uv/"
  exit 1
fi

uv venv --python 3.11 "${PYENV_DIR}"
# shellcheck disable=SC1091
source "${PYENV_DIR}/bin/activate"
uv pip install -r "${REQ_FILE}"
python - <<'PY'
import torch
import nemo.collections.asr  # noqa: F401
print("STT runtime verification ok", torch.__version__)
PY
touch "${MARKER}"
echo "STT runtime installed at ${PYENV_DIR}"
