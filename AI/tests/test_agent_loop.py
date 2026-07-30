"""자기 루프 에이전트 하네스 + 첫 적용(interview_prep) 테스트.

하네스 계약:
- 도구는 결정론 파이썬 함수, 에이전트(LLM)는 무엇을 쓸지·어떻게 말할지만 정한다.
- 도구 이름은 Literal 로 제한(환각 구조적 차단), 스텝 상한, 사용자향 문장 금지표현 검증.
- LLM 불가면 None → 호출부가 결정론 폴백(기능이 통째로 죽지 않는다).
"""

from __future__ import annotations

import pytest

from jobis_ai.agents.agent_loop import ToolSpec, run_agent_loop

ANALYSIS = {
    "gaps": [{"requirementId": "r1", "missingSkills": ["Kafka"],
              "reason": "메시징 큐 경험 근거 없음", "severity": "high"}],
    "strengths": [{"matchedSkills": ["React", "TypeScript"],
                   "text": "MindConnect 에서 React+TS 로 마인드맵 UI 구현"}],
}
PROFILE = {
    "skills": [{"name": "React"}, {"name": "TypeScript"}],
    "experiences": [],
    "projects": [{"role": "MindConnect — React 기반 마인드맵 앱 프론트엔드 담당",
                  "period": "2025.03~2025.08"}],
}


def _echo_tool(observation: str = "관찰값") -> ToolSpec:
    return ToolSpec("probe", "테스트용 도구", lambda state, arg: (f"{observation}:{arg}", {}))


def _stub_decisions(monkeypatch, decisions):
    """run_structured 를 정해진 결정 시퀀스로 대체한다(스키마는 하네스가 만든 것 그대로)."""

    seq = iter(decisions)

    def fake(schema, system, user_content, *, node, tier="default"):
        try:
            return schema(**next(seq)), []
        except StopIteration:
            return None, [{"code": "test_exhausted", "message": "결정 시퀀스 소진"}]

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake)


def test_loop_uses_tool_then_replies(monkeypatch):
    """도구를 부르고 그 관찰로 답한다 — 도구 결과가 다음 판단의 입력이 된다."""

    _stub_decisions(monkeypatch, [
        {"action": "use_tool", "tool": "probe", "arg": "React"},
        {"action": "reply", "reply": "React 경험을 더 구체적으로 말씀해 주시겠어요?"},
    ])
    outcome = run_agent_loop(
        goal_system="목표", facts={}, tools={"probe": _echo_tool()},
        state={}, node="test_loop",
    )
    assert outcome is not None
    assert outcome.reply.startswith("React 경험")
    assert outcome.steps == [{"tool": "probe", "arg": "React", "observation": "관찰값:React"}]


def test_loop_rejects_unknown_tool_name():
    """도구 이름은 Literal 로 제한된다 — 미등록 이름은 스키마 단계에서 막힌다."""

    from jobis_ai.agents.agent_loop import _decision_schema

    schema = _decision_schema(("probe",))
    with pytest.raises(Exception):
        schema(action="use_tool", tool="지어낸도구", arg="")


def test_loop_accepts_tool_name_in_action_field(monkeypatch):
    """`action` 자리에 도구 이름을 써도 받는다 — 실측(2026-07-29)으로 턴을 통째로 날린 표기.

    모델이 `action="save_draft"` 를 냈고 Literal 이 막아 3회 재시도 끝에 자소서 턴이 실패했다.
    두 칸(action·tool)에 나눠 담는 건 우리 사정이지 모델의 자연스러운 표기가 아니다.
    막을 것은 **없는 도구**지 표기가 아니므로, 등록된 이름이면 흡수한다.
    """

    _stub_decisions(monkeypatch, [
        {"action": "probe", "arg": "React"},                       # tool 칸 없이 action 에 도구 이름
        {"action": "reply", "reply": "확인했습니다. 이어서 볼까요?"},
    ])
    outcome = run_agent_loop(goal_system="목표", facts={}, tools={"probe": _echo_tool()},
                             state={}, node="test_loop")
    assert outcome.steps == [{"tool": "probe", "arg": "React", "observation": "관찰값:React"}]
    assert outcome.reply.startswith("확인했습니다")


