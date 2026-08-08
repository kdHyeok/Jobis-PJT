from __future__ import annotations

import json
from datetime import date

import pytest

from jobis_ai.career_pipeline.config import Settings
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.contracts.posting import (
    ApprovedRoleCatalogEntry,
    PostingInterpretationRequest,
    PostingStatus,
    RequirementCategory,
)
from jobis_ai.career_pipeline.contracts.source import (
    SourceAcquisitionRequest,
    SourceEntryPoint,
    SourceInputType,
    SourceVerificationRequest,
    VerifiedBy,
)
from jobis_ai.career_pipeline.interpretation import PostingInterpretationFailure, PostingInterpretationService
from jobis_ai.career_pipeline.interpretation.draft import PostingDiscoveryDraft
from jobis_ai.career_pipeline.interpretation.service import _build_prompt, _restore_draft_evidence_ids
from jobis_ai.career_pipeline.llm import JsonProviderError, StructuredGenerator
from jobis_ai.career_pipeline.source import SourceAcquisitionService


SETTINGS = Settings(
    environment="test",
    shared_secret="test-ai-secret-123",
    host="127.0.0.1",
    port=8300,
)


class StaticProvider:
    name = "scripted"
    model = "fixture-model"

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls = 0
        self.requests: list[dict] = []

    def complete_json(self, **kwargs) -> str:
        self.requests.append(kwargs)
        index = min(self.calls, len(self.payloads) - 1)
        self.calls += 1
        return json.dumps(self.payloads[index], ensure_ascii=False)


def test_provider_limit_is_not_reported_as_invalid_posting_structure() -> None:
    class LimitedProvider:
        name = "codex_cli"
        model = "gpt-5.6-luna"

        def complete_json(self, **_kwargs) -> str:
            raise JsonProviderError("usage limit reached")

    service = PostingInterpretationService(
        StructuredGenerator(LimitedProvider(), max_attempts=1)
    )

    with pytest.raises(PostingInterpretationFailure) as raised:
        service.discover(verified_request("백엔드 개발자 신입 채용"))

    assert raised.value.code is ErrorCode.AI_PROVIDER_UNAVAILABLE


def verified_request(raw_text: str) -> PostingInterpretationRequest:
    source_service = SourceAcquisitionService(settings=SETTINGS)
    source = source_service.acquire(SourceAcquisitionRequest(
        input_type=SourceInputType.TEXT,
        entry_point=SourceEntryPoint.CHAT,
        text=raw_text,
    ))
    verified = source_service.verify(SourceVerificationRequest(
        source_document=source,
        verified_text=source.raw_text,
        verified_by=VerifiedBy.USER,
    ))
    return PostingInterpretationRequest(
        source_document=verified.source_document,
        verified_snapshot=verified.verified_snapshot,
        as_of_date=date(2026, 8, 4),
    )


def evidence_id(request: PostingInterpretationRequest, phrase: str) -> str:
    matches = [
        segment.segment_id
        for segment in request.verified_snapshot.evidence_segments
        if phrase in segment.text
    ]
    assert matches, phrase
    return matches[0]


def test_interpretation_prompt_uses_compact_evidence_rows() -> None:
    request = verified_request("\n".join(
        f"필수 요건 {index:03d}: Java와 Spring 역량"
        for index in range(1, 141)
    ))

    prompt = _build_prompt(request)
    payload = json.loads(prompt.text)

    assert prompt.truncated is False
    assert len(payload["evidenceSegments"]) == 140
    assert all(set(segment) == {"segmentId", "text"} for segment in payload["evidenceSegments"])
    assert [segment["segmentId"] for segment in payload["evidenceSegments"][:3]] == [
        "E001",
        "E002",
        "E003",
    ]
    assert prompt.evidence_alias_to_id["E001"] == request.verified_snapshot.evidence_segments[0].segment_id
    assert len(prompt.text) < 20_000


