from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from jobis_ai.career_pipeline.contracts.common import WarningItem, WarningSeverity
from jobis_ai.career_pipeline.contracts.errors import ErrorCode
from jobis_ai.career_pipeline.contracts.posting import (
    AtomicRequirement,
    CompanyCandidate,
    NormalizationStatus,
    Position,
    PostingInterpretationRequest,
    PostingStatus,
    RequirementCategory,
    RequirementObligation,
    Responsibility,
    RoleCandidate,
    RoleStatus,
    StructuredPosting,
)
from jobis_ai.career_pipeline.contracts.validation import (
    ContractReferenceError,
    validate_posting_evidence,
    validate_snapshot_source,
)
from jobis_ai.career_pipeline.llm import (
    JsonProviderContractError,
    JsonProviderError,
    JsonProviderNotConfigured,
    LlmProgressCallback,
    StructuredGenerator,
)
from jobis_ai.career_pipeline.source.service import SourceAcquisitionFailure, require_verified_snapshot

from .draft import (
    PostingDiscoveryDraft,
    PostingInterpretationDraft,
    RequirementDraft,
    SelectedPositionDetailDraft,
)


INTERPRETER_VERSION = "posting-interpreter-3.4.0"
DISCOVERY_VERSION = "posting-discovery-3.4.0"
DETAIL_VERSION = "posting-detail-3.4.0"
MAX_PROMPT_CHARS = 32_000


ROLE_CATALOG: dict[str, tuple[str, str]] = {
    "role.web_backend": ("SOFTWARE_ENGINEERING", "WEB_BACKEND"),
    "role.web_frontend": ("SOFTWARE_ENGINEERING", "WEB_FRONTEND"),
    "role.full_stack": ("SOFTWARE_ENGINEERING", "FULL_STACK"),
    "role.mobile_android": ("SOFTWARE_ENGINEERING", "MOBILE_ANDROID"),
    "role.mobile_ios": ("SOFTWARE_ENGINEERING", "MOBILE_IOS"),
    "role.game_client": ("GAME_ENGINEERING", "GAME_CLIENT"),
    "role.game_server": ("GAME_ENGINEERING", "GAME_SERVER"),
    "role.game_engine": ("GAME_ENGINEERING", "GAME_ENGINE"),
    "role.qa": ("QUALITY_ENGINEERING", "QA_ENGINEERING"),
    "role.test_automation": ("QUALITY_ENGINEERING", "TEST_AUTOMATION"),
    "role.devops": ("PLATFORM_ENGINEERING", "DEVOPS"),
    "role.cloud_engineering": ("PLATFORM_ENGINEERING", "CLOUD_ENGINEERING"),
    "role.sre": ("PLATFORM_ENGINEERING", "SITE_RELIABILITY_ENGINEERING"),
    "role.data_engineering": ("DATA", "DATA_ENGINEERING"),
    "role.data_science": ("DATA", "DATA_SCIENCE"),
    "role.ml_engineering": ("AI", "ML_ENGINEERING"),
    "role.security_engineering": ("SECURITY", "SECURITY_ENGINEERING"),
    "role.embedded": ("HARDWARE_SOFTWARE", "EMBEDDED_SOFTWARE"),
}

ROLE_DISPLAY_LABELS: dict[str, tuple[str, ...]] = {
    "WEB_BACKEND": ("백엔드", "Backend"),
    "WEB_FRONTEND": ("프론트엔드", "Frontend"),
    "FULL_STACK": ("풀스택", "Full Stack", "Fullstack"),
    "MOBILE_ANDROID": ("안드로이드", "Android"),
    "MOBILE_IOS": ("iOS",),
    "GAME_CLIENT": ("게임 클라이언트", "클라이언트"),
    "GAME_SERVER": ("게임 서버", "서버"),
    "GAME_ENGINE": ("게임 엔진", "엔진"),
    "QA_ENGINEERING": ("QA", "품질 보증"),
    "TEST_AUTOMATION": ("테스트 자동화",),
    "DEVOPS": ("DevOps", "데브옵스"),
    "CLOUD_ENGINEERING": ("클라우드", "Cloud"),
    "SITE_RELIABILITY_ENGINEERING": ("SRE", "Site Reliability"),
    "DATA_ENGINEERING": ("데이터 엔지니어", "Data Engineer"),
    "DATA_SCIENCE": ("데이터 사이언티스트", "Data Scientist"),
    "ML_ENGINEERING": ("ML 엔지니어", "Machine Learning"),
    "SECURITY_ENGINEERING": ("보안", "Security"),
    "EMBEDDED_SOFTWARE": ("임베디드", "Embedded"),
}