def test_loop_reports_reason_when_llm_unavailable(monkeypatch):
    """LLM 불가면 빈 reply + **이유**를 돌려준다.

    전에는 None 을 돌려줬는데, 그러면 호출부가 폴백을 만들면서 실패 이유를 잃었다
    (실측: 폴백 답변이 나왔는데 warnings 가 비어 원인을 알 수 없었다).
    """

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured",
                        lambda *a, **k: (None, [{"code": "llm_call_failed", "message": "x"}]))
    outcome = run_agent_loop(goal_system="목표", facts={}, tools={"probe": _echo_tool()},
                             state={}, node="test_loop")
    assert outcome.reply == ""
    assert any(w["code"] == "llm_call_failed" for w in outcome.warnings)


def test_loop_asks_rewrite_on_forbidden_expression(monkeypatch):
    """금지표현이면 **한 번 다시 쓰게 한다** — 통째로 폴백시키지 않는다.

    금지표현 목록에는 '반드시'·'무조건' 처럼 코칭 문장에서 자연스럽게 나오는 낱말이 있다.
    한 번 걸렸다고 기능을 폴백시키면 맥락 있는 답변을 매번 버리게 된다(실측: 답변 점검
    턴이 계속 템플릿으로 떨어졌다).
    """

    _stub_decisions(monkeypatch, [
        {"action": "reply", "reply": "이건 반드시 이렇게 답하세요."},          # 금지표현
        {"action": "reply", "reply": "이 부분은 구체적으로 답하시면 좋아요. 어떻게 하셨나요?"},
    ])
    outcome = run_agent_loop(goal_system="목표", facts={}, tools={"probe": _echo_tool()},
                             state={}, node="test_loop")
    assert outcome.reply.startswith("이 부분은 구체적으로")
    assert any(w["code"] == "loop_reply_rewritten" for w in outcome.warnings)
    # 재작성 지시가 관찰로 들어가 다음 판단의 입력이 된다
    assert any(s["tool"] == "(검증)" for s in outcome.steps)


def test_loop_gives_up_after_repeated_forbidden_expression(monkeypatch):
    """계속 금지표현만 쓰면 결국 빈 reply — 호출부가 폴백하고 이유는 남는다."""

    def fake(schema, system, user_content, *, node, tier="default"):
        return schema(action="reply", reply="무조건 됩니다."), []

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake)
    outcome = run_agent_loop(goal_system="목표", facts={}, tools={"probe": _echo_tool()},
                             state={}, node="test_loop", max_steps=2)
    assert outcome.reply == ""
    assert any(w["code"] in ("loop_reply_rewritten", "loop_reply_forbidden_expression")
               for w in outcome.warnings)


def test_loop_stops_at_max_steps(monkeypatch):
    """상한에 걸리면 도구를 더 쓰지 않고 답만 만든다 — 무한 루프 방어."""

    calls = []
    tool = ToolSpec("probe", "테스트용", lambda s, a: (calls.append(a) or "또 관찰", {}))

    # 에이전트가 **끝없이 도구만 부르려 해도** 상한에서 끊기는지 본다. 상한 뒤의 마지막
    # 호출은 하네스가 node="..._final" 로 부르며 답변만 요청한다.
    def fake(schema, system, user_content, *, node, tier="default"):
        if node.endswith("_final"):
            return schema(action="reply", reply="여기까지 확인했어요. 다음으로 무엇을 볼까요?"), []
        return schema(action="use_tool", tool="probe", arg="또"), []

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake)
    outcome = run_agent_loop(goal_system="목표", facts={}, tools={"probe": tool},
                             state={}, node="test_loop", max_steps=3)
    assert outcome is not None
    assert len(calls) == 3, "상한을 넘겨 도구를 부르면 안 된다"
    assert outcome.reply.startswith("여기까지")