def test_published_role_catalog_is_added_to_the_interpreter_prompt() -> None:
    request = verified_request("AI 보안 담당자 채용")
    request = request.model_copy(update={
        "approved_role_catalog": [ApprovedRoleCatalogEntry(
            canonical_role_id="security.ai-security",
            family="SECURITY_ENGINEERING",
            specialization="AI_SECURITY",
        )],
    })

    payload = json.loads(_build_prompt(request).text)

    assert {
        "canonicalRoleId": "security.ai-security",
        "family": "SECURITY_ENGINEERING",
        "specialization": "AI_SECURITY",
    } in payload["roleCatalog"]


def test_discovery_restores_short_evidence_aliases_to_verified_ids() -> None:
    request = verified_request("백엔드 개발자 신입 채용")

    class AliasProvider:
        name = "codex_cli"
        model = "gpt-5.6-luna"

        def complete_json(self, **kwargs) -> str:
            prompt = json.loads(kwargs["user_prompt"])
            alias = prompt["evidenceSegments"][0]["segmentId"]
            return json.dumps({
                "company": None,
                "postingTitle": "백엔드 개발자 신입 채용",
                "postingTitleEvidenceIds": [alias],
                "positions": [{
                    "positionKey": "backend",
                    "sourceTitle": "백엔드 개발자",
                    "role": role(
                        "SOFTWARE_ENGINEERING",
                        "WEB_BACKEND",
                        alias,
                        "role.web_backend",
                    ),
                    "experience": experience("NEW_GRADUATE", alias),
                }],
            }, ensure_ascii=False)

    service = PostingInterpretationService(
        StructuredGenerator(AliasProvider(), max_attempts=1)
    )
    posting = service.discover(request)
    actual_id = request.verified_snapshot.evidence_segments[0].segment_id

    assert posting.posting_title_evidence_ids == [actual_id]
    assert posting.positions[0].role.evidence_ids == [actual_id]
    assert posting.positions[0].experience.evidence_ids == [actual_id]
    assert not any(item.code == "EVIDENCE_ID_REPAIRED" for item in posting.warnings)


def test_discovery_repairs_one_missing_trailing_evidence_character() -> None:
    request = verified_request("백엔드 개발자 신입 채용")
    actual_id = request.verified_snapshot.evidence_segments[0].segment_id
    shortened = actual_id[:-1]

    class ShortenedProvider:
        name = "codex_cli"
        model = "gpt-5.6-luna"

        def complete_json(self, **_kwargs) -> str:
            return json.dumps({
                "company": None,
                "postingTitle": "백엔드 개발자 신입 채용",
                "postingTitleEvidenceIds": [shortened],
                "positions": [{
                    "positionKey": "backend",
                    "sourceTitle": "백엔드 개발자",
                    "role": role(
                        "SOFTWARE_ENGINEERING",
                        "WEB_BACKEND",
                        shortened,
                        "role.web_backend",
                    ),
                    "experience": experience("NEW_GRADUATE", shortened),
                }],
            }, ensure_ascii=False)

    service = PostingInterpretationService(
        StructuredGenerator(ShortenedProvider(), max_attempts=1)
    )
    posting = service.discover(request)

    assert posting.positions[0].role.evidence_ids == [actual_id]
    warning = next(item for item in posting.warnings if item.code == "EVIDENCE_ID_REPAIRED")
    assert warning.evidence_ids == [actual_id]


def test_ambiguous_short_evidence_alias_is_not_guessed() -> None:
    request = verified_request("백엔드 개발자 신입 채용")
    draft = PostingDiscoveryDraft.model_validate({
        "company": None,
        "postingTitle": None,
        "postingTitleEvidenceIds": [],
        "positions": [{
            "positionKey": "backend",
            "sourceTitle": "백엔드 개발자",
            "role": role(
                "SOFTWARE_ENGINEERING",
                "WEB_BACKEND",
                "E00",
                "role.web_backend",
            ),
            "experience": experience("NEW_GRADUATE", "E00"),
        }],
    })

    restored, repairs = _restore_draft_evidence_ids(
        draft,
        {"E001": "vseg-one", "E002": "vseg-two"},
        request,
    )

    assert restored.positions[0].role.evidence_ids == ["E00"]
    assert repairs == []


