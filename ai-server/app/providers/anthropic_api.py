from __future__ import annotations

from typing import TypeVar

from anthropic import APIError, APITimeoutError, AsyncAnthropic
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
from app.providers.json_support import parse_model
from app.settings import Settings

T = TypeVar("T", bound=BaseModel)


class AnthropicApiProvider(AnalysisProvider):
    name = "anthropic"

    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise ProviderNotConfigured("ANTHROPIC_API_KEY is required")
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.request_timeout_seconds,
            max_retries=2,
        )
        self._model = settings.anthropic_model

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        if request.question_count < 3:
            decision = await self._ask(
                posting_clarification_prompt(request),
                ClarificationDecision,
                1_500,
            )
            if decision.status == "NEEDS_INPUT":
                return AnalysisResponse(
                    status="NEEDS_INPUT",
                    question=decision.question,
                )
        completed = await self._ask(
            posting_analysis_prompt(request),
            CompletedAnalysisResponse,
            12_000,
        )
        return completed.to_analysis_response()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return await self._ask(chat_prompt(request), ChatResponse, 2_000)

    async def verify_evidence(
        self, request: EvidenceVerificationRequest
    ) -> EvidenceVerificationResponse:
        return await self._ask(evidence_prompt(request), EvidenceVerificationResponse, 4_000)

    async def extract_career(
        self, request: CareerExtractionRequest
    ) -> CareerExtractionResponse:
        return await self._ask(
            career_extraction_prompt(request),
            CareerExtractionResponse,
            8_000,
        )

    async def _ask(self, prompt: str, response_model: type[T], max_tokens: int) -> T:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
        except APITimeoutError as exception:
            raise ProviderExecutionError("Anthropic request timed out") from exception
        except APIError as exception:
            raise ProviderExecutionError("Anthropic request failed") from exception
        text = "".join(block.text for block in response.content if block.type == "text")
        return parse_model(text, response_model)
