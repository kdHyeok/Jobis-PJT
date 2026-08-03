"""에이전트 간 통신 — 자기 루프 에이전트가 다른 담당에게 직접 물어본다 (평가 문서 §2-2).

지금까지 에이전트가 서로에게 요청할 통로는 없었다(공유는 세션 blackboard 뿐). 자기 루프가
생기면서 "이건 저쪽이 이미 계산한다"는 상황이 실제로 생겼다 — 자소서가 쓸 근거가 빈약할 때
무엇이 왜 빈약한지는 이력서 진단이 이미 세는 일이다.

여기서 못 박는 계약(전부 **가드**다 — 통로를 열되 좁게 연다):
- 화이트리스트에 선언한 상대만. 등록돼 있어도 선언 안 했으면 못 부른다.
- heavy(수십 초 파이프라인)는 금지 — 동의 게이트를 에이전트가 우회하면 안 된다.
- 전제 자산이 없으면 실행하지 않고 그 사실을 관찰로 돌려준다.
- 위임 안에서 또 위임 금지(재귀 폭주 방어).
- **읽기 전용** — 상대의 sessionUpdates 는 적용하지 않는다(상태 전이는 오케스트레이터만).
- 상대의 경고를 삼키지 않는다.
"""

from __future__ import annotations

from jobis_ai.agents import AgentResult
from jobis_ai.agents.agent_loop import (
    TOOL_WARNINGS_KEY,
    ToolSpec,
    call_agent_readonly,
    delegate_tool,
    run_agent_loop,
)

SESSION = {
    "profile": {"skills": [{"name": "Python"}], "projects": [], "experiences": [],
                "certifications": [], "awards": [], "education": [], "languages": []},
}


def _state(session: dict | None = None) -> dict:
    return {"_session": session if session is not None else dict(SESSION)}


def test_delegate_calls_declared_agent_and_returns_its_answer():
    tool = delegate_tool(("resume_diagnosis",))
    observation, data = tool.run(_state(), "resume_diagnosis")
    assert "resume_diagnosis 의 답" in observation
    assert "Python" in observation or "이력서" in observation
    assert TOOL_WARNINGS_KEY not in data or data[TOOL_WARNINGS_KEY]


def test_delegate_refuses_undeclared_target():
    """등록된 에이전트라도 **선언하지 않았으면** 못 부른다 — 통로는 좁게 연다."""

    tool = delegate_tool(("resume_diagnosis",))
    observation, _ = tool.run(_state(), "career_chat")
    assert "물어볼 수 없습니다" in observation
    assert "resume_diagnosis" in observation, "부를 수 있는 상대를 알려줘야 스스로 고친다"


def test_delegate_refuses_heavy_agent():
    """heavy 는 금지 — 에이전트가 말없이 수십 초 파이프라인을 시작하면 동의 게이트가 무의미해진다."""

    tool = delegate_tool(("fit_analysis",))
    session = {**SESSION, "resume": {"sourceType": "text", "value": "x"},
               "job_posting": {"sourceType": "text", "value": "y"}}
    observation, _ = tool.run(_state(session), "fit_analysis")
    assert "무거운 파이프라인" in observation


# --- 가드는 한 곳에만 있다 -----------------------------------------------------------
def test_guards_apply_to_non_loop_callers_too():
    """**루프 밖에서 부를 때도 같은 가드를 지난다.**

    전에는 가드가 두 벌이었다 — `delegate_tool` 과 `application_plan._related_postings`
    (단발 호출이라 도구를 못 쓰는 자리에서 손으로 재현한 것). 후자에는 heavy 검사와 중첩
    금지가 빠져 있었다: 같은 규칙이 경로에 따라 다르게 적용됐다는 뜻이다. 이 검사는 그
    가드가 다시 갈라지면 깨진다.
    """

    session = {**SESSION, "resume": {"sourceType": "text", "value": "x"},
               "job_posting": {"sourceType": "text", "value": "y"}}
    call = call_agent_readonly(session, "fit_analysis", caller="application_plan")
    assert call.refusal == "heavy"
    assert call.result is None