def test_loop_limit_reached_leaves_a_trace(monkeypatch):
    """상한 도달은 trace(action="limit")로 남는다 — 도달 **빈도**를 셀 곳이 없었다.

    DEFAULT_MAX_STEPS 주석은 "실제 도달 빈도를 보고 다시 조정한다"인데, 답을 만들면 경고도
    안 남아 빈도를 셀 수 없었다(평가 리포트 §3-2 감점). loop_consistency 가 이 이벤트를 센다.
    """

    from jobis_ai import trace

    def fake(schema, system, user_content, *, node, tier="default"):
        if node.endswith("_final"):
            return schema(action="reply", reply="여기까지 확인했어요."), []
        return schema(action="use_tool", tool="probe", arg="또"), []

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake)
    with trace.recording() as rec:
        run_agent_loop(goal_system="목표", facts={}, tools={"probe": _echo_tool()},
                       state={}, node="test_loop", max_steps=2)
    limits = [e for e in rec.events
              if e["kind"] == "agent_step" and e["detail"].get("action") == "limit"]
    assert len(limits) == 1
    assert limits[0]["detail"]["agent"] == "test_loop"


def test_loop_not_reaching_limit_leaves_no_limit_trace(monkeypatch):
    """상한 전에 스스로 답하면 limit 이벤트가 없다 — 있으면 도달률이 부풀려진다."""

    from jobis_ai import trace

    _stub_decisions(monkeypatch, [
        {"action": "reply", "reply": "바로 답합니다."},
    ])
    with trace.recording() as rec:
        run_agent_loop(goal_system="목표", facts={}, tools={"probe": _echo_tool()},
                       state={}, node="test_loop", max_steps=3)
    assert not any(e["kind"] == "agent_step" and e["detail"].get("action") == "limit"
                   for e in rec.events)


def test_loop_survives_tool_exception(monkeypatch):
    """도구가 터져도 루프는 죽지 않는다 — 실패를 관찰로 넘긴다."""

    def boom(state, arg):
        raise RuntimeError("도구 고장")

    _stub_decisions(monkeypatch, [
        {"action": "use_tool", "tool": "probe", "arg": ""},
        {"action": "reply", "reply": "지금은 근거를 확인하지 못했어요. 다시 시도해볼까요?"},
    ])
    outcome = run_agent_loop(
        goal_system="목표", facts={},
        tools={"probe": ToolSpec("probe", "터지는 도구", boom)},
        state={}, node="test_loop",
    )
    assert outcome is not None
    assert "도구 실행 실패" in outcome.steps[0]["observation"]
    assert any(w["code"] == "loop_tool_failed" for w in outcome.warnings)


# --- interview_prep — 첫 자기 루프 에이전트 ------------------------------------
def test_interview_tools_are_deterministic():
    """도구는 LLM 없이 값을 단정한다 — 소재·근거·답변 점검 전부."""

    from jobis_ai.agents.interview_prep import (
        _tool_check_answer,
        _tool_find_evidence,
        _tool_pick_material,
    )

    state = {"_analysis": ANALYSIS, "_profile": PROFILE, "usedTopics": [],
             "answers": [], "asked": [], "_lastMessage": ""}

    obs, _ = _tool_pick_material(state, "strength")
    assert "React" in obs and "MindConnect" in obs
    assert state["usedTopics"] == ["React, TypeScript"]
    # 같은 소재를 두 번 주지 않는다
    obs2, _ = _tool_pick_material(state, "strength")
    assert "소재가 없습니다" in obs2

    obs3, _ = _tool_find_evidence(state, "React")
    assert "MindConnect" in obs3
    # 없는 근거를 있다고 하지 않는다
    assert "확인되지 않습니다" in _tool_find_evidence(state, "Kafka")[0]

    obs4, _ = _tool_check_answer(state, "React 로 마인드맵 UI 를 3개월간 직접 구현하고 담당했습니다")
    assert "근거 있음" in obs4
    assert state["answers"][-1]["evidence"]["hasNumber"] is True
    assert "근거 부족" in _tool_check_answer(state, "잘 모르겠어요")[0]


