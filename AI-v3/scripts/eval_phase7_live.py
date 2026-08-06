from __future__ import annotations

from datetime import UTC, datetime

from jobis_ai_v3.capability_graph import closure_content_hash
from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.capability_graph import (
    CapabilityGraphClosure,
    CapabilityGraphEdge,
    CapabilityGraphNode,
    CapabilityRelationType,
    GraphApprovalStatus,
    GraphSource,
)
from jobis_ai_v3.contracts.fit import (
    AssessmentBasis,
    FitAssessment,
    FitAudit,
    FitMetrics,
    RequirementAssessment,
    RequirementStatus,
    VerdictProposal,
)
from jobis_ai_v3.contracts.normalization import (
    CapabilityCandidate,
    CapabilityKind,
    CapabilityNormalizationResult,
    MatchType,
    NormalizationAudit,
    NormalizationDecision,
    RequirementNormalization,
    ReviewStatus,
    RoadmapDisposition,
)
from jobis_ai_v3.contracts.posting import (
    AtomicRequirement,
    ExperienceKind,
    ExperienceRequirement,
    NormalizationStatus,
    Position,
    RequirementCategory,
    RequirementObligation,
    RoleCandidate,
    RoleStatus,
    StructuredPosting,
)
from jobis_ai_v3.contracts.resolution import ExperienceTrack
from jobis_ai_v3.contracts.roadmap import (
    CurrentRoadmapSnapshot,
    OpportunityTargetInput,
    RoadmapDraftRequest,
    RoadmapNodeKind,
    RoadmapRelationType,
)
from jobis_ai_v3.llm import StructuredGenerator, build_json_provider
from jobis_ai_v3.roadmap import RoadmapDraftService


NOW = datetime(2026, 8, 4, 11, 0, tzinfo=UTC)
GRAPH_VERSION = "phase7-live-1"
CASES = [
    {
        "id": "RMAP-001",
        "company": "Example Games",
        "position": "Backend engineer",
        "specialization": "WEB_BACKEND",
        "required": ("lang.java", "Java", CapabilityKind.PROGRAMMING_LANGUAGE,
                     "Java syntax, collections, exceptions, and object-oriented programming"),
        "preferred": ("messaging.kafka", "Kafka", CapabilityKind.MESSAGING,
                      "Kafka topics, producers, consumers, delivery guarantees, and operation"),
        "context": "게임 결제 이벤트를 안전하게 처리하고 운영 상태를 확인할 수 있는 백엔드 서비스",
    },
    {
        "id": "RMAP-002",
        "company": "Realtime Studio",
        "position": "Game server engineer",
        "specialization": "GAME_SERVER",
        "required": ("game.server-networking", "Realtime game server networking",
                     CapabilityKind.TECHNICAL_CAPABILITY,
                     "Authoritative state, matchmaking, synchronization, and latency handling"),
        "preferred": ("infrastructure.redis", "Redis", CapabilityKind.INFRASTRUCTURE,
                      "Redis data structures, expiration, caching, and production operation"),
        "context": "다수의 플레이어가 접속하는 매치메이킹과 상태 동기화 서버",
    },
]


