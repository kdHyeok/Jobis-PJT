from __future__ import annotations

from typing import TypeVar

from anthropic import APIError, APITimeoutError, AsyncAnthropic
from pydantic import BaseModel

from app.assessment_flow import (
    assemble_assessment_response,
    next_question_kind,
)
from app.models import (
    AnalysisRequest,
    AssessmentAnswerEvaluation,
    AssessmentQuestion,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    ClarificationDecision,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
    CompletedAnalysisResponse,
    Evaluation,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
)
from app.prompts import (
    assessment_grading_prompt,
    assessment_question_prompt,
    career_extraction_prompt,
    chat_prompt,
    evidence_prompt,
    posting_analysis_prompt,
    posting_clarification_prompt,
    shared_analysis_evaluation_prompt,
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

    async def decide_clarification(
        self, request: AnalysisRequest
    ) -> ClarificationDecision:
        return await self._ask(
            posting_clarification_prompt(request),
            ClarificationDecision,
            1_500,
        )

    async def complete_posting_analysis(
        self, request: AnalysisRequest
    ) -> CompletedAnalysisResponse:
        return await self._ask(
            posting_analysis_prompt(request),
            CompletedAnalysisResponse,
            12_000,
        )

    async def evaluate_shared_analysis(
        self, request: AnalysisRequest
    ) -> Evaluation:
        return await self._ask(
            shared_analysis_evaluation_prompt(request),
            Evaluation,
            3_000,
        )

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

    async def assess_competency(
        self, request: CompetencyAssessmentRequest
    ) -> CompetencyAssessmentResponse:
        evaluation = None
        if request.turns and request.turns[-1].answer_text:
            evaluation = await self._ask(
                assessment_grading_prompt(request),
                AssessmentAnswerEvaluation,
                3_000,
            )
        kind = next_question_kind(request, evaluation)
        question = None
        if kind is not None:
            question = await self._ask(
                assessment_question_prompt(request, kind, evaluation),
                AssessmentQuestion,
                3_000,
            )
        return assemble_assessment_response(evaluation, question)

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
