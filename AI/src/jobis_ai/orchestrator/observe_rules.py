"""관찰 규칙 — 에이전트를 실행한 뒤 **남은 계획을 다시 정한다. 결정론, LLM 없음.**

ReAct 의 관찰→재선택 자리다. 전에는 여기서 경량 LLM(`planner.observe_after`)에게 실행 결과
요약을 주고 `continue/finish/call` 을 받았다. 그 층을 규칙으로 내렸다. 근거는 셋이다:

1. **정보 열등.** 관찰 LLM 의 입력은 요약(reply 앞 300자·dataKeys·warningCodes·producedAssets·
   askedUser)이었다. 발화·세션 자산·대화 이력은 플래너가 이미 다 봤으므로 관찰이 더 가진 것은
   *방금의 실행 결과* 하나뿐인데, 그 결과에서 제어에 쓸 신호는 전부 **열거 가능한 구조화 값**이다
   (등급·need_more_info·생산된 자산·경고 코드). 규칙이 정확히 읽을 수 있는 값을 LLM 이 산문에서
   추측하게 만드는 구조였다 — 이 저장소가 판정 계층에서 이미 거부한 패턴이다.
2. **실측.** 2026-07-28 8턴 계측 + 07-29 실측에서 `call` 은 0건, `finish` 사례는 전부 규칙이
   덮는 범위였다. 관찰이 실행을 바꾼 사례가 없었다.
3. **자기 자리의 위험조차 못 막았다.** 판정이 실패해 `analysis` 가 생기지 않아도 뒤에 예정된
   자소서가 그대로 돌았다(`analysis=None` 위에서 초안 작성 — 2026-07-29 재현). 관찰이 앉아
   있던 자리가 정확히 그 자리였는데, `producedAssets=[]` 로부터 finish 를 추론하는 데
   시스템 무결성을 걸고 있었던 셈이다.

규칙은 셋이다(적용 순서대로). "되묻는 중이라 뒤가 무의미해졌다"는 전제 붕괴의 특수
사례라서 ②에 흡수됐다(아래 `drop_unrunnable` 주석 참고).

  ① 약한 판정 → 생성 단계 교체       (`weak_grade_transition`)
  ② 전제 붕괴 → 그 단계 제외          (`drop_unrunnable`, 전부 빠지면 finish)
  ③ 공고 수집 실패 → 소비 단계 제외   (`drop_posting_consumers` — URL 자산은 존재해서
     ②의 runnable 검사가 못 잡는 구멍, D64)

궤적 계약은 유지한다 — 호출부가 `trace.emit("observe", …)` 로 같은 형태를 남긴다. 관찰이
있었다는 사실과 그 이유는 여전히 사후에 읽을 수 있고, 이제 **왜 그렇게 정했는지가 규칙 이름으로
남는다**(LLM 의 자유 문장이 아니라).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jobis_ai.orchestrator.router import (
    agent_label,
    asset_label,
    runnable_now,
    session_assets,
)

# --- ① 약한 판정 → 생성 단계 교체 ---------------------------------------------------
#
# 이 규칙의 원형은 Agent_Test 프로토타입의 `agent/graph.py::_route_after_tools` 다:
# `analyze_gap` 직후 코드가 level 을 읽어 중/하면 대체직군 검색을 **강제**하고, 상이면 그냥
# 끝낸다. LLM 재량이 아니라 조건엣지다. 우리에게는 대화 수준에 그 대응물이 없었다 — 등급이
# 낮은데 자소서·면접이 예정돼 있으면 끊는 판단을 관찰(LLM)에 맡겨 뒀고, 그 관찰은 실측에서
# 한 번도 발동하지 않았다. 가장 중요한 제품 규칙을 부탁으로 두고 있던 셈이다.

# 이 등급이면 판정을 생성의 근거로 쓸 수 없다고 본다.
# "하" = overallScore < 0.4 (필수 요건 대부분 미충족), "판정불가" = 계산된 카테고리가 하나도
# 없음(`gap_matcher.overall_fit`). 경계의 단일 출처는 gap_matcher 이며 여기서 다시 정하지 않는다.
#
# **"중"은 넣지 않는다.** 0.4~0.7 은 "자소서를 쓸 만한가"가 사람마다 갈리는 구간이고, 갈리는
# 판단을 코드로 못 박는 것은 이 규칙이 피하려는 실수 그 자체다. 규칙으로 내릴 값은 명백한
# 것뿐이다 — 애매한 구간은 사용자가 정한다.
_WEAK_GRADES = ("하", "판정불가")

# 판정 근거의 **강도**에 산출물 가치가 좌우되는 생성 에이전트. 근거가 약하면 이번 턴에
# 돌리지 않는다. 로드맵(roadmap_manager)은 넣지 않는다 — 등급이 낮을 때야말로 필요한 것이고,
# application_plan 도 넣지 않는다(이 규칙이 대신 세우려는 것이다).
_GRADE_DEPENDENT = ("coverletter_draft", "interview_prep")

# 대신 실행할 것 — "지금 목표로 둘지(목표 상태)"와 지원 경로 2~3개를 세운다.
# 프로토타입이 중/하에서 대체직군 검색을 강제한 것과 같은 자리다(판정을 받고 나서 갈 길을 정한다).
_WEAK_GRADE_FALLBACK = "application_plan"

_PROCEED_ANYWAY = "판정을 보고도 그대로 진행하고 싶으시면 다시 말씀해 주세요 — 그때는 바로 해드려요."


@dataclass(frozen=True)
class Observation:
    """관찰 결과 — 남은 계획을 어떻게 할지.

    action  : "continue"(남은 큐를 그대로 실행) | "finish"(이번 턴 종료)
    queue   : 규칙이 보정한 남은 실행 큐
    note    : 사용자에게 나갈 문구. 규칙이 계획을 바꿨으면 **반드시 이유를 말한다** —
              말없이 빼면 사용자는 요청한 것이 왜 안 왔는지 알 수 없다.
    reason  : 궤적용 한 줄 (사용자 비노출)
    rule    : 결정한 규칙 이름. LLM 의 자유 문장 대신 이것이 궤적에 남는다.
    dropped : 규칙이 **빼버린** 단계들. 전에는 note 문장 안에만 남아서 호출부가 "무엇이
              빠졌는지"를 코드로 알 수 없었다 — 규칙은 "뺐다"까지만 하고 "대신 무엇을
              할까"는 아무도 묻지 않았다. 그 자리를 열기 위한 구조화 값이다.
    """

    action: str = "continue"
    queue: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""
    reason: str = ""
    rule: str = "none"
    dropped: tuple[str, ...] = field(default_factory=tuple)


def weak_grade_transition(
    analysis_data: dict, queue: list[str], dispatched: list[str], session: dict
) -> tuple[list[str], str]:
    """판정이 약하면 예정된 생성 단계를 지원 경로 설계로 **교체**한다.

    반환: (새 큐, 사용자에게 알릴 문구). 문구가 비어 있으면 아무것도 바꾸지 않았다는 뜻이다.

    **같은 턴에 판정이 나온 경우에만 적용된다** — 호출부가 `fit_analysis` 가 방금 실행된
    배치에서만 부른다. 그래서 사용자가 등급을 이미 보고 나서 다음 턴에 "그래도 자소서 써줘"
    라고 하면 `fit_analysis` 가 다시 돌지 않으므로 규칙도 걸리지 않는다. 규칙이 사용자를
    가두지 않는 것이 중요하다 — 우리가 막을 것은 *말없이 빈 근거 위에서 도는 것*이고,
    사용자가 판정을 알고 내리는 결정이 아니다.

    미완성 판정(`need_more_info`)은 손대지 않는다 — 그때는 전제 자산 `analysis` 가 승격되지
    않으므로 `drop_unrunnable` 이 뒤 단계를 걸러낸다(규칙 둘의 역할 분담).
    """

    if analysis_data.get("status") != "completed":
        return queue, ""
    grade = str(analysis_data.get("fitGrade") or "").strip()
    if grade not in _WEAK_GRADES:
        return queue, ""

    blocked = [name for name in queue if name in _GRADE_DEPENDENT]
    if not blocked:
        return queue, ""

    new_queue = [name for name in queue if name not in _GRADE_DEPENDENT]
    from jobis_ai.agents import get_agent_registry

    spec = get_agent_registry().get(_WEAK_GRADE_FALLBACK)
    inserted = (
        spec is not None
        and _WEAK_GRADE_FALLBACK not in dispatched
        and _WEAK_GRADE_FALLBACK not in new_queue
        and runnable_now(spec, session_assets(session))
    )
    if inserted:
        new_queue.insert(0, _WEAK_GRADE_FALLBACK)

    blocked_label = " · ".join(agent_label(name) for name in blocked)
    # 에이전트 라벨에 조사를 붙이지 않는다 — 라벨은 늘어나고 조사는 받침에 따라 갈리므로
    # 문구가 조용히 틀린다(실측: "지원 경로 설계**으로**"). 라벨은 문장 끝·중립 위치에만 둔다.
    head = f"적합도가 '{grade}'로 나와서 {blocked_label}은 "
    if inserted:
        note = (head + "잠시 미뤘어요. "
                "먼저 이 공고를 지금 목표로 둘지와 지원 경로부터 정리할게요. " + _PROCEED_ANYWAY)
    else:
        note = head + "이번 턴에 진행하지 않았어요. " + _PROCEED_ANYWAY
    return new_queue, note


# --- ② 전제 붕괴 → 그 단계 제외 ----------------------------------------------------
def _missing_asset(spec: Any, assets: set[str]) -> str:
    """이 에이전트가 지금 못 도는 이유가 되는 결측 자산 하나(라벨용)."""

    for asset in spec.preconditions:
        if asset not in assets:
            return asset
    alternatives = tuple(getattr(spec, "preconditions_any", ()))
    if alternatives and not (set(alternatives) & assets):
        return alternatives[0]
    return ""


def drop_unrunnable(
    queue: list[str], dispatched: list[str], session: dict
) -> tuple[list[str], str]:
    """전제가 무너진 단계를 큐에서 뺀다. 반환: (새 큐, 사용자에게 알릴 문구).

    `validate_plan` 은 턴 **시작**에 "생산자가 성공하면 전제가 충족된다"를 보고 계획을 짠다.
    생산자가 실패하면(판정이 등급을 못 내거나 LLM 호출이 실패하면) 그 가정이 무너지는데,
    실행 루프에는 그것을 다시 확인하는 자리가 없었다. 실제로 재현됐다(2026-07-29):
    `fit_analysis` 가 `analysis` 를 못 만들었는데 `coverletter_draft` 가 그대로 돌아
    **`analysis=None` 위에서 초안을 썼다.**

    큐는 **앞에서부터 시뮬레이션한다.** 뒤 항목의 전제를 앞 항목이 아직 만들 예정일 수 있어서,
    지금 못 돈다는 이유로 바로 빼면 정상 파이프라인을 부순다
    (예: `preference_intake` → `job_recommend`).

    이 규칙이 예전의 "되묻는 중이고 뒤가 지금 못 돌면 멈춘다"를 **흡수한다.** 되묻기는 그
    자체가 이유가 아니었다 — 되물어야 하는 상황에서 뒤 단계가 무의미해지는 것은 되묻는
    에이전트가 뒤 단계의 전제를 만들지 못했기 때문이고, 그건 곧 전제 붕괴다. 게다가 예전
    판정은 "하나라도 돌 수 있으면 계속"이라 **못 도는 항목은 그대로 실행됐다** — 위 결함의
    직접 원인이다.
    """

    from jobis_ai.agents import get_agent_registry

    registry = get_agent_registry()
    assets = session_assets(session)
    kept: list[str] = []
    dropped: list[tuple[str, str]] = []
    for name in queue:
        spec = registry.get(name)
        if spec is None:
            kept.append(name)      # 미등록 이름은 호출부가 따로 알린다
            continue
        if name in dispatched:
            continue               # 이미 돈 것은 큐에서 정리한다
        if runnable_now(spec, assets):
            kept.append(name)
            # 이 단계가 만들 자산은 **뒤 단계의 전제로 인정한다** — 아직 안 돌았을 뿐이다.
            assets |= set(spec.produces)
        else:
            dropped.append((name, _missing_asset(spec, assets)))

    if not dropped:
        return kept, ""

    labels = " · ".join(agent_label(name) for name, _ in dropped)
    lacks = " · ".join(dict.fromkeys(asset_label(a) for _, a in dropped if a))
    note = (f"{lacks}이 만들어지지 않아서 {labels}은 진행하지 못했어요. " if lacks
            else f"필요한 자료가 없어서 {labels}은 진행하지 못했어요. ")
    return kept, note


# --- ③ 공고 수집 실패 → 공고 소비 단계 제외 -----------------------------------------
def drop_posting_consumers(queue: list[str], dispatched: list[str]) -> tuple[list[str], str]:
    """공고 수집(posting_fetch)이 실패하면 공고를 전제로 하는 뒤 단계를 뺀다.

    drop_unrunnable 이 못 잡는 구멍이다 — URL 자산은 세션에 **존재**하므로(주소 형태)
    runnable_now 는 통과하는데, 내용이 없어서 뒤 단계는 빈 원문을 파싱하게 된다.
    수집 실패의 사용자 안내(본문 붙여넣기 요청)는 도구의 render 가 이미 말했으므로,
    여기는 "그래서 무엇을 안 했는지"만 짧게 말한다.
    """

    from jobis_ai.agents import get_agent_registry

    registry = get_agent_registry()
    dropped = [name for name in queue
               if (spec := registry.get(name)) is not None
               and "job_posting" in spec.preconditions and name not in dispatched]
    if not dropped:
        return queue, ""
    kept = [name for name in queue if name not in dropped]
    labels = " · ".join(agent_label(name) for name in dropped)
    return kept, f"공고 내용을 가져오지 못해 {labels}은 이번 턴에 진행하지 못했어요."


# --- 합성 ------------------------------------------------------------------------
def observe(
    batch: list[str], outcomes: dict[str, Any], queue: list[str],
    dispatched: list[str], session: dict,
) -> Observation:
    """방금 실행한 배치를 관찰하고 남은 계획을 정한다. **순수 함수 — LLM 없음.**

    batch    : 방금 실행한 에이전트 이름들(병렬 구간이면 여러 개)
    outcomes : 이름 → AgentResult
    queue    : 남은 실행 예정
    """

    notes: list[str] = []
    rules: list[str] = []
    working = list(queue)
    # 빠진 단계는 **이름으로** 센다. 규칙마다 note 문장을 파싱하면 문구를 고칠 때마다 깨진다.
    # 이미 돈 것(dispatched)은 큐 정리이지 탈락이 아니므로 제외한다.
    before = [n for n in queue if n not in dispatched]

    # ① 약한 판정 → 생성 단계 교체 (fit_analysis 가 방금 돈 배치에서만)
    if "fit_analysis" in batch:
        data = getattr(outcomes.get("fit_analysis"), "data", None) or {}
        working, note = weak_grade_transition(data, working, dispatched, session)
        if note:
            notes.append(note)
            rules.append("weak_grade")

    # ② 전제 붕괴 → 그 단계 제외
    working, note = drop_unrunnable(working, dispatched, session)
    if note:
        notes.append(note)
        rules.append("preconditions_broken")

    # ③ 공고 수집 실패 → 공고 소비 단계 제외 (posting_fetch 가 방금 돈 배치에서만)
    if "posting_fetch" in batch:
        data = getattr(outcomes.get("posting_fetch"), "data", None) or {}
        if data.get("fetched") is False:
            working, note = drop_posting_consumers(working, dispatched)
            if note:
                notes.append(note)
                rules.append("posting_fetch_failed")

    action = "continue" if working else "finish"
    if not rules:
        rules.append("queue_empty" if not working else "none")
    reason = {
        "weak_grade": "판정이 약해 생성 단계를 지원 경로 설계로 교체",
        "preconditions_broken": "전제가 만들어지지 않아 해당 단계를 제외",
        "posting_fetch_failed": "공고 수집이 실패해 공고 소비 단계를 제외",
        "queue_empty": "남은 예정이 없다",
        "none": "예정대로 계속",
    }
    return Observation(
        action=action,
        queue=tuple(working),
        note=" ".join(notes).strip(),
        reason=" / ".join(reason.get(r, r) for r in rules),
        rule="+".join(rules),
        dropped=tuple(n for n in before if n not in working),
    )
