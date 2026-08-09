"""판정 결과 → 웹 리포트(result) 변환.

웹은 DONE.result 를 그대로 analysis_results.result_json 에 저장하고 chat.html 이 렌더한다.
UI 가 실제로 읽는 키는 다음 7개다(static/*.html 전수 확인):
    readiness · decision · routes · roadmap · gaps · alternatives · artifact
(옛 result.json 에 있던 timeline·evidenceSummary 는 지금 UI 가 읽지 않아 만들지 않는다.)

**이 파일은 판정하지 않는다.** 점수·충족 여부·로드맵은 판정 그래프가 이미 확정한 값이고,
여기서는 그 값을 웹이 아는 이름으로 옮기고, 웹에만 있는 개념(지원 경로 카드, 목표 상태 판정)을
확정된 사실로부터 **규칙으로** 파생시킨다. 추측이 필요한 자리는 빈 값으로 남긴다.
"""

from __future__ import annotations

from typing import Any, Optional

# AlternativeJob.type → 대체 공고 카드 배지 문구
_ALT_LABEL = {
    "similar_role": "유사 직무",
    "lower_seniority": "낮은 연차",
    "similar_stack": "유사 스택",
    "stepping_stone": "디딤돌 공고",
}

_GRADE_CLASS = {"상": "good", "중": "mid", "하": "bad"}


def is_hard_constraint(text: str) -> bool:
    """이 요건이 프로젝트·학습으로 대체할 수 없는 조건인가.

    판정 기준은 application_plan 에이전트가 갖는다 — 브릿지가 따로 정의하면 두 곳이 갈린다.
    """

    from jobis_ai.agents.application_plan import is_hard_constraint as judge

    return judge(text)

# 요건 하나가 점수에서 차지하는 비중. 필수를 우대의 2배로 본다(gap_matcher 의 가중 원칙과 동일 방향).
_WEIGHT = {"required": 1.0, "preferred": 0.5}


def to_web_result(state: dict[str, Any]) -> dict[str, Any]:
    """판정 그래프 최종 상태 → 웹 result. 상태에 없는 정보는 만들어내지 않는다."""

    analysis = state.get("analysisResult") or {}
    gap = state.get("gapAnalysisResult") or {}
    roadmap_result = state.get("roadmapResult") or {}

    req_status: list[dict] = list(gap.get("requirementStatus") or [])
    items: list[dict] = list(analysis.get("roadmap") or roadmap_result.get("roadmap") or [])

    deltas = _step_deltas(req_status, items)
    web_roadmap = _roadmap(items, deltas, req_status)
    web_gaps = _gaps(req_status, items)
    readiness = _readiness(analysis, web_gaps, web_roadmap, deltas)
    # 목표 상태·지원 경로는 application_plan 에이전트 산출물을 그대로 쓴다.
    plan = state.get("applicationPlan") or {}
    decision = plan.get("decision") or dict(_UNDETERMINED)
    routes = list(plan.get("routes") or [])
    alt_cards, alt_suggestions = _alternatives(analysis.get("alternativeJobs") or [])

    return {
        "meta": {
            "engine": "jobis-ai",
            "modelVersion": (analysis.get("meta") or {}).get("modelVersion", ""),
            "generatedAt": (analysis.get("meta") or {}).get("generatedAt", ""),
            "confidence": _mean_confidence(req_status),
            "status": analysis.get("status", ""),
        },
        "readiness": readiness,
        "decision": decision,
        "gaps": web_gaps,
        "roadmap": web_roadmap,
        "routes": routes,
        "alternatives": alt_cards,
        "artifact": _artifact(items, roadmap_result),
        # 판정 근거·경고는 UI 가 읽지 않지만 DB 에 함께 남겨 추적할 수 있게 한다.
        "trace": {
            "fitGrade": analysis.get("fitGrade", ""),
            "overallScore": analysis.get("overallScore"),
            "scoreBasis": gap.get("scoreBasis") or {},
            "assumptions": list(roadmap_result.get("assumptions") or []),
            "warnings": list(analysis.get("warnings") or []),
            "sources": list(analysis.get("sources") or []),
            # 출처 공고가 없어 카드로 내지 못한 대체 경로 제안(RAG 미연결 시 여기 쌓인다).
            "alternativeSuggestions": alt_suggestions,
        },
    }


