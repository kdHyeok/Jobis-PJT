"""그래프 노드 함수 (설계 13.3).

각 노드는 GraphState 를 읽어 **부분 갱신 dict** 를 반환한다.
현재는 모두 mock 산출물을 반환하는 스켈레톤이며, 이후 실제 LangChain 체인(설계 8~14장)으로 교체한다.
교체 시 이 파일의 함수 시그니처(state -> dict)와 출력 스키마(contracts.domain)는 유지한다.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from jobis_ai.contracts.domain import (
    AlternativeJob,
    AlternativePathResult,
    AwardEntry,
    BootcampEntry,
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    GapAnalysisResult,
    LanguageEntry,
    NormalizedJobPosting,
    NormalizedUserProfile,
    PathComparison,
    ProjectEntry,
    Requirement,
    RetrySignal,
    RoadmapResult,
    SkillEntry,
    VerifierResult,
    Violation,
)
from jobis_ai.career_graph import get_career_graph
from jobis_ai.cert_db import Certification, get_cert_db
from jobis_ai.config import get_settings
from jobis_ai.extract import extract_text
from jobis_ai.gap_matcher import get_gap_matcher, overall_fit, to_gap_payload
from jobis_ai.graph.state import GraphState, Status
from jobis_ai.nl_render import render_summary
from jobis_ai.profile_completeness import build_completion_questions, find_missing_enum_fields
from jobis_ai.project_template_db import ProjectTemplate, get_project_template_db
from jobis_ai.rag import RagResult, get_rag_adapter
from jobis_ai.roadmap_scheduler import PRIORITY_RANK, PlannedItem
from jobis_ai.roadmap_scheduler import schedule as schedule_roadmap
from jobis_ai.role_taxonomy import SENIORITY_KO, get_role_taxonomy
from jobis_ai.rule_extractor import RuleExtraction, extract_rules
from jobis_ai.skill_taxonomy import get_skill_taxonomy
from jobis_ai.skill_to_cert import get_skill_to_cert
from jobis_ai.structured import llm_unconfigured, run_structured
from jobis_ai.sufficiency_rules import assess as assess_sufficiency
from jobis_ai.sufficiency_rules import build_questions
from jobis_ai.verify_rules import (
    check_consistency,
    check_evidence_grounding,
    check_forbidden_lexicon,
    validate_schema,
)

# 재시도 상한 (설계 16.2)
MAX_NODE_RETRY = 2
MAX_VERIFY_RETRY = 1


def _log(node: str, message: str, to: str | None = None) -> dict[str, Any]:
    """toolLog/핸드오프 이벤트 한 건 (설계 17.3의 from→to 시각화 연동)."""

    return {
        "node": node,
        "message": message,
        "to": to,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


def _mark_generation_failed(empty_model, node: str, warnings: list[dict]) -> None:
    """LLM 호출 실패 시: 가짜 샘플 대신 빈 결과 + 실패 경고 + uncertainty 로 정직하게 처리.

    (키가 아예 없는 개발 모드에서는 mock 샘플을 쓰지만, 키가 있는데 호출이 실패한 경우엔
    그럴듯한 가짜 결과를 내면 안 되므로 이 경로로 온다.)
    """

    empty_model.uncertainties.append("AI 호출 실패로 결과를 생성하지 못했습니다(재시도가 필요합니다).")
    warnings.append({"code": "generation_failed",
                     "message": f"{node}: LLM 결과 생성 실패 — 빈 결과 반환(가짜 폴백 아님)"})


# 오케스트라가 생성 실패한 에이전트에게 "다시 작업"을 지시하는 최대 횟수 (설계 16.2 노드 재시도)
MAX_GEN_RETRY = 1


def _gen_retry_updates(node: str, state: GraphState, failed: bool) -> dict[str, Any]:
    """에이전트 산출물 검증 결과를 상태에 기록한다.

    실패면 nodeFailed 플래그를 세우고 retryCount 를 올린다 → 다음 라우터가 그걸 보고
    같은 에이전트를 다시 부른다(다음 에이전트로 넘어가지 않는다). 성공/개발모드(mock)면 플래그 해제.
    """

    node_failed = dict(state.get("nodeFailed") or {})
    node_failed[node] = failed
    updates: dict[str, Any] = {"nodeFailed": node_failed}
    if failed:
        rc = dict(state.get("retryCount") or {})
        rc[node] = rc.get(node, 0) + 1
        updates["retryCount"] = rc
    return updates


def _should_retry_node(state: GraphState, node: str) -> bool:
    """직전 에이전트가 생성 실패했고 재시도 예산이 남았으면 True(같은 에이전트에게 재지시)."""

    failed = (state.get("nodeFailed") or {}).get(node, False)
    count = (state.get("retryCount") or {}).get(node, 0)
    return bool(failed) and count <= MAX_GEN_RETRY


# --- 에이전트별 산출물 검증 라우터 (다음 에이전트 호출 전에 검증) ---
# parse ∥ profile 은 병렬 분기다(builder 팬아웃). 성공 시 "inputs_ready" 로 합류 지점
# (check_profile_completeness, defer)에 신호만 보낸다 — 서로의 다음 노드를 지정하지 않는다.
def route_after_parse(state: GraphState) -> str:
    return "parse_job_posting" if _should_retry_node(state, "parse_job_posting") else "inputs_ready"


def route_after_profile(state: GraphState) -> str:
    return "build_user_profile" if _should_retry_node(state, "build_user_profile") else "inputs_ready"


def _fit_grade(state: GraphState) -> str:
    return str((state.get("gapAnalysisResult") or {}).get("fitGrade") or "")


def route_after_gap(state: GraphState) -> str:
    if _should_retry_node(state, "analyze_gap"):
        return "analyze_gap"
    # 상 등급: 요구 역량을 대부분 충족 → 부족 역량을 채우는 로드맵은 만들지 않고 진단만 낸다 (2026-07-21).
    # 다만 사용자가 대안 공고를 명시적으로 요청(includeAlternatives)했다면 그건 존중해 보여준다.
    if _fit_grade(state) == "상":
        return "find_alternatives" if state.get("includeAlternatives") else "verify_result"
    return "plan_roadmap"


def route_after_roadmap(state: GraphState) -> str:
    # 로드맵 생성 실패면 재지시, 아니면 대체경로(옵션)→검증 (기존 route_alternatives 통합)
    if _should_retry_node(state, "plan_roadmap"):
        return "plan_roadmap"
    # 중·하 등급은 부족 역량이 있으므로 대안 공고까지 추천한다. 요청 옵션(includeAlternatives)도 존중.
    if _fit_grade(state) in ("중", "하") or state.get("includeAlternatives"):
        return "find_alternatives"
    return "verify_result"


def route_after_alternatives(state: GraphState) -> str:
    return "find_alternatives" if _should_retry_node(state, "find_alternatives") else "verify_result"


# ---------------------------------------------------------------------------
# parse_job_posting  (Job Posting Parser, 설계 8장)
# ---------------------------------------------------------------------------
class _JobPostingRead(BaseModel):
    """파서 2차 LLM 추출 스키마 — **읽기 전용**(설계 §0 ① 읽기 계층).

    `NormalizedJobPosting` 과 달리 `roleCategory`/`seniority` 가 **없다**. 그 둘은 '판단'이라
    `role_taxonomy` 룰이 결정한다(§3.1). LLM 에게 애초에 그 필드를 주지 않아야 판단을 안 한다 —
    프롬프트로 "하지 마라"라고 적는 것보다 스키마에서 빼는 게 확실하다.
    """

    # 설명을 비워 두면 약한 모델이 이 칸을 그냥 건너뛴다(gpt-4.1 계열에서 실측: 둘 다 빈 문자열).
    # 구조화 출력에서 필드 설명은 프롬프트보다 강하게 작동한다 — 지우지 말 것.
    jobTitle: str = Field(default="", description=(
        "공고의 직무명. 제목에서 회사명·연차 표기를 걷어낸 순수 직무명만. "
        "예: '[클라우드웨이브] 백엔드 엔지니어 (경력 3년 이상)' → '백엔드 엔지니어'"))
    companyName: str = Field(default="", description=(
        "채용하는 회사 이름. 대괄호·괄호 안에 있어도 뽑는다. "
        "예: '[클라우드웨이브] 백엔드 엔지니어' → '클라우드웨이브'. 원문에 없으면 빈 문자열."))
    requiredRequirements: list[Requirement] = Field(default_factory=list)
    preferredRequirements: list[Requirement] = Field(default_factory=list)
    techStack: list[str] = Field(default_factory=list)
    domainKeywords: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


_JOB_PARSER_SYSTEM = """너는 채용공고에서 필드를 뽑아내는 추출기다. 판단하지 않는다 — 적합도·합격 가능성·로드맵은 네 일이 아니다.
주어진 공고 원문에 **실제로 적힌 것만** 뽑는다.

입력 JSON 필드:
- requiredSection / preferredSection: 룰이 이미 분리한 '자격요건' / '우대사항' 섹션. 비어 있으면 헤더가 없는 공고다.
- fullText: 공고 전문.
- knownTechStack: 룰이 이미 확정한 기술 스택. **이미 확정됐으니 다시 뽑을 필요 없다.** 여기 없는 기술만 techStack 에 추가한다.

