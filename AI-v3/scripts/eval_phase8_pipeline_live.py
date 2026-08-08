from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from jobis_ai_v3.capability_graph import closure_content_hash
from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.capability_graph import (
    CapabilityGraphCatalog,
    CapabilityGraphClosure,
    CapabilityGraphEdge,
    CapabilityGraphNode,
    CapabilityNodeType,
    CapabilityRelationType,
    GraphConfidence,
    GraphConfidenceBand,
    GraphReviewStatus,
    GraphSnapshotScope,
    GraphSource,
    GraphSourceType,
    LearningLayer,
    VerificationMethod,
)
from jobis_ai_v3.contracts.fit import UserEvidenceBundle
from jobis_ai_v3.contracts.normalization import (
    CapabilityCatalogEntry,
    CapabilityCatalogSnapshot,
    CapabilityKind,
)
from jobis_ai_v3.contracts.pipeline import AnalysisPipelineRequest, PipelineStatus
from jobis_ai_v3.contracts.roadmap import CurrentRoadmapSnapshot, RoadmapNodeKind
from jobis_ai_v3.contracts.source import (
    ExtractionMethod,
    ExtractionSegment,
    SourceDocument,
    SourceInputType,
    SourceStatus,
    VerifiedBy,
    VerifiedPostingSnapshot,
)
from jobis_ai_v3.fit import FitAnalysisService
from jobis_ai_v3.interpretation import PostingInterpretationService
from jobis_ai_v3.llm import StructuredGenerator, build_json_provider
from jobis_ai_v3.normalization import CapabilityNormalizationService
from jobis_ai_v3.pipeline import AnalysisPipelineService
from jobis_ai_v3.project_planning import ProjectPlanningService
from jobis_ai_v3.resolution import PostingResolutionService
from jobis_ai_v3.roadmap import RoadmapDraftService


NOW = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)
CATALOG_VERSION = "phase8-live-catalog-1"
GRAPH_VERSION = "phase8-live-graph-1"
RAW_TEXT = """네오게임즈 백엔드 개발자(신입)
담당 업무: 게임 결제 이벤트를 처리하는 REST API 개발과 운영
필수 요건: Java, Spring Boot, MySQL, Git 사용 경험
우대 사항: Kafka 기반 비동기 처리 경험
""".strip()


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def source_pair() -> tuple[SourceDocument, VerifiedPostingSnapshot]:
    lines = [line for line in RAW_TEXT.splitlines() if line]
    segments = [
        ExtractionSegment(
            segment_id=f"seg-live-{index}",
            text=line,
            method=ExtractionMethod.USER_PASTE,
            confidence=1.0,
        )
        for index, line in enumerate(lines, start=1)
    ]
    source = SourceDocument(
        source_document_id="source-phase8-live",
        input_type=SourceInputType.TEXT,
        original_input=RAW_TEXT,
        captured_at=NOW,
        extraction_revision=1,
        extractor_version="phase8-live-fixture",
        canonical_input_hash=digest(RAW_TEXT),
        raw_text=RAW_TEXT,
        content_hash=digest(RAW_TEXT),
        segments=segments,
        status=SourceStatus.VERIFIED,
    )
    snapshot = VerifiedPostingSnapshot(
        verified_snapshot_id="snapshot-phase8-live",
        source_document_id=source.source_document_id,
        source_revision=1,
        verified_text=RAW_TEXT,
        evidence_segments=segments,
        verified_by=VerifiedBy.USER,
        verified_at=NOW,
        snapshot_hash=digest(f"{source.content_hash}\n{RAW_TEXT}"),
    )
    return source, snapshot


def catalog() -> CapabilityCatalogSnapshot:
    definitions = [
        ("foundation.programming", "프로그래밍 기초", CapabilityKind.COMPUTER_SCIENCE, ["프로그래밍 기초"]),
        ("lang.java", "Java", CapabilityKind.PROGRAMMING_LANGUAGE, ["Java", "자바"]),
        ("framework.spring-boot", "Spring Boot", CapabilityKind.FRAMEWORK, ["Spring Boot", "스프링 부트"]),
        ("database.mysql", "MySQL", CapabilityKind.DATABASE, ["MySQL"]),
        ("tool.git", "Git", CapabilityKind.TOOL, ["Git"]),
        ("protocol.rest-api", "REST API", CapabilityKind.PROTOCOL, ["REST API", "RESTful API"]),
        ("messaging.kafka", "Kafka", CapabilityKind.MESSAGING, ["Kafka"]),
    ]
    return CapabilityCatalogSnapshot(
        catalog_version=CATALOG_VERSION,
        entries=[CapabilityCatalogEntry(
            canonical_key=key,
            display_name=name,
            kind=kind,
            scope_definition=f"{name}의 핵심 개념을 이해하고 회사 프로젝트에서 구현·검증하는 범위",
            aliases=aliases,
            version=1,
        ) for key, name, kind, aliases in definitions],
    )