# ---------------------------------------------------------------------------
# 적합도(readiness)
# ---------------------------------------------------------------------------
def _readiness(analysis: dict, gaps: list[dict], roadmap: list[dict], deltas: list[int]) -> dict:
    """현재 점수 · 완주 시 예상 · 한 줄 판정.

    now 는 판정 엔진의 overallScore(0~1)를 100점으로 옮긴 값이다. goal 은 "로드맵이 메우는
    요건 비중"만큼 올라간다고 본다(_step_deltas). 근거가 없어 점수가 없으면 None 으로 남긴다 —
    UI 는 now 가 없으면 '—' 로 표시한다.
    """

    score = analysis.get("overallScore")
    now = round(score * 100) if isinstance(score, (int, float)) else None
    grade = analysis.get("fitGrade") or ""
    top = next((g for g in gaps if g["mark"] != "ok"), None)
    top_gap = top["requirement"] if top else ""

    if now is None:
        judge = "판정 근거가 부족해 등급을 내지 않았어요 — 자료를 더 주시면 다시 볼게요."
    elif top_gap:
        judge = f"적합도 {grade} 등급 · 지금 가장 큰 격차는 “{top_gap}”이에요"
    else:
        judge = f"적합도 {grade} 등급 · 확인된 미충족 요건은 없어요"

    gain = sum(deltas)
    return {
        "now": now,
        # 완주 시 예상. 97 상한은 "완벽 충족" 단정을 피하려는 표시 상한이다.
        "goal": min(97, now + gain) if now is not None else None,
        "judge": judge,
        "judgeClass": _GRADE_CLASS.get(grade, "unknown"),
        "topGap": top_gap,
        "topGapFix": _top_gap_fix(top, roadmap),
        "weekFocus": roadmap[0]["title"] if roadmap else "",
        "summary": analysis.get("summary") or "",
    }


def _top_gap_fix(top: Optional[dict], roadmap: list[dict]) -> str:
    """가장 큰 격차를 메우는 로드맵 스텝을 가리킨다.

    구조적 제약이면 스텝을 가리키지 않는다 — 로드맵으로 닫히는 격차가 아니라서
    "준비 과제 01로 보완"은 사실이 아니다.
    """

    if not top:
        return ""
    # 대체 불가 조건은 로드맵 유무와 무관하게 사실을 먼저 말한다(상 등급이면 로드맵이 아예 없다).
    if top.get("hard"):
        return "준비 과제로 대체 불가 — 조건을 충족할 다른 경로 필요"
    if not roadmap:
        return ""
    rid = top.get("requirementId")
    for item in roadmap:
        if rid and rid in (item.get("requirementIds") or []):
            return f"준비 과제 {item['no']}로 보완 · {item.get('delta', '')}".strip(" ·")
    return ""