규칙:
- requiredSection 이 비어 있지 않으면 requiredRequirements 는 **그 섹션에서만** 뽑는다. preferredSection 도 마찬가지.
  두 섹션이 모두 비어 있을 때만 fullText 에서 "우대/있으면 좋음" 같은 표현으로 필수·우대를 구분한다.
- 각 requirement 는 한 문장 단위로 쪼갠다. requirementId 는 아무 값이나 넣어도 된다(뒤에서 룰이 재부여한다).
- techStack 은 knownTechStack 에 **없는** 기술/언어/도구만. domainKeywords 는 산업·서비스 도메인 키워드(예: 커머스, 핀테크).
- 원문에 없는 내용을 지어내지 말 것. 불명확하거나 원문이 부실하면 uncertainties 에 한국어로 기록한다.
- 모든 텍스트는 한국어로 출력한다."""


def _mock_job_posting() -> NormalizedJobPosting:
    """LLM 미설정/실패 시 폴백용 샘플 (스켈레톤 동작 보존)."""

    return NormalizedJobPosting(
        jobTitle="백엔드 개발자",
        companyName="예시기업",
        roleCategory="backend",  # role_taxonomy 표준 키
        seniority="junior",
        requiredRequirements=[
            Requirement(requirementId="req-1", text="Java/Spring Boot 기반 REST API 개발 경험", type="required"),
            Requirement(requirementId="req-2", text="RDBMS 설계 및 SQL 활용 능력", type="required"),
        ],
        preferredRequirements=[
            Requirement(requirementId="pref-1", text="AWS 배포 경험", type="preferred"),
        ],
        techStack=["Java", "Spring Boot", "MySQL", "AWS"],
        domainKeywords=["채용", "커머스"],
        uncertainties=["LLM 미사용 폴백 결과입니다."],
    )


# LLM 이 "값 없음"을 빈 문자열 대신 자리표시자로 채워 넣을 때가 있다("<UNKNOWN>", "N/A", "미상").
# 그대로 두면 하류가 그걸 진짜 값으로 믿는다 — 예: fetch_company_context("<UNKNOWN>") 로 RAG 호출.
_PLACEHOLDER_VALUES = {
    "<unknown>", "unknown", "n/a", "na", "none", "null", "미상", "없음", "불명",
    "미명시", "명시되지 않음", "-", "?", "??",
}


def _clean_field(value: str) -> str:
    """자리표시자를 빈 문자열로. '모른다'는 빈 값으로 표현해야 하류가 오해하지 않는다."""

    text = (value or "").strip()
    return "" if text.lower() in _PLACEHOLDER_VALUES else text


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        key = (raw or "").strip()
        low = key.lower()
        if key and low not in seen:
            seen.add(low)
            out.append(key)
    return out


def _normalize_job_schema(posting: NormalizedJobPosting) -> NormalizedJobPosting:
    """설계 8.3-4 Schema Normalize: id 재부여·중복 제거·표준화.

    기술명은 `skill_taxonomy` 로 표준화한다(ReactJS→React). 이게 없으면 뒤의 `gap_matcher`
    1차 정확 매칭이 표기 차이만으로 전부 빗나간다.
    """

    for i, r in enumerate(posting.requiredRequirements, start=1):
        r.requirementId = f"req-{i}"
        r.type = "required"
    for i, r in enumerate(posting.preferredRequirements, start=1):
        r.requirementId = f"pref-{i}"
        r.type = "preferred"

    posting.techStack = get_skill_taxonomy().normalize_all(posting.techStack)
    posting.domainKeywords = _dedup_keep_order(posting.domainKeywords)
    posting.rawChunks = []  # 원문 청크는 상태 비대화 방지로 비운다
    return posting


def _validate_job_posting(posting: NormalizedJobPosting) -> list[dict]:
    """설계 8.3-5 Output Validate: 필수 필드/최소 정합성 검사 → warnings (예외 아님)."""

    warnings: list[dict] = []
    if not posting.jobTitle.strip():
        warnings.append({"code": "missing_job_title", "message": "직무명(jobTitle)을 추출하지 못했습니다."})
    if not posting.requiredRequirements:
        warnings.append(
            {"code": "no_required_requirements", "message": "필수 요구사항이 비어 있습니다. 공고 본문이 부실할 수 있습니다."}
        )
    if not posting.techStack:
        warnings.append({"code": "empty_tech_stack", "message": "기술 스택이 비어 있습니다."})
    return warnings


def _build_parser_input(text: str, rules: RuleExtraction) -> str:
    """2차 LLM 추출에 넘길 입력. 룰이 이미 확정한 것은 '확정됨'으로 알려 재추출을 막는다."""

    return json.dumps(
        {
            "requiredSection": rules.requiredSection,
            "preferredSection": rules.preferredSection,
            "fullText": text,
            "knownTechStack": rules.techStack,
        },
        ensure_ascii=False,
    )


def _apply_rule_extraction(
    posting: NormalizedJobPosting, rules: RuleExtraction, text: str
) -> list[dict]:
    """룰 산출물(기술스택·연차·직군)을 LLM 산출물 위에 덮어써 확정한다.

    순서가 중요하다: **룰이 LLM 을 이긴다.** 룰은 원문에 그렇게 적혀 있을 때만 값을 내므로
    정밀도가 높고, LLM 은 그럴듯하게 지어낼 수 있다. 겹치면 룰 쪽을 신뢰한다.
    """

    warnings: list[dict] = []
    roles = get_role_taxonomy()

    # 자리표시자 제거 — classify_role 이 jobTitle 을 읽기 전에 해야 한다.
    posting.jobTitle = _clean_field(posting.jobTitle)
    posting.companyName = _clean_field(posting.companyName)
    if not posting.companyName:
        warnings.append({
            "code": "no_company_name",
            "message": "회사명을 확정하지 못했습니다(기업 맥락 RAG 조회를 건너뜁니다).",
        })

    # 기술스택: 룰이 찾은 것(확정) 먼저, LLM 이 추가로 찾은 것(사전에 없는 신기술 등)을 뒤에.
    posting.techStack = get_skill_taxonomy().normalize_all([*rules.techStack, *posting.techStack])

    # 직군·연차: LLM 추정이 아니라 taxonomy 룰이 결정한다(§3.1).
    posting.roleCategory = roles.classify_role(posting.jobTitle, text)
    posting.seniority = roles.classify_seniority(posting.jobTitle, text, years=rules.minYears)
    # 숫자 원본을 보존한다 — 사다리 칸은 손실 요약이라 판정(연차 대 연차)과 표기(원문)는
    # 이 값을 우선한다.
    posting.minYears = rules.minYears
    posting.yearsEvidence = rules.yearsEvidence

    if not posting.roleCategory:
        warnings.append({
            "code": "role_unclassified",
            "message": "직무 카테고리를 규칙으로 분류하지 못했습니다(대체 경로 탐색이 제한될 수 있음).",
        })
    if not posting.seniority:
        warnings.append({
            "code": "seniority_unknown",
            "message": "요구 연차 근거를 찾지 못해 미상으로 둡니다(추측하지 않음).",
        })
    elif rules.yearsEvidence:
        posting.uncertainties.append(
            f"요구 연차는 원문 '{rules.yearsEvidence}' 근거로 {posting.seniority} 로 분류했습니다."
        )
    return warnings


def parse_job_posting(state: GraphState) -> dict[str, Any]:
    """공고 입력(url/text/file) → NormalizedJobPosting (설계 8.3 체인 + §3.1 하이브리드 추출).

    extract → **1차 룰 추출** → 2차 LLM 추출(잔여 비정형만) → **룰 덮어쓰기/taxonomy 표준화**
    → validate. LLM 은 '읽기'만 하고, 직군·연차 '판단'은 role_taxonomy 가 한다.

    멱등: 이미 파싱된 공고가 상태에 있으면 그대로 쓴다. 대화형 진입(공고만 먼저 정리해 보여주고
    이력서를 받은 뒤 판정)에서 같은 공고를 두 번 파싱해 LLM 을 이중 호출하는 것을 막는다.
    """

    already = state.get("normalizedJobPosting") or {}
    if any(already.get(k) for k in ("requiredRequirements", "preferredRequirements",
                                    "techStack", "jobTitle")):
        return {
            "status": Status.PARSING_JOB,
            "normalizedJobPosting": already,
            "toolLog": [_log("parse_job_posting", "이미 파싱된 공고를 재사용", to="build_user_profile")],
        }

    # 1) input normalize + 2) text extract
    extracted = extract_text(state.get("jobPostingInput"))
    warnings = list(extracted.warnings)

    # 3) 1차 룰 추출 — 기술스택·연차·섹션을 LLM 없이 먼저 확정 (§3.1)
    rules = extract_rules(extracted.text)
    if not rules.has_sections and extracted.text.strip():
        warnings.append({
            "code": "no_requirement_sections",
            "message": "자격요건/우대사항 헤더를 찾지 못해 전문에서 LLM 추출로 처리합니다.",
        })

    # 4) 2차 LLM 추출 — 룰이 못 잡은 비정형 요구사항만 (읽기 전용 스키마)
    read, llm_warnings = run_structured(
        _JobPostingRead,
        _JOB_PARSER_SYSTEM,
        _build_parser_input(extracted.text, rules),
        node="parse_job_posting",
    )
    warnings.extend(llm_warnings)

    gen_failed = False
    if read is None:
        if llm_unconfigured(warnings):
            posting = _mock_job_posting()            # 키 없음(개발 모드)
        else:
            posting = NormalizedJobPosting()          # 호출 실패 → 가짜 대신 빈 결과
            _mark_generation_failed(posting, "parse_job_posting", warnings)
            gen_failed = True
    else:
        posting = NormalizedJobPosting(**read.model_dump())
        # 5) 룰 덮어쓰기 + 6) schema normalize + 7) output validate
        warnings.extend(_apply_rule_extraction(posting, rules, extracted.text))
        posting = _normalize_job_schema(posting)
        warnings.extend(_validate_job_posting(posting))

    return {
        "status": Status.PARSING_JOB,
        "normalizedJobPosting": posting.model_dump(),
        "warnings": [{**w, "node": "parse_job_posting"} for w in warnings],
        "toolLog": [_log("parse_job_posting", "채용공고 구조화 완료", to="build_user_profile")],
        **_gen_retry_updates("parse_job_posting", state, gen_failed),
    }


# ---------------------------------------------------------------------------
# build_user_profile  (User Profile Builder, 설계 9장)
# ---------------------------------------------------------------------------
class _EvidenceRead(BaseModel):
    """근거 한 건. gap_matcher·verify_rules 가 evidenceId 로 참조 무결성을 검사한다."""

    evidenceId: str = Field(default="", description="근거 식별자. ev-1, ev-2 … 순서대로.")
    source: str = Field(default="", description=(
        "이 근거가 나온 항목의 id. 예: prj-1(프로젝트) / exp-1(재직) / edu-1(학력) / "
        "boot-1(부트캠프) / award-1(수상)"))
    text: str = Field(default="", description=(
        "원문에 적힌 구체적 사실·성과 문장 한 개. 요약·윤색하지 말고 그대로 담는다."))


class _UserProfileRead(BaseModel):
    """프로필 빌더의 LLM 추출 스키마 — **읽기 전용**(설계 §0 ① 읽기 계층).

    `NormalizedUserProfile` 과 달리 없는 필드가 둘이다:
    - `skillEvidence`      : "이 근거가 이 스킬을 증명한다"는 매핑은 룰이 만든다(§3.2-④).
                             LLM 에게 맡기면 근거를 지어내 붙인다.
    - `clarificationQuestions`: 무엇을 물을지는 `sufficiency_rules` 가 정한다(§3.3/§3.4).
                             "정보가 부족한가"는 판단(Decide)이라 LLM 이 할 일이 아니다.
    """

    education: list[EducationEntry] = Field(default_factory=list)
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[SkillEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    languages: list[LanguageEntry] = Field(default_factory=list)
    bootcamp: list[BootcampEntry] = Field(default_factory=list)
    awards: list[AwardEntry] = Field(default_factory=list)
    # list[dict] 로 두면 구조화 출력에서 '형태 없는 객체 배열'이 되어 약한 모델이 빈 배열을 낸다
    # (gpt-4.1/mini 실측: evidenceMap=0 → 근거가 없어 판정 자체가 불가능해졌다).
    # 항목 타입을 명시해야 어떤 모델이든 채운다.
    evidenceMap: list[_EvidenceRead] = Field(default_factory=list, description=(
        "판정이 인용할 근거 문장 목록. 위 항목들(prj-1/exp-1/edu-1 등)에서 뽑은 "
        "구체적 사실·성과 문장을 원문 그대로 담는다. 스킬 하나당 최소 한 건은 만든다."))
    uncertainties: list[str] = Field(default_factory=list)


_PROFILE_BUILDER_SYSTEM = """너는 취업 준비자의 이력서/포트폴리오에서 항목을 뽑아내는 추출기다. 판단하지 않는다 —
적합도·강약점·합격 가능성은 네 일이 아니다. 주어진 이력서 원문에 **실제로 적힌 것만** 뽑는다.