def build_request(case: dict) -> RoadmapDraftRequest:
    required_key, required_name, required_kind, required_scope = case["required"]
    preferred_key, preferred_name, preferred_kind, preferred_scope = case["preferred"]
    position_id = "pos-target"
    requirements = [
        AtomicRequirement(
            requirement_id="req-required",
            source_text=required_name,
            atomic_text=required_name,
            obligation=RequirementObligation.REQUIRED,
            category=RequirementCategory.TECHNOLOGY,
            applies_to_position_ids=[position_id],
            evidence_ids=["seg-required"],
            confidence=1.0,
            normalization_status=NormalizationStatus.PENDING,
        ),
        AtomicRequirement(
            requirement_id="req-preferred",
            source_text=preferred_name,
            atomic_text=preferred_name,
            obligation=RequirementObligation.PREFERRED,
            category=RequirementCategory.TECHNOLOGY,
            applies_to_position_ids=[position_id],
            evidence_ids=["seg-preferred"],
            confidence=1.0,
            normalization_status=NormalizationStatus.PENDING,
        ),
        AtomicRequirement(
            requirement_id="req-project-context",
            source_text=case["context"],
            atomic_text=case["context"],
            obligation=RequirementObligation.INFORMATIONAL,
            category=RequirementCategory.RESPONSIBILITY,
            applies_to_position_ids=[position_id],
            evidence_ids=["seg-context"],
            confidence=1.0,
            normalization_status=NormalizationStatus.NOT_APPLICABLE,
        ),
    ]
    posting = StructuredPosting(
        analysis_version="phase7-live",
        verified_snapshot_id="snapshot-phase7-live",
        positions=[Position(
            position_id=position_id,
            source_title=case["position"],
            role=RoleCandidate(
                family="SOFTWARE_ENGINEERING",
                specialization=case["specialization"],
                status=RoleStatus.NEW_CANDIDATE,
                confidence=1.0,
                evidence_ids=["seg-role"],
            ),
            experience=ExperienceRequirement(
                kind=ExperienceKind.NEW_GRADUATE,
                confidence=1.0,
                evidence_ids=["seg-exp"],
            ),
            requirements=requirements,
        )],
    )
    assessments = [
        RequirementAssessment(
            requirement_id="req-required",
            status=RequirementStatus.EVIDENCED,
            required=True,
            included_in_denominator=True,
            basis=AssessmentBasis.CAREER_EVIDENCE,
            posting_evidence_ids=["seg-required"],
            reason="Relevant career evidence exists.",
            confidence=0.9,
        ),
        RequirementAssessment(
            requirement_id="req-preferred",
            status=RequirementStatus.UNKNOWN,
            required=False,
            included_in_denominator=False,
            basis=AssessmentBasis.NO_INFORMATION,
            posting_evidence_ids=["seg-preferred"],
            reason="No user evidence was supplied.",
            confidence=0.8,
        ),
    ]
    fit = FitAssessment(
        fit_assessment_id=f"fit-{case['id'].lower()}",
        common_analysis_id=f"analysis-{case['id'].lower()}",
        selected_position_id=position_id,
        selected_experience_track=ExperienceTrack.NEW_GRADUATE,
        user_evidence_set_id="evidence-live",
        user_evidence_revision=1,
        policy_version="fit-policy-0.1",
        formal_eligibility=RequirementStatus.NOT_APPLICABLE,
        requirement_assessments=assessments,
        metrics=FitMetrics(
            required_total=1,
            required_known=1,
            required_verified_met=0,
            preferred_total=1,
            claimed_readiness_percent=100,
            evidenced_readiness_percent=100,
            verified_readiness_percent=0,
        ),
        verdict_proposal=VerdictProposal.STRENGTHEN_THEN_APPLY,
        audit=FitAudit(
            matcher_version="phase7-live",
            policy_version="fit-policy-0.1",
            provider="fixture",
            model="fixture",
            generation_attempts=1,
            generation_duration_ms=1,
            evaluated_requirement_ids=["req-required", "req-preferred"],
        ),
    )
    normalization_items = []
    for req_id, key, category, required in [
        ("req-required", required_key, RequirementCategory.TECHNOLOGY, True),
        ("req-preferred", preferred_key, RequirementCategory.TECHNOLOGY, False),
    ]:
        normalization_items.append(RequirementNormalization(
            requirement_id=req_id,
            source_category=category,
            disposition=RoadmapDisposition.LEARNING_CAPABILITY,
            decision=NormalizationDecision.AUTO_SELECTED,
            selected_canonical_key=key,
            candidates=[CapabilityCandidate(
                canonical_key=key,
                match_type=MatchType.EXACT_ALIAS,
                confidence=1.0,
                reason="Approved exact fixture",
            )],
            review_status=ReviewStatus.NOT_REQUIRED,
            evidence_ids=["seg-required" if required else "seg-preferred"],
            reason="Approved exact fixture",
        ))
    normalization_items.append(RequirementNormalization(
        requirement_id="req-project-context",
        source_category=RequirementCategory.RESPONSIBILITY,
        disposition=RoadmapDisposition.PROJECT_CONTEXT,
        decision=NormalizationDecision.NOT_APPLICABLE,
        review_status=ReviewStatus.NOT_REQUIRED,
        evidence_ids=["seg-context"],
        reason="Used in the target project brief.",
    ))
    normalization = CapabilityNormalizationResult(
        normalization_id=f"normalization-{case['id'].lower()}",
        common_analysis_id=f"analysis-{case['id'].lower()}",
        selected_position_id=position_id,
        catalog_version=GRAPH_VERSION,
        items=normalization_items,
        audit=NormalizationAudit(
            normalizer_version="phase7-live",
            catalog_version=GRAPH_VERSION,
        ),
    )
    source = GraphSource(
        source_id="source-phase7-live",
        title="Approved capability graph fixture",
        uri="https://example.invalid/graph",
        publisher="JOBIS evaluation",
        retrieved_at=NOW,
        content_hash="sha256:" + "a" * 64,
    )
    foundation_key = "foundation.programming"
    graph = CapabilityGraphClosure(
        graph_version=GRAPH_VERSION,
        catalog_version=GRAPH_VERSION,
        generated_at=NOW,
        content_hash="sha256:" + "0" * 64,
        target_capability_keys=[required_key, preferred_key],
        nodes=[
            CapabilityGraphNode(
                canonical_key=foundation_key,
                display_name="Programming foundations",
                kind=CapabilityKind.COMPUTER_SCIENCE,
                scope_definition="Control flow, data structures, functions, and basic problem solving",
                level=1,
                universal_foundation=True,
                approval_status=GraphApprovalStatus.APPROVED,
                source_ids=[source.source_id],
            ),
            CapabilityGraphNode(
                canonical_key=required_key,
                display_name=required_name,
                kind=required_kind,
                scope_definition=required_scope,
                level=2,
                approval_status=GraphApprovalStatus.APPROVED,
                source_ids=[source.source_id],
            ),
            CapabilityGraphNode(
                canonical_key=preferred_key,
                display_name=preferred_name,
                kind=preferred_kind,
                scope_definition=preferred_scope,
                level=3,
                approval_status=GraphApprovalStatus.APPROVED,
                source_ids=[source.source_id],
            ),
        ],
        edges=[CapabilityGraphEdge(
            edge_id="edge-foundation-required",
            from_capability_key=foundation_key,
            to_capability_key=required_key,
            relation_type=CapabilityRelationType.HARD_PREREQUISITE,
            confidence=0.95,
            approval_status=GraphApprovalStatus.APPROVED,
            source_ids=[source.source_id],
            reason="Approved prerequisite fixture.",
        )],
        sources=[source],
    )
    graph = graph.model_copy(update={"content_hash": closure_content_hash(graph)})
    return RoadmapDraftRequest(
        common_analysis_id=f"analysis-{case['id'].lower()}",
        structured_posting=posting,
        selected_position_id=position_id,
        fit_assessment=fit,
        normalization=normalization,
        capability_graph=graph,
        current_roadmap=CurrentRoadmapSnapshot(roadmap_version=0),
        opportunity=OpportunityTargetInput(
            opportunity_id=f"opportunity-{case['id'].lower()}",
            company_name=case["company"],
            position_title=case["position"],
        ),
    )