def experience(kind: str, evidence: str, **extra) -> dict:
    return {
        "kind": kind,
        "minMonths": None,
        "maxMonths": None,
        "experiencedMinMonths": None,
        "confidence": 0.98,
        "evidenceIds": [evidence],
        **extra,
    }


def role(
    family: str,
    specialization: str,
    evidence: str,
    canonical: str | None,
) -> dict:
    return {
        "family": family,
        "specialization": specialization,
        "canonicalRoleIdCandidate": canonical,
        "confidence": 0.96,
        "evidenceIds": [evidence],
    }


def base_draft(request: PostingInterpretationRequest, *, title: str, title_evidence: str) -> dict:
    return {
        "company": None,
        "postingTitle": title,
        "postingTitleEvidenceIds": [title_evidence],
        "positions": [],
        "sharedConditions": [],
        "applicationDeadline": None,
        "applicationDeadlineEvidenceIds": [],
    }


def run_draft(request: PostingInterpretationRequest, draft: dict):
    provider = StaticProvider([draft])
    service = PostingInterpretationService(StructuredGenerator(provider, max_attempts=2))
    return service.interpret(request), provider


def test_discovery_then_selected_detail_is_small_grounded_and_roadmap_scoped() -> None:
    request = verified_request(
        "[ESTgames] 웹 개발자\n"
        "이스트게임즈는 게임 제작 전문 기업입니다.\n"
        "프론트엔드 개발\n"
        "백엔드 개발\n"
        "신입 또는 경력 3년 이상\n"
        "담당 업무: REST API 개발\n"
        "필수: Java와 Spring Boot 개발 경험\n"
        "필수: 주변 동료와 원활하게 협업\n"
        "근무지: 서울 서초구\n"
        "접수 마감: 채용 시 마감"
    )
    title = evidence_id(request, "[ESTgames]")
    company = evidence_id(request, "이스트게임즈는")
    frontend = evidence_id(request, "프론트엔드 개발")
    backend = evidence_id(request, "백엔드 개발")
    career = evidence_id(request, "신입 또는 경력")
    duty = evidence_id(request, "REST API")
    java = evidence_id(request, "Java와 Spring")
    behavioral = evidence_id(request, "원활하게 협업")
    location = evidence_id(request, "근무지")
    deadline = evidence_id(request, "접수 마감")
    discovery_draft = {
        "company": {
            "displayName": "이스트게임즈 (ESTgames)",
            "evidenceIds": [title, company],
            "confidence": 0.98,
        },
        "postingTitle": "[ESTgames] 웹 개발자",
        "postingTitleEvidenceIds": [title],
        "positions": [
            {
                "positionKey": "frontend",
                "sourceTitle": "프론트엔드",
                "role": role(
                    "SOFTWARE_ENGINEERING",
                    "WEB_FRONTEND",
                    frontend,
                    "role.web_frontend",
                ),
                "experience": experience(
                    "NEW_GRADUATE_OR_EXPERIENCED",
                    career,
                    experiencedMinMonths=36,
                ),
            },
            {
                "positionKey": "backend",
                "sourceTitle": "백엔드",
                "role": role(
                    "SOFTWARE_ENGINEERING",
                    "WEB_BACKEND",
                    backend,
                    "role.web_backend",
                ),
                "experience": experience(
                    "NEW_GRADUATE_OR_EXPERIENCED",
                    career,
                    experiencedMinMonths=36,
                ),
            },
        ],
    }
    detail_draft = {
        "responsibilities": [{
            "atomicText": "REST API 개발",
            "evidenceIds": [duty],
            "confidence": 0.97,
        }],
        "requirements": [
            {
                "atomicText": "Java와 Spring Boot 개발 경험",
                "obligation": "REQUIRED",
                "category": "TECHNOLOGY",
                "evidenceIds": [java],
                "confidence": 0.97,
            },
            {
                "atomicText": "주변 동료와 원활하게 협업",
                "obligation": "REQUIRED",
                "category": "BEHAVIORAL",
                "evidenceIds": [behavioral],
                "confidence": 0.9,
            },
            {
                "atomicText": "서울 서초구 근무",
                "obligation": "INFORMATIONAL",
                "category": "EMPLOYMENT_CONDITION",
                "evidenceIds": [location],
                "confidence": 0.9,
            },
        ],
        "applicationDeadline": None,
        "applicationDeadlineEvidenceIds": [deadline],
    }
    provider = StaticProvider([discovery_draft, detail_draft])
    service = PostingInterpretationService(
        StructuredGenerator(provider, max_attempts=1)
    )

    discovery = service.discover(request)
    detailed = service.interpret_selected(
        request,
        discovery=discovery,
        selected_position_id="pos-2",
    )
    detail_prompt = json.loads(provider.requests[1]["user_prompt"])
    backend_alias = next(
        alias
        for alias, actual_id in _build_prompt(request).evidence_alias_to_id.items()
        if actual_id == backend
    )

    assert provider.calls == 2
    assert detail_prompt["selectedPosition"]["role"]["evidenceIds"] == [backend_alias]
    assert backend not in provider.requests[1]["user_prompt"]
    assert discovery.company.display_name == "이스트게임즈"
    assert all(not position.requirements for position in discovery.positions)
    assert detailed.positions[0].requirements == []
    assert len(detailed.positions[1].responsibilities) == 1
    assert [item.atomic_text for item in detailed.positions[1].requirements] == [
        "Java와 Spring Boot 개발 경험"
    ]
    assert detailed.application_deadline_evidence_ids == []
    assert {warning.code for warning in detailed.warnings} >= {
        "COMPANY_NAME_GROUNDED_TO_SOURCE",
        "NON_ROADMAP_REQUIREMENTS_OMITTED",
        "DEADLINE_EVIDENCE_REPAIRED",
    }