**experiences 와 projects 를 헷갈리지 말 것 (가장 중요):**
- experiences 는 **정규직/계약직/인턴 등 고용 관계가 있었던 재직 이력만.** 급여를 받는 근무였는지가 기준이다.
- 학교 수업/동아리/부트캠프(SSAFY 등)/개인 프로젝트/사이드 프로젝트는 고용 관계가 아니므로 **전부 projects 에 넣는다.**
- 같은 활동을 experiences 와 projects 양쪽에 중복해서 적지 말 것 — 하나로 결정해서 한쪽에만 넣는다.

항목별 필드:
- education 각 항목: { "id": "edu-1", "school", "major", "degree"(고졸/전문학사/학사/석사/박사), "status"(졸업/재학/휴학/중퇴/수료), "period" }
- experiences 각 항목: { "id": "exp-1", "company", "role", "employmentType"(정규직/계약직/인턴/파견), "period", "summary" }
- projects 각 항목: { "id": "prj-1", "title", "projectType"(팀 프로젝트/개인 프로젝트), "period", "teamSize", "role", "summary", "techStack": [...], "achievements": [...] }.
  achievements 는 문제-조치-성과가 드러나는 문장 리스트로, 가능하면 수치를 포함한다.
- skills 각 항목: { "name", "level" }(level: beginner/intermediate/advanced). 원문에 숙련도 언급이 없으면 level 은 빈 문자열로 둔다. **숙련도를 추측하지 말 것.**
- certifications 각 항목: { "id": "cert-1", "name", "status"(취득/필기합격/응시예정 등), "acquiredDate" }
- languages 각 항목: { "id": "lang-1", "name", "testName"(토익/오픽/JLPT 등, 시험 없으면 빈 문자열), "score", "testDate", "proficiency"(시험 점수가 없을 때만 자유 서술로, 예: "Native") }
- bootcamp 각 항목: { "id": "boot-1", "name", "organization", "track", "period", "summary" }
- awards 각 항목: { "id": "award-1", "title", "organization", "date", "description" }
- evidenceMap 은 { "evidenceId": "ev-1", "source": "<위 항목들의 id, 예: prj-1/exp-1/edu-1/boot-1/award-1>", "text": "<한 문장 근거>" } 리스트.
  뒤 단계의 판정이 이 문장들만 근거로 인용하므로, **원문에 있는 구체적 사실·성과 문장**을 그대로 담는다. 요약·윤색하지 말 것.
