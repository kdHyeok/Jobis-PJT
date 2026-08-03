"""판정 엔진 산출물 → v2 계약 변환. **이 파일은 판단하지 않는다** (webbridge/adapter.py 와 같은 지위).

점수·충족 여부·목표 상태는 판정 그래프와 application_plan 이 이미 확정한 값이고, 여기서는
그 값을 v2 백엔드가 아는 스키마(JobContext/Evaluation/ChangeProposal)로 옮기기만 한다.
추측이 필요한 자리는 비우거나 예외를 낸다 — 근거 없는 값을 만들지 않는다(AGENTS.md §2-5).

어댑터 표기 규약 (v2 스키마가 요구하지만 엔진이 정하지 않는 값 — 전부 상수, 판정 아님):
  · CREATE 스킬 노드의 level=2, 기회(OPPORTUNITY) 노드의 level=3 — 난이도 판정이 아니라
    "지정해야 하는 필드의 기본 표기"다. 엔진이 수준을 판정하게 되면 그 값으로 바꾼다.
  · rank 는 요건 등장 순서다(정렬 표시용).
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Optional

from jobis_ai.v2bridge.models import (
    AnalysisQuestion,
    AnalysisQuestionOption,
    AnalyzedCompetency,
    AnalyzedRequirement,
    CareerFragmentSuggestion,
    CareerSnapshot,
    ChangeProposal,
    CompetencyProposal,
    Evaluation,
    ExistingNode,
    ExperienceRequirement,
    JobContext,
    ProposedEdge,
    ProposedNode,
    ProposedRequirement,
    SuggestedAction,
    TargetProjectBrief,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 목표 상태 → v2 verdict
# ---------------------------------------------------------------------------
# application_plan 의 판정 코드(룰 산출)를 v2 의 3개 verdict 로 옮긴다.
#   APPLY_WITH_POLISH("정리 후 지원")를 APPLY_NOW 로 두는 근거: 자료 정리는 역량 보강이
#   아니라 표현 정돈이라 "지금 지원 가능" 판정이 유지된다 (STRENGTHEN 은 역량 격차가 전제).
#   MID_TERM_TARGET(대체 불가 조건 충돌)은 "이 공고보다 다른 경로 먼저" — ALTERNATIVE_FIRST.
_VERDICT = {
    "APPLY_NOW": "APPLY_NOW",
    "APPLY_WITH_POLISH": "APPLY_NOW",
    "REINFORCE_FIRST": "STRENGTHEN_THEN_APPLY",
    "MID_TERM_TARGET": "ALTERNATIVE_FIRST",
}


class VerdictUndetermined(Exception):
    """판정 보류(UNDETERMINED)는 v2 의 세 verdict 어디에도 대응하지 않는다.

    모른다 ≠ 아니다(AGENTS.md §2-1) — 보류를 임의의 verdict 로 내보내면 근거 없는 단정이
    백엔드 DB 에 남는다. 호출부가 이 예외를 받아 실패(재시도 가능)로 처리한다.
    """


def verdict_from_plan(decision_status: str) -> str:
    verdict = _VERDICT.get(decision_status or "")
    if verdict is None:
        raise VerdictUndetermined(f"목표 상태 '{decision_status}' 는 verdict 로 옮길 수 없어요")
    return verdict


def build_evaluation(analysis: dict, decision: dict, req_status: list[dict]) -> Evaluation:
    """analysisResult + applicationPlan.decision → Evaluation. 문구는 엔진 산출물만 쓴다."""

    verdict = verdict_from_plan(str(decision.get("status") or ""))
    summary = (analysis.get("summary") or "").strip() or (decision.get("headline") or "").strip()
    if not summary:
        # 요약이 비면 판정 사실로만 조립한다(새 판단·수사 없음).
        grade = analysis.get("fitGrade") or ""
        summary = f"적합도 {grade} 판정" if grade else "판정을 완료했어요"

    reasons = [str(r).strip() for r in (decision.get("reasons") or []) if str(r).strip()]
    if not reasons:
        reasons = [f"미충족: {r.get('text')}" for r in req_status
                   if r.get("status") in ("not_met", "partially_met") and r.get("text")][:5]
    if not reasons:
        reasons = [summary]
    return Evaluation(verdict=verdict, summary=summary, reasons=reasons)


# ---------------------------------------------------------------------------
# 공고 이해 → JobContext
# ---------------------------------------------------------------------------
# 지도의 트랙 가지는 이 10종 중 하나에서만 자란다(백엔드 `posting_path_profiles.primary_track`).
# 크롤링 `roleCategory` 표기의 흔들림을 여기서 흡수한다.
_ROLE_TO_TRACK = {
    "backend": "BACKEND", "server": "BACKEND", "be": "BACKEND",
    "frontend": "FRONTEND", "fe": "FRONTEND", "web": "FRONTEND",
    "fullstack": "FULLSTACK", "full_stack": "FULLSTACK",
    "data": "DATA", "data_engineer": "DATA", "data_analyst": "DATA",
    "ai": "AI", "ml": "AI", "mlops": "AI",
    "devops": "DEVOPS", "infra": "DEVOPS", "sre": "DEVOPS",
    "cloud": "CLOUD", "security": "SECURITY", "game": "GAME",
    "mobile": "MOBILE", "android": "MOBILE", "ios": "MOBILE",
}


def track_from_posting(posting: dict) -> str | None:
    """roleCategory → CareerTrack. **모르면 None** — 짐작해서 채우지 않는다.

    백엔드 SQL 은 트랙이 없으면 `coalesce(..., 'BACKEND')` 로 메우지만, 그건 백엔드가
    자기 기본값을 쓰는 것이고 우리가 BACKEND 라고 **주장**하는 것과 다르다(§2-1 모른다 ≠
    아니다). 못 고른 것은 3단계에서 LLM 이 공고를 읽고 정한다.
    """

    raw = str(posting.get("roleCategory") or "").strip().lower().replace("-", "_")
    return _ROLE_TO_TRACK.get(raw)


def _years(value: Any) -> float | None:
    """파서가 낸 연차 값 → 숫자. 빈 문자열·None·비숫자는 전부 '모름'이다."""

    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def experience_requirement(posting: dict) -> ExperienceRequirement | None:
    """공고 연차 표기 → 경력 관문 재료. 근거 문구나 연차가 없으면 None.

    출처는 **파서가 이미 뽑아 둔 `minYears`/`maxYears`** 다(`graph.nodes.parse_job_posting`).
    크롤링 행용인 `posting_floor_years(experience, …)` 를 부르지 않는다 — 정규화된 공고에는
    `experience` 칸이 없어서(실측: 빈 문자열) 항상 None 이 나왔고, **경력 관문이 통째로
    안 생겼다**(2026-08-03 실 모델 검증). 같은 값을 두 번 세지 않는 것이 원칙인데
    엉뚱한 계산기를 재사용한 것이 원인이다.

    **근거 문구(sourceText)가 없으면 아무것도 내지 않는다.** "경력 요건 없음"이라고 쓰면
    확인 못 한 것을 없다고 단정하는 것이고, 그 위에 신입용 경로가 그려진다.
    """

    evidence = str(posting.get("yearsEvidence") or "").strip()
    if not evidence:
        return None
    minimum = _years(posting.get("minYears"))
    if minimum is None:
        return None
    maximum = _years(posting.get("maxYears"))
    months = max(0, round(minimum * 12))
    return ExperienceRequirement(
        type="REQUIRED" if months > 0 else "NONE",
        minimum_months=months,
        maximum_months=(round(maximum * 12) if maximum is not None
                        and round(maximum * 12) >= months else None),
        source_text=evidence[:1_000],
    )


def build_job_context(posting: dict) -> JobContext:
    """normalizedJobPosting → JobContext. 파싱 결과만 옮기고 없는 필드는 None."""

    return JobContext(
        company_name=posting.get("companyName") or None,
        role_title=posting.get("jobTitle") or posting.get("roleCategory") or None,
        employment_type=posting.get("employmentType") or None,
        experience_text=posting.get("yearsEvidence") or posting.get("seniority") or None,
        primary_track=track_from_posting(posting),
        experience_requirement=experience_requirement(posting),
        parsed_data=dict(posting),
    )


# ---------------------------------------------------------------------------
# 요건 판정 → CompetencyProposal (지도의 재료)
# ---------------------------------------------------------------------------
# 여기는 **결정론만** 쓴다. 분류를 LLM 이 하는 것은 3단계이고, 그때 이 함수가 못 채운
# 자리(taxonomy 밖 요건·트랙 미해결)를 메운다. 지금 단계의 목표는 하나다 —
# `competencyProposal` 이 null 이라서 워커가 매번 FAILED 로 끝나는 것을 멈추는 것.
#
# 앵커는 `skill_taxonomy` 다. canonicalKey 는 `user_competencies` 의 유일키라 같은 기술이
# 공고마다 다른 키를 받으면 사용자 역량이 쪼개진다 — 사전이 아는 기술은 **반드시** 사전 키를
# 쓴다. 사전 밖 표기를 임베딩으로 흡수하는 폴백(`_resolve_by_embedding`)은 GMS 를 타므로
# 지금 꺼져 있다. 그래서 사전 밖 요건은 키를 짓되 `roadmapEligible=false` 로 둔다.

# taxonomy 카테고리 → (stage, domain 고정값 또는 None=주 직무를 따른다).
# 문서 규칙 8·9 를 그대로 옮긴 것이다: 테스트·언어·프레임워크는 **주 직무 레인**에 두고,
# DB·클라우드·CI/CD 는 자기 분야로 간다.
_CATEGORY_TO_STAGE_DOMAIN = {
    "language": ("LANGUAGE", None),
    "framework": ("FRAMEWORK", None),
    "database": ("DATA", "DATA"),
    "data": ("DATA", "DATA"),
    "testing": ("QUALITY", None),
    "devops": ("OPERATIONS", "DEVOPS"),
    "cloud": ("OPERATIONS", "CLOUD"),
    "etc": ("FRAMEWORK", None),
}
# 사전이 모르는 요건이 놓일 자리. 주 직무 레인의 서비스 개발 단계 — 지도에서 눈에 띄되
# 특정 분야를 사칭하지 않는다.
_UNKNOWN_STAGE_DOMAIN = ("FRAMEWORK", None)
# 필수는 실무 수준, 우대는 인지 수준. **자리를 채우는 규칙이지 측정값이 아니다** —
# 공고가 요구하는 실제 수준은 3단계에서 원문을 읽어 정한다.
_LEVEL_BY_RELATION = {"REQUIRED": 3, "PREFERRED": 2}


def _competencies_in(req: dict, fallback_title: str, track: str) -> list[tuple]:
    """요건 하나 → [(title, canonicalKey, stage, domain, kind, roadmapEligible), …].

    **하나가 아니라 목록이다.** "Java/Spring 기반 REST API" 처럼 한 문장이 여러 독립 역량을
    요구하는 것이 보통이고, 그걸 한 노드로 뭉치면 사용자는 Java 만 해도 그 칸이 끝난 줄
    안다. 원문(sourceText)은 공유하되 역량은 나눈다.

    문장에서 기술을 찾는 것은 `find_in_text` 다 — `resolve` 는 기술 **이름**을 받는 함수라
    요건 문장을 그대로 넘기면 언제나 못 찾는다. 둘 다 별칭 사전(정규식)만 쓰므로 GMS 를
    타지 않는다.
    """

    from jobis_ai.skill_taxonomy import get_skill_taxonomy

    # 합성 연차 요건(graph/nodes._seniority_requirement)은 기술이 아니라 경력이다.
    # 백엔드가 이걸 경력 관문 노드로 흡수한다(isCareerGateRequirement).
    if str(req.get("kind") or "") == "seniority":
        return [(fallback_title, "career.experience", "EXPERIENCE", "CAREER",
                 "EXPERIENCE", False)]

    taxonomy = get_skill_taxonomy()
    found = taxonomy.find_in_text(str(req.get("text") or ""))
    if found:
        out = []
        for name in found:
            skill = taxonomy.resolve(name)      # 사전에서 나온 이름이라 반드시 맞는다
            if skill is None:                   # 방어적 — 사전이 바뀌어도 죽지 않는다
                continue
            stage, fixed_domain = _CATEGORY_TO_STAGE_DOMAIN.get(
                skill.category, _UNKNOWN_STAGE_DOMAIN)
            out.append((skill.canonical, f"skill.{skill.key}", stage,
                        fixed_domain or track, "TECHNOLOGY", True))
        if out:
            return out

    # 사전이 모르면 **무엇으로 검증하는지도 모른다.** 검증 못 하는 노드를 지도에 올리면
    # 사용자가 영원히 완료할 수 없는 칸이 된다 → 결과에는 남기되 로드맵에서 뺀다(§2-1).
    key = slug(fallback_title)
    if len(key) < 2:
        return []
    stage, domain = _UNKNOWN_STAGE_DOMAIN
    return [(fallback_title, f"skill.{key}", stage, domain or track, "KNOWLEDGE", False)]


def draft_competencies(
    posting: dict, req_status: list[dict], gaps: list[dict], track: str,
) -> tuple[list[dict], list[AnalyzedRequirement]]:
    """요건 판정 → (역량 초안, 요건 행). **ref 를 매기는 자리는 여기 하나다.**

    초안을 모델이 아니라 dict 로 두는 이유: LLM 분류를 얹기 전 값에는 자리채움이 섞여
    있는데(사전 밖 요건의 stage), 모델로 만들면 그 자리채움이 "검증을 통과한 값"처럼 보인다.
    """

    missing_skills = {g.get("requirementId"): list(g.get("missingSkills") or [])
                      for g in (gaps or [])}
    drafts: list[dict] = []
    requirements: list[AnalyzedRequirement] = []
    by_key: dict[str, str] = {}      # canonicalKey → ref (같은 역량을 두 번 만들지 않는다)
    seen: set[tuple[str, str]] = set()

    dropped: list[str] = []

    for index, req in enumerate(req_status or [], start=1):
        text = " ".join(str(req.get("text") or "").split())
        if not text:
            continue
        relation = "REQUIRED" if (req.get("type") or "required") == "required" else "PREFERRED"
        entries = _competencies_in(req, _skill_title(req, missing_skills), track)
        if not entries:
            # 한글 산문만 있는 요건("원활한 커뮤니케이션") — canonicalKey 는 ascii 라 안정된
            # 키를 만들 수 없고, roadmapEligible=false 로 남겨도 카탈로그·준비도 분모 어디에도
            # 쓰이지 않는다. 그래서 빼되 **몇 건을 뺐는지는 남긴다**(§2-6).
            dropped.append(text[:60])
            continue

        for order, (title, canonical, stage, domain, kind, eligible) in enumerate(entries):
            ref = by_key.get(canonical)
            if ref is None:
                ref = f"req-{index:02d}-{order:02d}" if len(entries) > 1 else f"req-{index:02d}"
                by_key[canonical] = ref
                drafts.append({
                    "ref": ref,
                    "canonicalKey": canonical,      # **LLM 에게 보내지 않는다**
                    "title": title[:160],
                    # 무엇을 갖추면 충족인지는 공고 원문이 정의한다. 한 문장이 여러 역량으로
                    # 갈려도 범위는 같은 문장이다 — 우리가 쪼개 쓰면 원문 근거가 아니게 된다.
                    "sourceText": text[:4_000],
                    "relation": relation,
                    "stage": stage,
                    "domain": domain,
                    "kind": kind,
                    "roadmapEligible": eligible,
                    # 사전이 아는 기술인가 — 모델에게 **어디를 고쳐야 하는지** 알려 준다.
                    "known": eligible,
                })
            if (ref, relation) in seen:
                continue      # 같은 역량·같은 강도는 한 줄만 (계약 검증 대상)
            seen.add((ref, relation))
            requirements.append(AnalyzedRequirement(
                competency_ref=ref,
                relation=relation,
                source_text=text[:4_000],
                confidence=_confidence_of(req),
            ))

    if dropped:
        log.info("[v2bridge] 역량으로 옮기지 못한 요건 %d건 (사전 밖·비ascii): %s",
                 len(dropped), " / ".join(dropped[:5]))
    return drafts, requirements


def build_competency_proposal(
    posting: dict, req_status: list[dict], gaps: list[dict], track: str,
    enrichment: Any = None,
) -> CompetencyProposal | None:
    """요건 판정(+ 선택적 LLM 분류) → CompetencyProposal. 못 만들면 **None**.

    None 이 되는 경우는 하나다 — 로드맵에 올릴 수 있는 역량이 하나도 없어서
    `targetProject` 가 증명할 대상을 못 찾을 때.

    `enrichment` 는 `enrich.PostingEnrichment`(없어도 된다). **덮어쓰는 것은 분류뿐이다** —
    canonicalKey·title·sourceText 는 결정론 값이 이긴다. 키가 흔들리면 지도가 쪼개지고,
    근거 문구는 원문이어야 한다.
    """

    drafts, requirements = draft_competencies(posting, req_status, gaps, track)
    classified = {c.ref: c for c in getattr(enrichment, "competencies", None) or []}
    competencies: list[AnalyzedCompetency] = []
    for draft in drafts:
        got = classified.get(draft["ref"])
        eligible = bool(got.roadmapEligible) if got else draft["roadmapEligible"]
        method = (got.verificationMethod or "").strip() if got else ""
        if eligible and not method:
            # 검증 방법 없이 eligible 만 켜면 계약 위반이다 — 정형 문구로 메운다.
            method = f"{draft['title']} 을(를) 사용한 코드와 실행 결과로 확인한다."
        competencies.append(AnalyzedCompetency(
            ref=draft["ref"],
            canonical_key=draft["canonicalKey"],
            title=draft["title"],
            domain=got.domain if got else draft["domain"],
            kind=got.kind if got else draft["kind"],
            stage=got.stage if got else draft["stage"],
            scope_definition=draft["sourceText"],
            required_level=(got.requiredLevel if got
                            else _LEVEL_BY_RELATION[draft["relation"]]),
            roadmap_eligible=eligible,
            verification_method=method or None,
        ))

    if not competencies or not requirements:
        return None

    provable = [c.ref for c in competencies
                if c.roadmap_eligible
                and any(r.competency_ref == c.ref and r.relation == "REQUIRED"
                        for r in requirements)][:30]
    if not provable:
        return None

    return CompetencyProposal(
        competencies=competencies[:100],
        requirements=requirements[:200],
        target_project=_target_project(posting, competencies, provable, enrichment),
    )


def _target_project(
    posting: dict, competencies: list[AnalyzedCompetency], provable: list[str],
    enrichment: Any,
) -> TargetProjectBrief:
    """PROJECT 노드. LLM 이 읽은 과제가 있으면 그것, 없으면 정형 조립.

    **증명 대상(requiredCompetencyRefs)은 어느 쪽이든 결정론이 정한다.** 무엇을 증명해야
    하는지는 "필수이면서 검증 가능한 역량"이라는 계산이지 창작이 아니고, LLM 이 여기를
    고르면 정성 역량을 끌어와 계약 검증(502)에 걸린다.
    """

    draft = getattr(enrichment, "targetProject", None)
    if draft is not None:
        return TargetProjectBrief(
            title=draft.title,
            objective=draft.objective,
            domain_context=draft.domainContext,
            required_competency_refs=provable,
            deliverables=list(draft.deliverables)[:20],
            acceptance_criteria=list(draft.acceptanceCriteria)[:30],
        )

    # 정형 조립 — 공고 요건을 옮긴 것이지 회사 맞춤 기획이 아니다(LLM 없을 때의 폴백).
    proven = {c.ref: c.title for c in competencies}
    company = str(posting.get("companyName") or "").strip()
    role = str(posting.get("jobTitle") or posting.get("roleCategory") or "").strip()
    label = " ".join(b for b in (company, role) if b) or "이 공고"
    return TargetProjectBrief(
        title=f"{label} 필수 요건 검증 과제"[:200],
        objective=f"{label} 의 필수 요건 {len(provable)}건을 하나의 결과물로 증명한다.",
        domain_context=(str(posting.get("industry") or "").strip()
                        or company or role or "해당 공고의 업무 도메인"),
        required_competency_refs=provable,
        deliverables=["실행 가능한 저장소", "실행·테스트 결과"],
        acceptance_criteria=[f"{proven[ref]} 사용 근거가 코드와 실행 결과로 확인된다."
                             for ref in provable][:30],
    )


def _confidence_of(req: dict) -> float:
    value = req.get(_STATUS_TO_CONFIDENCE_KEY)
    if isinstance(value, (int, float)) and 0 <= value <= 1:
        return float(value)
    # 판정 엔진이 신뢰도를 안 주면 **원문 인용이라는 사실만** 남긴다. 1.0 은 "확실하다"가
    # 아니라 "이 문장이 공고에 있었다"는 뜻이고, 근거 문구는 원문 그대로다.
    return 1.0


# ---------------------------------------------------------------------------
# 요건 판정 → ChangeProposal (그래프 변경안, legacy)
# ---------------------------------------------------------------------------
_ASCII_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#.]{1,}")
_SLUG_ALLOWED = re.compile(r"[^a-z0-9.-]+")

_STATUS_TO_CONFIDENCE_KEY = "confidence"


def slug(text: str) -> str:
    """canonical_key 조각용 슬러그. ascii 로 표현되지 않으면 빈 문자열(위조하지 않는다)."""

    tokens = _ASCII_TOKEN.findall(text or "")
    if not tokens:
        return ""
    joined = "-".join(t.lower() for t in tokens)
    joined = _SLUG_ALLOWED.sub("-", joined).strip("-.")
    return joined[:80]


def _skill_title(req: dict, missing_skills: dict[str, list[str]]) -> str:
    """요건을 대표하는 노드 이름. 부족 스킬(판정 산출) > 요건 원문 순."""

    rid = req.get("requirementId")
    skills = missing_skills.get(rid) or []
    if skills and str(skills[0]).strip():
        return str(skills[0]).strip()[:160]
    return (req.get("text") or "요건")[:160]


def _match_existing(title: str, text: str, nodes: list[ExistingNode]) -> Optional[ExistingNode]:
    """보수적 재사용 매칭 — 이름이 정확히 같거나, 노드 이름이 요건 원문에 그대로 등장할 때만.

    REUSE 는 기존 UUID 를 정확히 지정해야 하므로(그래프 불변 조건) 틀린 매칭이 CREATE 누락보다
    훨씬 나쁘다. 애매하면 CREATE 로 둔다 — 중복은 사용자가 승인 단계에서 거를 수 있다.
    """

    low_title = title.lower().strip()
    low_text = (text or "").lower()
    for node in nodes:
        node_title = node.title.lower().strip()
        if not node_title:
            continue
        if node_title == low_title:
            return node
        if len(node_title) >= 2 and node_title in low_text:
            return node
        if slug(title) and node.canonical_key.split(".")[-1] == slug(title):
            return node
    return None


def build_change_proposal(
    career: CareerSnapshot,
    posting: dict,
    req_status: list[dict],
    gaps: list[dict],
    posting_id: str,
) -> ChangeProposal:
    """요건 판정(requirementStatus) → 노드·간선·요건 변경안.

    구조: 공고를 대표하는 OPPORTUNITY 노드 1개 + 요건별 노드(기존 노드에 맞으면 REUSE,
    아니면 CREATE) + 각 요건 노드 → OPPORTUNITY_PATH 간선. 요건 행(confidence 포함)은
    판정 엔진의 requirementStatus 를 그대로 옮긴다.
    """

    domain = (posting.get("roleCategory") or "GENERAL").upper()[:40] or "GENERAL"
    missing_skills = {g.get("requirementId"): list(g.get("missingSkills") or [])
                      for g in (gaps or [])}

    opp_ref = "opportunity"
    company = posting.get("companyName") or ""
    role = posting.get("jobTitle") or posting.get("roleCategory") or ""
    opp_title = " ".join(b for b in (company, role) if b).strip() or "이 공고"
    opportunity = ProposedNode(
        ref=opp_ref,
        action="CREATE",
        canonical_key=f"opportunity.posting-{str(posting_id).replace('-', '')[:12].lower()}",
        title=f"{opp_title} 지원"[:160],
        subtitle=None,
        domain=domain,
        kind="OPPORTUNITY",
        scope_definition=f"'{opp_title}' 공고의 필수 요건을 근거로 지원할 수 있는 상태",
        level=3,
        rank=0,
        detail={"postingId": str(posting_id)},
    )

    nodes: list[ProposedNode] = [opportunity]
    edges: list[ProposedEdge] = []
    requirements: list[ProposedRequirement] = []
    reused: dict[str, str] = {}          # 기존 노드 UUID → 이미 만든 ref
    created_keys: dict[tuple, str] = {}  # CREATE 정체성 → ref (같은 요건 중복 생성 방지)

    for index, req in enumerate(req_status or [], start=1):
        text = str(req.get("text") or "").strip()
        if not text:
            continue
        title = _skill_title(req, missing_skills)
        existing = _match_existing(title, text, career.nodes)

        if existing is not None:
            ref = reused.get(str(existing.id))
            if ref is None:
                ref = f"req-{index:02d}"
                reused[str(existing.id)] = ref
                nodes.append(ProposedNode(
                    ref=ref,
                    action="REUSE",
                    existing_node_id=existing.id,
                    canonical_key=existing.canonical_key,
                    title=existing.title[:160],
                    domain=existing.domain[:40] or domain,
                    kind=existing.kind if existing.kind in (
                        "FOUNDATION", "SKILL", "PROJECT", "CREDENTIAL", "EXPERIENCE",
                        "OPPORTUNITY", "OPPORTUNITY_CLUSTER") else "SKILL",
                    scope_definition=existing.scope_definition,
                    level=existing.level,
                    rank=index,
                    detail={"sourceText": text},
                ))
                edges.append(ProposedEdge(from_ref=ref, to_ref=opp_ref,
                                          edge_kind="OPPORTUNITY_PATH"))
        else:
            key_slug = slug(title)
            canonical = (f"skill.{key_slug}" if key_slug
                         else f"skill.posting-{str(posting_id).replace('-', '')[:8].lower()}"
                              f".req-{index:02d}")
            identity = (canonical, 2, " ".join(text.lower().split()))
            ref = created_keys.get(identity)
            if ref is None:
                ref = f"req-{index:02d}"
                created_keys[identity] = ref
                nodes.append(ProposedNode(
                    ref=ref,
                    action="CREATE",
                    canonical_key=canonical,
                    title=title,
                    domain=domain,
                    kind="SKILL",
                    scope_definition=text,   # 무엇을 갖추면 충족인지는 공고 원문이 정의한다
                    level=2,
                    rank=index,
                    detail={
                        "sourceText": text,
                        "judgedStatus": req.get("status") or "",
                        "judgedReason": req.get("reason") or "",
                    },
                ))
                edges.append(ProposedEdge(from_ref=ref, to_ref=opp_ref,
                                          edge_kind="OPPORTUNITY_PATH"))

        requirements.append(ProposedRequirement(
            node_ref=ref,
            kind="REQUIRED" if (req.get("type") or "required") == "required" else "PREFERRED",
            source_text=text[:1000] or None,
            confidence=(req.get(_STATUS_TO_CONFIDENCE_KEY)
                        if isinstance(req.get(_STATUS_TO_CONFIDENCE_KEY), (int, float))
                        else None),
        ))

    return ChangeProposal(
        base_graph_version=career.version,
        nodes=nodes[:100],
        edges=edges[:200],
        requirements=requirements[:200],
    )


# ---------------------------------------------------------------------------
# 되묻기 → AnalysisQuestion (선택형)
# ---------------------------------------------------------------------------
_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")


def question_key(engine_question: dict) -> str:
    """엔진 질문의 안정 키. field 가 계약 패턴에 맞으면 그대로, 아니면 질문 텍스트 해시.

    같은 질문이 다음 요청에서 다시 나왔을 때 answers 의 question_key 와 만나야 하므로
    텍스트 기반으로 결정론이어야 한다.
    """

    field = str(engine_question.get("field") or "").strip()
    if _KEY_PATTERN.match(field):
        return field
    text = str(engine_question.get("question") or engine_question.get("text") or "")
    return "q-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def build_question(engine_question: dict) -> Optional[AnalysisQuestion]:
    """엔진 되묻기 → 선택형 질문. **선택지가 없는 질문은 만들지 않는다**(None).

    v2 는 2~4개 선택지를 요구한다. 엔진이 선택지를 주지 않았는데 여기서 지어내면
    존재하지 않는 선택을 사용자에게 강요하게 된다 — 그 경우 호출부(service)가
    "정보 없음으로 진행" 경로를 탄다(엔진의 uncertain 처리에 맡긴다).
    """

    text = str(engine_question.get("question") or engine_question.get("text") or "").strip()
    raw_options = [str(o).strip() for o in (engine_question.get("options") or []) if str(o).strip()]
    if not text or not (2 <= len(raw_options) <= 4):
        return None

    options = []
    used_values: set[str] = set()
    for i, label in enumerate(raw_options, start=1):
        value = slug(label) or f"opt-{i}"
        if value in used_values:
            value = f"{value}-{i}"
        used_values.add(value)
        options.append(AnalysisQuestionOption(
            value=value[:120],
            label=label[:240],
            description=f"'{label[:200]}' 기준으로 분석을 계속해요.",
        ))

    reason = str(engine_question.get("reason") or "").strip() \
        or "이 답에 따라 분석 결과가 달라져요."
    return AnalysisQuestion(key=question_key(engine_question), text=text[:1000],
                            reason=reason[:1000], options=options)


# ---------------------------------------------------------------------------
# 대화 응답 매핑
# ---------------------------------------------------------------------------
# 오케스트레이터가 실행한 에이전트 → v2 intent. 라우팅 사실의 번역이지 재판정이 아니다.
_AGENT_INTENT = {
    "posting_analysis": "POSTING_ANALYSIS",
    "fit_analysis": "POSTING_ANALYSIS",
    "job_recommend": "POSTING_ANALYSIS",
    "roadmap_manager": "ROADMAP_QUESTION",
    "application_plan": "ROADMAP_QUESTION",
    "resume_diagnosis": "PROFILE_DISCOVERY",
    "preference_intake": "PROFILE_DISCOVERY",
    "career_chat": "GENERAL_CAREER",
    "interview_prep": "OTHER",
    "coverletter_draft": "OTHER",
}


def chat_intent(dispatched: list[str]) -> str:
    for agent in dispatched or []:
        intent = _AGENT_INTENT.get(agent)
        if intent:
            return intent
    return "GENERAL_CAREER"


# trace 이벤트 kind → 사용자에게 보일 단계 라벨. **번역이지 재판정이 아니다** — 무엇을
# 보일지는 아래 progress_steps 가 이벤트 종류로만 정하고, 내용은 기록을 옮겨 적는다.
_PROGRESS_LABEL = {
    "planner": "계획 수립",
    "fallback": "대화 전환",
    "dispatch": "실행 계획",
    "consent_gate": "실행 전 확인",
    "observe": "실행 후 재점검",
    "url_intake": "자료 접수",
    "resume_intake": "자료 접수",
    "recall": "이전 대화 검토",
    "delegate": "에이전트 위임",
    "delegate_refused": "위임 거부",
    "llm_usage": "LLM 사용량",
}


class ProgressMapper:
    """trace 이벤트 하나 → 진행 단계 하나(또는 None). **번역이지 재판정이 아니다.**

    턴 종료 타임라인(progress_steps)과 실시간 스트리밍(/v1/chat/stream, D75)이 같은
    매핑을 쓴다 — 상태는 agent_start 시각(소요시간 계산)뿐이라 인스턴스로 든다.
    """

    def __init__(self) -> None:
        self._started: dict[str, int] = {}

    def map(self, ev: dict) -> dict | None:
        from jobis_ai.orchestrator.router import agent_label

        kind = str(ev.get("kind") or "")
        detail = ev.get("detail") or {}
        ms = int(ev.get("elapsedMs") or 0)

        def _step(step: str, label: str, text: str) -> dict:
            return {"step": step, "label": label, "detail": text[:300], "elapsedMs": ms}

        if kind == "planner":
            sel = ", ".join(agent_label(a) for a in (detail.get("selectedAgents") or []))
            return _step("planner", _PROGRESS_LABEL[kind],
                         f"선택: {sel or '(없음)'} · 확신 {float(detail.get('confidence') or 0):.2f}")
        if kind == "fallback":
            return _step("fallback", _PROGRESS_LABEL[kind], "플래너 불가 — 대화형 에이전트가 턴을 받음")
        if kind == "dispatch":
            if detail.get("inserted"):
                ins = detail["inserted"]
                names = ins if isinstance(ins, list) else [ins]
                return _step("dispatch", _PROGRESS_LABEL[kind],
                             ", ".join(agent_label(str(n)) for n in names) + "을(를) 실행 계획에 추가")
            if detail.get("agents") is not None:
                seq = " → ".join(agent_label(a) for a in (detail.get("agents") or []))
                return _step("dispatch", _PROGRESS_LABEL[kind], seq or "(실행할 것 없음)")
            return None
        if kind == "consent_gate":
            return _step("consent_gate", _PROGRESS_LABEL[kind], str(detail.get("ask") or ""))
        if kind in ("url_intake", "resume_intake"):
            return _step(kind, _PROGRESS_LABEL[kind], str(ev.get("label") or ""))
        if kind == "agent_start":
            self._started[str(detail.get("agent") or "")] = ms
            # 시작도 한 단계로 낸다 — 스트리밍에서 "지금 무엇을 하는 중"이 이 이벤트다.
            # 어떤 자료(세션 자산)를 보고 시작하는지 함께 표기한다(D93).
            name = str(detail.get("agent") or "")
            assets = [str(a) for a in (detail.get("sessionAssets") or [])
                      if not str(a).startswith("_")]
            seen = f" · 입력: {', '.join(assets[:6])}" if assets else ""
            return _step(f"start:{name}", agent_label(name), f"실행 중…{seen}")
        if kind == "agent_end":
            name = str(detail.get("agent") or "")
            t0 = self._started.pop(name, None)
            dur = f" · {(ms - t0) / 1000:.1f}초" if t0 is not None else ""
            warn = len(detail.get("warnings") or [])
            # 오케스트레이터에 무엇을 넘겼는지(sessionUpdates 키 = 상태 전이 요청, D93).
            handed = [str(k) for k in (detail.get("sessionUpdates") or [])]
            hand_note = f" · 넘김: {', '.join(handed[:5])}" if handed else ""
            # 캐시 재사용 턴 — 새로 분석한 게 아니라 저장된 분석을 본 것이므로 라벨을
            # "분석 자료 검토"로 구분한다(D83, 사용자 지시: 로그가 실제 일과 일치해야 한다).
            if (detail.get("data") or {}).get("fromCache"):
                return _step(name, "분석 자료 검토",
                             "저장된 공고 정리에서 조회"
                             + (f" · 경고 {warn}건" if warn else "") + dur)
            return _step(name, agent_label(name),
                         "완료" + (f" · 경고 {warn}건" if warn else "") + dur + hand_note)
        if kind == "agent_step":
            # 자기 루프의 스텝 단위(D93) — 어떤 도구를 왜 불렀고 무엇을 관찰했는지.
            name = str(detail.get("agent") or "")
            step_no = detail.get("step")
            action = str(detail.get("action") or "")
            if action == "use_tool":
                obs = str(detail.get("observation") or "").strip()
                text = (f"스텝{step_no} · 도구 {detail.get('tool')} 호출"
                        + (f" — {obs[:80]}" if obs else ""))
            elif action == "reply":
                text = f"스텝{step_no} · 답변 작성"
            elif action == "limit":
                text = "도구 사용 상한 도달 — 지금까지 관찰로 답변 작성"
            else:
                text = "중단(판단 불가)"
            return _step(f"loop:{name}", f"{agent_label(name)} 루프", text)
        if kind == "recall":
            return _step("recall", _PROGRESS_LABEL[kind], str(ev.get("label") or ""))
        if kind == "delegate":
            # 에이전트 간 데이터 이동(D93) — 누가 누구에게 물었고 무슨 데이터를 받았나.
            src = str(detail.get("from") or "")
            target = str(detail.get("target") or "")
            keys = [str(k) for k in (detail.get("dataKeys") or [])]
            got = (f" · 받은 데이터: {', '.join(keys[:5])}" if keys
                   else (f" · 결과 {detail.get('results')}건"
                         if detail.get("results") is not None else ""))
            return _step("delegate", _PROGRESS_LABEL[kind],
                         (f"{src} → {target}" if src else target) + got)
        if kind == "delegate_refused":
            return _step("delegate_refused", _PROGRESS_LABEL[kind],
                         f"{detail.get('target')} — {detail.get('reason')}")
        if kind == "node":
            return _step(f"node:{detail.get('node')}", f"판정 노드 · {detail.get('node')}",
                         f"{detail.get('durationMs')}ms" if detail.get("durationMs") else "")
        if kind == "observe":
            if str(detail.get("rule") or "none") not in ("none", "queue_empty"):
                return _step("observe", _PROGRESS_LABEL[kind], str(detail.get("reason") or ""))
            return None
        if kind == "llm_usage":
            tokens = (f" · 토큰 {detail.get('inputTokens')}→{detail.get('outputTokens')}"
                      if detail.get("inputTokens") is not None else "")
            return _step("llm_usage", _PROGRESS_LABEL[kind], f"LLM 콜 {detail.get('calls')}건{tokens}")
        return None


def progress_steps(events: list[dict]) -> list[dict]:
    """trace 이벤트 → 채팅 UI 의 "진행 과정" 단계 목록 (턴 종료 후 타임라인).

    타임라인에는 start:* 단계를 빼고 완료 단계만 싣는다 — 사후 목록에서 "실행 중…"은
    거짓말이 된다(스트리밍에서만 의미가 있다).
    """

    mapper = ProgressMapper()
    steps = [s for ev in events or [] if (s := mapper.map(ev))]
    return [s for s in steps if not str(s["step"]).startswith("start:")][:60]


# 이 담당들이 돌면 커리어 지도에 보여줄 것이 생긴다. 로드맵을 **만드는** 쪽(roadmap_manager)과
# 지원 경로를 **세우는** 쪽(application_plan) 둘 다 지도 화면의 내용이다.
_MAP_PRODUCERS = ("roadmap_manager", "application_plan")


def chat_actions(
    follow_ups: list[dict], dispatched: list[str] | None = None,
) -> tuple[bool, list[SuggestedAction]]:
    """되묻기가 요구한 자산 + 이번 턴의 산출 → (공고 요청 여부, 제안 행동).

    `OPEN_MAP` 은 **로드맵을 채팅으로 읊지 않기 위한 유일한 레버**다(백엔드 계약). 지도에
    생긴 것을 말로 다시 나열하면 사용자는 같은 내용을 두 번 보고, 지도를 열 이유가 없어진다.
    무엇이 생겼는지는 화면이 보여주고 채팅은 **생겼다는 사실만** 알린다.

    실행 사실(dispatched)로만 정한다 — 답변 문장을 뒤져 "로드맵을 만든 것 같다"고 추측하지
    않는다(그건 재판정이다). 요구된 자산과 마찬가지로 **기록의 번역**이다.
    """

    fields = {str(q.get("field") or "") for q in (follow_ups or [])}
    actions: list[SuggestedAction] = []
    should_request_posting = "job_posting" in fields
    if should_request_posting:
        actions.append(SuggestedAction(action="ATTACH_POSTING", label="공고 첨부하기"))
    if fields & {"resume", "resume_extra"}:
        actions.append(SuggestedAction(action="OPEN_STORAGE", label="커리어 저장소 열기"))
    if any(agent in _MAP_PRODUCERS for agent in (dispatched or [])):
        actions.append(SuggestedAction(action="OPEN_MAP", label="커리어 지도 보기"))
    return should_request_posting, actions[:3]


# ---------------------------------------------------------------------------
# 커리어 스냅샷 → 판정 근거 텍스트
# ---------------------------------------------------------------------------
def career_text(career: CareerSnapshot) -> str:
    """확정된 조각·노드를 이력 원천 텍스트로. webbridge/runner._evidence_text 와 같은 원리 —
    엔진은 텍스트 원천을 받으므로, 백엔드가 보낸 정형 조각을 줄글로 잇는다. 없는 사실을 더하지
    않고 조각의 필드만 옮긴다."""

    lines: list[str] = []
    for frag in career.fragments:
        head = f"[{frag.kind}] {frag.title}".strip()
        body = (frag.description or "").strip()
        lines.append(f"{head}\n{body}".strip())
    for node in career.nodes:
        if (node.progress_status or "").upper() in ("COMPLETED", "VERIFIED", "DONE"):
            scope = (node.scope_definition or "").strip()
            lines.append(f"[보유 역량] {node.title} ({node.domain}, 수준 {node.level})"
                         + (f"\n{scope}" if scope else ""))
    return "\n\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# 정형 프로필 → 커리어 조각 제안
# ---------------------------------------------------------------------------
def _suggest(kind: str, title: str, description: str = "",
             detail: Optional[dict[str, Any]] = None) -> Optional[CareerFragmentSuggestion]:
    title = (title or "").strip()
    if not title:
        return None
    key_slug = slug(title)
    canonical = f"{kind.lower()}.{key_slug}" if key_slug else None
    return CareerFragmentSuggestion(
        kind=kind, title=title[:180], description=(description or "").strip()[:4000],
        canonical_key=canonical, detail=detail or {},
    )


def fragments_from_profile(profile: dict) -> list[CareerFragmentSuggestion]:
    """NormalizedUserProfile → v2 조각 제안. webbridge/_profile_to_fragments 와 같은 옮기기 —
    v2 는 조각 종류가 더 풍부해(EXPERIENCE/EDUCATION/ACHIEVEMENT) 그대로 대응시킨다."""

    out: list[Optional[CareerFragmentSuggestion]] = []

    for s in profile.get("skills") or []:
        out.append(_suggest("SKILL", s.get("name") or "", s.get("level") or ""))

    for p in profile.get("projects") or []:
        bits = [p.get("projectType"), p.get("period"), p.get("summary")]
        out.append(_suggest("PROJECT", p.get("title") or "",
                            " · ".join(b for b in bits if b)))

    for e in profile.get("experiences") or []:
        label = " · ".join(b for b in (e.get("company"), e.get("role")) if b)
        bits = [e.get("employmentType"), e.get("period"), e.get("summary")]
        out.append(_suggest("EXPERIENCE", label, " · ".join(b for b in bits if b)))

    for ed in profile.get("education") or []:
        label = " ".join(b for b in (ed.get("school"), ed.get("major")) if b)
        bits = [ed.get("degree"), ed.get("status"), ed.get("period")]
        out.append(_suggest("EDUCATION", label, " · ".join(b for b in bits if b)))

    for b in profile.get("bootcamp") or []:
        bits = [b.get("organization"), b.get("track"), b.get("period"), b.get("summary")]
        out.append(_suggest("EDUCATION", b.get("name") or "",
                            " · ".join(x for x in bits if x)))

    for c in profile.get("certifications") or []:
        bits = [c.get("status"), c.get("acquiredDate")]
        out.append(_suggest("CREDENTIAL", c.get("name") or "",
                            " · ".join(x for x in bits if x)))

    for lang in profile.get("languages") or []:
        label = " ".join(b for b in (lang.get("name"), lang.get("testName")) if b)
        bits = [lang.get("score"), lang.get("proficiency"), lang.get("testDate")]
        out.append(_suggest("CREDENTIAL", label, " · ".join(x for x in bits if x)))

    for a in profile.get("awards") or []:
        bits = [a.get("organization"), a.get("date"), a.get("description")]
        out.append(_suggest("ACHIEVEMENT", a.get("title") or "",
                            " · ".join(x for x in bits if x)))

    return [f for f in out if f is not None][:100]


def extraction_summary(fragments: list[CareerFragmentSuggestion]) -> str:
    """조각 수 세기만으로 만드는 요약(계약상 필수 필드). 개수는 사실이라 판단이 아니다."""

    counts: dict[str, int] = {}
    for f in fragments:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    labels = {"SKILL": "기술", "PROJECT": "프로젝트", "EXPERIENCE": "경력",
              "EDUCATION": "교육", "CREDENTIAL": "자격·어학", "ACHIEVEMENT": "수상",
              "LINK": "링크"}
    parts = [f"{labels.get(k, k)} {v}건" for k, v in counts.items()]
    return f"원문에서 {', '.join(parts)}을 검토 가능한 조각으로 분리했어요."