def _mean_confidence(req_status: list[dict]) -> Optional[float]:
    """요건 판정 신뢰도의 평균. 판정된 요건이 없으면 None."""

    vals = [r.get("confidence") for r in req_status if isinstance(r.get("confidence"), (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else None


# ---------------------------------------------------------------------------
# 요건 대조(gaps)
# ---------------------------------------------------------------------------
_MARK = {"met": "ok", "not_met": "no", "partially_met": "tri", "uncertain": "tri"}

# 문제부터 보여준다 — UI 리포트는 gaps 앞 3개만 렌더한다(chat.html buildReport).
_MARK_ORDER = {"no": 0, "tri": 1, "ok": 2}


def _gaps(req_status: list[dict], items: list[dict]) -> list[dict]:
    """요건별 충족 판정 → 웹 gaps. requirementStatus 가 원천이다(met 도 함께 실어 보낸다).

    구조적 제약(경력 N년 등)에는 "준비 과제로 보완"이라고 쓰지 않는다 — plan_roadmap 이
    그 요건을 스텝에 묶어 놨더라도 로드맵을 다 해서 채워지는 조건이 아니다.
    """

    covers = _requirement_to_step(items)
    rows = []
    for r in req_status:
        mark = _MARK.get(r.get("status") or "", "tri")
        rid = r.get("requirementId")
        step = covers.get(rid)
        hard = is_hard_constraint(r.get("text") or "")
        if mark == "ok":
            fix = "충족"
        elif hard:
            fix = "준비 과제로 대체할 수 없는 조건 — 중기 목표로 두는 항목"
        elif step:
            fix = f"준비 과제 {step}로 보완"
        else:
            fix = r.get("reason") or "보완 방법을 아직 정하지 못했어요"
        rows.append({
            "requirementId": rid,
            "requirement": r.get("text") or "",
            "mark": mark,
            "type": r.get("type") or "required",
            "hard": hard,
            "evidence": r.get("reason") or "",
            "evidenceRefs": list(r.get("matchedEvidenceIds") or []),
            "fix": fix,
        })
    rows.sort(key=lambda g: (_MARK_ORDER.get(g["mark"], 1), g["type"] != "required"))
    return rows


def _requirement_to_step(items: list[dict]) -> dict[str, str]:
    """requirementId → 그걸 메우는 로드맵 스텝 번호(roadmap 의 no 와 같은 표기)."""

    out: dict[str, str] = {}
    for i, item in enumerate(items, start=1):
        for rid in item.get("relatedRequirementIds") or []:
            out.setdefault(rid, f"{i:02d}")
    return out


# ---------------------------------------------------------------------------
# 로드맵(roadmap)
# ---------------------------------------------------------------------------
def _step_deltas(req_status: list[dict], items: list[dict]) -> list[int]:
    """스텝별 예상 상승폭(+N).

    파생 규칙: 요건 하나가 가진 점수 비중(필수 1.0 / 우대 0.5, 전체 합 = 100점)을 계산해,
    그 스텝이 새로 메우는 **미충족 요건**의 비중만 더한다. 이미 충족인 요건이나 다른 스텝이
    먼저 메우는 요건은 두 번 세지 않는다. 근거 없는 수치를 만들지 않으려는 계산이다.

    구조적 제약(경력 N년·학위 등)은 상승폭에서 뺀다 — 로드맵을 다 해도 그 조건은 채워지지
    않으므로, 포함하면 "포트폴리오 정리로 +21" 처럼 근거 없이 부풀려진 숫자가 나간다.
    """

    weights = {r.get("requirementId"): _WEIGHT.get(r.get("type") or "required", 1.0)
               for r in req_status}
    hard = {r.get("requirementId") for r in req_status
            if is_hard_constraint(r.get("text") or "")}
    unmet = {r.get("requirementId") for r in req_status
             if r.get("status") != "met" and r.get("requirementId") not in hard}
    total_w = sum(weights.values())
    if not total_w or not items:
        return [0] * len(items)

    claimed: set = set()
    deltas: list[int] = []
    for item in items:
        share = 0.0
        for rid in item.get("relatedRequirementIds") or []:
            if rid in unmet and rid not in claimed:
                claimed.add(rid)
                share += weights.get(rid, 0.0)
        deltas.append(round(100 * share / total_w))
    return deltas


def _roadmap(items: list[dict], deltas: list[int], req_status: list[dict]) -> list[dict]:
    """RoadmapItem → 웹 roadmap 스텝.

    status 는 분석 시점 기준이다. 아직 아무것도 시작하지 않았으므로 첫 스텝만 active,
    나머지는 locked(선행 스텝 필요)로 둔다. 진행 상태는 이후 웹이 자체 DB 로 관리한다.
    """

    texts = {r.get("requirementId"): r.get("text") or "" for r in req_status}
    out = []
    for i, item in enumerate(items):
        no = f"{i + 1:02d}"
        rids = list(item.get("relatedRequirementIds") or [])
        period = " ~ ".join(x for x in (item.get("startDate"), item.get("endDate")) if x)
        meta_bits = [b for b in (
            period,
            f"주 {item['estimatedHours']}시간" if item.get("estimatedHours") else "",
            f"우선순위 {item.get('priority')}" if item.get("priority") else "",
        ) if b]
        out.append({
            "no": no,
            "title": item.get("title") or "",
            "status": "active" if i == 0 else "locked",
            "state": (f"진행 예정 · {item.get('startDate') or ''}".strip(" ·") if i == 0
                      else f"잠김 · 선행: 과제 {i:02d}"),
            "delta": f"+{deltas[i]} 예상" if i < len(deltas) and deltas[i] else "",
            "meta": " · ".join(meta_bits),
            "body": item.get("goal") or "",
            "tasks": list(item.get("tasks") or []),
            "doneCriteria": item.get("doneCriteria") or "",
            # 태그는 이 스텝이 겨냥하는 요건 이름 — 임의 키워드를 붙이지 않는다.
            # 대체 불가 조건은 뺀다. 이 스텝을 끝내도 채워지지 않는 요건이라
            # "이 과제가 경력 3년을 겨냥한다"고 표시하면 사실이 아니다.
            "tags": [texts[r] for r in rids
                     if texts.get(r) and not is_hard_constraint(texts[r])][:3],
            "requirementIds": rids,
            "prerequisite": (out[i - 1]["title"] if i else None),
        })
    return out


# ---------------------------------------------------------------------------
# 목표 상태 판정(decision) · 지원 경로(routes)
# ---------------------------------------------------------------------------
# **여기서 만들지 않는다.** 판정과 문구 모두 application_plan 에이전트가 낸다(AI 안에서 근거를
# 갖고 만들어야 추적된다). 이 파일은 그 산출물을 웹이 아는 키 이름으로 옮기기만 한다.
_UNDETERMINED = {
    "status": "UNDETERMINED", "label": "판정 보류", "headline": "",
    "reasons": [], "hardConstraints": [], "nextTarget": "", "recheckCondition": "",
}


# ---------------------------------------------------------------------------
# 대체 공고 · 대표 산출물
# ---------------------------------------------------------------------------
def _alternatives(alt_jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """AlternativeJob → (대체 공고 카드, 카드로 못 낸 제안).

    rawText 는 "이 공고로 재분석" 버튼이 새 분석에 넣는 공고 원문이다(chat.html reanalyze).
    출처 공고가 없으면 카드로 내지 않는다 — 빈 원문으로 재분석이 돌면 버튼이 눌리는 순간
    빈 공고를 분석하게 된다. 대신 제안 자체는 버리지 않고 trace 에 남겨 둔다.
    RAG 가 연결되지 않은 동안은 출처가 없어 카드가 비는 것이 정상이고, UI 는 그때
    "추천할 대체 공고가 없어요"로 표시한다.
    """

    cards, suggestions = [], []
    for i, a in enumerate(alt_jobs):
        source = a.get("sourceJobPostingId") or ""
        row = {
            "id": source or f"alt{i + 1}",
            "label": _ALT_LABEL.get(a.get("type") or "", "관련 공고"),
            "company": a.get("companyName") or "",
            "role": a.get("title") or "",
            "career": "",
            "reason": a.get("reason") or "",
            "rawText": source,
            "matchedStrengths": list(a.get("matchedStrengths") or []),
            "reducedGaps": list(a.get("reducedGaps") or []),
        }
        (cards if source else suggestions).append(row)
    return cards, suggestions


def _artifact(items: list[dict], roadmap_result: dict) -> dict:
    """대표 산출물 — 첫 스텝을 그대로 쓴다 (chat.html 은 title 만 읽는다)."""

    if not items:
        return {"title": ""}
    first = items[0]
    return {
        "title": first.get("title") or "",
        "why": first.get("goal") or "",
        "duration": " ~ ".join(x for x in (first.get("startDate"), first.get("endDate")) if x),
        "outputs": list(first.get("tasks") or []),
        "doneCriteria": first.get("doneCriteria") or "",
        "totalWeeks": roadmap_result.get("totalWeeks") or 0,
    }
