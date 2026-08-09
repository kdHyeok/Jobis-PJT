"""읽기 계층 노드 — 비정형 입력을 정형 필드로 **추출**한다 (AGENTS §1 읽기).

여기서 하는 일은 하나다: 공고 원문 → `NormalizedJobPosting`, 이력서 원문 →
`NormalizedUserProfile`. **판정하지 않는다** — 적합도·심각도·로드맵은 `nodes.py` 소관이고,
`roleCategory`/`seniority` 처럼 판단이 섞이는 필드는 LLM 스키마에서 빼고 룰로 파생한다.

`nodes.py` 에서 갈라져 나왔다. 계층이 파일 경계와 일치해야 "이 판정을 어디에 넣나"가
읽는 사람에게 자명해진다(그전에는 여섯 책임이 한 파일에 있었다).
공개 이름은 `nodes.py` 가 그대로 재수출하므로 호출부(builder·에이전트·평가·테스트)는 바뀌지 않는다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from jobis_ai.contracts.domain import (
    AwardEntry,
    BootcampEntry,
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    NormalizedJobPosting,
    NormalizedUserProfile,
    ProjectEntry,
    Requirement,
    SkillEntry,
)
from jobis_ai.extract import extract_text
from jobis_ai.graph.node_common import (
    _gen_retry_updates,
    _log,
    _mark_generation_failed,
)
from jobis_ai.graph.state import GraphState, Status
from jobis_ai.role_taxonomy import get_role_taxonomy
from jobis_ai.rule_extractor import RuleExtraction, extract_rules
from jobis_ai.skill_taxonomy import get_skill_taxonomy
from jobis_ai.structured import llm_unconfigured, run_structured

# ---------------------------------------------------------------------------
# parse_job_posting  (Job Posting Parser, 설계 8장)
# ---------------------------------------------------------------------------
_ROLE_KEY_MENU = ", ".join(
    f"{key}({get_role_taxonomy().label_of(key)})" for key in get_role_taxonomy().all_role_keys()
)


class _JobPostingRead(BaseModel):
    """파서 2차 LLM 추출 스키마 — **읽기 전용**(설계 §0 ① 읽기 계층).

    `seniority`(연차 사다리 칸)는 여기 **없다** — 그건 판단이라 `role_taxonomy` 룰이 정한다.
    LLM 에게 애초에 그 필드를 주지 않아야 판단을 안 한다(§2-2: 프롬프트로 "하지 마라"라고
    적는 것보다 스키마에서 빼는 게 확실하다).

    **연차(min/maxYears)는 여기 있다 — 읽기지 판단이 아니다(D118).** "공고가 몇 년을
    요구하나"는 비정형 → 정형 추출이고, 정규식은 그 읽기의 조악한 구현이었다: 회사 소개의
    "2025년"·"차세대", "학력무관", 프로젝트 나열 속 "8년 이상"을 요구 연차로 읽은 실측이
    `rule_extractor` 주석에 넷 쌓여 있다. **years → 사다리 칸(seniority)은 그대로 룰이다.**

    **`roleCategory` 도 여기 있다 — 단, 열린 생성이 아니라 닫힌 선택이다(D120).** "이 직무가
    사전의 어느 직군에 가장 가까운가"는 의미 유사도 판단이고, 별칭 사전은 그걸 못 한다:
    사전에 없는 표기가 오면 미상으로 떨어진다(실측 Gno=49638113 — "AI Agent 개발자"가
    `role_unclassified`, 대체 경로 탐색이 막혔다). 별칭을 계속 늘리는 것은 새 직무명이 생길
    때마다 지는 경주다. **사전(선택지)은 여전히 룰이 소유한다** — LLM 은 그 목록에서 고르기만
    하고, 목록 밖 값은 버려진다. `career_graph` 전이 관계와 RAG 쿼리가 이 키를 쓰므로
    없는 키가 들어오면 하류가 조용히 끊긴다.
    """

    # 설명을 비워 두면 약한 모델이 이 칸을 그냥 건너뛴다(gpt-4.1 계열에서 실측: 둘 다 빈 문자열).
    # 구조화 출력에서 필드 설명은 프롬프트보다 강하게 작동한다 — 지우지 말 것.
    jobTitle: str = Field(default="", description=(
        "공고의 직무명. 제목에서 회사명·연차 표기를 걷어낸 순수 직무명만. "
        "예: '[클라우드웨이브] 백엔드 엔지니어 (경력 3년 이상)' → '백엔드 엔지니어'"))
    companyName: str = Field(default="", description=(
        "채용하는 회사 이름. 대괄호·괄호 안에 있어도 뽑는다. "
        "예: '[클라우드웨이브] 백엔드 엔지니어' → '클라우드웨이브'. 원문에 없으면 빈 문자열."))
    roleCategory: str = Field(default="", description=(
        "이 공고의 직무가 **아래 목록 중 어디에 가장 가까운가**. 목록의 키를 그대로 하나만 "
        f"적는다(괄호는 설명이다): {_ROLE_KEY_MENU}. "
        "직무명 표기가 목록과 달라도 하는 일이 같으면 그 키를 고른다"
        "(예: 'AI Agent 개발자' → ml_engineer, '서비스 서버 개발' → backend). "
        "목록 어디에도 해당하지 않으면 빈 문자열 — **목록에 없는 값을 만들지 않는다.**"))
    minYears: int | None = Field(default=None, description=(
        "이 공고가 **지원 자격으로** 요구하는 최소 경력 연차(숫자). 신입/경력무관이면 0. "
        "요구 연차를 적지 않았으면 null — 추측하지 않는다. "
        "회사 소개·프로젝트 이력·설립연도에 적힌 연수는 요구 연차가 아니다."))
    maxYears: int | None = Field(default=None, description=(
        "요구 연차의 **상한**. 범위로 적었을 때만('경력 3~7년' → 7). "
        "'3년 이상'처럼 상한이 없으면 null."))
    yearsEvidence: str = Field(default="", description=(
        "minYears 를 읽어낸 **원문 그대로의 조각**('경력 3년 이상'). 원문에 없는 말을 쓰면 "
        "안 된다 — 이 문자열이 원문에 그대로 없으면 값 전체가 버려진다. 근거가 없으면 빈 문자열."))
    requiredRequirements: list[Requirement] = Field(default_factory=list)
    preferredRequirements: list[Requirement] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list, description=(
        "이 자리가 **무슨 일을 하는가**. '담당업무·주요업무·Responsibilities·What you'll do' "
        "섹션의 항목을 한 줄씩. 여러 축으로 나뉘어 있으면(예: '앱 백엔드' / '공통 플랫폼' / "
        "'크레딧 원장') 축마다 한 줄로, 그 축이 무엇을 만드는지까지 적는다. "
        "**요건(할 줄 알아야 하는 것)이 아니라 업무(하게 될 일)다** — 섞지 않는다. "
        "원문에 담당업무 서술이 없으면 빈 목록."))
    conditions: list[str] = Field(default_factory=list, description=(
        "요건·업무 밖의 **채용 조건**을 '라벨: 값' 한 줄씩. 원문에 적힌 것만: "
        "고용형태(정규직/계약직), 수습 기간, 계약 기간, 근무지, 근무 시간, 급여, 학력, "
        "접수 기간·마감일, 접수 방법, 복리후생. 예: '고용형태: 정규직(수습 3개월)'. "
        "**원문에 없는 항목은 줄을 만들지 않는다** — '미기재'라고 적지 말고 그냥 뺀다."))
    hiringProcess: list[str] = Field(default_factory=list, description=(
        "전형 절차를 순서대로 한 단계씩(예: '서류 전형', '1차 면접(실무)', '2차 면접(임원)'). "
        "원문에 절차 서술이 없으면 빈 목록 — 일반적인 절차를 지어내지 않는다."))
    teamContext: str = Field(default="", description=(
        "이 자리가 속한 **조직·팀**과 협업 상대를 원문 근거로 한두 문장. 팀 이름, 그 팀이 "
        "책임지는 영역, 함께 일하는 조직. 원문에 조직 서술이 없으면 빈 문자열."))
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
- **위 섹션 제약은 requiredRequirements/preferredRequirements 에만 적용된다.** responsibilities·conditions·hiringProcess·teamContext 는 **fullText 전체에서** 읽는다 — 이 항목들은 요건 섹션 밖(제목 근처, 표, 공고 아래쪽)에 흩어져 있다. 끝까지 훑고 나서 채운다.
- responsibilities 와 requiredRequirements 를 섞지 않는다: **하게 될 일**은 responsibilities, **갖고 있어야 하는 것**은 requirements 다. 같은 문장을 양쪽에 넣지 않는다.
- techStack 은 knownTechStack 에 **없는** 기술/언어/도구만. domainKeywords 는 산업·서비스 도메인 키워드(예: 커머스, 핀테크).
- roleCategory 는 **목록에서 고르는 것**이지 지어내는 것이 아니다. 직무명 표기가 목록과 달라도 하는 일이 같으면 그 키를 고르고, 정말 해당이 없으면 빈 문자열로 둔다.
- 연차(minYears/maxYears)는 **지원 자격으로 요구한 것만** 읽는다. 회사 설립연도·연혁("2025년 차세대"), 수행 프로젝트 나열 속 연수, "학력무관"의 무관은 요구 연차가 아니다. 헤더/요약에 적힌 요구 연차가 본문 어딘가의 숫자보다 우선한다. yearsEvidence 에는 그 근거를 **원문 그대로** 옮긴다.
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
    "미명시", "명시되지 않음", "미기재", "기재없음", "기재 없음", "해당없음", "해당 없음",
    "-", "?", "??",
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
    posting.responsibilities = _dedup_keep_order(posting.responsibilities)
    posting.hiringProcess = _dedup_keep_order(posting.hiringProcess)
    # 자리표시자 줄("근무지: 미기재")은 버린다 — 못 찾은 것을 없다고 단정하게 되고, 그건
    # 사용자가 원문에 있는 조건을 놓치는 경로다(§2-1 모른다 ≠ 아니다).
    posting.conditions = [
        line for line in _dedup_keep_order(posting.conditions)
        if _clean_field(line.partition(":")[2] or line)
    ]
    posting.teamContext = _clean_field(posting.teamContext)
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

    **연차만 예외다(D118)** — 정규식은 "어디에 적혀 있나"를 못 봐서 회사 소개·프로젝트
    나열의 숫자를 요구 연차로 읽었다. 대신 LLM 값은 근거 검증을 통과해야 채택한다
    (`yearsEvidence` 가 원문에 그대로 있을 것) — 실패하면 룰 값으로 되돌린다.
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

    # 연차: LLM 이 **읽고**(어디에 적힌 숫자인지 의미로 가른다), 근거 검증을 통과할 때만
    # 채택한다. 실패하면 룰 값으로 되돌린다 — 검증 없이 받으면 §2-5(없는 근거 금지)가 뚫린다.
    evidence = _clean_field(posting.yearsEvidence)
    llm_read_years = posting.minYears is not None and bool(evidence) and evidence in text
    if not llm_read_years:
        if posting.minYears is not None:
            warnings.append({
                "code": "years_evidence_unverified",
                "message": (f"LLM 이 읽은 요구 연차({posting.minYears}년)의 근거"
                            f"'{evidence or '(없음)'}'를 원문에서 찾지 못해 룰 값으로 되돌립니다."),
            })
        posting.minYears = rules.minYears
        posting.maxYears = rules.maxYears
        posting.yearsEvidence = rules.yearsEvidence
    else:
        posting.yearsEvidence = evidence

    # 직군(D120) — 세 단계, 정밀한 것부터:
    #   ① 직무명의 별칭 정확 일치(룰). 사전에 있는 표기면 이게 가장 확실하다.
    #   ② LLM 이 사전 목록에서 고른 값. 표기가 사전에 없을 때 의미로 잇는다.
    #   ③ 본문 빈도(룰). 마지막 수단 — 직무명이 아니라 본문에서 세는 거라 오분류가 쉽다
    #      (담당업무에 "백엔드"가 몇 번 나온다고 백엔드 공고인 것은 아니다). LLM 뒤로 내렸다.
    llm_pick = _clean_field(posting.roleCategory).lower()
    if llm_pick and not roles.is_known_role(llm_pick):
        # 사전 밖 값은 버린다 — career_graph·RAG 가 이 키로 조회하므로 없는 키는 하류를
        # 조용히 끊는다. 버렸다는 사실은 남긴다(§2-6).
        warnings.append({
            "code": "role_pick_off_taxonomy",
            "message": f"LLM 이 사전에 없는 직군 '{llm_pick}' 을 골라 무시합니다",
        })
        llm_pick = ""
    posting.roleCategory = (roles.classify_role(posting.jobTitle, "")
                            or llm_pick
                            or roles.classify_role("", text))
    # 사다리 칸은 연차 숫자를 5칸으로 뭉갠 **손실 요약**이다 — 판정(연차 대 연차)과 표기(원문)는
    # minYears/yearsEvidence 를 우선한다.
    posting.seniority = roles.classify_seniority(posting.jobTitle, text, years=posting.minYears)

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
    elif posting.yearsEvidence:
        posting.uncertainties.append(
            f"요구 연차는 원문 '{posting.yearsEvidence}' 근거로 {posting.seniority} 로 분류했습니다."
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
            "message": "명시적인 자격요건/우대사항 헤더가 없어 공고 전문에서 요구사항을 추출했습니다.",
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

    # 멱등(D84) — 이미 구조화된 프로필이 상태에 있으면 그대로 쓴다. parse_job_posting 과
    # 같은 규약: 화이트보드(세션 profile)의 지식을 진입부가 실어 주면 LLM 재추출이 없다.
    already = state.get("normalizedUserProfile") or {}
    if any(already.get(k) for k in ("skills", "experiences", "projects", "education")):
        return {
            "status": Status.BUILDING_PROFILE,
            "normalizedUserProfile": already,
            "toolLog": [_log("build_user_profile", "이미 구조화된 프로필을 재사용",
                             to="check_sufficiency")],
        }

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
