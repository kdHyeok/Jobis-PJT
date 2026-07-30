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
import re
from typing import Any, Optional

from jobis_ai.v2bridge.models import (
    AnalysisQuestion,
    AnalysisQuestionOption,
    CareerFragmentSuggestion,
    CareerSnapshot,
    ChangeProposal,
    Evaluation,
    ExistingNode,
    JobContext,
    ProposedEdge,
    ProposedNode,
    ProposedRequirement,
    SuggestedAction,
)

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
def build_job_context(posting: dict) -> JobContext:
    """normalizedJobPosting → JobContext. 파싱 결과만 옮기고 없는 필드는 None."""

    return JobContext(
        company_name=posting.get("companyName") or None,
        role_title=posting.get("jobTitle") or posting.get("roleCategory") or None,
        employment_type=posting.get("employmentType") or None,
        experience_text=posting.get("yearsEvidence") or posting.get("seniority") or None,
        parsed_data=dict(posting),
    )


# ---------------------------------------------------------------------------
# 요건 판정 → ChangeProposal (그래프 변경안)
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


def chat_actions(follow_ups: list[dict]) -> tuple[bool, list[SuggestedAction]]:
    """되묻기가 요구한 자산 → (공고 요청 여부, 제안 행동). 요구된 것만 옮긴다."""

    fields = {str(q.get("field") or "") for q in (follow_ups or [])}
    actions: list[SuggestedAction] = []
    should_request_posting = "job_posting" in fields
    if should_request_posting:
        actions.append(SuggestedAction(action="ATTACH_POSTING", label="공고 첨부하기"))
    if fields & {"resume", "resume_extra"}:
        actions.append(SuggestedAction(action="OPEN_STORAGE", label="커리어 저장소 열기"))
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
