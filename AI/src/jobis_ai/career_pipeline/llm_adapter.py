"""Adapter from the career pipeline's strict schemas to the shared JOBIS LLM.

The career pipeline deliberately does not own a provider.  Production calls go
through :mod:`jobis_ai.structured`, so chat and career analysis share the same
authentication, model selection, retry policy, usage accounting and tracing.
The optional provider argument exists only for deterministic unit-test doubles.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

from jobis_ai.config import get_settings
from jobis_ai.llm_usage import collecting
from jobis_ai.structured import run_structured

from .contracts.parsing import StructuredContractError, parse_structured_payload
from .cancellation import raise_if_cancelled


ModelT = TypeVar("ModelT", bound=BaseModel)


class JsonProviderError(RuntimeError):
    """The configured provider failed or returned an invalid contract."""


class JsonProviderContractError(JsonProviderError):
    """The provider responded, but its structured payload violated the contract."""


class JsonProviderNotConfigured(JsonProviderError):
    """No usable shared JOBIS provider is configured."""


@dataclass(frozen=True, slots=True)
class LlmProgressEvent:
    kind: str
    elapsed_ms: int
    message: str
    stream_event_count: int = 0


LlmProgressCallback = Callable[[LlmProgressEvent], None]


class JsonCompletionProvider(Protocol):
    name: str
    model: str

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        effort: str,
        progress_callback: LlmProgressCallback | None = None,
    ) -> str | dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class StructuredGeneration:
    value: BaseModel
    provider: str
    model: str
    attempts: int
    duration_ms: int
    final_effort: str
    effort_history: tuple[str, ...]
    provider_duration_ms: int | None
    provider_api_duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cache_creation_input_tokens: int | None
    cache_read_input_tokens: int | None
    total_cost_usd: float | None
    session_ids: tuple[str, ...]


class StructuredGenerator:
    """Generate a validated Pydantic object using the shared provider boundary."""

    def __init__(
        self,
        provider: JsonCompletionProvider | None = None,
        *,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
        initial_effort: str = "medium",
        retry_effort: str = "high",
    ) -> None:
        self._provider = provider
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff_seconds
        self._initial_effort = initial_effort
        self._retry_effort = retry_effort

    @property
    def provider_name(self) -> str:
        if self._provider is not None:
            return self._provider.name
        return get_settings().llm_provider

    @property
    def model_name(self) -> str:
        if self._provider is not None:
            return self._provider.model
        return get_settings().active_model("default")

    def generate(
        self,
        model: type[ModelT],
        *,
        system_prompt: str,
        user_prompt: str,
        progress_callback: LlmProgressCallback | None = None,
    ) -> tuple[ModelT, StructuredGeneration]:
        started = time.perf_counter()
        _notify(progress_callback, "STARTED", 0, "분석 에이전트가 구조화 작업을 시작했어요")

        usage_summary: dict[str, Any] = {}
        if self._provider is None:
            value, warnings, usage_summary = self._generate_with_shared_provider(
                model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                progress_callback=progress_callback,
                started=started,
            )
            if value is None:
                detail = "; ".join(str(item.get("message") or item) for item in warnings)
                if any(item.get("code") == "llm_not_configured" for item in warnings):
                    raise JsonProviderNotConfigured(detail or "JOBIS LLM is not configured")
                if any(item.get("code") == "llm_contract_validation_failed" for item in warnings):
                    raise JsonProviderContractError(detail or "structured response violated the contract")
                raise JsonProviderError(detail or "shared JOBIS LLM generation failed")
            attempts = 1
            effort_history = (self._initial_effort,)
        else:
            value, attempts, effort_history = self._generate_with_test_provider(
                model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                progress_callback=progress_callback,
            )

        duration_ms = round((time.perf_counter() - started) * 1000)
        _notify(
            progress_callback,
            "COMPLETED",
            duration_ms,
            "분석 에이전트가 구조화 결과를 확인했어요",
        )
        metadata = StructuredGeneration(
            value=value,
            provider=self.provider_name,
            model=self.model_name,
            attempts=attempts,
            duration_ms=duration_ms,
            final_effort=effort_history[-1],
            effort_history=effort_history,
            provider_duration_ms=_optional_int(usage_summary.get("durationMs")) or duration_ms,
            provider_api_duration_ms=_optional_int(usage_summary.get("durationMs")),
            input_tokens=_optional_int(usage_summary.get("inputTokens")),
            output_tokens=_optional_int(usage_summary.get("outputTokens")),
            cache_creation_input_tokens=None,
            cache_read_input_tokens=None,
            total_cost_usd=_optional_float(usage_summary.get("costUsd")),
            session_ids=(),
        )
        return value, metadata

    def _generate_with_shared_provider(
        self,
        model: type[ModelT],
        *,
        system_prompt: str,
        user_prompt: str,
        progress_callback: LlmProgressCallback | None,
        started: float,
    ) -> tuple[ModelT | None, list[dict], dict[str, Any]]:
        # 구조화 호출은 동기 API지만 사용자에게는 5초마다 살아 있는 진행
        # 신호를 보낸다. copy_context가 분석 job id와 usage collector를 worker
        # thread로 넘겨 Codex CLI 취소와 실측 사용량을 같은 호출에 묶는다.
        with collecting() as usage:
            executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="jobis-career-structured",
            )
            context = copy_context()
            future = executor.submit(
                context.run,
                run_structured,
                model,
                system_prompt,
                user_prompt,
                node=f"career_pipeline.{model.__name__}",
                tier="default",
            )
            heartbeat = 0
            try:
                while True:
                    try:
                        value, warnings = future.result(timeout=5)
                        break
                    except FutureTimeoutError:
                        raise_if_cancelled()
                        heartbeat += 1
                        elapsed_ms = round((time.perf_counter() - started) * 1000)
                        _notify(
                            progress_callback,
                            "RUNNING",
                            elapsed_ms,
                            "분석 근거를 정리하고 있어요"
                            if heartbeat % 2
                            else "구조화 결과의 누락과 참조를 확인하고 있어요",
                            stream_event_count=heartbeat,
                        )
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
        return value, warnings, usage.summary()

    def _generate_with_test_provider(
        self,
        model: type[ModelT],
        *,
        system_prompt: str,
        user_prompt: str,
        progress_callback: LlmProgressCallback | None,
    ) -> tuple[ModelT, int, tuple[str, ...]]:
        assert self._provider is not None
        last_error: Exception | None = None
        prompt = user_prompt
        efforts: list[str] = []
        for attempt in range(1, self._max_attempts + 1):
            effort = self._initial_effort if attempt == 1 else self._retry_effort
            efforts.append(effort)
            try:
                raw = self._provider.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    json_schema=model.model_json_schema(by_alias=True),
                    effort=effort,
                    progress_callback=progress_callback,
                )
                payload = getattr(raw, "payload", raw)
                return parse_structured_payload(payload, model), attempt, tuple(efforts)
            except JsonProviderNotConfigured:
                raise
            except JsonProviderContractError:
                # Retrying a response that already violated the local schema only
                # repeats the same deterministic failure and obscures the real cause.
                raise
            except JsonProviderError as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    prompt = (
                        f"{user_prompt}\n\n직전 응답은 계약 검증에 실패했습니다: {str(exc)[:1200]}\n"
                        "원문 근거를 유지하고 JSON 계약만 바로잡으세요."
                    )
                    time.sleep(self._retry_backoff * attempt)
            except (StructuredContractError, ValueError, TypeError) as exc:
                raise JsonProviderContractError(
                    f"structured response violated the contract: {exc}"
                ) from exc
        raise JsonProviderError(
            f"structured response failed validation after {self._max_attempts} attempts: {last_error}"
        )


def _notify(
    callback: LlmProgressCallback | None,
    kind: str,
    elapsed_ms: int,
    message: str,
    *,
    stream_event_count: int = 0,
) -> None:
    if callback is not None:
        callback(LlmProgressEvent(
            kind=kind,
            elapsed_ms=elapsed_ms,
            message=message,
            stream_event_count=stream_event_count,
        ))


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None
