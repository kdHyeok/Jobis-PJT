from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from jobis_ai_v3.api import create_app
from jobis_ai_v3.capability_graph import InMemoryCapabilityGraphPort, closure_content_hash
from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.capability_graph import (
    CapabilityGraphClosure,
    CapabilityGraphNode,
    CapabilityNodeType,
    GraphConfidence,
    GraphConfidenceBand,
    GraphReviewStatus,
    GraphSnapshotScope,
    GraphSource,
    GraphSourceType,
    LearningLayer,
    ProjectNecessity,
    VerificationMethod,
)
from jobis_ai_v3.contracts.fit import FitAnalysisResult, FitAnalysisStatus, FitAssessment, UserEvidenceBundle
from jobis_ai_v3.contracts.normalization import (
    CapabilityCatalogEntry,
    CapabilityCatalogSnapshot,
    CapabilityKind,
    CapabilityNormalizationResult,
    MatchType,
    NormalizationAudit,
    NormalizationDecision,
    RequirementNormalization,
    ReviewStatus,
    RoadmapDisposition,
)
from jobis_ai_v3.contracts.pipeline import AnalysisPipelineRequest, PipelineStatus
from jobis_ai_v3.contracts.posting import RequirementCategory
from jobis_ai_v3.contracts.progress import AnalysisStage, ProgressStatus
from jobis_ai_v3.contracts.resolution import ClarificationAnswer
from jobis_ai_v3.contracts.project_planning import (
    CompanyProjectBlueprint,
    PlannedProjectTask,
    ProjectPlanningAudit,
)
from jobis_ai_v3.contracts.roadmap import CurrentRoadmapSnapshot, RoadmapProposal
from jobis_ai_v3.contracts.source import SourceStatus
from jobis_ai_v3.pipeline import AnalysisPipelineService
from jobis_ai_v3.resolution import PostingResolutionService


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
EXAMPLES = (
    Path(__file__).resolve().parents[2]
    / "contract-fixtures/examples/jobis.ai.v3alpha1/valid-contracts.json"
)


class StaticPostingService:
    def __init__(self, posting) -> None:
        self.posting = posting
        self.calls = 0

    def interpret(self, _request):
        self.calls += 1
        return self.posting

    def discover(self, _request, **_kwargs):
        self.calls += 1
        return self.posting

    def interpret_selected(self, _request, **_kwargs):
        self.calls += 1
        return self.posting


class StaticFitService:
    def __init__(self, assessment: FitAssessment) -> None:
        self.assessment = assessment
        self.calls = 0

    def analyze(self, _request):
        self.calls += 1
        return FitAnalysisResult(status=FitAnalysisStatus.COMPLETED, assessment=self.assessment)


class StaticNormalizationService:
    def __init__(self, result: CapabilityNormalizationResult) -> None:
        self.result = result
        self.calls = 0

    def normalize(self, _request):
        self.calls += 1
        return self.result


class StaticProjectPlanningService:
    def __init__(self, result: CompanyProjectBlueprint) -> None:
        self.result = result

    def plan(self, _request, **_kwargs):
        return self.result


class StaticRoadmapService:
    def __init__(self, proposal: RoadmapProposal) -> None:
        self.proposal = proposal

    def compose(self, _request):
        return self.proposal


def catalog() -> CapabilityCatalogSnapshot:
    return CapabilityCatalogSnapshot(
        catalog_version="catalog-pipeline-1",
        entries=[CapabilityCatalogEntry(
            canonical_key="java.classes-objects",
            display_name="Java class and object modelling",
            kind=CapabilityKind.PROGRAMMING_LANGUAGE,
            scope_definition="Model state and behavior with Java classes and collaborating objects",
            aliases=["Java classes"],
            version=1,
        )],
    )


def normalization() -> CapabilityNormalizationResult:
    return CapabilityNormalizationResult(
        normalization_id="normalization-example",
        common_analysis_id="analysis-example",
        selected_position_id="pos-backend",
        catalog_version="catalog-pipeline-1",
        items=[RequirementNormalization(
            requirement_id="req-java",
            source_category=RequirementCategory.TECHNOLOGY,
            disposition=RoadmapDisposition.LEARNING_CAPABILITY,
            decision=NormalizationDecision.AUTO_SELECTED,
            selected_canonical_key="java.classes-objects",
            candidates=[{
                "canonicalKey": "java.classes-objects",
                "matchType": MatchType.EXACT_ALIAS,
                "confidence": 1.0,
                "reason": "Exact alias",
            }],
            review_status=ReviewStatus.NOT_REQUIRED,
            evidence_ids=["seg-req"],
            reason="Exact alias",
        )],
        audit=NormalizationAudit(
            normalizer_version="normalizer-test",
            catalog_version="catalog-pipeline-1",
        ),
    )