def test_interview_multi_turn_state_persists(monkeypatch):
    """1턴: 질문 → 2턴: 답변 점검 + 꼬리 질문. 상태가 턴을 넘어 이어진다."""

    from jobis_ai.agents import interview_prep

    # 1턴 — 소재를 고르고 질문을 기록한 뒤 묻는다
    _stub_decisions(monkeypatch, [
        {"action": "use_tool", "tool": "pick_material", "arg": "strength"},
        {"action": "use_tool", "tool": "record_question",
         "arg": "React 로 무엇을 구현했는지 말씀해 주시겠어요?"},
        {"action": "reply", "reply": "React 로 무엇을 구현했는지 말씀해 주시겠어요?"},
    ])
    session = {"analysis": ANALYSIS, "profile": PROFILE, "last_message": "면접 연습하고 싶어"}
    first = interview_prep.run(session)

    saved = first.sessionUpdates["interview"]
    assert len(saved["asked"]) == 1
    assert saved["usedTopics"] == ["React, TypeScript"]
    assert "_analysis" not in saved, "턴 내부 재료는 세션에 저장하지 않는다"

    # 2턴 — 저장된 상태를 이어받아 답변을 점검하고 파고든다
    _stub_decisions(monkeypatch, [
        {"action": "use_tool", "tool": "check_answer", "arg": ""},
        {"action": "reply", "reply": "기술 언급은 있었지만 본인 역할이 빠졌어요. 어느 부분을 직접 맡으셨나요?"},
    ])
    session2 = {"analysis": ANALYSIS, "profile": PROFILE, "interview": saved,
                "last_message": "React 로 마인드맵 UI 를 만들었어요"}
    second = interview_prep.run(session2)

    state2 = second.sessionUpdates["interview"]
    assert len(state2["answers"]) == 1, "답변이 상태에 쌓여야 한다"
    assert state2["answers"][0]["evidence"]["verdict"] in ("근거 있음", "근거 부족")
    assert len(state2["asked"]) == 1, "이전 턴의 질문 기록이 유지돼야 한다"
    assert "역할" in second.reply


def test_interview_falls_back_without_llm():
    """LLM 불가면 기존 결정론 템플릿으로 — 면접 준비가 통째로 죽지 않는다."""

    from jobis_ai.agents import interview_prep

    result = interview_prep.run({"analysis": ANALYSIS, "profile": PROFILE})
    assert "면접 예상 질문" in result.reply
    assert result.data["questions"], "폴백도 질문을 낸다"


def test_interview_without_analysis_says_so():
    """판정 결과가 없으면 소재가 없다고 정직하게 말한다(질문을 지어내지 않는다)."""

    from jobis_ai.agents import interview_prep

    result = interview_prep.run({})
    assert "적합도 분석" in result.reply
    assert any(w["code"] == "no_interview_basis" for w in result.warnings)


def test_material_selection_prefers_user_projects_and_required(monkeypatch):
    """소재 선택은 합리적 조건으로 정렬된다 — 사용자 프로젝트에 실제로 등장하는 것 우선.

    "회사가 요구하는 스택 중 사용자가 실제로 해본 것" 이 연습 가치가 가장 크다(답할 소재가
    있다). 그다음이 공고 필수 요건·격차 심각도·기재만 되고 근거 없는 것 순이다.
    이 순위는 **결정론 계산**이고 LLM 이 바꿀 수 없다.
    """

    from jobis_ai.agents.interview_prep import _tool_pick_material

    analysis = {
        "requirements": [
            {"requirementId": "r-react", "type": "required"},
            {"requirementId": "r-three", "type": "preferred"},
        ],
        "gaps": [{"requirementId": "r-three", "missingSkills": ["Three.js"],
                  "reason": "3D 경험 없음", "severity": "low"}],
        "strengths": [{"requirementId": "r-react", "matchedSkills": ["React"],
                       "text": "React 로 UI 구현"}],
    }
    state = {"_analysis": analysis, "_profile": PROFILE, "usedTopics": [],
             "asked": [], "answers": [], "_lastMessage": ""}

    obs, _ = _tool_pick_material(state, "")
    # React: 프로젝트 등장(+3) + 필수 요건(+2) = 5  vs  Three.js: 우대(+1) = 1
    assert "React" in obs
    assert "MindConnect" in obs, "질문을 걸 프로젝트를 함께 줘야 한다"
    assert "필수 요건" in obs and "실제로 등장" in obs, "고른 이유를 밝혀야 한다"


