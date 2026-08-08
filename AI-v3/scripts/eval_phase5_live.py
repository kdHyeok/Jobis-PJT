from __future__ import annotations

import sys

from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.fit import (
    ClaimState,
    EvidenceSourceType,
    EvidenceState,
    FitAnalysisRequest,
    FormalFact,
    RequirementStatus,
    UserCompetencyEvidence,
    UserEvidenceBundle,
    UserEvidenceItem,
    VerificationState,
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
from jobis_ai_v3.fit import FitAnalysisService
from jobis_ai_v3.llm import StructuredGenerator, build_json_provider


CASES = {
    "FIT-001": (
        "Java 개발 경험",
        "lang.java",
        "Java",
        "Java syntax, types, collections, exceptions, and object-oriented programming",
        "VERIFIED_MET",
    ),
    "FIT-002": (
        "Java 언어의 기본 문법과 객체지향 프로그래밍 경험",
        "spring.transaction",
        "Spring transaction management",
        "Transaction boundaries, propagation, isolation, and rollback in Spring applications",
        "UNKNOWN",
    ),
    "FIT-003": (
        "Kafka 기반 비동기 메시지 처리 경험",
        "os.linux",
        "Linux",
        "Linux shell, processes, permissions, filesystems, and service operation",
        "UNKNOWN",
    ),
    "FIT-004": (
        "게임 개발에 대한 열정과 책임감",
        "engine.unity",
        "Unity",
        "Implementing game-client scenes, components, physics, UI, and lifecycle with Unity",
        "UNKNOWN",
    ),
    "FIT-005": (
        "구현 편의보다 실제 사용자의 경험과 제품 목표를 기준으로 시스템을 설계하는 자세",
        "backend.rest-api",
        "REST API",
        "Designing HTTP resources, methods, status codes, validation, and error responses",
        "UNKNOWN",
    ),
    "FIT-006": (
        "JPA/Hibernate를 이용한 ORM 및 도메인 설계 경험",
        "framework.spring-boot",
        "Spring Boot",
        "Configuring and implementing Spring Boot web applications and dependency injection",
        "NOT_VERIFIED_MET",
    ),
    "FIT-007": (
        "FluxionDB 스트림 저장소 운영 경험",
        "database.fluxiondb",
        "FluxionDB stream storage",
        "Operating FluxionDB stream retention, partitions, recovery, and production monitoring",
        "VERIFIED_MET",
    ),
    "FIT-008": (
        "C#과 Unity를 이용한 게임 클라이언트 개발 경험",
        "game.server-networking",
        "Realtime game server networking",
        "Authoritative multiplayer server state, matchmaking, synchronization, and latency handling",
        "NOT_VERIFIED_MET",
    ),
}


def posting(requirement_text: str) -> StructuredPosting:
    return StructuredPosting(
        analysis_version="fit-live-fixture",
        verified_snapshot_id="snapshot-fit-live",
        positions=[
            Position(
                position_id="pos-target",
                source_title="Target role",
                role=RoleCandidate(
                    family="SOFTWARE_ENGINEERING",
                    specialization="TARGET_ROLE",
                    status=RoleStatus.NEW_CANDIDATE,
                    confidence=1.0,
                    evidence_ids=["seg-role"],
                ),
                experience=ExperienceRequirement(
                    kind=ExperienceKind.NEW_GRADUATE,
                    confidence=1.0,
                    evidence_ids=["seg-exp"],
                ),
                requirements=[
                    AtomicRequirement(
                        requirement_id="req-target",
                        source_text=requirement_text,
                        atomic_text=requirement_text,
                        obligation=RequirementObligation.REQUIRED,
                        category=RequirementCategory.TECHNICAL_CAPABILITY,
                        applies_to_position_ids=["pos-target"],
                        evidence_ids=["seg-req"],
                        confidence=1.0,
                        normalization_status=NormalizationStatus.PENDING,
                    )
                ],
            )
        ],
    )


def request(requirement: str, key: str, display: str, scope: str) -> FitAnalysisRequest:
    evidence = UserEvidenceItem(
        evidence_id="ev-target",
        source_type=EvidenceSourceType.VERIFICATION_ANSWER,
        text=f"The user passed a verification scoped to: {scope}",
        verification_state=VerificationState.VERIFIED,
        confidence=1.0,
    )
    competency = UserCompetencyEvidence(
        competency_id=key,
        display_name=display,
        scope_definition=scope,
        claim_state=ClaimState.CLAIMED,
        evidence_state=EvidenceState.EVIDENCED,
        verification_state=VerificationState.VERIFIED,
        claimed_level=2,
        verified_level=2,
        evidence_refs=[evidence.evidence_id],
        confidence=1.0,
    )
    return FitAnalysisRequest(
        common_analysis_id="analysis-fit-live",
        structured_posting=posting(requirement),
        selected_position_id="pos-target",
        selected_experience_track=ExperienceTrack.NEW_GRADUATE,
        user_evidence=UserEvidenceBundle(
            evidence_set_id="evidence-fit-live",
            revision=1,
            competencies=[competency],
            evidence_items=[evidence],
        ),
        skip_remaining_evidence_questions=True,
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
    service = FitAnalysisService(
        StructuredGenerator(build_json_provider(settings), max_attempts=2)
    )
    selected = {
        key: value
        for key, value in CASES.items()
        if len(sys.argv) == 1 or key in sys.argv[1:]
    }
    passed = 0
    for case_id, (requirement, key, display, scope, expectation) in selected.items():
        try:
            result = service.analyze(request(requirement, key, display, scope))
            status = result.assessment.requirement_assessments[0].status
            ok = (
                status is RequirementStatus.VERIFIED_MET
                if expectation == "VERIFIED_MET"
                else status is RequirementStatus.UNKNOWN
                if expectation == "UNKNOWN"
                else status is not RequirementStatus.VERIFIED_MET
            )
            passed += int(ok)
            print(
                f"{case_id}\t{'PASS' if ok else 'FAIL'}\t{status.value}\t"
                f"{result.assessment.requirement_assessments[0].reason}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - evaluation reports every case
            print(f"{case_id}\tERROR\t{type(exc).__name__}: {exc}", flush=True)
    print(f"SUMMARY\t{passed}/{len(selected)}", flush=True)
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