def graph() -> CapabilityGraphClosure:
    source = GraphSource(
        source_id="source-pipeline",
        title="Pipeline curriculum fixture",
        uri="https://example.invalid/pipeline-curriculum",
        publisher="JOBIS test",
        source_type=GraphSourceType.INTERNAL_DESIGN,
        retrieved_at=NOW,
        evidence_summary="Atomic Java capability fixture for the complete pipeline.",
        snapshot_scope=GraphSnapshotScope.INTERNAL_RECORD,
        content_hash="sha256:" + "a" * 64,
    )
    value = CapabilityGraphClosure(
        graph_version="0.1.0-alpha.1",
        generated_at=NOW,
        content_hash="sha256:" + "0" * 64,
        target_capability_keys=["java.classes-objects"],
        nodes=[CapabilityGraphNode(
            canonical_key="java.classes-objects",
            technology_key="lang.java",
            display_name="Java class and object modelling",
            node_type=CapabilityNodeType.PERFORMANCE,
            kind=CapabilityKind.PROGRAMMING_LANGUAGE,
            objective="Model state and behavior with Java classes and collaborating objects.",
            scope_definition="Classes, constructors, fields, methods, and object collaboration",
            verification_methods=[VerificationMethod.IMPLEMENT],
            confidence=GraphConfidence(
                band=GraphConfidenceBand.VERIFIED,
                reason="The fixture is explicitly reviewed.",
            ),
            review_status=GraphReviewStatus.APPROVED,
            version=1,
            source_ids=[source.source_id],
        )],
        edges=[],
        sources=[source],
        learning_order=[
            LearningLayer(depth=0, capability_keys=["java.classes-objects"]),
        ],
    )
    return value.model_copy(update={"content_hash": closure_content_hash(value)})


def project_blueprint() -> CompanyProjectBlueprint:
    return CompanyProjectBlueprint(
        blueprint_id="project-blueprint-example",
        common_analysis_id="analysis-example",
        selected_position_id="pos-backend",
        title="Example Games backend project",
        objective="Demonstrate the atomic Java capability in a runnable service.",
        domain_context="Game backend service",
        tasks=[PlannedProjectTask(
            task_key="task.draft.java-service",
            necessity=ProjectNecessity.REQUIRED,
            title="Java service core",
            objective="Model the service with collaborating Java objects.",
            acceptance_criteria=["The service runs", "Automated tests pass"],
            capability_keys=["java.classes-objects"],
            requirement_ids=["req-java"],
        )],
        audit=ProjectPlanningAudit(
            planner_version="planner-test",
            graph_version="0.1.0-alpha.1",
            graph_content_hash="sha256:" + "b" * 64,
            provider="scripted",
            model="fixture",
            generation_attempts=1,
            generation_duration_ms=1,
        ),
    )


def pipeline(structured_posting) -> AnalysisPipelineService:
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    return AnalysisPipelineService(
        posting_service=StaticPostingService(structured_posting),
        resolution_service=PostingResolutionService(),
        fit_service=StaticFitService(FitAssessment.model_validate(examples["fit-assessment"])),
        normalization_service=StaticNormalizationService(normalization()),
        project_planning_service=StaticProjectPlanningService(project_blueprint()),
        graph_port=InMemoryCapabilityGraphPort(graph()),
        roadmap_service=StaticRoadmapService(
            RoadmapProposal.model_validate(examples["roadmap-proposal"])
        ),
    )


def request(source_document, verified_snapshot) -> AnalysisPipelineRequest:
    return AnalysisPipelineRequest(
        job_id="job-pipeline-1",
        common_analysis_id="analysis-example",
        as_of_date=NOW.date(),
        source_document=source_document.model_copy(update={"status": SourceStatus.VERIFIED}),
        verified_snapshot=verified_snapshot,
        user_evidence=UserEvidenceBundle(
            evidence_set_id="evidence-set-example",
            revision=1,
        ),
        current_roadmap=CurrentRoadmapSnapshot(roadmap_version=0),
        opportunity_id="opportunity-example",
    )


