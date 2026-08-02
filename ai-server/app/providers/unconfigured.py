from app.models import (
    AnalysisRequest,
    AnalysisResponse,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
)
from app.providers.base import AnalysisProvider, ProviderNotConfigured


class UnconfiguredProvider(AnalysisProvider):
    name = "unconfigured"

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
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

    def _raise(self) -> None:
        raise ProviderNotConfigured(
            "No production AI provider is configured. "
            "Configure a provider instead of returning fabricated analysis data."
        )