- 원문에 없는 경력·수치를 지어내지 말 것. 애매하면 uncertainties 에 한국어로 남긴다.
- 모든 텍스트는 한국어로 출력한다."""


def _mock_user_profile() -> NormalizedUserProfile:
    """LLM 미설정/실패 시 폴백용 샘플 (스켈레톤 동작 보존)."""

    # 근거는 2건 이상이어야 한다 — sufficiency_rules 의 최소 근거 기준(_MIN_EVIDENCE_COUNT)에
    # 미달하면 폴백 프로필만으로도 need_more_info 로 빠져 나머지 경로를 못 밟는다.
    return NormalizedUserProfile(
        projects=[
            {"id": "prj-1", "title": "Spring Boot 커머스 API", "summary": "주문/결제 REST API 구현"},
        ],
        skills=[{"name": "Java", "level": "intermediate"}, {"name": "Spring Boot", "level": "intermediate"}],
        evidenceMap=[
            {"evidenceId": "ev-1", "source": "prj-1",
             "text": "Spring Boot 와 JPA 로 주문/결제 REST API 를 구현했습니다."},
            {"evidenceId": "ev-2", "source": "prj-1",
             "text": "MySQL 인덱스 설계로 주문 조회 응답시간을 단축했습니다."},
        ],
        skillEvidence={
            "Spring Boot": ["ev-1"], "Spring": ["ev-1"], "JPA": ["ev-1"], "REST API": ["ev-1"],
            "MySQL": ["ev-2"], "RDBMS": ["ev-2"], "SQL": ["ev-2"],
        },
        clarificationQuestions=[],
        uncertainties=["LLM 미사용 폴백 결과입니다."],
    )


def _normalize_profile_skills(profile: NormalizedUserProfile, resume_text: str) -> None:
    """스킬명을 taxonomy 표준형으로 바꾸고, 룰이 원문에서 추가 발견한 스킬을 합친다 (§3.2-③).

    LLM 이 놓친 스킬을 정규식이 줍는다. 다만 룰로 주운 스킬은 **숙련도를 알 수 없으므로
    level 을 비워 둔다** — "원문에 이 기술명이 있다"와 "이 기술을 잘한다"는 다른 얘기다.
    근거 없는 스킬은 뒤의 gap_matcher 가 evidence 부재로 알아서 약하게 취급한다.
    """

    taxonomy = get_skill_taxonomy()
    merged: dict[str, SkillEntry] = {}

    for raw in profile.skills:
        name = taxonomy.normalize(raw.name)
        if not name:
            continue
        key = name.lower()
        if key not in merged:
            merged[key] = SkillEntry(name=name, level=raw.level)

    for name in taxonomy.find_in_text(resume_text):
        merged.setdefault(name.lower(), SkillEntry(name=name, level=""))

    # 수반 스킬 보강: MySQL 을 안다면 RDBMS·SQL 도 아는 것이다(§skill_taxonomy.implies).
    for name in taxonomy.with_implied([s.name for s in merged.values()]):
        merged.setdefault(name.lower(), SkillEntry(name=name, level=""))

    profile.skills = list(merged.values())


def _build_skill_evidence(profile: NormalizedUserProfile) -> dict[str, list[str]]:
    """evidenceMap 을 훑어 '스킬 → 그 스킬이 등장한 evidenceId 들' 표를 만든다 (§3.2-④).

    이 표가 gap_matcher 의 matchedEvidenceIds 근거가 된다. 룰로 만들기 때문에
    **존재하지 않는 근거를 인용하는 일이 구조적으로 불가능**하다.

    근거 문장에서 찾은 스킬은 수반 스킬까지 확장한다 — "MySQL 인덱스 튜닝" 이라는 근거는
    MySQL 뿐 아니라 RDBMS·SQL 의 근거이기도 하다.
    """

    taxonomy = get_skill_taxonomy()
    mapping: dict[str, list[str]] = {}
    for evidence in profile.evidenceMap:
        evidence_id = str(evidence.get("evidenceId", ""))
        if not evidence_id:
            continue
        found = taxonomy.find_in_text(str(evidence.get("text", "")))
        for name in taxonomy.with_implied(found):
            mapping.setdefault(name, [])
            if evidence_id not in mapping[name]:
                mapping[name].append(evidence_id)
    return mapping


def _reassign_ids(entries: list, prefix: str) -> None:
    """LLM 이 중복/누락 id 를 내면 evidenceMap.source 인용이 엉킨다 — 순서대로 재부여한다."""

    for i, entry in enumerate(entries, start=1):
        entry.id = f"{prefix}-{i}"


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _filter_grounded_evidence(profile: NormalizedUserProfile, resume_text: str) -> int:
    """evidenceMap.text 가 실제 원문에 있는 문장인지 대조해, 없으면 제거한다 (환각 방지).

    프롬프트로 "원문 그대로 인용하라"고 시켜도 지켜진다는 보장은 없다 — 이 문장이 뒤에서
    skillEvidence/met 판정의 근거로 그대로 쓰이므로, 원문에 없는 문장이 섞여 들어오면
    "증명됐다"는 판정 자체가 조작 가능해진다(verify_result.check_evidence_grounding 이
    evidenceId 참조 무결성을 검증하는 것과 같은 이유로, 그보다 한 단계 앞선 지점을 막는다).

    공백/줄바꿈만 정규화한 **정확 부분 문자열 대조**다 — 퍼지 매칭은 안 한다. 느슨하게
    잡으면 진짜 환각도 통과시킬 위험이 있고, 이 프롬프트는 애초에 "요약·윤색 금지, 그대로
    담아라"이므로 사소한 표기 차이까지 봐줄 이유가 없다.

    반환: 제거된(환각 의심) 문장 수.
    """

    source = _normalize_ws(resume_text)
    grounded: list[dict] = []
    hallucinated = 0
    for evidence in profile.evidenceMap:
        text = _normalize_ws(str(evidence.get("text", "")))
        if text and text in source:
            grounded.append(evidence)
        else:
            hallucinated += 1
    profile.evidenceMap = grounded
    return hallucinated


def _derive_evidence_map(profile: NormalizedUserProfile) -> list[dict]:
    """추출된 항목의 서술 → 근거 목록. 모델이 evidenceMap 을 비워 보냈을 때의 대체 경로.

    새 문장을 만들지 않는다 — 이미 뽑아 놓은 summary·achievements·description 을 그대로
    근거 자리로 옮긴다. 그래서 원문 대조(_filter_grounded_evidence)와 모순되지 않는다.
    """

    rows: list[dict] = []

    def add(source: str, *texts: str) -> None:
        for text in texts:
            text = (text or "").strip()
            if len(text) >= 10:   # 한 문장이라 보기 어려운 토막은 근거로 쓰지 않는다
                rows.append({"evidenceId": "", "source": source, "text": text})

    for i, prj in enumerate(profile.projects, start=1):
        add(f"prj-{i}", prj.summary, *(prj.achievements or []))
    for i, exp in enumerate(profile.experiences, start=1):
        add(f"exp-{i}", exp.summary)
    for i, boot in enumerate(profile.bootcamp, start=1):
        add(f"boot-{i}", boot.summary)
    for i, award in enumerate(profile.awards, start=1):
        add(f"award-{i}", award.description)
    for i, edu in enumerate(profile.education, start=1):
        label = " ".join(x for x in (edu.school, edu.major, edu.degree, edu.status) if x)
        add(f"edu-{i}", label)
    return rows


def _normalize_profile_schema(
    profile: NormalizedUserProfile, resume_text: str
) -> list[dict]:
    """프로필 결정론 정리: 근거 원문 대조 → id 재부여 → 스킬 표준화 → skillEvidence 구축."""

    warnings: list[dict] = []

    # evidenceMap.text 가 원문에 실제로 있는지 먼저 걸러낸다 — 그래야 환각 문장이
    # evidenceId 를 받거나 skillEvidence 에 반영되는 일 자체가 없다.
    hallucinated = _filter_grounded_evidence(profile, resume_text)
    if hallucinated:
        warnings.append({
            "code": "hallucinated_evidence",
            "message": f"원문에서 확인되지 않는 근거 문장 {hallucinated}건을 제거했습니다.",
        })

    # LLM 이 근거 목록을 비워 보내면 **룰로 만든다.** 약한 모델은 항목 리스트는 채우면서
    # evidenceMap 은 건너뛴다(gpt-4.1/mini 실측 0건). 근거가 없으면 판정 자체가 불가능해지므로,
    # 이미 추출된 항목의 서술을 그대로 근거로 옮긴다 — 새로 지어내는 문장이 아니라 재배치다.
    if not profile.evidenceMap:
        derived = _derive_evidence_map(profile)
        if derived:
            profile.evidenceMap = derived
            warnings.append({
                "code": "evidence_map_derived",
                "message": f"LLM 이 근거 목록을 비워 보내 추출 항목에서 {len(derived)}건을 파생했습니다.",
            })

    # evidenceId/각 항목 id 를 순서대로 재부여한다. LLM 이 중복 id 를 내면 근거 인용이 서로 엉킨다.
    for i, evidence in enumerate(profile.evidenceMap, start=1):
        evidence["evidenceId"] = f"ev-{i}"
    _reassign_ids(profile.education, "edu")
    _reassign_ids(profile.experiences, "exp")
    _reassign_ids(profile.projects, "prj")
    _reassign_ids(profile.bootcamp, "boot")
    _reassign_ids(profile.awards, "award")
    _reassign_ids(profile.certifications, "cert")
    _reassign_ids(profile.languages, "lang")

    _normalize_profile_skills(profile, resume_text)
    profile.skillEvidence = _build_skill_evidence(profile)

    if not profile.evidenceMap:
        warnings.append({
            "code": "no_evidence_map",
            "message": "근거(evidenceMap)가 비어 있습니다. 요구사항 충족 판정이 불가능에 가깝습니다.",
        })
    elif not profile.skillEvidence:
        warnings.append({
            "code": "no_skill_evidence",
            "message": "근거 문장에서 알려진 기술명을 찾지 못해 스킬↔근거 매핑이 비었습니다.",
        })
    return warnings


def build_user_profile(state: GraphState) -> dict[str, Any]:
    """이력서 원천(resumeInput) → NormalizedUserProfile (설계 9.3 체인 + §3.2).

    extract → LLM 항목 추출(읽기 전용) → **skill_taxonomy 표준화 + skillEvidence 룰 구축**.
    "이 경험이 이 스킬을 증명한다"는 매핑은 LLM 이 아니라 룰이 만든다.

    resumeInput 이 없으면(실서비스의 DB 조회 경로 미구현 단계) 폴백 샘플을 쓴다.
    """

    resume_source = state.get("resumeInput")
    warnings: list[dict] = []
    resume_text = ""
    read: _UserProfileRead | None = None

    if not resume_source:
        profile = _mock_user_profile()
        warnings.append(
            {"code": "no_resume_source", "message": "resumeInput 이 없어 폴백 프로필을 사용합니다."}
        )
    else:
        extracted = extract_text(resume_source)
        resume_text = extracted.text
        warnings.extend(extracted.warnings)
        read, llm_warnings = run_structured(
            _UserProfileRead,
            _PROFILE_BUILDER_SYSTEM,
            resume_text,
            node="build_user_profile",
        )
        warnings.extend(llm_warnings)

    gen_failed = False
    if resume_source:
        if read is None:
            if llm_unconfigured(warnings):
                profile = _mock_user_profile()        # 키 없음(개발 모드)
            else:
                profile = NormalizedUserProfile()      # 호출 실패 → 가짜 대신 빈 결과
                _mark_generation_failed(profile, "build_user_profile", warnings)
                gen_failed = True
        else:
            profile = NormalizedUserProfile(**read.model_dump())
            warnings.extend(_normalize_profile_schema(profile, resume_text))

    return {
        "status": Status.BUILDING_PROFILE,
        "normalizedUserProfile": profile.model_dump(),
        "warnings": [{**w, "node": "build_user_profile"} for w in warnings],
        "toolLog": [_log("build_user_profile", "사용자 프로필 구조화 완료", to="check_sufficiency")],
        **_gen_retry_updates("build_user_profile", state, gen_failed),
    }


# ---------------------------------------------------------------------------
# check_profile_completeness  (프로필 결측 enum 필드 보완, §3.2 후속 · 비블로킹)
# ---------------------------------------------------------------------------
def check_profile_completeness(state: GraphState) -> dict[str, Any]:
    """docx 에서 못 뽑은 enum 필드(degree/status/employmentType/projectType)를 찾는다.

    **순수 룰 — LLM 호출 없음.** sufficiency_rules 와 달리 여기서 찾은 결측은
    분석을 막지 않는다 — gap_matcher 가 이 값들을 참조하지 않으므로 analyze_gap 을
    미룰 이유가 없다. 결과는 followUpQuestions 가 아니라 profileCompletionQuestions 에
    실려 최종 응답에만 곁들여진다(assemble_output 참고).
    """

    profile = state.get("normalizedUserProfile") or {}
    missing = find_missing_enum_fields(profile)
    questions = build_completion_questions(missing)

    return {
        "profileCompletionQuestions": questions,
        "toolLog": [_log("check_profile_completeness", "프로필 결측 필드 확인(룰)", to="check_sufficiency")],
    }


# ---------------------------------------------------------------------------
# _build_comparison_requirements  (gap_matcher 에 넘길 비교항목 조립, check_sufficiency/
# analyze_gap 공용)
# ---------------------------------------------------------------------------
def _tech_stack_requirements(posting: dict, existing: list[dict]) -> list[dict]:
    """techStack → 합성 요구사항(preferred). 이미 요구사항 문장에 언급된 기술은 제외한다.

    requiredRequirements/preferredRequirements 문장 안에 "Spring Boot 3년" 처럼 이미
    녹아 있는 기술은 그쪽에서 이미 매칭되므로, techStack 에도 넣으면 같은 스킬을 두 번
    판정하게 된다.
    """

    taxonomy = get_skill_taxonomy()
    mentioned: set[str] = set()
    for req in existing:
        mentioned.update(taxonomy.find_in_text(str(req.get("text", ""))))

    out: list[dict] = []
    for i, skill in enumerate(posting.get("techStack", []), start=1):
        if skill in mentioned:
            continue
        out.append({"requirementId": f"tech-{i}", "text": skill, "type": "preferred"})
    return out


def _domain_keyword_requirements(posting: dict) -> list[dict]:
    """domainKeywords → 합성 요구사항(preferred, kind=domain_keyword).

    도메인 적합도는 필수 자격요건이 아니라 '있으면 좋은' 신호라 preferred 로 둔다.
    """

    return [
        {"requirementId": f"domain-{i}", "text": kw, "type": "preferred", "kind": "domain_keyword"}
        for i, kw in enumerate(posting.get("domainKeywords", []), start=1)
        if str(kw).strip()
    ]


def _seniority_requirement(posting: dict) -> list[dict]:
    """posting.seniority → 합성 요구사항(required, kind=seniority).

    연차 요건은 보통 자격요건(필수)으로 명시되므로 required 로 둔다. seniority 가
    비어 있으면(원문에서 못 정함) 비교할 기준 자체가 없으니 아무것도 만들지 않는다.
    `roleCategory` 도 함께 실어서, gap_matcher 가 연차 계산 시 무관한 직군 경력
    (예: 백엔드 공고에 미술학원 강사 경력)을 걸러낼 수 있게 한다.
    """

    seniority = str(posting.get("seniority", "")).strip()
    if not seniority:
        return []
    # 표기는 공고가 한 말(yearsEvidence)을 그대로 — 사다리 라벨("주니어 신입")은 공고에
    # 없는 단어("신입")를 만들어낼 수 있어 숫자 근거가 없을 때만 쓴다.
    evidence = str(posting.get("yearsEvidence") or "").strip()
    label = evidence or SENIORITY_KO.get(seniority, seniority)
    return [{
        "requirementId": "seniority-1",
        "text": f"요구 연차: {label}",
        "type": "required",
        "kind": "seniority",
        "seniority": seniority,
        "minYears": posting.get("minYears"),
        "yearsEvidence": evidence,
        "roleCategory": str(posting.get("roleCategory", "")),
    }]


def _build_comparison_requirements(posting: dict) -> list[dict]:
    """공고에서 gap_matcher 비교 대상으로 쓸 요구사항 전체를 조립한다.

    requiredRequirements/preferredRequirements(원문 문장) + techStack/domainKeywords/
    seniority(합성 항목)를 합친다. check_sufficiency 와 analyze_gap 이 둘 다 이 목록을
    써야 두 노드의 판단 기준이 어긋나지 않는다.
    """

    base = list(posting.get("requiredRequirements", [])) + list(
        posting.get("preferredRequirements", [])
    )
    # 순수 연차 줄("프론트엔드 개발 경력 2년 이상")은 텍스트 매칭에서 뺀다 — 같은 제약이
    # 두 번 판정되면(텍스트 의미판정 "경험 있음→충족" vs 연차 룰 "2년 미달→미충족")
    # 리포트가 자기모순이 된다. 이 제약은 합성 seniority 요건이 단독으로 담당한다.
    # 단, 연차 표기가 있어도 기술 토큰이 함께 있는 줄("Python 경력 2년 이상")은
    # 기술 요건이기도 하므로 남긴다.
    evidence = str(posting.get("yearsEvidence") or "").strip()
    if evidence:
        tech = [t.lower() for t in (posting.get("techStack") or [])]

        def _is_pure_years_line(text: str) -> bool:
            if evidence not in text:
                return False
            rest = text.replace(evidence, " ").lower()
            return not any(t in rest for t in tech)

        base = [r for r in base if not _is_pure_years_line(str(r.get("text", "")))]
    base += _tech_stack_requirements(posting, base)
    base += _domain_keyword_requirements(posting)
    base += _seniority_requirement(posting)
    return base


# ---------------------------------------------------------------------------
# check_sufficiency  (정보 충분성 판단, 설계 13.4)
# ---------------------------------------------------------------------------
def check_sufficiency(state: GraphState) -> dict[str, Any]:
    """정보 충분성 판정 (설계 13.4 + §3.3). **순수 룰 — LLM 호출 없음.**

    커버리지를 재려면 요구사항↔스킬 매칭이 필요하므로 `gap_matcher` 를 재사용한다.
    임베딩 없이 룰 모드로만 도는 싼 게이트다(어차피 판정 불가 건을 찾는 게 목적).

    판정 결과는 상태에 실어 두고, 분기는 route_sufficiency 가 그 결과만 읽는다.
    """

    posting = state.get("normalizedJobPosting") or {}
    profile = state.get("normalizedUserProfile") or {}
    requirements = _build_comparison_requirements(posting)

    report = get_gap_matcher().match(requirements, profile)
    verdict = assess_sufficiency(report, profile)
    questions = build_questions(verdict)

    # '왜 멈췄는가'는 분석을 막은 결핍(blocking)만 말해야 한다. 부가 질문거리까지 이유로
    # 늘어놓으면 사소한 결핍 때문에 멈춘 것처럼 보인다.
    blocking_reasons = [m.detail for m in verdict.blocking]
    warnings: list[dict] = []
    if not verdict.sufficient:
        warnings.append({
            "code": "insufficient_info",
            "message": "정보가 부족해 추가 질문이 필요합니다: " + "; ".join(blocking_reasons[:3]),
        })

    return {
        "sufficiency": {
            "sufficient": verdict.sufficient,
            "evidenceCount": verdict.evidenceCount,
            "undecidableRequiredCount": verdict.undecidableRequiredCount,
            "reasons": blocking_reasons,
        },
        "followUpQuestions": questions,
        "warnings": [{**w, "node": "check_sufficiency"} for w in warnings],
        "toolLog": [_log("check_sufficiency", "정보 충분성 판단(룰)")],
    }


def route_sufficiency(state: GraphState) -> str:
    """정보가 부족하면 ask_user, 충분하면 analyze_gap 으로 분기 (설계 13.4).

    판정은 check_sufficiency 가 이미 끝냈다. 라우터는 그 결과만 읽는다
    (여기서 다시 판단하면 판정 로직이 두 곳으로 갈라진다).
    """

    verdict = state.get("sufficiency") or {}
    return "analyze_gap" if verdict.get("sufficient", True) else "ask_user"


# ---------------------------------------------------------------------------
# ask_user  (추가 질문 생성 후 중단, 설계 13.4)
# ---------------------------------------------------------------------------
def ask_user(state: GraphState) -> dict[str, Any]:
    """추가 질문 제시 후 중단 (설계 13.4 + §3.4).

    질문은 check_sufficiency 의 룰이 이미 확정해 followUpQuestions 에 실어 뒀다.
    이 노드는 그걸 사용자에게 내보내는 역할만 한다 — 무엇을 물을지는 룰이 정한다.
    (문구를 자연스럽게 다듬는 nl_render 는 말하기 계층에서 별도로 붙는다.)
    """

    return {
        "status": Status.NEED_INFO,
        "toolLog": [_log("ask_user", "추가 질문 생성 — 사용자 응답 대기", to="assemble_output")],
    }


# ---------------------------------------------------------------------------
# analyze_gap  (Gap Analyzer, 설계 10장)
# ---------------------------------------------------------------------------
# 폴백 mock 이 없다: 이 노드는 LLM 을 호출하지 않으므로 'LLM 미설정' 폴백 자체가 성립하지 않는다.
# 입력이 비면 빈 결과 + warning 으로 정직하게 처리한다.
def analyze_gap(state: GraphState) -> dict[str, Any]:
    """공고 요구사항 vs 사용자 프로필 → GapAnalysisResult (설계 10장 + §3.5).

    **판정은 `gap_matcher` 가 결정론으로 한다. 이 노드는 LLM 을 호출하지 않는다.**
    충족/미충족·심각도·점수는 전부 계산 결과다. reason 문장을 사람 말투로 다듬는 일은
    `nl_render`(말하기 계층)가 맡는다 — 그때도 판정 자체는 바뀌지 않는다.

    기업 맥락은 RAG 어댑터로 조회해 **근거로 첨부**한다. RAG 미연결이면 빈 결과 + warning 이며,
    프로필 근거만으로 판정한다(RAG 실패를 전체 실패로 만들지 않는다).
    """

    posting = state.get("normalizedJobPosting") or {}
    profile = state.get("normalizedUserProfile") or {}
    requirements = _build_comparison_requirements(posting)

    warnings: list[dict] = []
    sources: list[dict] = []

    # RAG hook point ① — 기업 맥락 조회 (설계 10 판정 근거 우선순위의 '기업 정보' 단계)
    # 회사명이 없으면 호출하지 않는다. 빈 회사명으로는 RAG 가 의미 있는 검색을 할 수 없고,
    # 무관한 조각이 섞여 판정 근거를 오염시킬 위험만 있다(rag-team-interface-spec §2 오염 방지).
    company_name = posting.get("companyName", "")
    if company_name:
        rag = get_rag_adapter().fetch_company_context(company_name, requirements)
    else:
        rag = RagResult(warnings=[{
            "code": "company_context_skipped",
            "message": "회사명 미확정 — 기업 맥락 조회를 건너뛰고 프로필 근거만으로 판정합니다.",
        }])
    warnings.extend(rag.warnings)
    sources.extend(rag.sources)

    # 판정 — gap_matcher 결정론 엔진 (§3.5). LLM 호출 없음.
    report = get_gap_matcher().match(requirements, profile)
    warnings.extend(report.warnings)

    result = GapAnalysisResult(**to_gap_payload(report))

    # 종합 적합도 등급 (2026-07-21). 상이면 로드맵/대안 없이 진단만, 중·하면 로드맵·대안까지
    # 이어 붙인다(라우팅은 route_after_gap / route_after_roadmap 이 이 값을 읽어 분기한다).
    result.overallScore, result.fitGrade = overall_fit(result.scoreBasis.model_dump())

    if not requirements:
        warnings.append({
            "code": "no_requirements",
            "message": "공고 요구사항이 없어 갭 분석을 수행하지 못했습니다.",
        })
        result.uncertainties.append("공고에서 요구사항을 추출하지 못해 판정할 대상이 없습니다.")
    if report.undecidable_count:
        result.uncertainties.append(
            f"서술형 요구사항 {report.undecidable_count}건은 자동 판정하지 못해 '판정 불가'로 남겼습니다."
        )

    # RAG 조회 산출물을 결과에 반영 (계약의 companyContext/sources 필드 활용).
    # 판정에는 쓰지 않는다 — 기업 맥락은 근거·서술 재료일 뿐이다(rag-team-interface-spec §5).
    result.companyContext = rag.items
    result.sources = rag.sources

    return {
        "status": Status.ANALYZING_GAP,
        "gapAnalysisResult": result.model_dump(),
        "warnings": [{**w, "node": "analyze_gap"} for w in warnings],
        "sources": sources,
        "toolLog": [_log("analyze_gap", "갭 분석 완료(결정론 매칭)", to="plan_roadmap")],
        # 매칭은 LLM 생성이 아니라 계산이므로 '생성 실패' 재시도 개념이 없다.
        **_gen_retry_updates("analyze_gap", state, False),
    }


# ---------------------------------------------------------------------------
# plan_roadmap  (Roadmap Planner, 설계 11장)
# ---------------------------------------------------------------------------
# 폴백 mock 없음 — 이 노드는 LLM 을 호출하지 않는다(항목은 cert_db/project_template_db 에서 온다).
def _cert_to_item(cert: Certification, gap: dict) -> PlannedItem:
    """자격증 → 로드맵 항목. 문구를 지어내지 않고 cert_db 의 정형 데이터를 그대로 쓴다.

    doneCriteria 가 "자격증 취득"이라 **진짜 측정 가능**한 게 이 설계의 핵심 이점이다(§3.6).
    """

    schedule_note = (
        "상시 응시 가능" if cert.alwaysAvailable
        else f"연 {cert.examWindowsPerYear}회 시행 — 시험 일정 확인 후 응시 접수"
    )
    return PlannedItem(
        title=f"{cert.name} 취득",
        goal=f"{cert.name}({cert.issuer}) 취득으로 해당 역량을 공인 자격으로 증명한다",
        tasks=[*cert.subjects, schedule_note],
        doneCriteria=f"{cert.name} 최종 합격(합격증 번호 제시 가능)",
        priority=str(gap.get("severity", "medium")),
        relatedRequirementIds=[str(gap.get("requirementId", ""))],
        estimatedHours=cert.prepHours,
        source="cert",
    )


def _template_to_item(template: ProjectTemplate, gap: dict) -> PlannedItem:
    """프로젝트 과제 → 로드맵 항목. 템플릿의 측정 가능한 doneCriteria 를 그대로 쓴다."""

    return PlannedItem(
        title=template.title,
        goal=template.goal,
        tasks=list(template.tasks),
        doneCriteria=template.doneCriteria,
        priority=str(gap.get("severity", "medium")),
        relatedRequirementIds=[str(gap.get("requirementId", ""))],
        estimatedHours=template.estimatedHours,
        source="project",
    )


def _select_roadmap_items(gaps: list[dict]) -> tuple[list[PlannedItem], list[dict]]:
    """gap 목록 → 학습 항목 후보 (§3.6-②~④). **LLM 없음.**

    각 gap 의 missingSkills 를 자격증(skill_to_cert) → 없으면 프로젝트 과제
    (project_template_db) 순으로 매핑한다. 같은 항목이 여러 gap 에 걸리면 하나로 합치고
    relatedRequirementIds 를 누적한다 — 같은 자격증을 두 번 따게 하면 안 된다.
    """

    mapper = get_skill_to_cert()
    templates = get_project_template_db()
    taxonomy = get_skill_taxonomy()

    by_title: dict[str, PlannedItem] = {}
    warnings: list[dict] = []
    uncovered_skills: list[str] = []

    def _add(item: PlannedItem) -> None:
        existing = by_title.get(item.title)
        if existing is None:
            by_title[item.title] = item
            return
        # 이미 있는 항목이면 요구사항만 누적하고, 우선순위는 더 높은 쪽으로 올린다.
        for req_id in item.relatedRequirementIds:
            if req_id and req_id not in existing.relatedRequirementIds:
                existing.relatedRequirementIds.append(req_id)
        if PRIORITY_RANK.get(item.priority, 1) < PRIORITY_RANK.get(existing.priority, 1):
            existing.priority = item.priority

    for gap in gaps:
        missing = [str(s) for s in (gap.get("missingSkills") or [])]

        # 부족 스킬이 특정되지 않은 gap(= '기재됐으나 근거 없음' 유형) → 근거 보강 과제
        if not missing:
            _add(_template_to_item(templates.fallback(), gap))
            continue

        for skill in missing:
            cert = get_cert_db().easiest(mapper.certs_for(skill))
            if cert:
                _add(_cert_to_item(cert, gap))
                continue

            skill_obj = taxonomy.resolve(skill)
            template = templates.best_for_skill(skill_obj.key if skill_obj else skill)
            if template:
                _add(_template_to_item(template, gap))
            else:
                # 자격증도 과제도 없는 스킬 — 지어내지 않고 정직하게 알린다.
                if skill not in uncovered_skills:
                    uncovered_skills.append(skill)

    if uncovered_skills:
        warnings.append({
            "code": "uncovered_gap_skills",
            "message": (
                f"다음 부족 역량은 대응하는 자격증·프로젝트 과제가 아직 없어 로드맵에 넣지 "
                f"못했습니다: {', '.join(uncovered_skills)}"
            ),
        })
    return list(by_title.values()), warnings


def plan_roadmap(state: GraphState) -> dict[str, Any]:
    """부족 역량 + 기간/시간 제약 → RoadmapResult (설계 11.3 체인 + §3.6).

    **로드맵을 LLM 이 창작하지 않는다.** 무엇을 배울지는 `cert_db`/`project_template_db`
    에서 꺼내고, 순서·기간·시간은 `roadmap_scheduler` 가 계산한다. 이 노드는 LLM 을
    호출하지 않는다 — 문구 다듬기는 `nl_render`(말하기 계층)가 맡는다.
    """

    weeks = state.get("preparationPeriodWeeks", 0)
    weekly = state.get("availableHoursPerWeek", 0)
    gap = state.get("gapAnalysisResult") or {}

    # 1) Constraint Normalize
    start_date = _dt.date.today().isoformat()
    budget_hours = weeks * weekly
    warnings: list[dict] = []

    # 2) 항목 선정 — 자격증 우선, 없으면 프로젝트 과제
    items, select_warnings = _select_roadmap_items(list(gap.get("gaps", [])))
    warnings.extend(select_warnings)

    # 3) 배치 — 우선순위·예산·기간 제약 안에서 결정론 계산
    plan = schedule_roadmap(items, start_date=start_date, total_weeks=weeks, weekly_hours=weekly)

    result = RoadmapResult(
        roadmap=plan.items,
        totalWeeks=weeks,
        weeklyLoadHours=weekly,
        assumptions=list(plan.notes),
    )

    if not gap.get("gaps"):
        warnings.append({
            "code": "no_gaps",
            "message": "부족 역량이 없어 학습 로드맵을 생성하지 않았습니다.",
        })
    elif not plan.items:
        warnings.append({"code": "empty_roadmap", "message": "생성된 로드맵 항목이 없습니다."})
    if plan.dropped:
        warnings.append({
            "code": "refit_to_budget",
            "message": (
                f"가용 예산({budget_hours}h)·기간({weeks}주)에 맞춰 "
                f"{len(plan.dropped)}개 항목 제외: {plan.dropped}"
            ),
        })

    return {
        "status": Status.PLANNING_ROADMAP,
        "roadmapResult": result.model_dump(),
        "warnings": [{**w, "node": "plan_roadmap"} for w in warnings],
        "toolLog": [_log("plan_roadmap", "로드맵 생성 완료(자격증 DB + 결정론 배치)", to="verify_result")],
        # 계산이므로 '생성 실패' 재시도 개념이 없다.
        **_gen_retry_updates("plan_roadmap", state, False),
    }


# ---------------------------------------------------------------------------
# find_alternatives  (Alternative Path Finder, 설계 14장, 2차 우선순위)
# ---------------------------------------------------------------------------
def _build_alternative_query(
    posting: dict, gap: dict, sub_roles: list | None = None
) -> str:
    """설계 14.3-1 Query Build: 공고·gap·하위 직업군 기반 대체 경로 탐색 쿼리.

    sub_roles(career_graph 도출)가 주어지면 '하위/징검다리 직업군' 라벨을 쿼리에 실어
    RAG(search)가 그 직업군들의 실존 공고를 검색하게 한다. (없으면 기존 동작과 동일)
    """

    parts = [posting.get("jobTitle", ""), posting.get("roleCategory", "")]
    parts += [sr.label for sr in (sub_roles or [])]
    parts += posting.get("techStack", [])[:5]
    parts += [g.get("requirementId", "") for g in gap.get("gaps", [])]
    return " ".join(p for p in parts if p).strip()


# 폴백 mock 없음 — 이 노드는 LLM 을 호출하지 않는다(경로는 career_graph/RAG 에서 온다).
def _estimated_gap_size(gaps: list[dict]) -> str:
    """gap 목록 → 갭 크기 한 단어. 가장 심한 severity 를 대표값으로 쓴다."""

    severities = {str(g.get("severity", "low")) for g in gaps}
    if "high" in severities:
        return "high"
    if "medium" in severities:
        return "medium"
    return "low" if gaps else "none"


def _strength_skills(gap: dict) -> list[str]:
    """충족 판정된 요구사항에서 확인된 스킬들 — 어느 경로로 가든 들고 가는 자산."""

    out: list[str] = []
    for strength in gap.get("strengths", []):
        for skill in strength.get("matchedSkills", []):
            if skill not in out:
                out.append(skill)
    return out


def _alternatives_from_rag(
    candidates: list[dict], profile: dict, gap: dict
) -> list[AlternativeJob]:
    """RAG 가 찾아 준 실존 공고 후보 → 대체 경로 (§3.7-⑥).

    각 후보 공고 본문에서 요구 기술을 뽑아 `gap_matcher` 로 **다시 매칭**한다.
    reducedGaps 는 "목표 공고에선 부족했는데 이 자리에선 요구하지 않는 것"으로 **계산**하고,
    matchedStrengths 는 이 자리에서 살릴 수 있는 강점으로 계산한다. LLM 추측이 아니다.
    """

    taxonomy = get_skill_taxonomy()
    matcher = get_gap_matcher()
    target_missing = {
        skill for g in gap.get("gaps", []) for skill in (g.get("missingSkills") or [])
    }

    jobs: list[AlternativeJob] = []
    for candidate in candidates:
        text = str(candidate.get("text", ""))
        skills = taxonomy.find_in_text(text)
        if not skills:
            continue

        # 후보 공고의 요구 기술을 의사 requirement 로 만들어 프로필과 매칭
        pseudo_reqs = [
            {"requirementId": f"alt-{i}", "text": skill, "type": "required"}
            for i, skill in enumerate(skills, start=1)
        ]
        report = matcher.match(pseudo_reqs, profile)
        matched = [s for m in report.matches if m.status == "met" for s in m.matchedSkills]

        # 목표 공고에서 부족했지만 이 자리는 요구하지 않는 역량 = 이 경로로 줄어드는 갭
        reduced = sorted(target_missing - set(skills))

        seniority = str(candidate.get("seniority", ""))
        jobs.append(AlternativeJob(
            type=_alt_type_for(seniority, gap),
            title=str(candidate.get("title") or candidate.get("companyName") or text[:40]),
            companyName=str(candidate.get("companyName", "")),
            matchedStrengths=matched,
            reducedGaps=reduced,
            reason=(
                f"보유 역량 {len(matched)}개를 그대로 살릴 수 있고, "
                f"목표 공고에서 부족했던 {len(reduced)}개 역량을 이 자리는 요구하지 않습니다."
            ),
            sourceJobPostingId=candidate.get("jobPostingId"),
            confidence=float(candidate.get("score", 0.0) or 0.0),
        ))
    return jobs


def _alt_type_for(seniority: str, gap: dict) -> str:
    """후보 공고의 연차 → AlternativeJob.type. 연차 정보가 없으면 유사 직무로 본다."""

    if seniority in ("intern", "junior"):
        return "lower_seniority"
    return "similar_role"


def _alternatives_from_sub_roles(sub_roles: list, gap: dict) -> list[AlternativeJob]:
    """RAG 미연결 폴백 — career_graph 가 도출한 경로 '유형'만 제시한다.

    **회사·공고를 지어내지 않는다.** companyName 은 빈 문자열, sourceJobPostingId 는 None.
    reducedGaps 도 비운다 — 실제 공고 없이는 "이 자리에선 뭐가 덜 필요한지"를 알 수 없고,
    추측해서 채우면 그게 바로 이 노드가 피하려던 허구다.
    """

    strengths = _strength_skills(gap)
    return [
        AlternativeJob(
            type=sr.relation,
            title=sr.label,
            companyName="",
            matchedStrengths=strengths,
            reducedGaps=[],
            reason=(
                f"목표 직무로 가는 징검다리로 '{sr.label}' 경로가 있습니다. "
                f"보유 역량({', '.join(strengths) if strengths else '근거 확인된 역량 없음'})을 "
                f"살리면서 경력을 쌓을 수 있습니다."
            ),
            sourceJobPostingId=None,
            confidence=0.0,  # 실공고 근거가 없으므로 신뢰도를 주장하지 않는다
        )
        for sr in sub_roles
    ]


def find_alternatives(state: GraphState) -> dict[str, Any]:
    """대체 취업 경로 추천 (설계 14.3 체인 + §3.7). **LLM 호출 없음.**

    경로 설계는 `career_graph`(목표 → 하위/징검다리 직군), 실공고는 RAG(`search`),
    매칭은 `gap_matcher` 재사용. RAG 미연결이면 실제 공고를 지어내지 않고 경로
    '유형'만 제안한다.
    """

    posting = state.get("normalizedJobPosting") or {}
    profile = state.get("normalizedUserProfile") or {}
    gap = state.get("gapAnalysisResult") or {}

    warnings: list[dict] = []
    sources: list[dict] = []

    # 1) sub-role derive (career_graph) — 목표 직군 → 도달 가능한 하위/징검다리 직군
    #    roleCategory 가 비어 있으면 직무명에서 다시 분류한다. 파서가 채워 주는 게 정상이지만,
    #    "백엔드 개발자"라고 적힌 공고를 직군 미상이라며 포기하는 건 부실하다 —
    #    role_taxonomy 가 바로 그 분류를 하는 툴이므로 여기서 한 번 더 시도한다.
    role_category = posting.get("roleCategory", "") or get_role_taxonomy().classify_role(
        posting.get("jobTitle", "")
    )
    sub_roles = get_career_graph().derive_sub_roles(role_category, posting.get("seniority", ""))

    # 2) query build  3) candidate search — RAG hook ② (내부 벡터 → 부족 시 웹검색 폴백)
    query = _build_alternative_query(posting, gap, sub_roles)
    rag = get_rag_adapter().search(query)
    warnings.extend(rag.warnings)
    sources.extend(rag.sources)

    # 4~6) 후보 → 매칭 계산 (실공고가 있으면 계산, 없으면 경로 유형만)
    result = AlternativePathResult(sources=rag.sources)
    if rag.items:
        result.alternativeJobs = _alternatives_from_rag(rag.items, profile, gap)

    if not result.alternativeJobs:
        result.alternativeJobs = _alternatives_from_sub_roles(sub_roles, gap)
        result.uncertainties.append(
            "실제 공고 검색(RAG) 미연결 — 경로 유형 제안이며 구체 공고는 미확정입니다."
        )
        if not sub_roles:
            warnings.append({
                "code": "no_alternative_path",
                "message": "직무·연차 정보가 부족해 대체 경로를 도출하지 못했습니다.",
            })

    result.pathComparison = PathComparison(
        directPath={
            "targetJob": posting.get("jobTitle", ""),
            "estimatedGapSize": _estimated_gap_size(list(gap.get("gaps", []))),
        },
        alternativePaths=[
            {"type": j.type, "title": j.title,
             "estimatedGapSize": "low" if j.reducedGaps else "unknown"}
            for j in result.alternativeJobs
        ],
    )

    return {
        "status": Status.FINDING_ALTERNATIVES,
        "alternativeJobs": [j.model_dump() for j in result.alternativeJobs],
        "warnings": [{**w, "node": "find_alternatives"} for w in warnings],
        "sources": sources,
        "toolLog": [_log("find_alternatives", "대체 경로 추천 완료(career_graph + 매칭 계산)",
                         to="verify_result")],
        # 계산이므로 '생성 실패' 재시도 개념이 없다.
        **_gen_retry_updates("find_alternatives", state, False),
    }


# ---------------------------------------------------------------------------
# verify_result  (Result Verifier, 설계 12장)
# ---------------------------------------------------------------------------
# no_evidence 위반이 이 수를 넘으면 표현 완화가 아니라 구조 결함으로 보고 analyze_gap 재시도.
_NO_EVIDENCE_RETRY_THRESHOLD = 3


def verify_result(state: GraphState) -> dict[str, Any]:
    """최종 산출물 검수 (설계 12.3 + §3.8). **LLM 없이 결정적 규칙으로만 검사한다.**

    검사 로직은 `verify_rules` 4종이 소유하고, 이 노드는 순서대로 부르고 결과를 모아
    재시도 여부만 판단한다.
    """

    gap = dict(state.get("gapAnalysisResult") or {})
    roadmap = state.get("roadmapResult") or {}
    profile = state.get("normalizedUserProfile") or {}
    weeks = state.get("preparationPeriodWeeks", 0)

    violations: list[Violation] = []
    warnings: list[dict] = []

    # 1) Schema Validate
    violations.extend(validate_schema(gap, roadmap))

    # 2) Policy Check — 금지 표현(표현 수준 → 완화 후 통과)
    lexicon_violations, lexicon_warnings = check_forbidden_lexicon(gap, roadmap)
    violations.extend(lexicon_violations)
    warnings.extend(lexicon_warnings)

    # 3) Evidence Check — 환각 근거 검출 + sanitize
    gap, evidence_violations, evidence_warnings, no_evidence_count = check_evidence_grounding(
        gap, profile
    )
    violations.extend(evidence_violations)
    warnings.extend(evidence_warnings)

    # 4) Consistency Check — 기간·requirementId 교차 검증
    consistency_violations, consistency_warnings = check_consistency(gap, roadmap, weeks)
    violations.extend(consistency_violations)
    warnings.extend(consistency_warnings)

    # 5) Rewrite Softener / Retry 판단
    structural = [v for v in violations if v.type in ("missing_field", "inconsistent")]
    retry_count = (state.get("retryCount") or {}).get("verify_result", 0)
    retry_signal = RetrySignal()
    if (no_evidence_count >= _NO_EVIDENCE_RETRY_THRESHOLD or structural) and retry_count < MAX_VERIFY_RETRY:
        retry_signal = RetrySignal(required=True, targetAgent="analyze_gap",
                                   reason="근거 환각 과다 또는 구조 결함으로 갭 분석 재시도")

    passed = not structural and no_evidence_count < _NO_EVIDENCE_RETRY_THRESHOLD
    verdict = VerifierResult(passed=passed, violations=violations, retrySignal=retry_signal)

    result: dict[str, Any] = {
        "status": Status.VERIFYING,
        "verification": verdict.model_dump(),
        "warnings": [{**w, "node": "verify_result"} for w in warnings],
        "gapAnalysisResult": gap,  # sanitize 반영
        "toolLog": [_log("verify_result", "검증 완료", to="assemble_output")],
    }
    if retry_signal.required:
        merged = dict(state.get("retryCount") or {})
        merged["verify_result"] = retry_count + 1
        result["retryCount"] = merged
    return result


def route_verification(state: GraphState) -> str:
    """검증 실패 시 원인 노드로 재시도, 통과 시 조립 (설계 13.4 / 16.1).

    재시도 예산(retryCount) 판단은 verify_result 가 이미 반영해 retrySignal 로 확정한다.
    라우터는 그 신호만 따른다(여기서 retryCount 를 다시 검사하면 이중 가드로 첫 재시도가 막힌다).
    """

    verdict = state.get("verification") or {}
    signal = verdict.get("retrySignal") or {}
    if signal.get("required"):
        target = signal.get("targetAgent")
        if target in {"analyze_gap", "plan_roadmap"}:
            return target
    return "assemble_output"


# ---------------------------------------------------------------------------
# assemble_output  (result_assembler, 설계 13.3 / 15.3)
# ---------------------------------------------------------------------------
def assemble_output(state: GraphState) -> dict[str, Any]:
    """최종 결과 조립 (설계 13.3 / 15.3 + §3.9).

    구조 조립은 룰이 하고, **여기서 nl_render(LLM)가 확정된 사실을 사람 말로 옮긴다.**
    파이프라인에서 LLM 이 사용자 대면 문장을 쓰는 유일한 지점이다 — 그리고 그 문장조차
    금지 표현 검사를 통과해야 살아남는다.
    """

    gap = state.get("gapAnalysisResult") or {}
    roadmap = state.get("roadmapResult") or {}
    posting = state.get("normalizedJobPosting") or {}
    follow_ups = state.get("followUpQuestions") or []

    status = "need_more_info" if follow_ups else "completed"

    requirements = list(posting.get("requiredRequirements", [])) + list(
        posting.get("preferredRequirements", [])
    )

    # 정보가 부족해 멈춘 경우엔 요약할 분석 결과가 없다 — 질문이 곧 메시지다.
    summary = ""
    render_warnings: list[dict] = []
    if status == "completed":
        summary, render_warnings = render_summary(gap, roadmap, posting)

    analysis_result = {
        "analysisId": state.get("analysisId", ""),
        "status": status,
        "summary": summary,
        # 종합 적합도 등급/점수 (2026-07-21). 정보 부족(need_more_info)이면 아직 분석 전이라 빈 값.
        "fitGrade": gap.get("fitGrade", "") if status == "completed" else "",
        "overallScore": gap.get("overallScore") if status == "completed" else None,
        "requirements": requirements,
        "strengths": gap.get("strengths", []),
        "gaps": gap.get("gaps", []),
        "roadmap": roadmap.get("roadmap", []),
        "alternativeJobs": state.get("alternativeJobs") or [],
        "followUpQuestions": follow_ups,
        # 비블로킹 — status 와 무관하게 항상 실어 보낸다(분석은 이미 끝났거나 계속 진행됨).
        "profileCompletionQuestions": state.get("profileCompletionQuestions") or [],
        "sources": state.get("sources", []),
        "warnings": [
            *state.get("warnings", []),
            *[{**w, "node": "assemble_output"} for w in render_warnings],
        ],
        "meta": {
            "retriedNodes": [k for k, v in (state.get("retryCount") or {}).items() if v > 0],
            "generatedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            # 설정에서 읽는다 — config.model_version 이 애초에 이 용도로 있는 값이다.
            "modelVersion": get_settings().model_version,
        },
    }
    return {
        "status": Status.COMPLETED if status == "completed" else Status.NEED_INFO,
        "isComplete": True,
        "analysisResult": analysis_result,
        "warnings": [{**w, "node": "assemble_output"} for w in render_warnings],
        "toolLog": [_log("assemble_output", "최종 결과 조립 완료")],
    }
