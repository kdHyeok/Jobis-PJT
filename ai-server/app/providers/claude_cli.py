from __future__ import annotations

import asyncio
import json
import logging
import shutil
from contextlib import suppress
from typing import Any, TypeVar

from pydantic import BaseModel

from app.models import (
    AnalysisRequest,
    AnalysisResponse,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    ClarificationDecision,
    CompletedAnalysisResponse,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
)
from app.prompts import (
    career_extraction_prompt,
    chat_prompt,
    evidence_prompt,
    posting_analysis_prompt,
    posting_clarification_prompt,
)
from app.providers.base import (
    AnalysisProvider,
    ProviderExecutionError,
    ProviderNotConfigured,
)
from app.providers.json_support import InvalidProviderResponse, parse_model
from app.settings import Settings

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("uvicorn.error")


class ClaudeCliProvider(AnalysisProvider):
    name = "claude_cli"

    def __init__(self, settings: Settings):
        executable = shutil.which("claude")
        if not executable:
            raise ProviderNotConfigured("Claude Code CLI is not installed")
        self._executable = executable
        self._model = settings.claude_cli_model
        self._timeout = settings.request_timeout_seconds
        self._progress_interval = max(1.0, settings.progress_log_interval_seconds)
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        request_id = str(request.analysis_job_id)
        if request.question_count < 3:
            decision = await self._ask(
                posting_clarification_prompt(request, include_schema=False),
                ClarificationDecision,
                operation="posting_analysis",
                request_id=request_id,
                phase="clarification",
            )
            if decision.status == "NEEDS_INPUT":
                return AnalysisResponse(
                    status="NEEDS_INPUT",
                    question=decision.question,
                )
        completed = await self._ask(
            posting_analysis_prompt(request, include_schema=False),
            CompletedAnalysisResponse,
            operation="posting_analysis",
            request_id=request_id,
            phase="final_proposal",
        )
        return completed.to_analysis_response()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return await self._ask(
            chat_prompt(request),
            ChatResponse,
            operation="chat_reply",
            request_id=str(request.conversation_id),
            phase="response",
        )

    async def verify_evidence(
        self, request: EvidenceVerificationRequest
    ) -> EvidenceVerificationResponse:
        return await self._ask(
            evidence_prompt(request),
            EvidenceVerificationResponse,
            operation="evidence_verification",
            request_id=str(request.evidence.id),
            phase="verification",
        )

    async def extract_career(
        self, request: CareerExtractionRequest
    ) -> CareerExtractionResponse:
        return await self._ask(
            career_extraction_prompt(request),
            CareerExtractionResponse,
            operation="career_extraction",
            request_id=str(request.source_id),
            phase="extraction",
        )

    async def _ask(
        self,
        prompt: str,
        response_model: type[T],
        *,
        operation: str = "unknown",
        request_id: str = "-",
        phase: str = "request",
    ) -> T:
        async with self._semaphore:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._timeout
            last_error: Exception | None = None
            for attempt in range(2):
                remaining = deadline - loop.time()
                if remaining <= 1:
                    raise ProviderExecutionError(
                        "Claude CLI exceeded the total request time limit"
                    ) from last_error
                # 첫 응답에 전체 시간의 90%까지 사용하고, 구조가 잘못된
                # 경우를 위한 한 번의 짧은 교정 시간을 남긴다.
                attempt_timeout = (
                    min(remaining, max(1.0, self._timeout * 0.9))
                    if attempt == 0
                    else remaining
                )
                retry_note = ""
                if attempt > 0:
                    validation_feedback = str(last_error or "unknown validation error")
                    retry_note = (
                        "\n이전 응답이 아래 검증 오류로 거절되었다. 오류가 난 필드만이 아니라 "
                        "전체 결과가 JSON 스키마와 조건부 필수 규칙을 만족하도록 다시 출력하라.\n"
                        f"<validation_error>{validation_feedback[:2_000]}</validation_error>"
                    )
                try:
                    output = await self._run(
                        prompt + retry_note,
                        timeout=attempt_timeout,
                        json_schema=response_model.model_json_schema(by_alias=True),
                        operation=operation,
                        request_id=request_id,
                        phase=phase,
                        attempt=attempt + 1,
                    )
                    return parse_model(output, response_model)
                except InvalidProviderResponse as exception:
                    last_error = exception
                    self._log_progress(
                        operation,
                        request_id,
                        phase,
                        attempt + 1,
                        "schema_invalid",
                    )
            raise last_error or InvalidProviderResponse("Claude did not return a response")

    async def _run(
        self,
        prompt: str,
        timeout: float | None = None,
        json_schema: dict[str, Any] | None = None,
        *,
        operation: str = "unknown",
        request_id: str = "-",
        phase: str = "request",
        attempt: int = 1,
    ) -> str:
        command_timeout = self._timeout if timeout is None else max(0.01, timeout)
        command = [
            self._executable,
            "-p",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--model",
            self._model,
            "--tools",
            "",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
        ]
        if json_schema is not None:
            command.extend(
                [
                    "--json-schema",
                    json.dumps(json_schema, ensure_ascii=False),
                ]
            )
        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline = started + command_timeout
        self._log_progress(
            operation,
            request_id,
            phase,
            attempt,
            "started",
            prompt_chars=len(prompt),
            timeout_seconds=round(command_timeout, 1),
        )

        process: asyncio.subprocess.Process | None = None
        stderr_task: asyncio.Task[bytes] | None = None
        read_task: asyncio.Task[bytes] | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,
            )
        except OSError as exception:
            self._log_progress(
                operation,
                request_id,
                phase,
                attempt,
                "failed_to_start",
            )
            raise ProviderExecutionError(
                f"Claude CLI could not be started: {exception}"
            ) from exception

        try:
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            stderr_task = asyncio.create_task(process.stderr.read())
            try:
                process.stdin.write(prompt.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

            result_event: dict[str, Any] | None = None
            milestones: set[str] = set()
            next_heartbeat = started + self._progress_interval
            read_task = asyncio.create_task(process.stdout.readline())

            while True:
                now = loop.time()
                if now >= deadline:
                    read_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await read_task
                    await self._stop_process(process)
                    self._log_progress(
                        operation,
                        request_id,
                        phase,
                        attempt,
                        "timed_out",
                        elapsed_seconds=round(now - started, 1),
                        timeout_seconds=round(command_timeout, 1),
                    )
                    raise ProviderExecutionError(
                        f"Claude CLI request timed out after {command_timeout:.0f} seconds"
                    )

                wait_seconds = min(
                    deadline - now,
                    max(0.01, next_heartbeat - now),
                )
                done, _ = await asyncio.wait({read_task}, timeout=wait_seconds)
                if not done:
                    now = loop.time()
                    self._log_progress(
                        operation,
                        request_id,
                        phase,
                        attempt,
                        "running",
                        elapsed_seconds=round(now - started, 1),
                        timeout_seconds=round(command_timeout, 1),
                    )
                    while next_heartbeat <= now:
                        next_heartbeat += self._progress_interval
                    continue

                raw_line = read_task.result()
                if not raw_line:
                    break
                read_task = asyncio.create_task(process.stdout.readline())
                try:
                    event = json.loads(raw_line.decode("utf-8", errors="strict"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._log_progress(
                        operation,
                        request_id,
                        phase,
                        attempt,
                        "unparsed_stream_event",
                    )
                    continue
                if isinstance(event, dict):
                    self._log_stream_milestone(
                        event,
                        milestones,
                        operation,
                        request_id,
                        phase,
                        attempt,
                    )
                    if event.get("type") == "result":
                        result_event = event

                now = loop.time()
                if now >= next_heartbeat:
                    self._log_progress(
                        operation,
                        request_id,
                        phase,
                        attempt,
                        "running",
                        elapsed_seconds=round(now - started, 1),
                        timeout_seconds=round(command_timeout, 1),
                    )
                    while next_heartbeat <= now:
                        next_heartbeat += self._progress_interval

            remaining = max(0.01, deadline - loop.time())
            try:
                return_code = await asyncio.wait_for(process.wait(), timeout=remaining)
            except TimeoutError:
                await self._stop_process(process)
                raise ProviderExecutionError(
                    f"Claude CLI request timed out after {command_timeout:.0f} seconds"
                )
            stderr = (
                await stderr_task
                if stderr_task is not None
                else b""
            )
            if return_code != 0:
                self._log_progress(
                    operation,
                    request_id,
                    phase,
                    attempt,
                    "process_failed",
                    exit_code=return_code,
                    elapsed_seconds=round(loop.time() - started, 1),
                )
                detail = stderr.decode("utf-8", errors="replace")[:500]
                raise ProviderExecutionError(
                    f"Claude CLI failed with code {return_code}: {detail}"
                )
            if result_event is None:
                raise InvalidProviderResponse(
                    "Claude CLI stream did not include a result event"
                )
            if result_event.get("is_error"):
                status = result_event.get("api_error_status") or result_event.get("subtype")
                raise ProviderExecutionError(
                    f"Claude CLI returned an error result: {status or 'unknown'}"
                )

            usage = result_event.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            self._log_progress(
                operation,
                request_id,
                phase,
                attempt,
                "completed",
                elapsed_seconds=round(loop.time() - started, 1),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cost_usd=result_event.get("total_cost_usd", 0),
            )
            if json_schema is not None and isinstance(
                result_event.get("structured_output"), dict
            ):
                return json.dumps(
                    result_event["structured_output"],
                    ensure_ascii=False,
                )
            if isinstance(result_event.get("result"), str):
                return result_event["result"]
            raise InvalidProviderResponse(
                "Claude CLI result event did not include a usable result"
            )
        except asyncio.CancelledError:
            if process is not None:
                await self._stop_process(process)
            raise
        finally:
            if read_task is not None and not read_task.done():
                read_task.cancel()
                with suppress(asyncio.CancelledError):
                    await read_task
            if stderr_task is not None and not stderr_task.done():
                stderr_task.cancel()
            if process is not None and process.returncode is None:
                await self._stop_process(process)

    async def _stop_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        with suppress(ProcessLookupError):
            process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            logger.warning("Claude CLI process did not stop after kill")

    def _log_stream_milestone(
        self,
        event: dict[str, Any],
        milestones: set[str],
        operation: str,
        request_id: str,
        phase: str,
        attempt: int,
    ) -> None:
        event_type = event.get("type")
        if event_type == "system" and event.get("subtype") == "init":
            milestone = "connected"
            metrics = {"model": event.get("model", self._model)}
        elif event_type == "stream_event" and isinstance(event.get("event"), dict):
            stream_event = event["event"]
            if stream_event.get("type") == "message_start":
                milestone = "generation_started"
                metrics = {"ttft_ms": event.get("ttft_ms", 0)}
            elif (
                stream_event.get("type") == "content_block_start"
                and isinstance(stream_event.get("content_block"), dict)
                and stream_event["content_block"].get("name") == "StructuredOutput"
            ):
                milestone = "structured_output_started"
                metrics = {}
            else:
                return
        else:
            return
        if milestone in milestones:
            return
        milestones.add(milestone)
        self._log_progress(
            operation,
            request_id,
            phase,
            attempt,
            milestone,
            **metrics,
        )

    def _log_progress(
        self,
        operation: str,
        request_id: str,
        phase: str,
        attempt: int,
        state: str,
        **metrics: object,
    ) -> None:
        metric_text = " ".join(
            f"{key}={value}"
            for key, value in metrics.items()
            if value is not None
        )
        logger.info(
            "JOBISS_AI_PROGRESS operation=%s request_id=%s phase=%s "
            "attempt=%d state=%s%s",
            operation,
            request_id,
            phase,
            attempt,
            state,
            f" {metric_text}" if metric_text else "",
        )
