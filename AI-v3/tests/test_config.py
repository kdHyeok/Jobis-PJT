from __future__ import annotations

import pytest

from jobis_ai_v3.config import LOCAL_DEFAULT_SECRET, Settings


def test_local_mode_uses_safe_local_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOBIS_AI_SHARED_SECRET", raising=False)
    monkeypatch.setenv("JOBIS_ENV", "local")

    settings = Settings.from_env()

    assert settings.shared_secret == LOCAL_DEFAULT_SECRET
    assert settings.port == 8300


def test_nonlocal_mode_requires_explicit_nondefault_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBIS_ENV", "production")
    monkeypatch.delenv("JOBIS_AI_SHARED_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="at least 16"):
        Settings.from_env()


def test_invalid_port_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBIS_AI_PORT", "70000")

    with pytest.raises(RuntimeError, match="between 1 and 65535"):
        Settings.from_env()


def test_capability_graph_url_requires_its_own_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPABILITY_GRAPH_URL", "http://127.0.0.1:8400")
    monkeypatch.delenv("CAPABILITY_GRAPH_SHARED_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="CAPABILITY_GRAPH_SHARED_SECRET"):
        Settings.from_env()
