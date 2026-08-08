"""Career-pipeline infrastructure settings backed by the shared JOBIS env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from jobis_ai.config import get_settings


@dataclass(frozen=True, slots=True)
class Settings:
    # The first four fields keep construction convenient for old deterministic
    # workflow tests.  Runtime authentication and binding still belong to the
    # single v2bridge application, not to this internal settings object.
    environment: str = "local"
    shared_secret: str = ""
    host: str = "127.0.0.1"
    port: int = 8400
    source_fetch_timeout_seconds: float = 30.0
    source_max_text_bytes: int = 2 * 1024 * 1024
    source_max_image_bytes: int = 20 * 1024 * 1024
    jina_enabled: bool = False
    jina_api_key: str = ""
    clova_api_key: str = ""
    clova_vlm_url: str = (
        "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005"
    )
    capability_graph_url: str = ""
    capability_graph_shared_secret: str = ""
    capability_graph_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "Settings":
        shared = get_settings()
        return cls(
            source_fetch_timeout_seconds=_positive_float(
                "JOBIS_SOURCE_FETCH_TIMEOUT_SECONDS", 30.0
            ),
            source_max_text_bytes=_positive_int(
                "JOBIS_SOURCE_MAX_TEXT_BYTES", 2 * 1024 * 1024
            ),
            source_max_image_bytes=_positive_int(
                "JOBIS_SOURCE_MAX_IMAGE_BYTES", 20 * 1024 * 1024
            ),
            jina_enabled=_boolean("JOBIS_JINA_ENABLED", False),
            jina_api_key=shared.jina_api_key,
            clova_api_key=shared.clova_api_key,
            clova_vlm_url=shared.clova_vlm_url,
            capability_graph_url=os.getenv("CAPABILITY_GRAPH_URL", "").strip().rstrip("/"),
            capability_graph_shared_secret=os.getenv(
                "CAPABILITY_GRAPH_SHARED_SECRET", ""
            ).strip(),
            capability_graph_timeout_seconds=_positive_float(
                "CAPABILITY_GRAPH_TIMEOUT_SECONDS", 10.0
            ),
        )


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be positive")
    return value


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value
