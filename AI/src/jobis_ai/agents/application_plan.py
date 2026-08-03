"""application_plan 에이전트 — "이 공고를 지금 목표로 둘지"와 "어떤 경로로 지원할지".

**판정 결과의 소비자.** 세션의 analysis(AnalyzeResponse)만 근거로 삼는다 — 분석에 없는 사실을
새로 만들지 않는다.

두 산출물:
  decision — 목표 상태 판정 (지금 지원 / 정리 후 지원 / 보강 후 지원 / 중기 목표 / 판정 보류)
  routes   — 준비·지원 경로 2~3개 (지금 지원 / 산출물 만들고 지원 / 유사공고 병행)

계층 분리(이 저장소의 규율):
  · 판정(status·effort·hardRisk·무엇이 확인됐나)은 **룰**이 한다 — 전수 검증 가능하고 흔들리지 않는다.
  · 표현(headline·이유 문장·경로 제목·요약)은 **LLM**이 쓴다. 실패·미설정이면 결정론 문구로 폴백한다
    (nl_render 와 같은 하네스). 금지표현 검사를 통과하지 못한 문장은 버린다.

이 산출물이 없으면 웹 리포트의 "목표 상태"·"지원 경로" 칸이 빈다. 예전에는 웹 브릿지가 그 문구를
직접 지어냈는데, 판정과 말이 AI 밖에서 만들어지면 근거를 추적할 수 없어 여기로 옮겼다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import posting_identity
from jobis_ai.gap_matcher import GRADE_HIGH, GRADE_MID
from jobis_ai.structured import run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

# 프로젝트·학습으로 대체할 수 없는 조건(구조적 제약)의 표현. 이런 필수 요건이 미충족이면
# "지금 지원"이 아니라 중기 목표로 판정한다 — 로드맵을 다 해도 그 조건 자체는 채워지지 않는다.
_HARD_CONSTRAINT = re.compile(
    r"(경력\s*\d+\s*년|\d+\s*년\s*(이상|↑)|신입\s*(불가|제외)|"
    r"(학사|석사|박사)\s*(이상|학위)|전공자?\s*(만|한정)|자격증\s*필수|필수\s*자격)"
)

# 점수 구간 → 목표 상태. 경계는 **gap_matcher 에서 가져온다**(D16 = 등급 경계의 단일 출처).
# 전에는 70/40 을 리터럴로 다시 적고 주석으로 "같은 자리에 둔다"고만 해 뒀는데, 그건 값이
# 갈라질 때 아무도 못 잡는 형태다 — 한쪽만 고쳐도 테스트가 통과한다.

_STATUS_LABEL = {
    "APPLY_NOW": "지금 지원",
    "APPLY_WITH_POLISH": "정리 후 지원",
    "REINFORCE_FIRST": "보강 후 지원",
    "MID_TERM_TARGET": "중기 목표",
    "UNDETERMINED": "판정 보류",
}


def is_hard_constraint(text: str) -> bool:
    """이 요건이 프로젝트·학습으로 대체할 수 없는 조건인가. (웹 표시 계층도 이 판정을 쓴다)"""

    return bool(_HARD_CONSTRAINT.search(text or ""))


# ---------------------------------------------------------------------------
# 판정 [룰]
# ---------------------------------------------------------------------------
def _requirement_rows(analysis: dict) -> tuple[list[str], list[str], list[dict]]:
    """(충족 요건, 미충족 요건, 구조적 제약) — 분석 결과의 사실만 추린다."""

    met = [s.get("text", "") for s in (analysis.get("strengths") or []) if s.get("text")]

    texts = {r.get("requirementId"): r.get("text", "") for r in (analysis.get("requirements") or [])}
    types = {r.get("requirementId"): r.get("type", "required") for r in (analysis.get("requirements") or [])}

    unmet: list[str] = []
    hard: list[dict] = []
    for gap in analysis.get("gaps") or []:
        rid = gap.get("requirementId")
        text = texts.get(rid) or rid or ""
        if not text:
            continue
        unmet.append(text)
        if types.get(rid, "required") == "required" and is_hard_constraint(text):
            hard.append({
                "requirement": text,
                "current": gap.get("reason") or "현재 자료에서 확인되지 않음",
                "substitutableByProject": False,
            })
    return met, unmet, hard


def _decide_status(analysis: dict, unmet: list[str], hard: list[dict]) -> str:
    """목표 상태 코드. 순수 룰 — 점수와 요건 판정만 본다."""

    score = analysis.get("overallScore")
    if analysis.get("status") != "completed" or not isinstance(score, (int, float)):
        return "UNDETERMINED"
    if hard:
        return "MID_TERM_TARGET"

    if score >= GRADE_HIGH:
        return "APPLY_NOW" if not unmet else "APPLY_WITH_POLISH"
    if score >= GRADE_MID:
        return "REINFORCE_FIRST"
    return "MID_TERM_TARGET"


# ---------------------------------------------------------------------------
# 표현 [LLM] — 판정은 이미 확정돼 있고, 그것을 사람 말로 옮긴다
# ---------------------------------------------------------------------------
class _RouteWrite(BaseModel):
    """경로 한 장의 문구."""

    id: str = Field(default="", description="as_is | reinforce | parallel 중 입력으로 준 값 그대로.")
    title: str = Field(default="", description="경로 이름 한 줄(10자 내외). 예: '지금 증거로 바로 지원'")
    summary: str = Field(default="", description=(
        "이 경로가 무엇인지 한두 문장. facts 에 있는 회사·요건·산출물만 근거로 쓴다."))
    benefits: list[str] = Field(default_factory=list, description="장점 1~2개, 각 한 구절.")
    risks: list[str] = Field(default_factory=list, description="감수할 점 1~2개, 각 한 구절.")


class _PlanWrite(BaseModel):
    """판정 문구 + 경로 문구. 판정 코드(status)는 입력으로 주며 바꾸지 않는다."""

    headline: str = Field(default="", description=(
        "목표 상태를 한 문장으로. status 가 뜻하는 바를 사용자 말로 옮긴다. "
        "합격 가능성을 단정하지 않는다."))
    reasons: list[str] = Field(default_factory=list, description=(
        "그 판정의 이유 1~3개. facts 의 요건·점수만 근거로 든다. 없는 사실을 만들지 않는다."))
    nextTarget: str = Field(default="", description=(
        "권장하는 첫 목표 한 구절. 중기 목표·보강 후 지원일 때만 채우고, 아니면 빈 문자열."))
    recheckCondition: str = Field(default="", description=(
        "언제 다시 판정해 보면 좋은지 한 구절. 해당 없으면 빈 문자열."))
    routes: list[_RouteWrite] = Field(default_factory=list, description=(
        "입력으로 준 경로 3개 전부에 대해 한 장씩. id 를 바꾸지 않는다."))


_SYSTEM = """너는 취업 준비자에게 "이 공고를 지금 목표로 둘지, 어떤 경로로 지원할지"를 설명하는 조언자다.