def test_missing_source_text_is_reconstructed_from_verified_evidence() -> None:
    request = verified_request(
        "백엔드 개발자를 모집합니다.\n필수: Java와 Spring Boot 개발 경험"
    )
    title = evidence_id(request, "백엔드 개발자")
    requirement = evidence_id(request, "Java와 Spring Boot")
    draft = base_draft(request, title="백엔드 개발자", title_evidence=title)
    draft["positions"] = [{
        "positionKey": "backend",
        "sourceTitle": "웹 백엔드 개발자",
        "role": role("SOFTWARE_ENGINEERING", "WEB_BACKEND", title, "role.web_backend"),
        "experience": experience("UNKNOWN", title),
        "responsibilities": [],
        "requirements": [{
            "atomicText": "Java와 Spring Boot 개발 경험",
            "obligation": "REQUIRED",
            "category": "TECHNOLOGY",
            "evidenceIds": [requirement],
            "confidence": 0.95,
        }],
    }]

    posting, _provider = run_draft(request, draft)

    assert posting.positions[0].source_title == "백엔드"
    assert posting.positions[0].requirements[0].source_text == (
        "필수: Java와 Spring Boot 개발 경험"
    )


def test_collaboration_target_does_not_become_a_second_position() -> None:
    request = verified_request(
        "백엔드 개발자를 모집합니다.\n프론트엔드 개발자와 협업합니다."
    )
    backend = evidence_id(request, "백엔드 개발자")
    draft = base_draft(request, title="백엔드 개발자", title_evidence=backend)
    draft["positions"] = [{
        "positionKey": "backend",
        "sourceTitle": "백엔드 개발자",
        "role": role("SOFTWARE_ENGINEERING", "WEB_BACKEND", backend, "role.web_backend"),
        "experience": experience("UNKNOWN", backend),
        "responsibilities": [],
        "requirements": [],
    }]

    posting, _provider = run_draft(request, draft)

    assert len(posting.positions) == 1
    assert posting.positions[0].role.specialization == "WEB_BACKEND"