def main() -> int:
    settings = Settings(
        environment="local",
        shared_secret="live-eval-secret-123",
        host="127.0.0.1",
        port=8300,
        llm_provider="claude_code",
        claude_cli="claude",
        claude_code_model="sonnet",
        llm_timeout_seconds=180,
        llm_max_attempts=2,
    )
    service = RoadmapDraftService(
        StructuredGenerator(build_json_provider(settings), max_attempts=2)
    )
    passed = 0
    for case in CASES:
        try:
            request = build_request(case)
            proposal = service.compose(request)
            project = next(
                item for item in proposal.operations
                if item.node_kind is RoadmapNodeKind.TARGET_PROJECT
            )
            required_key = case["required"][0]
            preferred_key = case["preferred"][0]
            bonus = any(
                relation.relation_type is RoadmapRelationType.BONUS_SUPPORTS_PROJECT
                for relation in proposal.relations
            )
            ok = (
                project.project_spec.required_capability_keys == [required_key]
                and project.project_spec.preferred_capability_keys == [preferred_key]
                and bonus
                and proposal.status.value == "DRAFT"
            )
            passed += int(ok)
            print(
                f"{case['id']}\t{'PASS' if ok else 'FAIL'}\t{project.title}\t"
                f"deliverables={len(project.project_spec.deliverables)}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - evaluation reports every case
            print(f"{case['id']}\tERROR\t{type(exc).__name__}: {exc}", flush=True)
    print(f"SUMMARY\t{passed}/{len(CASES)}", flush=True)
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
