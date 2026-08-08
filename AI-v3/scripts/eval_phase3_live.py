from __future__ import annotations

import sys
from datetime import date

from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.posting import PostingInterpretationRequest
from jobis_ai_v3.contracts.source import (
    SourceAcquisitionRequest,
    SourceEntryPoint,
    SourceInputType,
    SourceVerificationRequest,
    VerifiedBy,
)
from jobis_ai_v3.interpretation import PostingInterpretationService
from jobis_ai_v3.llm import StructuredGenerator, build_json_provider
from jobis_ai_v3.source import SourceAcquisitionService


CASES = {
    "ROLE-001": "백엔드 개발자를 모집합니다. 프론트엔드 개발자와 협업합니다.",
    "ROLE-002": (
        "웹 개발자 모집. TypeScript와 Next.js 기반 프론트엔드 또는 Java와 Kotlin을 사용하는 "
        "Spring 기반 백엔드. 신입 또는 경력 3년 이상. 프론트엔드 우대: React, Next.js. "
        "백엔드 우대: Spring Boot, REST API, JPA."
    ),
    "ROLE-003": (
        "Unity와 C#을 사용한 2D 게임 클라이언트 개발, 라이브 서비스 업데이트와 UI 구현을 "
        "담당합니다. AWS와 SQL 사용 경험 우대."
    ),
    "ROLE-004": (
        "실시간 멀티플레이 게임 서버 개발자를 모집합니다. 매치메이킹, 상태 동기화, "
        "네트워크 지연 대응을 개발합니다."
    ),
    "EXP-001": "지원 자격: 신입. 회사 소개: QA 분야에서 19년의 경험을 축적했습니다. QA 엔지니어 모집.",
    "EXP-002": "10년 이상 서비스를 운영해 온 회사입니다. 신입 백엔드 개발자를 모집합니다.",
    "EXP-003": "프론트엔드: 신입. 백엔드: 경력 3년 이상. QA: 경력 2년 이상.",
    "REQ-001": (
        "백엔드 개발자 모집. 필수: Celery · REST API · 백엔드 구현 편의가 아닌, "
        "실제 사용자의 경험과 제품 목표를 기준으로 시스템을 설계하는 자세"
    ),
    "REQ-002": "게임 클라이언트 개발자 모집. 우대: 게임 개발에 대한 열정과 책임감.",
    "REQ-004": "백엔드 개발자 모집. 필수: FluxionDB를 이용한 스트림 저장소 운영 경험.",
}


def _request(text: str, settings: Settings) -> PostingInterpretationRequest:
    source_service = SourceAcquisitionService(settings=settings)
    source = source_service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.TEXT,
        entry_point=SourceEntryPoint.INTERNAL,
        text=text,
    ))
    verified = source_service.verify(SourceVerificationRequest(
        source_document=source,
        verified_text=source.raw_text,
        verified_by=VerifiedBy.OPERATOR,
    ))
    return PostingInterpretationRequest(
        source_document=verified.source_document,
        verified_snapshot=verified.verified_snapshot,
        as_of_date=date(2026, 8, 4),
    )


def _passes(case_id: str, posting) -> bool:
    positions = posting.positions
    specializations = [position.role.specialization for position in positions]
    experiences = [position.experience for position in positions]
    if case_id == "ROLE-001":
        return len(positions) == 1 and specializations == ["WEB_BACKEND"]
    if case_id == "ROLE-002":
        return (
            len(positions) == 2
            and set(specializations) == {"WEB_FRONTEND", "WEB_BACKEND"}
            and all(item.kind.value == "NEW_GRADUATE_OR_EXPERIENCED" for item in experiences)
            and all(item.experienced_min_months == 36 for item in experiences)
        )
    if case_id == "ROLE-003":
        return len(positions) == 1 and specializations == ["GAME_CLIENT"]
    if case_id == "ROLE-004":
        return len(positions) == 1 and specializations == ["GAME_SERVER"]
    if case_id in {"EXP-001", "EXP-002"}:
        return (
            len(positions) == 1
            and experiences[0].kind.value == "NEW_GRADUATE"
            and experiences[0].min_months is None
        )
    if case_id == "EXP-003":
        actual = {
            position.role.specialization: position.experience.min_months
            for position in positions
        }
        return actual == {"WEB_FRONTEND": None, "WEB_BACKEND": 36, "QA_ENGINEERING": 24}
    requirements = [item for position in positions for item in position.requirements]
    if case_id == "REQ-001":
        technologies = {item.atomic_text.casefold() for item in requirements if item.category.value == "TECHNOLOGY"}
        return (
            any("celery" in item for item in technologies)
            and any("rest api" in item for item in technologies)
            and any(item.category.value == "BEHAVIORAL" for item in requirements)
        )
    if case_id == "REQ-002":
        return (
            any(item.category.value == "BEHAVIORAL" for item in requirements)
            and not any(item.category.value == "TECHNOLOGY" for item in requirements)
        )
    if case_id == "REQ-004":
        return any(
            "fluxiondb" in item.atomic_text.casefold()
            and item.category.value == "TECHNOLOGY"
            and item.normalization_status.value == "PENDING"
            for item in requirements
        )
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
    interpreter = PostingInterpretationService(
        StructuredGenerator(build_json_provider(settings), max_attempts=2)
    )
    passed = 0
    selected = {key: value for key, value in CASES.items() if len(sys.argv) == 1 or key in sys.argv[1:]}
    for case_id, text in selected.items():
        try:
            posting = interpreter.interpret(_request(text, settings))
            ok = _passes(case_id, posting)
            passed += int(ok)
            positions = [
                {
                    "role": position.role.specialization,
                    "experience": position.experience.kind.value,
                    "minMonths": position.experience.min_months,
                    "experiencedMinMonths": position.experience.experienced_min_months,
                }
                for position in posting.positions
            ]
            print(f"{case_id}\t{'PASS' if ok else 'FAIL'}\t{positions}", flush=True)
        except Exception as exc:  # noqa: BLE001 - evaluation must report every case
            print(f"{case_id}\tERROR\t{type(exc).__name__}: {exc}", flush=True)
    print(f"SUMMARY\t{passed}/{len(selected)}", flush=True)
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
