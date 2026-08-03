from abc import ABC, abstractmethod

from app.models import (
    AnalysisRequest,
    AnalysisResponse,
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


class AnalysisProvider(ABC):
    name: str

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        if request.shared_analysis is None and request.question_count < 3:
            decision = await self.decide_clarification(request)
            if decision.status == "NEEDS_INPUT":
                return AnalysisResponse(
                    status="NEEDS_INPUT",
                    question=decision.question,
                )
        if request.shared_analysis is not None:
            evaluation = await self.evaluate_shared_analysis(request)
            return AnalysisResponse(
                status="COMPLETED",
                job=request.shared_analysis.job,
                evaluation=evaluation,
                competency_proposal=request.shared_analysis.competency_proposal,
            )
        completed = await self.complete_posting_analysis(request)
        return completed.to_analysis_response()

    @abstractmethod
    async def decide_clarification(
        self, request: AnalysisRequest
    ) -> ClarificationDecision:
        raise NotImplementedError

    @abstractmethod
    async def complete_posting_analysis(
        self, request: AnalysisRequest
    ) -> CompletedAnalysisResponse:
        raise NotImplementedError

    @abstractmethod
    async def evaluate_shared_analysis(
        self, request: AnalysisRequest
    ) -> Evaluation:
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

    @abstractmethod
    async def assess_competency(
        self, request: CompetencyAssessmentRequest
    ) -> CompetencyAssessmentResponse:
        raise NotImplementedError


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderExecutionError(RuntimeError):
    pass