def test_refusal_reason_is_a_code_not_just_a_sentence():
    """거부 사유를 코드로 남긴다 — 관찰 문장이 바뀌어도 hand-off 집계가 안 깨지게."""

    assert call_agent_readonly({}, "없는에이전트").refusal == "unregistered"
    assert call_agent_readonly({}, "job_recommend").refusal == "preconditions_missing"
    assert call_agent_readonly(
        dict(SESSION), "career_chat", allowed=("resume_diagnosis",)
    ).refusal == "not_declared"


def test_delegate_refuses_when_preconditions_missing():
    """전제가 없으면 실행하지 않고 무엇이 없는지 말한다(빈 근거 위에서 돌지 않는다)."""

    tool = delegate_tool(("interview_prep",))
    observation, _ = tool.run(_state({}), "interview_prep")
    assert "지금 실행할 수 없습니다" in observation
    assert "analysis" in observation


def test_refusals_are_traced_with_a_reason_code():
    """**거부도 계측된다** — 성공만 남기면 hand-off 성공률의 분모가 없다(평가 리포트 §1-1).

    사유를 코드로 뽑는 이유: 관찰 문장은 사용자 눈에 맞춰 고쳐지지만 집계는 안 깨져야 한다.
    """

    from jobis_ai import trace

    tool = delegate_tool(("interview_prep",))
    with trace.recording() as recorder:
        tool.run(_state(), "career_chat")        # 선언 안 한 상대
        tool.run(_state({}), "interview_prep")   # 전제 없음
    seen = [(e["kind"], e["detail"]["reason"], e["detail"]["target"])
            for e in recorder.events if e["kind"] == "delegate_refused"]
    assert seen == [("delegate_refused", "not_declared", "career_chat"),
                    ("delegate_refused", "preconditions_missing", "interview_prep")]


def test_successful_delegation_is_traced():
    """성공은 `delegate` — 분자와 분모가 같은 곳(trace)에서 나와야 비율이 성립한다."""

    from jobis_ai import trace

    tool = delegate_tool(("resume_diagnosis",))
    with trace.recording() as recorder:
        tool.run(_state(), "resume_diagnosis")
    kinds = [e["kind"] for e in recorder.events if e["kind"].startswith("delegate")]
    assert kinds == ["delegate"]


def test_delegate_is_read_only(monkeypatch):
    """상대가 낸 sessionUpdates 는 적용하지 않는다 — 턴의 상태 전이는 오케스트레이터만 한다."""

    monkeypatch.setattr(
        "jobis_ai.agents.resume_diagnosis.run",
        lambda s: AgentResult(reply="진단했어요.", sessionUpdates={"analysis": {"몰래": "저장"}}),
    )
    session = dict(SESSION)
    tool = delegate_tool(("resume_diagnosis",))
    tool.run(_state(session), "resume_diagnosis")
    assert "analysis" not in session, "위임은 읽기 전용이다"


def test_delegate_does_not_leak_our_session_mutations(monkeypatch):
    """상대는 세션 사본을 받는다 — 우리 턴의 상태를 상대가 고치지 못한다."""

    def _mutating(session):
        session["profile"] = {"skills": [{"name": "상대가 넣은 값"}]}
        return AgentResult(reply="진단했어요.")

    monkeypatch.setattr("jobis_ai.agents.resume_diagnosis.run", _mutating)
    session = dict(SESSION)
    delegate_tool(("resume_diagnosis",)).run(_state(session), "resume_diagnosis")
    assert session["profile"]["skills"] == [{"name": "Python"}]


def test_delegate_carries_target_warnings(monkeypatch):
    """상대의 경고를 삼키지 않는다 — 삼키면 왜 그런 답이 나왔는지 사후에 못 찾는다."""

    monkeypatch.setattr(
        "jobis_ai.agents.resume_diagnosis.run",
        lambda s: AgentResult(reply="진단했어요.",
                              warnings=[{"code": "no_skill_evidence", "message": "근거 없음"}]),
    )
    observation, data = delegate_tool(("resume_diagnosis",)).run(_state(), "resume_diagnosis")
    assert data[TOOL_WARNINGS_KEY][0]["code"] == "delegated_warning"
    assert "resume_diagnosis" in data[TOOL_WARNINGS_KEY][0]["message"]