def test_material_selection_flags_claimed_but_unproven():
    """기재만 되고 경험 근거가 없는 스킬은 '면접에서 확인될 지점'으로 표시된다."""

    from jobis_ai.agents.interview_prep import _score_material

    profile = {"skills": [{"name": "Kafka"}], "projects": [], "experiences": []}
    score, reasons, landing = _score_material(
        {"topic": "Kafka", "requirementId": "r1", "severity": ""}, profile, {})
    assert landing == ""
    assert any("기재만" in r for r in reasons)
    assert score > 0


def test_interview_fallback_carries_failure_reason(monkeypatch):
    """루프가 실패해 템플릿으로 답할 때도 **왜 그랬는지**가 warnings 에 남는다."""

    from jobis_ai.agents import interview_prep

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured",
                        lambda *a, **k: (None, [{"code": "llm_call_failed", "message": "CLI 실패"}]))
    result = interview_prep.run({"analysis": ANALYSIS, "profile": PROFILE})
    assert "면접 예상 질문" in result.reply          # 템플릿 폴백
    assert any(w["code"] == "llm_call_failed" for w in result.warnings), \
        "폴백이 실패 이유를 삼키면 원인을 찾을 수 없다"


def test_loop_accepts_custom_max_steps(monkeypatch):
    """도구를 많이 써야 하는 에이전트는 상한을 올려 받는다(자소서: 쓰고 점검하고 고친다)."""

    seen: list[int] = []

    def fake(schema, system, user_content, *, node, tier="default"):
        if node.endswith("_final"):
            return schema(action="reply", reply="여기까지입니다."), []
        seen.append(1)
        return schema(action="use_tool", tool="probe", arg=""), []

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake)
    run_agent_loop(goal_system="목표", facts={}, tools={"probe": _echo_tool()},
                   state={}, node="test_loop", max_steps=6)
    assert len(seen) == 6


def test_interview_fallback_preserves_turn_progress(monkeypatch):
    """루프가 실패해도 이번 턴 도구 진행분(점검한 답변)은 보존된다."""

    from jobis_ai.agents import interview_prep

    calls = {"n": 0}

    def fake(schema, system, user_content, *, node, tier="default"):
        calls["n"] += 1
        if calls["n"] == 1:      # 답변 점검까지는 성공
            return schema(action="use_tool", tool="check_answer", arg=""), []
        return None, [{"code": "llm_call_failed", "message": "CLI 실패"}]

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake)
    prior = {"asked": [{"question": "React 경험을 말씀해 주세요", "topic": "React",
                        "type": "strength", "basis": "x"}],
             "answers": [], "usedTopics": ["React"]}
    result = interview_prep.run({
        "analysis": ANALYSIS, "profile": PROFILE, "interview": prior,
        "last_message": "React 로 UI 를 3개월간 직접 구현했어요",
    })
    saved = result.sessionUpdates["interview"]
    assert len(saved["answers"]) == 1, "점검한 답변이 폴백에서 사라지면 안 된다"
    assert saved["asked"] == prior["asked"], "이전 턴 질문 기록도 유지된다"
    assert any(w["code"] == "llm_call_failed" for w in result.warnings)
