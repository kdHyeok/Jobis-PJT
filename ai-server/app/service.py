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
from app.providers.anthropic_api import AnthropicApiProvider
from app.providers.base import AnalysisProvider
from app.providers.claude_cli import ClaudeCliProvider
from app.providers.unconfigured import UnconfiguredProvider
from app.settings import Settings


class AnalysisService:
    def __init__(self, settings: Settings):
        self._provider = self._resolve_provider(settings)

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        return await self._provider.analyze(request)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return await self._provider.chat(request)

    async def verify_evidence(
        self, request: EvidenceVerificationRequest
    ) -> EvidenceVerificationResponse:
        return await self._provider.verify_evidence(request)

    async def extract_career(
        self, request: CareerExtractionRequest
    ) -> CareerExtractionResponse:
        return await self._provider.extract_career(request)

    def _resolve_provider(self, settings: Settings) -> AnalysisProvider:
        if settings.analysis_provider == "unconfigured":
            return UnconfiguredProvider()
        if settings.analysis_provider == "claude_cli":
            return ClaudeCliProvider(settings)
        if settings.analysis_provider == "anthropic":
            return AnthropicApiProvider(settings)
        raise ValueError(f"Unsupported analysis provider: {settings.analysis_provider}")