SYSTEM_PROMPT = """너는 검증된 채용 공고 원문을 구조화하는 의미 해석기다.
적합도, 합격 가능성, 학습 순서, 로드맵을 만들지 않는다. 입력의 evidenceSegments에 실제로
있는 내용만 구조화한다.

핵심 규칙:
1. 회사가 실제로 모집하는 서로 다른 포지션을 positions[]로 모두 보존한다.
   프론트엔드와 백엔드처럼 별도 업무·자격·우대 섹션이 있으면 반드시 서로 다른 position이다.
   FULL_STACK은 한 지원자가 프론트엔드와 백엔드를 모두 담당한다고 원문이 명시한 경우에만 쓴다.
   여러 포지션을 한 공고에서 함께 모집한다는 이유만으로 FULL_STACK으로 합치지 않는다.
2. 협업 대상, 조직명, 사용 기술 언급만으로 별도 포지션을 만들지 않는다.
3. 포지션마다 직무와 경력 조건, 업무, 필수·우대 요건을 분리한다.
4. 회사 업력, 서비스 운영 연수, 프로젝트 연수는 지원자 요구 경력이 아니다.
5. '신입 또는 경력 3년 이상'은 NEW_GRADUATE_OR_EXPERIENCED와 experiencedMinMonths=36이다.
6. requirement와 responsibility의 sourceText는 evidence segment에 있는 원문을 그대로 복사한다.
   한 문장에 기술·자격·태도 또는 여러 업무가 섞였으면 원문은 공유해도 atomicText와 category를
   여러 항목으로 분리한다.
7. RESPONSIBILITY와 지원 자격을 섞지 않는다. 원문에 없는 선행 기술이나 프로젝트를 추가하지 않는다.
8. 알려진 role catalog와 정확히 맞으면 canonicalRoleIdCandidate를 넣는다. 맞지 않거나 새로운
   직무면 null로 두고 family/specialization 제안은 보존한다. 가장 가까운 기존 직무로 강제하지 않는다.
9. 회사명이 원문에 없으면 company는 null이다. 전체 공고 제목이 원문에 없고 포지션만 나열돼
   있으면 postingTitle도 null이다. 여러 포지션을 합친 제목을 만들지 않는다. 날짜가 없으면
   applicationDeadline은 null이다.
10. evidenceIds는 입력에 있는 ID만 사용한다. JSON 외 설명이나 내부 추론 과정을 출력하지 않는다.

요건 category 의미:
- TECHNOLOGY: 언어, 프레임워크, DB, 도구 자체
- TECHNICAL_CAPABILITY: 설계, 성능 개선, 테스트, 운영처럼 기술 수행 능력
- RESPONSIBILITY: 입사 후 담당 업무
- DOMAIN_KNOWLEDGE: 게임·금융 등 도메인 이해
- CREDENTIAL: 학위·전공·학력 등 형식 자격
- CERTIFICATION: 기사·기능사·벤더 인증 등 취득 여부를 확인할 수 있는 자격증
- LANGUAGE: 영어 회화·외국어 독해·공인 어학 수준 등 자연어 의사소통 역량
- EXPERIENCE: 실제 경력·프로젝트 경험 조건
- PORTFOLIO: 제출 결과물 조건
- BEHAVIORAL: 열정·책임감·협업 태도
- EMPLOYMENT_CONDITION: 근무지·고용형태·마감·전형
- OTHER: 위 범주에 속하지 않음
"""


# Keep repeated source sentences out of generated JSON. Exact source text is
# deterministic because each row already points at verified evidence IDs.
SYSTEM_PROMPT += """

Output-size rules:
- Omit sourceText in responsibilities and requirements. The server restores exact source text from evidenceIds.
- Never paraphrase sourceTitle. Use a short phrase literally present in the cited evidence.
- Put conditions shared by several positions in sharedConditions once instead of repeating them per position.
"""


DISCOVERY_SYSTEM_PROMPT = """너는 채용 공고의 분석 범위를 먼저 확인하는 의미 해석기다.
입력 evidenceSegments에 실제로 있는 내용만 사용한다.

규칙:
1. 회사명, 전체 공고 제목, 실제 모집 포지션, 포지션별 경력 조건만 추출한다.
2. 프론트엔드와 백엔드처럼 업무와 요건이 분리되어 있으면 별도 포지션으로 보존한다.
3. 한 공고에서 함께 모집한다는 이유로 FULL_STACK으로 합치지 않는다.
4. 협업 대상이나 사용 기술 언급만으로 별도 포지션을 만들지 않는다.
5. 회사 업력과 서비스 기간은 지원자의 요구 경력이 아니다.
6. 회사명과 sourceTitle은 인용한 evidence에 문자 그대로 존재하는 표기만 사용한다.
7. 자격요건, 우대사항, 복지, 급여, 주소, 전형 절차는 이 단계에서 추출하지 않는다.
8. evidenceIds는 입력에 있는 ID만 사용하고 원문에 없는 정보를 만들지 않는다.
9. 알려진 roleCatalog와 정확히 맞을 때만 canonicalRoleIdCandidate를 사용한다.
10. 채용 직무 목록이라도 현재 모집 중임을 나타내는 구체적인 직무명과 신입/경력 구분, 근무지,
    관련 요건 중 하나 이상이 함께 제시된 행은 선택 가능한 position 후보로 보존한다. 여러 후보가
    있으면 임의로 하나를 고르지 않는다. 서버가 사용자에게 지원할 직무를 질문한다.
11. 단순 직무 카테고리, 직무 소개 인터뷰, 회사 인재상처럼 실제 모집 행을 식별할 근거가 없는
    문서만 positions를 빈 배열로 둔다. 추측하거나 가짜 포지션을 만들지 않는다.
12. JSON 외 설명과 내부 추론은 출력하지 않는다.
"""


DETAIL_SYSTEM_PROMPT = """너는 사용자가 선택한 하나의 채용 포지션을 상세 구조화하는 의미 해석기다.
입력의 selectedPosition과 evidenceSegments에 실제로 있는 내용만 사용한다.

규칙:
1. selectedPosition의 입사 후 담당 업무를 responsibilities로 분리한다.
2. selectedPosition에 적용되는 필수·우대 요건만 requirements로 분리한다.
3. 공통 조건도 선택 포지션에 실제 적용되면 포함한다.
4. TECHNOLOGY, TECHNICAL_CAPABILITY, DOMAIN_KNOWLEDGE, CREDENTIAL, CERTIFICATION,
   LANGUAGE, EXPERIENCE, PORTFOLIO 중 취업 준비와 프로젝트 설계에 필요한 조건만 포함한다.
5. BEHAVIORAL, EMPLOYMENT_CONDITION, OTHER는 제외한다.
6. 급여, 복지, 근무지, 전형 절차, 문의처, 재지원 제한, 이력서 제출 안내는 제외한다.
7. sourceText는 생략하고 evidenceIds만 정확히 연결한다. 서버가 원문을 복원한다.
8. 책임과 요건을 섞지 않고, 원문에 없는 기술·프로젝트·선행지식을 추가하지 않는다.
9. 마감일이 명확한 날짜로 존재할 때만 applicationDeadline과 근거 ID를 함께 넣는다.
10. JSON 외 설명과 내부 추론은 출력하지 않는다.
"""