def test_actual_frontend_and_backend_positions_keep_separate_requirements() -> None:
    request = verified_request(
        "웹 개발자 모집.\n프론트엔드: TypeScript와 Next.js, React 경험 우대.\n"
        "백엔드: Java와 Kotlin, Spring Boot와 JPA 경험 우대.\n"
        "신입 또는 경력 3년 이상."
    )
    title = evidence_id(request, "웹 개발자 모집")
    front = evidence_id(request, "프론트엔드")
    back = evidence_id(request, "백엔드")
    exp = evidence_id(request, "신입 또는")
    draft = base_draft(request, title="웹 개발자 모집", title_evidence=title)
    shared_experience = experience(
        "NEW_GRADUATE_OR_EXPERIENCED",
        exp,
        experiencedMinMonths=36,
    )
    draft["positions"] = [
        {
            "positionKey": "frontend",
            "sourceTitle": "프론트엔드",
            "role": role("SOFTWARE_ENGINEERING", "WEB_FRONTEND", front, "role.web_frontend"),
            "experience": shared_experience,
            "responsibilities": [],
            "requirements": [{
                "sourceText": "React 경험 우대",
                "atomicText": "React 경험",
                "obligation": "PREFERRED",
                "category": "TECHNOLOGY",
                "evidenceIds": [front],
                "confidence": 0.95,
            }],
        },
        {
            "positionKey": "backend",
            "sourceTitle": "백엔드",
            "role": role("SOFTWARE_ENGINEERING", "WEB_BACKEND", back, "role.web_backend"),
            "experience": shared_experience,
            "responsibilities": [],
            "requirements": [{
                "sourceText": "JPA 경험 우대",
                "atomicText": "JPA 경험",
                "obligation": "PREFERRED",
                "category": "TECHNOLOGY",
                "evidenceIds": [back],
                "confidence": 0.95,
            }],
        },
    ]

    posting, _provider = run_draft(request, draft)

    assert [position.role.specialization for position in posting.positions] == [
        "WEB_FRONTEND", "WEB_BACKEND"
    ]
    assert posting.positions[0].requirements[0].atomic_text == "React 경험"
    assert posting.positions[1].requirements[0].atomic_text == "JPA 경험"


def test_company_history_years_do_not_replace_new_graduate_evidence() -> None:
    request = verified_request(
        "지원 자격: 신입.\n회사 소개: QA 분야에서 19년의 경험을 축적했습니다.\nQA 엔지니어 모집."
    )
    title = evidence_id(request, "QA 엔지니어")
    new_grad = evidence_id(request, "지원 자격: 신입")
    draft = base_draft(request, title="QA 엔지니어 모집", title_evidence=title)
    draft["positions"] = [{
        "positionKey": "qa-role",
        "sourceTitle": "QA 엔지니어",
        "role": role("QUALITY_ENGINEERING", "QA_ENGINEERING", title, "role.qa"),
        "experience": experience("NEW_GRADUATE", new_grad),
        "responsibilities": [],
        "requirements": [],
    }]

    posting, _provider = run_draft(request, draft)

    assert posting.positions[0].experience.kind.value == "NEW_GRADUATE"
    assert posting.positions[0].experience.min_months is None
    assert posting.positions[0].experience.evidence_ids == [new_grad]


def test_experience_track_statement_is_not_an_atomic_requirement() -> None:
    request = verified_request("Backend engineer. New graduates may apply.")
    title = evidence_id(request, "Backend engineer")
    track = evidence_id(request, "New graduates may apply")
    draft = base_draft(
        request,
        title="Backend engineer",
        title_evidence=title,
    )
    draft["positions"] = [{
        "positionKey": "backend",
        "sourceTitle": "Backend engineer",
        "role": role(
            "SOFTWARE_ENGINEERING",
            "WEB_BACKEND",
            title,
            "role.web_backend",
        ),
        "experience": experience("NEW_GRADUATE", track),
        "responsibilities": [],
        "requirements": [{
            "sourceText": "New graduates may apply.",
            "atomicText": "New graduates may apply",
            "obligation": "REQUIRED",
            "category": "EXPERIENCE",
            "evidenceIds": [track],
            "confidence": 0.95,
        }],
    }]

    posting, _provider = run_draft(request, draft)

    assert posting.positions[0].experience.kind.value == "NEW_GRADUATE"
    assert posting.positions[0].requirements == []