def test_pipeline_runs_one_verified_revision_to_draft(
    source_document,
    verified_snapshot,
    structured_posting,
) -> None:
    events = []
    result = pipeline(structured_posting).run(
        request(source_document, verified_snapshot),
        event_sink=events.append,
    )

    assert result.status is PipelineStatus.COMPLETED
    assert result.roadmap_proposal.status.value == "DRAFT"
    assert result.capability_graph.graph_version == "0.1.0-alpha.1"
    assert result.normalization.audit.normalizer_version == "project-blueprint-normalizer-3.3.0"
    assert result.fit.assessment.audit.matcher_version == "project-evidence-overlay-3.2.0"
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert any(
        event.stage is AnalysisStage.CAPABILITY_GRAPH_LOOKUP
        and event.status is ProgressStatus.RUNNING
        for event in events
    )
    assert events[-1].stage is AnalysisStage.RESULT_ASSEMBLY
    assert events[-1].status is ProgressStatus.COMPLETED
    assert all(
        event.stage_duration_ms is None
        for event in events
        if event.status is ProgressStatus.RUNNING
    )
    assert all(
        event.stage_duration_ms is not None
        for event in events
        if event.status is ProgressStatus.COMPLETED
    )
    running_stages = [
        event.stage for event in events if event.status is ProgressStatus.RUNNING
    ]
    assert running_stages.index(AnalysisStage.PROJECT_PLANNING) < running_stages.index(
        AnalysisStage.CAPABILITY_NORMALIZATION
    )
    assert running_stages.index(AnalysisStage.CAPABILITY_GRAPH_LOOKUP) < running_stages.index(
        AnalysisStage.FIT_ANALYSIS
    )
    partial_kinds = {
        event.partial_result.get("kind")
        for event in events
        if event.partial_result is not None
    }
    assert "POSITION_DISCOVERY" in partial_kinds
    assert "PROJECT_BLUEPRINT" in partial_kinds
    assert "CAPABILITY_GRAPH" in partial_kinds
    assert "ROADMAP_PROPOSAL" in partial_kinds


def test_pipeline_resume_reuses_structured_posting_checkpoint(
    source_document,
    verified_snapshot,
    structured_posting,
) -> None:
    service = pipeline(structured_posting)
    resumed = request(source_document, verified_snapshot).model_copy(update={
        "structured_posting_checkpoint": structured_posting,
    })

    result = service.run(resumed)

    assert result.status is PipelineStatus.COMPLETED
    assert service._posting.calls == 0


def test_pipeline_waits_for_selected_posting_review_before_project_planning(
    source_document,
    verified_snapshot,
    structured_posting,
) -> None:
    service = pipeline(structured_posting)
    initial = request(source_document, verified_snapshot).model_copy(update={
        "require_posting_confirmation": True,
    })

    waiting = service.run(initial)

    assert waiting.status is PipelineStatus.AWAITING_POSTING_CONFIRMATION
    assert waiting.posting_review is not None
    assert waiting.posting_review.selected_position_id == "pos-backend"
    assert waiting.posting_review.original_text == verified_snapshot.verified_text
    assert waiting.project_blueprint is None
    assert waiting.roadmap_proposal is None

    resumed = initial.model_copy(update={
        "structured_posting_checkpoint": waiting.structured_posting,
        "confirmed_posting_review_id": waiting.posting_review.review_id,
    })
    completed = service.run(resumed)

    assert completed.status is PipelineStatus.COMPLETED
    assert completed.posting_review.review_id == waiting.posting_review.review_id
    assert service._posting.calls == 1


