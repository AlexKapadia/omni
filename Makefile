# Omni — canonical developer commands (the spec for CI and humans).
# NOTE: `make` is absent on the Windows dev box (claude.md §7.1); run the
# underlying `uv run ...` commands directly there. Linux/CI use make.

.PHONY: test lint typecheck run

# Full engine test suite (pytest, asyncio auto mode, no network).
test:
	uv run pytest

# Lint: ruff with security rules (S) enabled for engine code.
lint:
	uv run ruff check .

# Types: mypy strict over engine/ and tests/ (files set in pyproject).
typecheck:
	uv run mypy

# Run the engine sidecar locally: 127.0.0.1 only, port from OMNI_ENGINE_PORT
# (default 8765). GET /health to verify liveness.
run:
	uv run python -m engine.server