- **판정은 이미 끝났다.** facts.status(목표 상태)와 각 경로의 부담(effort)·필수조건 충돌(hardRisk)은
  코드가 확정한 값이다. 너는 그것을 사람 말로 옮기기만 한다 — 판정을 바꾸거나 뒤집지 않는다.
- facts 에 있는 사실(회사·요건·점수·산출물)만 근거로 쓴다. 없는 경험·수치·회사를 만들지 않는다.
- 합격 가능성·적합 여부를 단정하거나 보장하지 않는다.
- 담백하게, 과장 없이. 각 문장은 짧게.

facts 필드:
- company / role: 목표 공고
- status: 목표 상태 코드 (APPLY_NOW=지금 지원 / APPLY_WITH_POLISH=정리 후 지원 /
  REINFORCE_FIRST=보강 후 지원 / MID_TERM_TARGET=중기 목표 / UNDETERMINED=판정 보류)
- score: 100점 환산 적합도 (없으면 null)
- met / unmet: 충족·미충족으로 판정된 요건
- hardConstraints: 프로젝트로 대체 불가능한 미충족 필수 조건
- firstStep: 로드맵 첫 과제(있으면 보강 경로의 산출물)
- routes: 문구를 채워야 할 경로들 (id·effort·hardRisk 는 확정값)"""


def _fallback_plan(facts: dict) -> dict:
    """LLM 미설정·실패 시의 결정론 문구. 사실만 나열하고 꾸미지 않는다."""

    status = facts["status"]
    company = facts.get("company") or "이 공고"
    hard = facts.get("hardConstraints") or []
    unmet = facts.get("unmet") or []
    score = facts.get("score")

    if status == "UNDETERMINED":
        headline = "지금 자료로는 목표 상태를 판정하기 어려워요."
        reasons = ["요건 충족 여부를 계산할 자료가 부족해요."]
    elif status == "MID_TERM_TARGET" and hard:
        headline = "지금 직접 지원보다 중기 목표로 두는 게 현실적이에요."
        reasons = [f"공고가 “{h['requirement']}”를 필수로 명시했어요." for h in hard]
        reasons.append("이 조건은 다른 프로젝트·학습으로 대체되지 않아요.")
    elif status == "APPLY_NOW":
        headline = "확인된 미충족 필수 요건이 없어요 — 지금 지원해도 되는 상태예요."
        reasons = ["필수 요건이 모두 충족으로 판정됐어요."]
    elif status == "APPLY_WITH_POLISH":
        headline = "전반적으로 충분해요 — 부족한 항목만 정리하고 지원하세요."
        reasons = [f"미충족 요건이 {len(unmet)}건 남아 있어요."]
    elif status == "REINFORCE_FIRST":
        headline = "핵심 격차 하나를 메우고 지원하는 게 유리해요."
        reasons = [f"현재 적합도 {score}점 · 미충족 요건 {len(unmet)}건."]
    else:
        headline = "지금은 준비 난도가 높아요 — 중기 목표로 두고 병행하세요."
        reasons = [f"현재 적합도 {score}점으로 미충족 요건이 많아요."]

    first = facts.get("firstStep") or ""
    routes = []
    for route in facts.get("routes") or []:
        rid = route["id"]
        if rid == "as_is":
            routes.append({
                "id": rid, "title": "지금 증거로 바로 지원",
                "summary": f"확인된 강점을 {company} 요건 순서로 정리해 곧바로 지원하는 경로예요.",
                "benefits": ["가장 빠름"], "risks": unmet[:1],
            })
        elif rid == "reinforce":
            routes.append({
                "id": rid,
                "title": "산출물 하나 만들고 지원",
                "summary": (f"“{first}”로 가장 큰 격차를 메운 뒤 지원하는 경로예요." if first
                            else "가장 큰 격차를 메울 산출물을 만든 뒤 지원하는 경로예요."),
                "benefits": ["격차를 정확히 겨냥"], "risks": ["준비 기간이 필요해요"],
            })
        else:
            routes.append({
                "id": rid, "title": "유사 공고 병행하며 실무 축적",
                "summary": "지금 지원 가능한 관련 공고를 함께 보며 부족한 실무를 쌓는 경로예요.",
                "benefits": ["실무 경력을 축적"], "risks": [f"{company}까지 시간이 가장 김"],
            })
    return {"headline": headline, "reasons": [r for r in reasons if r],
            "nextTarget": first if status in ("REINFORCE_FIRST", "MID_TERM_TARGET") else "",
            "recheckCondition": ("첫 준비 과제를 마친 뒤 재분석"
                                 if status == "REINFORCE_FIRST" else
                                 ("해당 필수 조건을 충족한 뒤 재분석" if hard else "")),
            "routes": routes}


def _write_plan(facts: dict) -> tuple[dict, list[dict]]:
    """문구를 LLM 이 쓰고, 실패하면 결정론 문구로 폴백한다."""

    read, warnings = run_structured(
        _PlanWrite, _SYSTEM, json.dumps(facts, ensure_ascii=False), node="application_plan",
    )
    if read is None:
        return _fallback_plan(facts), warnings

    written = read.model_dump()
    # 검사는 **쓰인 모든 문장**을 대상으로 한다. 경로의 장점·감수할 점까지 포함해야 하는데,
    # 실제로 "합격 가능성이 낮습니다"가 risks 에 섞여 들어온 적이 있다(단정 금지 위반).
    text_blob = " ".join([
        written.get("headline") or "",
        written.get("nextTarget") or "",
        written.get("recheckCondition") or "",
        " ".join(written.get("reasons") or []),
        " ".join(
            " ".join([r.get("title") or "", r.get("summary") or ""]
                     + list(r.get("benefits") or []) + list(r.get("risks") or []))
            for r in written.get("routes") or []
        ),
    ])
    if any(expr in text_blob for expr in FORBIDDEN_EXPRESSIONS):
        warnings.append({
            "code": "forbidden_expression",
            "message": "application_plan: 단정 표현이 있어 결정론 문구로 대체했습니다.",
        })
        return _fallback_plan(facts), warnings

    # 빈 칸은 결정론 문구로 메운다 — 화면에 빈 카드가 남지 않게.
    fallback = _fallback_plan(facts)
    if not (written.get("headline") or "").strip():
        written["headline"] = fallback["headline"]
    if not written.get("reasons"):
        written["reasons"] = fallback["reasons"]
    by_id = {r["id"]: r for r in fallback["routes"]}
    merged = []
    for route in written.get("routes") or []:
        base = by_id.get(route.get("id")) or {}
        merged.append({
            "id": route.get("id") or base.get("id", ""),
            "title": (route.get("title") or "").strip() or base.get("title", ""),
            "summary": (route.get("summary") or "").strip() or base.get("summary", ""),
            "benefits": route.get("benefits") or base.get("benefits", []),
            "risks": route.get("risks") or base.get("risks", []),
        })
    seen = {r["id"] for r in merged}
    merged += [r for r in fallback["routes"] if r["id"] not in seen]
    written["routes"] = merged
    return written, warnings


# ---------------------------------------------------------------------------
# 표현 — 결정론 조립 (판정·문구는 위에서 이미 정해졌다)
# ---------------------------------------------------------------------------
_EFFORT_LABEL = {"low": "부담 낮음", "mid": "부담 중간", "high": "부담 높음"}

_MAX_REASONS_IN_REPLY = 3


def render_plan_reply(decision: dict[str, Any], routes: list[dict[str, Any]]) -> str:
    """목표 상태 + 지원 경로를 대화 답변으로 조립한다. **LLM 없음** — 정해진 값을 옮겨 적는다.

    전에는 `f"{label} — {headline}"` 한 줄이었다. 그래서 이 에이전트의 산출물인 **지원 경로
    2~3개가 대화 채널에 아예 도달하지 않았다**(data 로만 나가 웹 리포트 패널에서만 보였다).
    등급이 낮을 때 이 에이전트로 강제 전이하기로 한 뒤(chat.weak_grade_transition) 그 결함이
    정면에 드러났다 — 사용자에게 "무엇을 할지"를 주려고 보낸 자리에서 아무것도 말하지 않았다.

    덤으로 동어반복도 막는다. 실측(2026-07-29): LLM headline 이
    `"이 목표는 중기 목표로 설정되었습니다."` 여서 답변이 `"중기 목표 — 이 목표는 중기 목표로
    설정되었습니다."` 로 나갔다. headline 이 label 을 되풀이하면 label 만 남긴다.
    """

    label = str(decision.get("label") or "").strip()
    headline = str(decision.get("headline") or "").strip()
    head = f"**{label}**" if label else ""
    # headline 이 label 을 되풀이하면 싣지 않는다(같은 말 두 번).
    if headline and not (label and label in headline):
        head = f"{head} — {headline}" if head else headline
    lines = [head] if head else []

    reasons = [str(r).strip() for r in (decision.get("reasons") or []) if str(r).strip()]
    lines += [f"· {r}" for r in reasons[:_MAX_REASONS_IN_REPLY]]

    route_lines = []
    for index, route in enumerate(routes, 1):
        title = str(route.get("title") or "").strip()
        if not title:
            continue
        tags = [_EFFORT_LABEL.get(str(route.get("effort") or ""), "")]
        if route.get("hardRisk"):
            # 프로젝트·학습으로 대체할 수 없는 조건이 걸려 있다 — 감추면 헛수고를 권하게 된다.
            tags.append("필수 조건 충돌")
        tag = " · ".join(t for t in tags if t)
        summary = str(route.get("summary") or "").strip()
        route_lines.append(f"{index}. [{tag}] {title}" + (f" — {summary}" if summary else ""))
        # 유사공고 병행 경로의 실공고(D91) — 경로 제목만 주고 공고를 안 주면 사용자는
        # 어디에 지원하며 병행하라는 것인지 알 수 없다.
        for posting in (route.get("relatedPostings") or [])[:3]:
            name = str(posting.get("companyName") or "").strip()
            title_text = str(posting.get("title") or "").strip()[:40]
            link = f" — {posting['url']}" if posting.get("url") else ""
            route_lines.append(f"   · {name} | {title_text}{link}")
    if route_lines:
        lines.append("지원 경로:")
        lines += route_lines

    recheck = str(decision.get("recheckCondition") or "").strip()
    if recheck:
        lines.append(f"(다시 판정해 볼 시점: {recheck})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 위임 — 유사공고 병행 경로의 실공고 (P1-a/D91)
# ---------------------------------------------------------------------------
def _related_postings(session: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """"유사공고 병행" 경로에 실을 실공고 — job_recommend 를 **읽기 전용**으로 소비한다.

    같은 계산(실공고 추천)을 여기서 다시 만들지 않고 물어본다(확장 계획 P1-a 1안).
    가드는 `call_agent_readonly` 한 곳에 있다 — 전에는 여기서 손으로 재현했는데 `heavy`
    검사와 중첩 위임 차단이 빠져 있었다(그쪽만 §2-7 동의 게이트를 우회할 수 있었다).

    실패해도 경로 문구는 기존 폴백으로 남는다 — 이 위임은 강화지 전제가 아니다.
    """

    from jobis_ai.agents.agent_loop import call_agent_readonly

    call = call_agent_readonly(session, "job_recommend", caller="application_plan")
    if call.refusal:
        # 거부는 trace 에 남았다(분모 기록). 경로 문구는 폴백으로 간다.
        return [], []

    recommendations = list((call.result.data or {}).get("recommendations") or [])[:3]
    related = [{"companyName": str(r.get("companyName") or ""),
                "title": str(r.get("title") or ""),
                "url": str(r.get("url") or "")} for r in recommendations]
    return related, call.warnings


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def run(session: dict[str, Any]) -> AgentResult:
    """세션의 analysis → {decision, routes}. 판정은 룰, 문구는 LLM."""

    analysis: dict = session.get("analysis") or {}
    if not analysis:
        return AgentResult(
            reply="아직 분석 결과가 없어 지원 경로를 세울 수 없어요. 공고와 이력서로 적합도 분석을 먼저 해주세요.",
            warnings=[{"code": "no_analysis",
                       "message": "application_plan: 세션에 analysis 가 없습니다."}],
        )

    met, unmet, hard = _requirement_rows(analysis)
    status = _decide_status(analysis, unmet, hard)
    score = analysis.get("overallScore")
    roadmap = list(analysis.get("roadmap") or [])
    first_step = (roadmap[0].get("title") or "") if roadmap else ""
    _company, _role = posting_identity(session)

    # 경로별 부담·필수조건 충돌은 룰이 정한다(문구가 아니라 판정이다).
    route_specs = [
        {"id": "as_is", "kind": "as_is", "effort": "low", "hardRisk": bool(hard), "deliverable": None},
        {"id": "reinforce", "kind": "reinforce", "effort": "mid", "hardRisk": bool(hard),
         "deliverable": first_step or None},
        {"id": "parallel", "kind": "parallel", "effort": "high", "hardRisk": False, "deliverable": None},
    ]

    facts = {
        # `posting.get("company")` 로 찾던 폴백은 늘 빈 값이었다 — job_posting 자산은
        # {sourceType, value} 원천이라 회사명 칸이 없다. 파싱 결과에서 읽는다.
        "company": _company,
        "role": _role,
        "status": status,
        "score": round(score * 100) if isinstance(score, (int, float)) else None,
        "met": met[:6],
        "unmet": unmet[:6],
        "hardConstraints": hard,
        "firstStep": first_step,
        "routes": [{"id": r["id"], "effort": r["effort"], "hardRisk": r["hardRisk"]} for r in route_specs],
    }
    written, warnings = _write_plan(facts)

    decision = {
        "status": status,
        "label": _STATUS_LABEL.get(status, status),
        "headline": written["headline"],
        "reasons": written["reasons"],
        "hardConstraints": hard,
        "nextTarget": written.get("nextTarget") or "",
        "recheckCondition": written.get("recheckCondition") or "",
    }
    # 유사공고 병행 경로의 실공고 — job_recommend 읽기 전용 위임(P1-a/D91).
    related, delegate_warnings = _related_postings(session)
    warnings.extend(delegate_warnings)

    written_routes = {r["id"]: r for r in written.get("routes") or []}
    routes = []
    for spec in route_specs:
        text = written_routes.get(spec["id"], {})
        routes.append({
            **spec,
            "title": text.get("title", ""),
            "summary": text.get("summary", ""),
            "benefits": text.get("benefits", []),
            "risks": text.get("risks", []),
            "confirmed": met[:3],
            "missing": unmet[:3],
            "relatedPostings": related if spec["id"] == "parallel" else [],
        })

    plan = {"decision": decision, "routes": routes}
    return AgentResult(
        reply=render_plan_reply(decision, routes),
        data={"applicationPlan": plan},
        warnings=warnings,
        sessionUpdates={"application_plan": plan},
    )
