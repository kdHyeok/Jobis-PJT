from __future__ import annotations

import os
from dataclasses import dataclass


LOCAL_DEFAULT_SECRET = "local-ai-v3-secret"


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    shared_secret: str
    host: str
    port: int
    jina_enabled: bool = False
    jina_api_key: str = ""
    clova_api_key: str = ""
    clova_vlm_url: str = (
        "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005"
    )
    source_fetch_timeout_seconds: float = 30.0
    source_max_text_bytes: int = 2 * 1024 * 1024
    source_max_image_bytes: int = 20 * 1024 * 1024
    llm_provider: str = "none"
    llm_model: str = "gpt-4.1-mini"
    llm_base_url: str = "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
    gms_key: str = ""
    claude_cli: str = "claude"
    claude_code_model: str = "sonnet"
    codex_cli: str = "codex"
    codex_model: str = "gpt-5.6-terra"
    llm_timeout_seconds: float = 180.0
    llm_max_attempts: int = 3
    llm_effort: str = "medium"
    llm_retry_effort: str = "high"
    capability_graph_url: str = ""
    capability_graph_shared_secret: str = ""
    capability_graph_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("JOBIS_ENV", "local").strip().lower()
        secret = os.getenv("JOBIS_AI_SHARED_SECRET", "").strip()
        if not secret and environment == "local":
            secret = LOCAL_DEFAULT_SECRET
        if len(secret) < 16:
            raise RuntimeError("JOBIS_AI_SHARED_SECRET must contain at least 16 characters")
        if environment != "local" and secret == LOCAL_DEFAULT_SECRET:
            raise RuntimeError("the local AI shared secret cannot be used outside local mode")

        host = os.getenv("JOBIS_AI_HOST", "127.0.0.1").strip()
        try:
            port = int(os.getenv("JOBIS_AI_PORT", "8300"))
        except ValueError as exc:
            raise RuntimeError("JOBIS_AI_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise RuntimeError("JOBIS_AI_PORT must be between 1 and 65535")
        timeout = _positive_float("JOBIS_SOURCE_FETCH_TIMEOUT_SECONDS", 30.0)
        max_text_bytes = _positive_int("JOBIS_SOURCE_MAX_TEXT_BYTES", 2 * 1024 * 1024)
        max_image_bytes = _positive_int("JOBIS_SOURCE_MAX_IMAGE_BYTES", 20 * 1024 * 1024)
        graph_url = os.getenv("CAPABILITY_GRAPH_URL", "").strip().rstrip("/")
        graph_secret = os.getenv("CAPABILITY_GRAPH_SHARED_SECRET", "").strip()
        if graph_url and len(graph_secret) < 16:
            raise RuntimeError(
                "CAPABILITY_GRAPH_SHARED_SECRET must contain at least 16 characters when the graph URL is configured"
            )
        return cls(
            environment=environment,
            shared_secret=secret,
            host=host,
            port=port,
            jina_enabled=_boolean("JOBIS_JINA_ENABLED", False),
            jina_api_key=os.getenv("JINA_API_KEY", "").strip(),
            clova_api_key=os.getenv("CLOVA_API_KEY", "").strip(),
            clova_vlm_url=os.getenv(
                "CLOVA_VLM_URL",
                "https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005",
            ).strip(),
            source_fetch_timeout_seconds=timeout,
            source_max_text_bytes=max_text_bytes,
            source_max_image_bytes=max_image_bytes,
            llm_provider=os.getenv("LLM_PROVIDER", "none").strip().lower(),
            llm_model=os.getenv("LLM_MODEL", "gpt-4.1-mini").strip(),
            llm_base_url=os.getenv(
                "LLM_BASE_URL",
                "https://gms.ssafy.io/gmsapi/api.openai.com/v1",
            ).rstrip("/"),
            gms_key=os.getenv("GMS_KEY", "").strip(),
            claude_cli=os.getenv("CLAUDE_CLI", "claude").strip(),
            claude_code_model=os.getenv("CLAUDE_CODE_MODEL", "sonnet").strip(),
            codex_cli=os.getenv("CODEX_CLI", "codex").strip(),
            codex_model=os.getenv("CODEX_MODEL", "gpt-5.6-terra").strip(),
            llm_timeout_seconds=_positive_float("JOBIS_LLM_TIMEOUT_SECONDS", 180.0),
            llm_max_attempts=_positive_int("JOBIS_LLM_MAX_ATTEMPTS", 3),
            llm_effort=_choice(
                "JOBIS_LLM_EFFORT", "medium", {"low", "medium", "high", "xhigh", "max"}
            ),
            llm_retry_effort=_choice(
                "JOBIS_LLM_RETRY_EFFORT", "high", {"low", "medium", "high", "xhigh", "max"}
            ),
            capability_graph_url=graph_url,
            capability_graph_shared_secret=graph_secret,
            capability_graph_timeout_seconds=_positive_float(
                "CAPABILITY_GRAPH_TIMEOUT_SECONDS", 10.0
            ),
        )


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


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be positive")
    return value


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _choice(name: str, default: str, allowed: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in allowed:
        raise RuntimeError(f"{name} must be one of {sorted(allowed)}")
    return value
