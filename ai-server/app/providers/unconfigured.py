from app.models import (
    AnalysisRequest,
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
from app.providers.base import AnalysisProvider, ProviderNotConfigured


class UnconfiguredProvider(AnalysisProvider):
    name = "unconfigured"

    async def decide_clarification(
        self, request: AnalysisRequest
    ) -> ClarificationDecision:
        self._raise()

    async def complete_posting_analysis(
        self, request: AnalysisRequest
    ) -> CompletedAnalysisResponse:
        self._raise()

    async def evaluate_shared_analysis(
        self, request: AnalysisRequest
    ) -> Evaluation:
        self._raise()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self._raise()

    async def verify_evidence(
        self, request: EvidenceVerificationRequest
    ) -> EvidenceVerificationResponse:
        self._raise()

    async def extract_career(
        self, request: CareerExtractionRequest
    ) -> CareerExtractionResponse:
        self._raise()

    async def assess_competency(
        self, request: CompetencyAssessmentRequest
    ) -> CompetencyAssessmentResponse:
        self._raise()

    def _raise(self) -> None:
        raise ProviderNotConfigured(
            "No production AI provider is configured. "
            "Configure a provider instead of returning fabricated analysis data."
        )
