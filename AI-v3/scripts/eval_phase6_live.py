from __future__ import annotations

import sys

from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.normalization import (
    CapabilityCatalogEntry,
    CapabilityCatalogSnapshot,
    CapabilityKind,
    CapabilityNormalizationRequest,
    NormalizationDecision,
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
from jobis_ai_v3.llm import StructuredGenerator, build_json_provider
from jobis_ai_v3.normalization import CapabilityNormalizationService


CASES = {
    "NORM-001": ("Java 개발 경험", "TECHNOLOGY", "CANDIDATE", "lang.java"),
    "NORM-002": ("Spring Boot 기반 웹 서버 개발", "TECHNOLOGY", "CANDIDATE", "framework.spring-boot"),
    "NORM-003": ("MySQL JOIN 작성 경험", "TECHNICAL_CAPABILITY", "CANDIDATE", "database.mysql"),
    "NORM-004": ("FluxionDB 스트림 저장소 운영", "TECHNOLOGY", "NEW", "FluxionDB"),
    "NORM-005": (
        "Spring 트랜잭션 전파와 격리 수준을 설정하고 롤백을 제어하는 경험",
        "TECHNICAL_CAPABILITY",
        "CANDIDATE",
        "spring.transaction-management",
    ),
    "NORM-006": (
        "실시간 게임 서버의 매치메이킹과 상태 동기화 구현",
        "TECHNICAL_CAPABILITY",
        "CANDIDATE",
        "game.server-networking",
    ),
    "NORM-007": ("Celery와 REST API 개발", "TECHNOLOGY", "SPLIT", None),
    "NORM-008": (
        "게임 개발에 대한 열정과 책임감",
        "BEHAVIORAL",
        "DISPOSITION",
        "FIT_ONLY",
    ),
    "NORM-009": (
        "게임 회사 맞춤형 포트폴리오 프로젝트 완성",
        "RESPONSIBILITY",
        "DISPOSITION",
        "PROJECT_CONTEXT",
    ),
}


def entry(key: str, name: str, kind: CapabilityKind, scope: str, aliases=None):
    return CapabilityCatalogEntry(
        canonical_key=key,
        display_name=name,
        kind=kind,
        scope_definition=scope,
        aliases=aliases or [],
        version=1,
    )


CATALOG = CapabilityCatalogSnapshot(
    catalog_version="phase6-live-1",
    entries=[
        entry(
            "lang.java", "Java", CapabilityKind.PROGRAMMING_LANGUAGE,
            "Java syntax, collections, exceptions, object-oriented programming, and standard library",
        ),
        entry(
            "framework.spring-boot", "Spring Boot", CapabilityKind.FRAMEWORK,
            "Spring Boot configuration, dependency injection, web applications, and production conventions",
        ),
        entry(
            "database.mysql", "MySQL", CapabilityKind.DATABASE,
            "MySQL schema, CRUD, JOIN, grouping, indexes, query plans, and transaction basics",
        ),
        entry(
            "spring.transaction-management", "Spring transaction management",
            CapabilityKind.TECHNICAL_CAPABILITY,
            "Spring transaction boundaries, propagation, isolation levels, rollback, and consistency",
            ["Spring 트랜잭션"],
        ),
        entry(
            "game.client-unity", "Unity game client development", CapabilityKind.TECHNICAL_CAPABILITY,
            "Unity scenes, components, game UI, client lifecycle, rendering, and local gameplay logic",
        ),
        entry(
            "game.server-networking", "Realtime game server networking", CapabilityKind.TECHNICAL_CAPABILITY,
            "Authoritative multiplayer server state, matchmaking, synchronization, and latency handling",
        ),
        entry(
            "tool.celery", "Celery", CapabilityKind.TOOL,
            "Celery task queues, workers, retries, scheduling, and asynchronous job operation",
        ),
        entry(
            "protocol.rest-api", "REST API", CapabilityKind.PROTOCOL,
            "HTTP resources, methods, status codes, validation, and error responses",
        ),
    ],
)


def posting(text: str, category: str) -> StructuredPosting:
    return StructuredPosting(
        analysis_version="normalization-live-fixture",
        verified_snapshot_id="snapshot-normalization-live",
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
                        source_text=text,
                        atomic_text=text,
                        obligation=RequirementObligation.REQUIRED,
                        category=RequirementCategory(category),
                        applies_to_position_ids=["pos-target"],
                        evidence_ids=["seg-req"],
                        confidence=1.0,
                        normalization_status=NormalizationStatus.PENDING,
                    )
                ],
            )
        ],
    )


def passes(kind: str, value: str | None, item) -> bool:
    if kind == "CANDIDATE":
        return (
            item.decision is NormalizationDecision.CANDIDATES_PROPOSED
            and value in {candidate.canonical_key for candidate in item.candidates}
        )
    if kind == "NEW":
        return (
            item.decision is NormalizationDecision.NEW_CANDIDATE_PROPOSED
            and value.casefold() in item.new_candidate.display_name.casefold()
        )
    if kind == "SPLIT":
        return item.decision is NormalizationDecision.SPLIT_REQUIRED
    if kind == "DISPOSITION":
        return item.disposition is RoadmapDisposition(value)
    return False


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
    service = CapabilityNormalizationService(
        StructuredGenerator(build_json_provider(settings), max_attempts=2)
    )
    selected = {
        key: value
        for key, value in CASES.items()
        if len(sys.argv) == 1 or key in sys.argv[1:]
    }
    passed = 0
    for case_id, (text, category, expected_kind, expected_value) in selected.items():
        try:
            result = service.normalize(CapabilityNormalizationRequest(
                common_analysis_id=f"analysis-{case_id.lower()}",
                structured_posting=posting(text, category),
                selected_position_id="pos-target",
                catalog=CATALOG,
            ))
            item = result.items[0]
            ok = passes(expected_kind, expected_value, item)
            passed += int(ok)
            candidates = [candidate.canonical_key for candidate in item.candidates]
            new_name = item.new_candidate.display_name if item.new_candidate else None
            print(
                f"{case_id}\t{'PASS' if ok else 'FAIL'}\t{item.decision.value}\t"
                f"{item.disposition.value}\t{candidates}\t{new_name}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - evaluation reports every case
            print(f"{case_id}\tERROR\t{type(exc).__name__}: {exc}", flush=True)
    print(f"SUMMARY\t{passed}/{len(selected)}", flush=True)
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