def test_unknown_role_is_preserved_as_new_candidate() -> None:
    request = verified_request(
        "Conversation Character Engineer를 모집합니다. AI 캐릭터 행동 파이프라인을 설계합니다."
    )
    title = evidence_id(request, "Conversation Character Engineer")
    draft = base_draft(
        request,
        title="Conversation Character Engineer",
        title_evidence=title,
    )
    draft["positions"] = [{
        "positionKey": "character",
        "sourceTitle": "Conversation Character Engineer",
        "role": role("AI", "CONVERSATION_CHARACTER_ENGINEERING", title, None),
        "experience": experience("UNKNOWN", title),
        "responsibilities": [],
        "requirements": [],
    }]

    posting, _provider = run_draft(request, draft)

    assert posting.positions[0].role.status.value == "NEW_CANDIDATE"
    assert posting.positions[0].role.canonical_role_id is None


def test_game_client_is_not_classified_as_web_backend_from_aws_or_sql() -> None:
    request = verified_request(
        "Unity와 C#을 사용한 2D 게임 클라이언트 개발자를 모집합니다. AWS와 SQL 경험 우대."
    )
    title = evidence_id(request, "게임 클라이언트")
    draft = base_draft(request, title="2D 게임 클라이언트 개발자", title_evidence=title)
    draft["positions"] = [{
        "positionKey": "game-client",
        "sourceTitle": "2D 게임 클라이언트 개발자",
        "role": role("GAME_ENGINEERING", "GAME_CLIENT", title, "role.game_client"),
        "experience": experience("UNKNOWN", title),
        "responsibilities": [],
        "requirements": [],
    }]

    posting, _provider = run_draft(request, draft)

    assert posting.positions[0].role.family == "GAME_ENGINEERING"
    assert posting.positions[0].role.specialization == "GAME_CLIENT"
    assert posting.positions[0].role.specialization != "WEB_BACKEND"


def test_service_history_years_do_not_become_required_experience() -> None:
    request = verified_request(
        "10년 이상 서비스를 운영해 온 회사입니다. 신입 백엔드 개발자를 모집합니다."
    )
    title = evidence_id(request, "신입 백엔드 개발자")
    draft = base_draft(request, title="신입 백엔드 개발자", title_evidence=title)
    draft["positions"] = [{
        "positionKey": "backend",
        "sourceTitle": "신입 백엔드 개발자",
        "role": role("SOFTWARE_ENGINEERING", "WEB_BACKEND", title, "role.web_backend"),
        "experience": experience("NEW_GRADUATE", title),
        "responsibilities": [],
        "requirements": [],
    }]

    posting, _provider = run_draft(request, draft)

    assert posting.positions[0].experience.kind.value == "NEW_GRADUATE"
    assert posting.positions[0].experience.min_months is None


def test_each_position_keeps_its_own_experience_requirement() -> None:
    request = verified_request(
        "프론트엔드: 신입.\n백엔드: 경력 3년 이상.\nQA 엔지니어: 경력 2년 이상."
    )
    front = evidence_id(request, "프론트엔드")
    back = evidence_id(request, "백엔드")
    qa = evidence_id(request, "QA 엔지니어")
    draft = base_draft(request, title="프론트엔드", title_evidence=front)
    draft["positions"] = [
        {
            "positionKey": "frontend",
            "sourceTitle": "프론트엔드",
            "role": role("SOFTWARE_ENGINEERING", "WEB_FRONTEND", front, "role.web_frontend"),
            "experience": experience("NEW_GRADUATE", front),
            "responsibilities": [],
            "requirements": [],
        },
        {
            "positionKey": "backend",
            "sourceTitle": "백엔드",
            "role": role("SOFTWARE_ENGINEERING", "WEB_BACKEND", back, "role.web_backend"),
            "experience": experience("EXPERIENCE_REQUIRED", back, minMonths=36),
            "responsibilities": [],
            "requirements": [],
        },
        {
            "positionKey": "qa-role",
            "sourceTitle": "QA 엔지니어",
            "role": role("QUALITY_ENGINEERING", "QA_ENGINEERING", qa, "role.qa"),
            "experience": experience("EXPERIENCE_REQUIRED", qa, minMonths=24),
            "responsibilities": [],
            "requirements": [],
        },
    ]

    posting, _provider = run_draft(request, draft)

    assert [position.experience.min_months for position in posting.positions] == [None, 36, 24]