class DynamicGraphPort:
    def __init__(self, capability_catalog: CapabilityCatalogSnapshot) -> None:
        self._catalog = {item.canonical_key: item for item in capability_catalog.entries}

    def _source(self) -> GraphSource:
        return GraphSource(
            source_id="source-phase8-live-graph",
            title="Phase 8 live approved curriculum",
            uri="https://example.invalid/phase8-live-curriculum",
            publisher="JOBIS live evaluation",
            source_type=GraphSourceType.INTERNAL_DESIGN,
            retrieved_at=NOW,
            evidence_summary="Reviewed live-evaluation capability fixture.",
            snapshot_scope=GraphSnapshotScope.INTERNAL_RECORD,
            content_hash="sha256:" + "b" * 64,
        )

    def _node(self, key: str, source: GraphSource) -> CapabilityGraphNode:
        entry = self._catalog[key]
        return CapabilityGraphNode(
            canonical_key=key,
            technology_key=key,
            display_name=entry.display_name,
            node_type=CapabilityNodeType.PERFORMANCE,
            kind=entry.kind,
            objective=f"Apply {entry.display_name} in a runnable backend project.",
            scope_definition=entry.scope_definition,
            verification_methods=[VerificationMethod.IMPLEMENT, VerificationMethod.TEST],
            aliases=entry.aliases,
            confidence=GraphConfidence(
                band=GraphConfidenceBand.VERIFIED,
                reason="The live evaluation fixture is explicitly reviewed.",
            ),
            review_status=GraphReviewStatus.APPROVED,
            version=entry.version,
            source_ids=[source.source_id],
        )

    def get_catalog(self) -> CapabilityGraphCatalog:
        source = self._source()
        capabilities = [self._node(key, source) for key in sorted(self._catalog)]
        value = CapabilityGraphCatalog(
            graph_version=GRAPH_VERSION,
            content_hash="sha256:" + "0" * 64,
            capabilities=capabilities,
        )
        payload = value.model_dump(mode="json", by_alias=True, exclude={"content_hash"})
        return value.model_copy(update={"content_hash": digest(str(payload))})

    def get_learning_closure(self, request) -> CapabilityGraphClosure:
        source = self._source()
        keys = list(dict.fromkeys(["foundation.programming", *request.target_capability_keys]))
        nodes = [self._node(key, source) for key in keys]
        edges = [CapabilityGraphEdge(
            relation_id=f"edge-foundation-{key.replace('.', '-')}",
            from_capability_key="foundation.programming",
            to_capability_key=key,
            relation_type=CapabilityRelationType.HARD_PREREQUISITE,
            reason="Programming fundamentals precede this scoped implementation practice.",
            confidence=GraphConfidence(
                band=GraphConfidenceBand.VERIFIED,
                reason="The fixture explicitly defines this prerequisite.",
            ),
            review_status=GraphReviewStatus.APPROVED,
            version=1,
            source_ids=[source.source_id],
        ) for key in request.target_capability_keys if key != "foundation.programming"]
        value = CapabilityGraphClosure(
            graph_version=GRAPH_VERSION,
            generated_at=NOW,
            content_hash="sha256:" + "0" * 64,
            target_capability_keys=request.target_capability_keys,
            boundary_capability_keys=request.boundary_capability_keys,
            nodes=nodes,
            edges=edges,
            sources=[source],
            learning_order=[
                LearningLayer(depth=0, capability_keys=["foundation.programming"]),
                LearningLayer(
                    depth=1,
                    capability_keys=[key for key in keys if key != "foundation.programming"],
                ),
            ],
        )
        return value.model_copy(update={"content_hash": closure_content_hash(value)})


def main() -> int:
    settings = Settings(
        environment="local",
        shared_secret="live-eval-secret-123",
        host="127.0.0.1",
        port=8300,
        llm_provider="codex_cli",
        codex_cli="codex",
        codex_model="gpt-5.6-luna",
        llm_timeout_seconds=240,
        llm_max_attempts=2,
        llm_effort="low",
        llm_retry_effort="medium",
    )
    provider = build_json_provider(settings)

    def generator() -> StructuredGenerator:
        return StructuredGenerator(provider, max_attempts=settings.llm_max_attempts)

    capability_catalog = catalog()
    pipeline = AnalysisPipelineService(
        posting_service=PostingInterpretationService(generator()),
        resolution_service=PostingResolutionService(),
        fit_service=FitAnalysisService(generator()),
        normalization_service=CapabilityNormalizationService(generator()),
        project_planning_service=ProjectPlanningService(generator()),
        graph_port=DynamicGraphPort(capability_catalog),
        roadmap_service=RoadmapDraftService(generator()),
    )
    source, snapshot = source_pair()
    events = []
    result = pipeline.run(AnalysisPipelineRequest(
        job_id="job-phase8-live",
        common_analysis_id="analysis-phase8-live",
        as_of_date=date(2026, 8, 4),
        source_document=source,
        verified_snapshot=snapshot,
        user_evidence=UserEvidenceBundle(
            evidence_set_id="evidence-phase8-live",
            revision=0,
        ),
        current_roadmap=CurrentRoadmapSnapshot(roadmap_version=0),
        opportunity_id="opportunity-phase8-live",
        skip_remaining_evidence_questions=True,
        requested_graph_version=GRAPH_VERSION,
    ), event_sink=events.append)

    if result.status is not PipelineStatus.COMPLETED:
        print(f"PIPELINE\tFAIL\tstatus={result.status.value}", flush=True)
        return 1
    project = next(
        item for item in result.roadmap_proposal.operations
        if item.node_kind is RoadmapNodeKind.TARGET_PROJECT
    )
    opportunity = next(
        item for item in result.roadmap_proposal.operations
        if item.node_kind is RoadmapNodeKind.OPPORTUNITY
    )
    sequences_ok = [item.sequence for item in events] == list(range(1, len(events) + 1))
    ok = (
        sequences_ok
        and result.roadmap_proposal.status.value == "DRAFT"
        and opportunity.opportunity_spec.minimum_experience_months == 0
        and bool(project.project_spec.required_capability_keys)
    )
    print(
        f"PIPELINE\t{'PASS' if ok else 'FAIL'}\tpositions={len(result.structured_posting.positions)}\t"
        f"normalized={len(result.normalization.items)}\tevents={len(events)}\tproject={project.title}",
        flush=True,
    )
    for event in events:
        print(f"EVENT\t{event.sequence}\t{event.stage.value}\t{event.status.value}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