def test_delegate_refuses_nested_delegation(monkeypatch):
    """위임 안에서 또 위임하면 재귀가 된다 — 깊이 1 로 막는다."""

    inner: dict = {}

    def _delegating_agent(session):
        obs, _ = delegate_tool(("resume_diagnosis",)).run(
            {"_session": session}, "resume_diagnosis")
        inner["observation"] = obs
        return AgentResult(reply="한 번 더 물어봤어요.")

    monkeypatch.setattr("jobis_ai.agents.career_chat.run", _delegating_agent)
    delegate_tool(("career_chat",)).run(_state(), "career_chat")
    assert "위임 안에서 또 위임할 수 없습니다" in inner["observation"]


def test_loop_lifts_tool_warnings_into_outcome(monkeypatch):
    """도구가 표준 키로 낸 경고는 outcome.warnings 로 올라간다(데이터에 남겨 두지 않는다)."""

    def _warner(state, arg):
        return "관찰", {"x": 1, TOOL_WARNINGS_KEY: [{"code": "c", "message": "m"}]}

    seq = iter([{"action": "use_tool", "tool": "probe", "arg": ""},
                {"action": "reply", "reply": "확인했어요."}])
    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured",
                        lambda schema, *a, **k: (schema(**next(seq)), []))
    outcome = run_agent_loop(
        goal_system="목표", facts={},
        tools={"probe": ToolSpec("probe", "테스트", _warner)}, state={}, node="t")
    assert any(w["code"] == "c" for w in outcome.warnings)
    assert TOOL_WARNINGS_KEY not in outcome.data
    assert outcome.data["x"] == 1


def test_coverletter_can_ask_resume_diagnosis(monkeypatch):
    """실제 소비자 — 자소서가 근거 부족을 만나면 이력서 진단에게 물어본다."""

    from jobis_ai.agents import coverletter_draft as cl

    monkeypatch.setattr(
        "jobis_ai.agents.resume_diagnosis.run",
        lambda s: AgentResult(reply="비어 있는 섹션 — 경력, 자격증, 수상."),
    )
    seq = iter([
        {"action": "use_tool", "tool": "ask_agent", "arg": "resume_diagnosis"},
        {"action": "use_tool", "tool": "save_draft",
         "arg": "강점: 재고 API 를 Django 로 구현했습니다."},
        {"action": "reply", "reply": "경력·자격증 항목이 비어 있어 강점 근거가 얇습니다."},
    ])
    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured",
                        lambda schema, *a, **k: (schema(**next(seq)), []))

    session = {
        "profile": {"projects": [{"title": "재고 API", "role": "백엔드",
                                  "techStack": ["Python", "Django"]}],
                    "skills": [{"name": "Python"}, {"name": "Django"}],
                    "experiences": [], "certifications": [], "awards": []},
        "analysis": {"requirements": [{"text": "Python 백엔드 경험"}], "gaps": []},
        "resume": {"sourceType": "text", "value": "x"},
    }
    result = cl.run(session)
    steps = {s["tool"] for s in result.data["loopSteps"]}
    assert "ask_agent" in steps
    assert "비어 있는 섹션" in next(
        s["observation"] for s in result.data["loopSteps"] if s["tool"] == "ask_agent")


def test_delegating_to_a_tool_gets_the_rendered_sentence():
    """**도구를 부르면 표현 계층을 거쳐 문장을 받는다.**

    `resume_diagnosis` 가 도구로 내려가면서(0729 표현 분리) entry 는 reply 를 비운다.
    위임이 render 를 거치지 않으면 관찰이 매번 "문장을 내지 않았습니다"가 되어 통로가
    조용히 쓸모없어진다 — 스텁으로 reply 를 넣는 테스트는 그걸 잡지 못하므로 **실제
    에이전트**로 검사한다.
    """

    session = {
        "profile": {
            "skills": [{"name": "Python"}, {"name": "Kubernetes"}],
            "skillEvidence": {"Python": ["exp-1"]},
            "projects": [{"id": "p1", "title": "API 서버"}],
            "education": [], "experiences": [], "certifications": [],
            "languages": [], "awards": [],
        },
    }
    observation, _ = delegate_tool(("resume_diagnosis",)).run(
        {"_session": session}, "resume_diagnosis")

    assert "문장을 내지 않았습니다" not in observation
    assert "이력서를 정리했어요" in observation
    assert "Kubernetes" in observation