def test_mixed_requirement_is_split_without_turning_behavior_into_technology() -> None:
    source = (
        "백엔드 개발자 모집.\n"
        "Celery · REST API · 백엔드 구현 편의가 아닌, 실제 사용자의 경험과 제품 목표를 기준으로 시스템을 설계하는 자세"
    )
    request = verified_request(source)
    title = evidence_id(request, "백엔드 개발자")
    mixed = evidence_id(request, "Celery")
    draft = base_draft(request, title="백엔드 개발자 모집", title_evidence=title)
    draft["positions"] = [{
        "positionKey": "backend",
        "sourceTitle": "백엔드 개발자",
        "role": role("SOFTWARE_ENGINEERING", "WEB_BACKEND", title, "role.web_backend"),
        "experience": experience("UNKNOWN", title),
        "responsibilities": [],
        "requirements": [
            {
                "sourceText": "Celery",
                "atomicText": "Celery",
                "obligation": "REQUIRED",
                "category": "TECHNOLOGY",
                "evidenceIds": [mixed],
                "confidence": 0.97,
            },
            {
                "sourceText": "REST API",
                "atomicText": "REST API",
                "obligation": "REQUIRED",
                "category": "TECHNOLOGY",
                "evidenceIds": [mixed],
                "confidence": 0.97,
            },
            {
                "sourceText": "실제 사용자의 경험과 제품 목표를 기준으로 시스템을 설계하는 자세",
                "atomicText": "사용자 경험과 제품 목표 중심 설계 자세",
                "obligation": "REQUIRED",
                "category": "BEHAVIORAL",
                "evidenceIds": [mixed],
                "confidence": 0.9,
            },
        ],
    }]

    posting, _provider = run_draft(request, draft)
    categories = [item.category for item in posting.positions[0].requirements]

    assert categories == [
        RequirementCategory.TECHNOLOGY,
        RequirementCategory.TECHNOLOGY,
        RequirementCategory.BEHAVIORAL,
    ]
    assert posting.positions[0].requirements[-1].normalization_status.value == "NOT_APPLICABLE"


def test_deadline_status_is_calculated_not_generated_by_model() -> None:
    request = verified_request("백엔드 개발자 모집.\n접수 마감: 2025-01-01")
    title = evidence_id(request, "백엔드 개발자")
    deadline = evidence_id(request, "접수 마감")
    draft = base_draft(request, title="백엔드 개발자 모집", title_evidence=title)
    draft["applicationDeadline"] = "2025-01-01"
    draft["applicationDeadlineEvidenceIds"] = [deadline]
    draft["positions"] = [{
        "positionKey": "backend",
        "sourceTitle": "백엔드 개발자",
        "role": role("SOFTWARE_ENGINEERING", "WEB_BACKEND", title, "role.web_backend"),
        "experience": experience("UNKNOWN", title),
        "responsibilities": [],
        "requirements": [],
    }]

    posting, _provider = run_draft(request, draft)

    assert posting.posting_status is PostingStatus.CLOSED


def test_hallucinated_evidence_text_is_rejected_after_structuring() -> None:
    request = verified_request("백엔드 개발자 모집.\nJava 경험 필수")
    title = evidence_id(request, "백엔드 개발자")
    java = evidence_id(request, "Java 경험")
    draft = base_draft(request, title="백엔드 개발자 모집", title_evidence=title)
    draft["positions"] = [{
        "positionKey": "backend",
        "sourceTitle": "백엔드 개발자",
        "role": role("SOFTWARE_ENGINEERING", "WEB_BACKEND", title, "role.web_backend"),
        "experience": experience("UNKNOWN", title),
        "responsibilities": [],
        "requirements": [{
            "sourceText": "Kotlin 경험 필수",
            "atomicText": "Kotlin 경험",
            "obligation": "REQUIRED",
            "category": "TECHNOLOGY",
            "evidenceIds": [java],
            "confidence": 0.9,
        }],
    }]

    with pytest.raises(PostingInterpretationFailure) as raised:
        run_draft(request, draft)

    assert raised.value.code is ErrorCode.POSTING_STRUCTURE_INVALID
