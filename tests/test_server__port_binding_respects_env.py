"""Binding-contract tests: env-driven port, loopback-only host, fail-closed.

The uvicorn config is asserted directly (via ``build_uvicorn_config``) so
no test opens a real socket — the contract is what matters: host is ALWAYS
127.0.0.1, port comes from OMNI_ENGINE_PORT, bad values abort startup.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.runtime_settings import LOOPBACK_HOST, load_engine_settings
from engine.server import build_uvicorn_config


def test_default_port_is_8765_when_env_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMNI_ENGINE_PORT", raising=False)
    config = build_uvicorn_config(load_engine_settings())
    assert config.port == 8765


def test_omni_engine_port_env_var_overrides_the_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNI_ENGINE_PORT", "9123")
    config = build_uvicorn_config(load_engine_settings())
    assert config.port == 9123


def test_host_is_loopback_only_regardless_of_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local-only invariant: there is no env var that can widen the bind.
    Even a hostile OMNI_BIND_HOST-style variable must change nothing."""
    monkeypatch.setenv("OMNI_ENGINE_PORT", "9200")
    # S104 suppressed below: these are deliberately hostile env values the
    # engine must IGNORE — the test asserts the bind stays on loopback.
    monkeypatch.setenv("OMNI_BIND_HOST", "0.0.0.0")  # noqa: S104
    monkeypatch.setenv("OMNI_HOST", "0.0.0.0")  # noqa: S104
    config = build_uvicorn_config(load_engine_settings())
    assert config.host == LOOPBACK_HOST == "127.0.0.1"


@pytest.mark.parametrize("bad_port", ["", "abc", "0", "-1", "65536", "80.5", "8765; rm -rf"])
def test_malformed_port_values_abort_startup_fail_closed(
    monkeypatch: pytest.MonkeyPatch, bad_port: str
) -> None:
    """Fail closed: a bad port must raise, never silently fall back."""
    monkeypatch.setenv("OMNI_ENGINE_PORT", bad_port)
    with pytest.raises(ValidationError):
        load_engine_settings()


@pytest.mark.parametrize("boundary_port", ["1", "65535"])
def test_boundary_ports_1_and_65535_are_accepted(
    monkeypatch: pytest.MonkeyPatch, boundary_port: str
) -> None:
    """Boundary-exact: the inclusive edges of the legal range parse."""
    monkeypatch.setenv("OMNI_ENGINE_PORT", boundary_port)
    assert load_engine_settings().engine_port == int(boundary_port)


def test_omni_db_path_env_var_overrides_the_database_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "elsewhere" / "custom.db"
    monkeypatch.setenv("OMNI_DB_PATH", str(override))
    assert load_engine_settings().db_path == override


def test_default_db_path_lives_under_localappdata_omni(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The default database is user-private: %LOCALAPPDATA%/Omni/omni.db."""
    monkeypatch.delenv("OMNI_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert load_engine_settings().db_path == tmp_path / "Omni" / "omni.db"