def test_multi_role_and_experience_are_resolved_before_selected_review(
    source_document,
    verified_snapshot,
    structured_posting,
) -> None:
    payload = structured_posting.model_dump(mode="json")
    backend = payload["positions"][0]
    backend["experience"] = {
        "kind": "NEW_GRADUATE_OR_EXPERIENCED",
        "min_months": None,
        "max_months": None,
        "experienced_min_months": 36,
        "confidence": 0.99,
        "evidence_ids": ["seg-exp"],
    }
    frontend = json.loads(json.dumps(backend))
    frontend["position_id"] = "pos-frontend"
    frontend["source_title"] = "프론트엔드"
    frontend["role"]["specialization"] = "WEB_FRONTEND"
    frontend["role"]["canonical_role_id"] = "role.web_frontend"
    frontend["requirements"][0]["requirement_id"] = "req-typescript"
    frontend["requirements"][0]["atomic_text"] = "TypeScript 개발 경험"
    frontend["requirements"][0]["applies_to_position_ids"] = ["pos-frontend"]
    responsibility = json.loads(json.dumps(backend["requirements"][0]))
    responsibility["requirement_id"] = "req-backend-duty"
    responsibility["atomic_text"] = "게임 서비스 백엔드 API 개발"
    responsibility["obligation"] = "INFORMATIONAL"
    responsibility["category"] = "RESPONSIBILITY"
    backend["requirements"].append(responsibility)
    payload["positions"] = [frontend, backend]
    multi = type(structured_posting).model_validate(payload)
    service = pipeline(multi)
    initial = request(source_document, verified_snapshot).model_copy(update={
        "require_posting_confirmation": True,
    })

    position_wait = service.run(initial)
    assert position_wait.status is PipelineStatus.AWAITING_CLARIFICATION
    position_question = position_wait.resolution.active_ambiguity
    assert [option.label for option in position_question.question.options] == [
        "프론트엔드",
        "백엔드",
    ]

    position_answer = ClarificationAnswer(
        ambiguity_id=position_question.ambiguity_id,
        selected_value="pos-backend",
        answered_at=NOW,
    )
    experience_wait = service.run(initial.model_copy(update={
        "structured_posting_checkpoint": position_wait.structured_posting,
        "clarification_answers": [position_answer],
    }))
    assert experience_wait.status is PipelineStatus.AWAITING_CLARIFICATION
    experience_question = experience_wait.resolution.active_ambiguity
    assert [option.value for option in experience_question.question.options] == [
        "track-new-graduate",
        "track-experienced",
    ]

    experience_answer = ClarificationAnswer(
        ambiguity_id=experience_question.ambiguity_id,
        selected_value="track-new-graduate",
        answered_at=NOW,
    )
    review_wait = service.run(initial.model_copy(update={
        "structured_posting_checkpoint": position_wait.structured_posting,
        "clarification_answers": [position_answer, experience_answer],
    }))

    assert review_wait.status is PipelineStatus.AWAITING_POSTING_CONFIRMATION
    assert review_wait.posting_review.position_title == "백엔드"
    assert review_wait.posting_review.selected_experience_track.value == "NEW_GRADUATE"
    assert [item.requirement_id for item in review_wait.posting_review.required_requirements] == [
        "req-java"
    ]
    assert [
        item.requirement_id
        for item in review_wait.posting_review.responsibility_requirements
    ] == ["req-backend-duty"]


def test_pipeline_rejects_checkpoint_from_another_snapshot(
    source_document,
    verified_snapshot,
    structured_posting,
) -> None:
    mismatched = structured_posting.model_copy(update={
        "verified_snapshot_id": "snapshot-other",
    })
    payload = request(source_document, verified_snapshot).model_dump(mode="json")
    payload["structured_posting_checkpoint"] = mismatched.model_dump(mode="json")

    with pytest.raises(ValueError, match="different verified snapshot"):
        AnalysisPipelineRequest.model_validate(payload)


def test_pipeline_stream_emits_progress_before_result(
    source_document,
    verified_snapshot,
    structured_posting,
) -> None:
    secret = "test-ai-secret-123"
    app = create_app(
        Settings(environment="test", shared_secret=secret, host="127.0.0.1", port=8300),
        pipeline_service=pipeline(structured_posting),
    )

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/v1/analysis-pipeline/stream",
                headers={
                    "X-JOBIS-AI-SECRET": secret,
                    "X-JOBIS-AI-CONTRACT": "jobis.ai.v3alpha1",
                },
                json=request(source_document, verified_snapshot).model_dump(
                    mode="json", by_alias=True
                ),
            )

    response = asyncio.run(send())
    rows = [json.loads(line) for line in response.text.splitlines() if line]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert rows[0]["type"] == "PROGRESS"
    assert rows[-1]["type"] == "RESULT"
    assert rows[-1]["result"]["status"] == "COMPLETED"
