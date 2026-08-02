from abc import ABC, abstractmethod

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


class AnalysisProvider(ABC):
    name: str

    @abstractmethod
    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        raise NotImplementedError

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    @abstractmethod
    async def verify_evidence(
        self, request: EvidenceVerificationRequest
    ) -> EvidenceVerificationResponse:
        raise NotImplementedError

    @abstractmethod
    async def extract_career(
        self, request: CareerExtractionRequest
    ) -> CareerExtractionResponse:
        raise NotImplementedError


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderExecutionError(RuntimeError):
    pass