EVIDENCE_ALIAS_INSTRUCTION = """
Evidence ID rules:
- evidenceSegments[].segmentId values are short aliases such as E001.
- Copy only those aliases into every evidenceIds field.
- Never invent, shorten, extend, or reconstruct an evidence alias.
"""

SYSTEM_PROMPT += EVIDENCE_ALIAS_INSTRUCTION
DISCOVERY_SYSTEM_PROMPT += EVIDENCE_ALIAS_INSTRUCTION
DETAIL_SYSTEM_PROMPT += EVIDENCE_ALIAS_INSTRUCTION


ROADMAP_RELEVANT_CATEGORIES = {
    RequirementCategory.TECHNOLOGY,
    RequirementCategory.TECHNICAL_CAPABILITY,
    RequirementCategory.DOMAIN_KNOWLEDGE,
    RequirementCategory.CREDENTIAL,
    RequirementCategory.CERTIFICATION,
    RequirementCategory.LANGUAGE,
    RequirementCategory.EXPERIENCE,
    RequirementCategory.PORTFOLIO,
}


class PostingInterpretationFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PromptPayload:
    text: str
    truncated: bool
    evidence_alias_to_id: dict[str, str]


class PostingInterpretationService:
    def __init__(self, generator: StructuredGenerator) -> None:
        self._generator = generator

    def interpret(self, request: PostingInterpretationRequest) -> StructuredPosting:
        try:
            validate_snapshot_source(request.verified_snapshot, request.source_document)
            require_verified_snapshot(request.source_document, request.verified_snapshot)
        except (ContractReferenceError, SourceAcquisitionFailure) as exc:
            code = exc.code if isinstance(exc, SourceAcquisitionFailure) else ErrorCode.CONTRACT_VALIDATION_FAILED
            raise PostingInterpretationFailure(code=code, message=str(exc), retryable=False) from exc

        prompt = _build_prompt(request)
        try:
            draft, metadata = self._generator.generate(
                PostingInterpretationDraft,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt.text,
            )
        except JsonProviderNotConfigured as exc:
            raise PostingInterpretationFailure(
                code=ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                message=str(exc),
                retryable=False,
            ) from exc
        except JsonProviderContractError as exc:
            raise PostingInterpretationFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc
        except JsonProviderError as exc:
            raise PostingInterpretationFailure(
                code=_provider_error_code(exc),
                message=str(exc),
                retryable=True,
            ) from exc

        draft, evidence_repairs = _restore_draft_evidence_ids(
            draft,
            prompt.evidence_alias_to_id,
            request,
        )
        posting = _compile_draft(
            draft,
            request=request,
            analysis_version=(
                f"{INTERPRETER_VERSION}:{metadata.provider}:{metadata.model}"
            ),
            input_truncated=prompt.truncated,
        )
        posting = _attach_evidence_repair_warning(posting, evidence_repairs)
        try:
            validate_posting_evidence(posting, request.source_document, request.verified_snapshot)
        except ContractReferenceError as exc:
            raise PostingInterpretationFailure(
                code=ErrorCode.POSTING_STRUCTURE_INVALID,
                message=str(exc),
                retryable=True,
            ) from exc
        return posting

    def discover(
        self,
        request: PostingInterpretationRequest,
        *,
        progress_callback: LlmProgressCallback | None = None,
    ) -> StructuredPosting:
        _validate_interpretation_input(request)
        prompt = _build_prompt(request)
        try:
            draft, metadata = self._generator.generate(
                PostingDiscoveryDraft,
                system_prompt=DISCOVERY_SYSTEM_PROMPT,
                user_prompt=prompt.text,
                progress_callback=progress_callback,
            )
        except JsonProviderNotConfigured as exc:
            raise PostingInterpretationFailure(
                code=ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                message=str(exc),
                retryable=False,
            ) from exc
        except JsonProviderContractError as exc:
            raise PostingInterpretationFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc
        except JsonProviderError as exc:
            raise PostingInterpretationFailure(
                code=_provider_error_code(exc),
                message=str(exc),
                retryable=True,
            ) from exc
        if not draft.positions:
            raise PostingInterpretationFailure(
                code=ErrorCode.ROLE_RESOLUTION_REQUIRED,
                message=(
                    "이 링크에서는 지원할 특정 모집 직무를 확정할 수 없습니다. "
                    "채용 직무 목록이나 직무 소개 페이지가 아닌 상세 공고 URL 또는 "
                    "회사명·직무명·지원 요건이 포함된 공고 원문을 입력해 주세요."
                ),
                retryable=False,
            )
        draft, evidence_repairs = _restore_draft_evidence_ids(
            draft,
            prompt.evidence_alias_to_id,
            request,
        )
        posting = _compile_discovery(
            draft,
            request=request,
            analysis_version=f"{DISCOVERY_VERSION}:{metadata.provider}:{metadata.model}",
            input_truncated=prompt.truncated,
        )
        posting = _attach_evidence_repair_warning(posting, evidence_repairs)
        _validate_compiled_posting(posting, request)
        return posting

    def interpret_selected(
        self,
        request: PostingInterpretationRequest,
        *,
        discovery: StructuredPosting,
        selected_position_id: str,
        progress_callback: LlmProgressCallback | None = None,
    ) -> StructuredPosting:
        _validate_interpretation_input(request)
        if selected_position_id not in {
            position.position_id for position in discovery.positions
        }:
            raise PostingInterpretationFailure(
                code=ErrorCode.ANALYSIS_STALE_RESULT,
                message=f"selected position {selected_position_id} is not in the discovery checkpoint",
                retryable=False,
            )
        prompt = _build_detail_prompt(request, discovery, selected_position_id)
        try:
            draft, metadata = self._generator.generate(
                SelectedPositionDetailDraft,
                system_prompt=DETAIL_SYSTEM_PROMPT,
                user_prompt=prompt.text,
                progress_callback=progress_callback,
            )
        except JsonProviderNotConfigured as exc:
            raise PostingInterpretationFailure(
                code=ErrorCode.AI_PROVIDER_NOT_CONFIGURED,
                message=str(exc),
                retryable=False,
            ) from exc
        except JsonProviderContractError as exc:
            raise PostingInterpretationFailure(
                code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                message=str(exc),
                retryable=False,
            ) from exc
        except JsonProviderError as exc:
            raise PostingInterpretationFailure(
                code=_provider_error_code(exc),
                message=str(exc),
                retryable=True,
            ) from exc
        draft, evidence_repairs = _restore_draft_evidence_ids(
            draft,
            prompt.evidence_alias_to_id,
            request,
        )
        posting = _compile_selected_detail(
            draft,
            request=request,
            discovery=discovery,
            selected_position_id=selected_position_id,
            analysis_version=f"{DETAIL_VERSION}:{metadata.provider}:{metadata.model}",
            input_truncated=prompt.truncated,
        )
        posting = _attach_evidence_repair_warning(posting, evidence_repairs)
        _validate_compiled_posting(posting, request)
        return posting


def _validate_interpretation_input(request: PostingInterpretationRequest) -> None:
    try:
        validate_snapshot_source(request.verified_snapshot, request.source_document)
        require_verified_snapshot(request.source_document, request.verified_snapshot)
    except (ContractReferenceError, SourceAcquisitionFailure) as exc:
        code = (
            exc.code
            if isinstance(exc, SourceAcquisitionFailure)
            else ErrorCode.CONTRACT_VALIDATION_FAILED
        )
        raise PostingInterpretationFailure(
            code=code,
            message=str(exc),
            retryable=False,
        ) from exc


def _provider_error_code(exc: JsonProviderError) -> ErrorCode:
    message = str(exc).casefold()
    if "timed out" in message or "timeout" in message:
        return ErrorCode.AI_TIMEOUT
    return ErrorCode.AI_PROVIDER_UNAVAILABLE


def _replace_prompt_evidence_ids(
    payload: Any,
    evidence_id_to_alias: dict[str, str],
) -> None:
    if isinstance(payload, list):
        for item in payload:
            _replace_prompt_evidence_ids(item, evidence_id_to_alias)
        return
    if not isinstance(payload, dict):
        return
    for key, value in payload.items():
        if key == "evidenceIds" and isinstance(value, list):
            payload[key] = [
                evidence_id_to_alias.get(item, item)
                for item in value
            ]
        else:
            _replace_prompt_evidence_ids(value, evidence_id_to_alias)


def _restore_draft_evidence_ids(
    draft: Any,
    evidence_alias_to_id: dict[str, str],
    request: PostingInterpretationRequest,
) -> tuple[Any, list[tuple[str, str]]]:
    known_ids = {
        segment.segment_id
        for segment in request.verified_snapshot.evidence_segments
    }
    accepted = {**evidence_alias_to_id, **{item: item for item in known_ids}}
    payload = draft.model_dump(mode="python")
    repairs: list[tuple[str, str]] = []

    def resolve(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if value in accepted:
            return accepted[value]
        candidates = {
            actual_id
            for supplied_id, actual_id in accepted.items()
            if len(supplied_id) == len(value) + 1 and supplied_id.startswith(value)
        }
        if len(candidates) == 1:
            repaired = next(iter(candidates))
            repairs.append((value, repaired))
            return repaired
        return value

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if (
                (key == "evidence_ids" or key.endswith("_evidence_ids"))
                and isinstance(value, list)
            ):
                node[key] = list(dict.fromkeys(resolve(item) for item in value))
            else:
                visit(value)

    visit(payload)
    return draft.__class__.model_validate(payload), list(dict.fromkeys(repairs))


def _attach_evidence_repair_warning(
    posting: StructuredPosting,
    repairs: list[tuple[str, str]],
) -> StructuredPosting:
    if not repairs:
        return posting
    repaired_ids = list(dict.fromkeys(repaired for _original, repaired in repairs))
    return posting.model_copy(update={
        "warnings": [
            *posting.warnings,
            WarningItem(
                code="EVIDENCE_ID_REPAIRED",
                message=(
                    f"AI가 잘못 복사한 근거 식별자 {len(repairs)}건을 "
                    "검증된 단일 후보로 복원했습니다."
                ),
                severity=WarningSeverity.INFO,
                evidence_ids=repaired_ids,
            ),
        ]
    })


def _validate_compiled_posting(
    posting: StructuredPosting,
    request: PostingInterpretationRequest,
) -> None:
    try:
        validate_posting_evidence(
            posting,
            request.source_document,
            request.verified_snapshot,
        )
    except ContractReferenceError as exc:
        raise PostingInterpretationFailure(
            code=ErrorCode.POSTING_STRUCTURE_INVALID,
            message=str(exc),
            retryable=True,
        ) from exc


def _build_prompt(request: PostingInterpretationRequest) -> PromptPayload:
    role_catalog = _role_catalog(request)
    # The verified snapshot keeps full extraction metadata for auditing. The
    # model only needs the stable evidence ID and its exact text. Sending every
    # locator, method and confidence field made a 5K posting expand to more than
    # 40K characters before the output schema was attached.
    evidence_alias_to_id = {
        f"E{index:03d}": segment.segment_id
        for index, segment in enumerate(
            request.verified_snapshot.evidence_segments,
            start=1,
        )
    }
    segments = [
        {"segmentId": alias, "text": segment.text}
        for alias, segment in zip(
            evidence_alias_to_id,
            request.verified_snapshot.evidence_segments,
            strict=True,
        )
    ]
    base = {
        "verifiedSnapshotId": request.verified_snapshot.verified_snapshot_id,
        "asOfDate": request.as_of_date.isoformat(),
        "roleCatalog": [
            {"canonicalRoleId": key, "family": value[0], "specialization": value[1]}
            for key, value in role_catalog.items()
        ],
        "evidenceSegments": segments,
        "evidenceIdInstruction": "Use only the exact E001-style segmentId aliases shown above.",
    }
    encoded = json.dumps(base, ensure_ascii=False)
    if len(encoded) <= MAX_PROMPT_CHARS:
        return PromptPayload(encoded, False, evidence_alias_to_id)

    retained: list[dict] = []
    used = 0
    head_count = max(1, len(segments) // 2)
    ordered = segments[:head_count] + list(reversed(segments[head_count:]))
    for segment in ordered:
        serialized = json.dumps(segment, ensure_ascii=False)
        if used + len(serialized) > MAX_PROMPT_CHARS - 6_000:
            continue
        retained.append(segment)
        used += len(serialized)
    retained_ids = {segment["segmentId"] for segment in retained}
    base["evidenceSegments"] = [segment for segment in segments if segment["segmentId"] in retained_ids]
    base["inputWarning"] = "일부 중간 세그먼트가 모델 입력 한도로 생략됨"
    retained_aliases = {
        alias: evidence_id
        for alias, evidence_id in evidence_alias_to_id.items()
        if alias in retained_ids
    }
    return PromptPayload(json.dumps(base, ensure_ascii=False), True, retained_aliases)


def _build_detail_prompt(
    request: PostingInterpretationRequest,
    discovery: StructuredPosting,
    selected_position_id: str,
) -> PromptPayload:
    base_prompt = _build_prompt(request)
    payload = json.loads(base_prompt.text)
    selected = next(
        position
        for position in discovery.positions
        if position.position_id == selected_position_id
    )
    selected_payload = selected.model_dump(mode="json", by_alias=True)
    _replace_prompt_evidence_ids(
        selected_payload,
        {evidence_id: alias for alias, evidence_id in base_prompt.evidence_alias_to_id.items()},
    )
    payload["selectedPosition"] = selected_payload
    payload["discoveredPositions"] = [
        {
            "positionId": position.position_id,
            "sourceTitle": position.source_title,
            "family": position.role.family,
            "specialization": position.role.specialization,
        }
        for position in discovery.positions
    ]
    return PromptPayload(
        json.dumps(payload, ensure_ascii=False),
        base_prompt.truncated,
        base_prompt.evidence_alias_to_id,
    )


def _compile_discovery(
    draft: PostingDiscoveryDraft,
    *,
    request: PostingInterpretationRequest,
    analysis_version: str,
    input_truncated: bool,
) -> StructuredPosting:
    evidence_by_id = {
        segment.segment_id: segment.text
        for segment in request.verified_snapshot.evidence_segments
    }
    warnings: list[WarningItem] = []
    if input_truncated:
        warnings.append(WarningItem(
            code="INTERPRETER_INPUT_TRUNCATED",
            message="모델 입력 한도로 일부 중간 원문이 생략되어 직무 범위 확인이 필요합니다.",
        ))
    positions: list[Position] = []
    for index, position_draft in enumerate(draft.positions, start=1):
        role, role_warning = _compile_role(position_draft.role, _role_catalog(request))
        source_title = _grounded_source_title(
            position_draft.source_title,
            position_draft.role.evidence_ids,
            evidence_by_id,
        )
        positions.append(Position(
            position_id=f"pos-{index}",
            source_title=_preferred_role_title(
                source_title,
                role.specialization,
                position_draft.role.evidence_ids,
                evidence_by_id,
            ),
            role=role,
            experience=position_draft.experience,
            responsibilities=[],
            requirements=[],
            warnings=[role_warning] if role_warning is not None else [],
        ))
    company = None
    if draft.company is not None:
        company_name, adjusted = _grounded_identity_text(
            draft.company.display_name,
            draft.company.evidence_ids,
            evidence_by_id,
        )
        company = CompanyCandidate(
            display_name=company_name,
            canonical_company_id=None,
            evidence_ids=draft.company.evidence_ids,
            confidence=draft.company.confidence,
        )
        if adjusted:
            warnings.append(WarningItem(
                code="COMPANY_NAME_GROUNDED_TO_SOURCE",
                message="회사명 표기를 인용 원문에 실제 존재하는 형태로 정리했습니다.",
                evidence_ids=draft.company.evidence_ids,
            ))
    posting_title, posting_title_ids = _safe_optional_grounded_text(
        draft.posting_title,
        draft.posting_title_evidence_ids,
        evidence_by_id,
        warnings,
        warning_code="POSTING_TITLE_EVIDENCE_REPAIRED",
    )
    return StructuredPosting(
        analysis_version=analysis_version,
        verified_snapshot_id=request.verified_snapshot.verified_snapshot_id,
        company=company,
        posting_title=posting_title,
        posting_title_evidence_ids=posting_title_ids,
        positions=positions,
        shared_conditions=[],
        application_deadline=None,
        application_deadline_evidence_ids=[],
        posting_status=PostingStatus.UNKNOWN,
        ambiguities=[],
        warnings=warnings,
    )


def _compile_selected_detail(
    draft: SelectedPositionDetailDraft,
    *,
    request: PostingInterpretationRequest,
    discovery: StructuredPosting,
    selected_position_id: str,
    analysis_version: str,
    input_truncated: bool,
) -> StructuredPosting:
    evidence_by_id = {
        segment.segment_id: segment.text
        for segment in request.verified_snapshot.evidence_segments
    }
    selected = next(
        position
        for position in discovery.positions
        if position.position_id == selected_position_id
    )
    responsibilities = [
        Responsibility(
            responsibility_id=f"resp-{index}",
            source_text=_grounded_source_text(
                item.source_text,
                item.evidence_ids,
                evidence_by_id,
            ),
            atomic_text=item.atomic_text,
            evidence_ids=item.evidence_ids,
            confidence=item.confidence,
        )
        for index, item in enumerate(draft.responsibilities, start=1)
    ]
    requirements: list[AtomicRequirement] = []
    seen_requirements: set[tuple[str, str, str, str]] = set()
    omitted = 0
    for item in draft.requirements:
        if (
            item.category not in ROADMAP_RELEVANT_CATEGORIES
            or item.obligation not in {
                RequirementObligation.REQUIRED,
                RequirementObligation.PREFERRED,
            }
        ):
            omitted += 1
            continue
        if _duplicates_position_experience(item, selected.experience):
            continue
        key = _requirement_key(item)
        if key in seen_requirements:
            continue
        seen_requirements.add(key)
        requirements.append(_compile_requirement(
            item,
            requirement_id=f"req-{len(requirements) + 1}",
            applies_to=[selected_position_id],
            evidence_by_id=evidence_by_id,
        ))
    warnings = list(discovery.warnings)
    if input_truncated:
        warnings.append(WarningItem(
            code="INTERPRETER_INPUT_TRUNCATED",
            message="모델 입력 한도로 일부 중간 원문이 생략되어 상세 요건 확인이 필요합니다.",
        ))
    if omitted:
        warnings.append(WarningItem(
            code="NON_ROADMAP_REQUIREMENTS_OMITTED",
            message=f"로드맵과 무관한 태도·근무 조건 {omitted}건을 상세 분석에서 제외했습니다.",
            severity=WarningSeverity.INFO,
        ))
    positions = [
        position.model_copy(update={
            "responsibilities": responsibilities,
            "requirements": requirements,
        })
        if position.position_id == selected_position_id
        else position
        for position in discovery.positions
    ]
    deadline_ids = (
        draft.application_deadline_evidence_ids
        if draft.application_deadline is not None
        else []
    )
    if draft.application_deadline is None and draft.application_deadline_evidence_ids:
        warnings.append(WarningItem(
            code="DEADLINE_EVIDENCE_REPAIRED",
            message="마감일 값 없이 반환된 마감일 근거 연결을 제거했습니다.",
            severity=WarningSeverity.INFO,
            evidence_ids=draft.application_deadline_evidence_ids,
        ))
    if draft.application_deadline is None:
        posting_status = PostingStatus.UNKNOWN
    elif draft.application_deadline < request.as_of_date:
        posting_status = PostingStatus.CLOSED
    else:
        posting_status = PostingStatus.ACTIVE
    return discovery.model_copy(update={
        "analysis_version": analysis_version,
        "positions": positions,
        "shared_conditions": [],
        "application_deadline": draft.application_deadline,
        "application_deadline_evidence_ids": deadline_ids,
        "posting_status": posting_status,
        "ambiguities": [],
        "warnings": warnings,
    })


def _compile_draft(
    draft: PostingInterpretationDraft,
    *,
    request: PostingInterpretationRequest,
    analysis_version: str,
    input_truncated: bool,
) -> StructuredPosting:
    evidence_by_id = {
        segment.segment_id: segment.text
        for segment in request.verified_snapshot.evidence_segments
    }
    warnings: list[WarningItem] = []
    if input_truncated:
        warnings.append(WarningItem(
            code="INTERPRETER_INPUT_TRUNCATED",
            message="모델 입력 한도로 일부 중간 원문이 생략되어 결과 확인이 필요합니다.",
        ))

    position_id_by_key = {
        position.position_key: f"pos-{index}"
        for index, position in enumerate(draft.positions, start=1)
    }
    requirement_counter = 0
    responsibility_counter = 0
    positions: list[Position] = []
    for position_draft in draft.positions:
        role, role_warning = _compile_role(position_draft.role, _role_catalog(request))
        position_warnings = [role_warning] if role_warning is not None else []
        responsibilities: list[Responsibility] = []
        for item in position_draft.responsibilities:
            responsibility_counter += 1
            responsibilities.append(Responsibility(
                responsibility_id=f"resp-{responsibility_counter}",
                source_text=_grounded_source_text(
                    item.source_text,
                    item.evidence_ids,
                    evidence_by_id,
                ),
                atomic_text=item.atomic_text,
                evidence_ids=item.evidence_ids,
                confidence=item.confidence,
            ))

        requirements: list[AtomicRequirement] = []
        seen_requirements: set[tuple[str, str, str, str]] = set()
        for item in position_draft.requirements:
            if _duplicates_position_experience(item, position_draft.experience):
                continue
            key = _requirement_key(item)
            if key in seen_requirements:
                continue
            seen_requirements.add(key)
            requirement_counter += 1
            requirements.append(_compile_requirement(
                item,
                requirement_id=f"req-{requirement_counter}",
                applies_to=[position_id_by_key[position_draft.position_key]],
                evidence_by_id=evidence_by_id,
            ))
        source_title = _grounded_source_title(
            position_draft.source_title,
            position_draft.role.evidence_ids,
            evidence_by_id,
        )
        positions.append(Position(
            position_id=position_id_by_key[position_draft.position_key],
            source_title=_preferred_role_title(
                source_title,
                role.specialization,
                position_draft.role.evidence_ids,
                evidence_by_id,
            ),
            role=role,
            experience=position_draft.experience,
            responsibilities=responsibilities,
            requirements=requirements,
            warnings=position_warnings,
        ))

    shared_conditions: list[AtomicRequirement] = []
    for item in draft.shared_conditions:
        requirement_counter += 1
        shared_conditions.append(_compile_requirement(
            item,
            requirement_id=f"req-{requirement_counter}",
            applies_to=[position_id_by_key[key] for key in item.applies_to_position_keys],
            evidence_by_id=evidence_by_id,
        ))

    company = None
    if draft.company is not None:
        company_name, adjusted = _grounded_identity_text(
            draft.company.display_name,
            draft.company.evidence_ids,
            evidence_by_id,
        )
        company = CompanyCandidate(
            display_name=company_name,
            canonical_company_id=None,
            evidence_ids=draft.company.evidence_ids,
            confidence=draft.company.confidence,
        )
        if adjusted:
            warnings.append(WarningItem(
                code="COMPANY_NAME_GROUNDED_TO_SOURCE",
                message="회사명 표기를 인용 원문에 실제 존재하는 형태로 정리했습니다.",
                evidence_ids=draft.company.evidence_ids,
            ))
    if draft.application_deadline is None:
        posting_status = PostingStatus.UNKNOWN
    elif draft.application_deadline < request.as_of_date:
        posting_status = PostingStatus.CLOSED
    else:
        posting_status = PostingStatus.ACTIVE

    posting_title, posting_title_ids = _safe_optional_grounded_text(
        draft.posting_title,
        draft.posting_title_evidence_ids,
        evidence_by_id,
        warnings,
        warning_code="POSTING_TITLE_EVIDENCE_REPAIRED",
    )
    deadline_ids = (
        draft.application_deadline_evidence_ids
        if draft.application_deadline is not None
        else []
    )
    if draft.application_deadline is None and draft.application_deadline_evidence_ids:
        warnings.append(WarningItem(
            code="DEADLINE_EVIDENCE_REPAIRED",
            message="마감일 값 없이 반환된 마감일 근거 연결을 제거했습니다.",
            severity=WarningSeverity.INFO,
            evidence_ids=draft.application_deadline_evidence_ids,
        ))
    return StructuredPosting(
        analysis_version=analysis_version,
        verified_snapshot_id=request.verified_snapshot.verified_snapshot_id,
        company=company,
        posting_title=posting_title,
        posting_title_evidence_ids=posting_title_ids,
        positions=positions,
        shared_conditions=shared_conditions,
        application_deadline=draft.application_deadline,
        application_deadline_evidence_ids=deadline_ids,
        posting_status=posting_status,
        ambiguities=[],
        warnings=warnings,
    )


def _compile_role(role_draft, role_catalog=None) -> tuple[RoleCandidate, WarningItem | None]:
    role_catalog = role_catalog or ROLE_CATALOG
    candidate = role_draft.canonical_role_id_candidate
    warning = None
    if candidate in role_catalog:
        family, specialization = role_catalog[candidate]
        return RoleCandidate(
            family=family,
            specialization=specialization,
            canonical_role_id=candidate,
            status=RoleStatus.CANDIDATE,
            confidence=role_draft.confidence,
            evidence_ids=role_draft.evidence_ids,
        ), None
    if candidate is not None:
        warning = WarningItem(
            code="UNKNOWN_CANONICAL_ROLE_CANDIDATE",
            message=f"사전에 없는 직무 ID {candidate}는 신규 후보로 보존했습니다.",
            severity=WarningSeverity.INFO,
            evidence_ids=role_draft.evidence_ids,
        )
    unknown = role_draft.family.casefold() == "unknown" or role_draft.specialization.casefold() == "unknown"
    return RoleCandidate(
        family=role_draft.family,
        specialization=role_draft.specialization,
        canonical_role_id=None,
        status=RoleStatus.UNKNOWN if unknown else RoleStatus.NEW_CANDIDATE,
        confidence=role_draft.confidence,
        evidence_ids=role_draft.evidence_ids,
    ), warning


def _role_catalog(request: PostingInterpretationRequest) -> dict[str, tuple[str, str]]:
    catalog = dict(ROLE_CATALOG)
    for item in request.approved_role_catalog:
        catalog[item.canonical_role_id] = (item.family, item.specialization)
    return catalog


def _compile_requirement(
    item,
    *,
    requirement_id: str,
    applies_to: list[str],
    evidence_by_id: dict[str, str],
) -> AtomicRequirement:
    category = _refine_formal_requirement_category(
        item.category,
        item.atomic_text,
    )
    normalized = (
        NormalizationStatus.PENDING
        if category in {
            RequirementCategory.TECHNOLOGY,
            RequirementCategory.TECHNICAL_CAPABILITY,
            RequirementCategory.DOMAIN_KNOWLEDGE,
            RequirementCategory.CREDENTIAL,
            RequirementCategory.CERTIFICATION,
            RequirementCategory.LANGUAGE,
            RequirementCategory.EXPERIENCE,
            RequirementCategory.PORTFOLIO,
        }
        else NormalizationStatus.NOT_APPLICABLE
    )
    return AtomicRequirement(
        requirement_id=requirement_id,
        source_text=_grounded_source_text(
            item.source_text,
            item.evidence_ids,
            evidence_by_id,
        ),
        atomic_text=item.atomic_text,
        obligation=item.obligation,
        category=category,
        applies_to_position_ids=applies_to,
        evidence_ids=item.evidence_ids,
        confidence=item.confidence,
        normalization_status=normalized,
    )


def _refine_formal_requirement_category(
    category: RequirementCategory,
    atomic_text: str,
) -> RequirementCategory:
    """Keep language and certificates out of project-learnable categories.

    The LLM still performs the primary classification. This narrow server-side
    guard only corrects common, observable category collisions so that spoken
    English is not treated as a technical project capability and certificates
    are not conflated with degrees or majors.
    """
    compact = re.sub(r"\s+", "", atomic_text).casefold()
    language_markers = (
        "영어회화",
        "영어의사소통",
        "비즈니스영어",
        "외국어",
        "어학",
        "toeic",
        "toefl",
        "opic",
        "일본어",
        "중국어",
        "englishcommunication",
        "spokenenglish",
        "languageproficiency",
    )
    if category in {
        RequirementCategory.TECHNICAL_CAPABILITY,
        RequirementCategory.BEHAVIORAL,
        RequirementCategory.CREDENTIAL,
        RequirementCategory.OTHER,
    } and any(marker in compact for marker in language_markers):
        return RequirementCategory.LANGUAGE

    certification_markers = (
        "자격증",
        "산업기사",
        "기능사",
        "정보처리기사",
        "기사자격",
        "certification",
        "certified",
        "professionallicense",
    )
    if category is RequirementCategory.CREDENTIAL and any(
        marker in compact for marker in certification_markers
    ):
        return RequirementCategory.CERTIFICATION
    return category


def _requirement_key(item: RequirementDraft) -> tuple[str, str, str, str]:
    return (
        (
            re.sub(r"\s+", "", item.source_text).casefold()
            if item.source_text is not None
            else "|".join(item.evidence_ids)
        ),
        re.sub(r"\s+", "", item.atomic_text).casefold(),
        item.obligation.value,
        item.category.value,
    )


def _grounded_source_text(
    proposed: str | None,
    evidence_ids: list[str],
    evidence_by_id: dict[str, str],
) -> str:
    """Restore omitted source text while preserving strict checks on supplied text."""
    cited = [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id]
    if proposed is not None:
        # A supplied value remains subject to strict evidence validation. Do
        # not hide a model hallucination by silently replacing it.
        return proposed
    if cited:
        return " ".join(cited)
    # Unknown IDs are reported by the reference validator. Keep this value
    # non-blank so contract construction can reach that useful error.
    return proposed or "unresolved evidence"


def _grounded_identity_text(
    proposed: str,
    evidence_ids: list[str],
    evidence_by_id: dict[str, str],
) -> tuple[str, bool]:
    cited = [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id]
    combined = " ".join(cited)
    if _normalized(proposed) in _normalized(combined):
        return proposed, False
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9._+-]*|[가-힣]{2,}", proposed)
    for candidate in candidates:
        if _normalized(candidate) in _normalized(combined):
            return candidate, True
    if cited:
        fallback = re.findall(r"[A-Za-z][A-Za-z0-9._+-]*|[가-힣]{2,}", combined)
        if fallback:
            return fallback[0], True
    return proposed, False


def _safe_optional_grounded_text(
    proposed: str | None,
    evidence_ids: list[str],
    evidence_by_id: dict[str, str],
    warnings: list[WarningItem],
    *,
    warning_code: str,
) -> tuple[str | None, list[str]]:
    if proposed is None:
        if evidence_ids:
            warnings.append(WarningItem(
                code=warning_code,
                message="값 없이 반환된 근거 연결을 제거했습니다.",
                severity=WarningSeverity.INFO,
                evidence_ids=evidence_ids,
            ))
        return None, []
    if not evidence_ids:
        warnings.append(WarningItem(
            code=warning_code,
            message="근거가 없는 텍스트 값을 제외했습니다.",
            severity=WarningSeverity.INFO,
        ))
        return None, []
    grounded, adjusted = _grounded_identity_text(
        proposed,
        evidence_ids,
        evidence_by_id,
    )
    if adjusted:
        warnings.append(WarningItem(
            code=warning_code,
            message="텍스트 표기를 인용 원문에 실제 존재하는 형태로 정리했습니다.",
            severity=WarningSeverity.INFO,
            evidence_ids=evidence_ids,
        ))
    return grounded, evidence_ids


def _grounded_source_title(
    proposed: str,
    evidence_ids: list[str],
    evidence_by_id: dict[str, str],
) -> str:
    cited = [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id]
    combined = " ".join(cited)
    if _normalized(proposed) in _normalized(combined):
        return proposed

    # Prefer a meaningful token from the proposed title (for example
    # "프론트엔드" or "백엔드") over exposing a whole paragraph as a UI title.
    candidates = re.findall(r"[A-Za-z0-9+#.]+|[가-힣]{2,}", proposed)
    supported = [item for item in candidates if _normalized(item) in _normalized(combined)]
    if supported:
        return max(supported, key=len)
    if cited:
        return min(cited, key=len)
    return proposed


def _preferred_role_title(
    fallback: str,
    specialization: str,
    evidence_ids: list[str],
    evidence_by_id: dict[str, str],
) -> str:
    combined = " ".join(
        evidence_by_id[item]
        for item in evidence_ids
        if item in evidence_by_id
    )
    for label in ROLE_DISPLAY_LABELS.get(specialization, ()):
        if _normalized(label) in _normalized(combined):
            return label
    return fallback


def _normalized(value: str) -> str:
    return "".join(value.casefold().split())


def _duplicates_position_experience(item: RequirementDraft, experience) -> bool:
    """Keep track eligibility out of atomic competency requirements.

    ExperienceRequirement is the authoritative contract for the applicant
    track. If the model repeats the same evidence as an atomic EXPERIENCE
    requirement, an allowance such as "new graduates may apply" would
    otherwise become something the user is asked to prove.
    """
    return (
        item.category is RequirementCategory.EXPERIENCE
        and bool(item.evidence_ids)
        and set(item.evidence_ids).issubset(set(experience.evidence_ids))
    )
