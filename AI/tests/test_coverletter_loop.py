"""coverletter_draft — 두 번째 자기 루프 에이전트(초안 → 자기비판 → 재작성) 테스트.

여기서 강제하는 계약:
- 도구는 결정론이다. 점검은 LLM 의 인상이 아니라 **세는 것**으로 판정한다.
- 근거의 출처는 도구 하나뿐이다(이력서 쪽). 공고 쪽(요건·부족 역량)만 프롬프트에 실린다.
- 사용자에게 나가는 초안 본문은 **검증 통과본**이다 — 화면과 저장분이 갈라지지 않는다.
- 루프가 실패해도 이번 턴에 기록된 초안은 살아남고, 실패 이유는 warnings 에 남는다.
- 이전 턴 초안을 이어받아 **지목된 문단만** 고칠 수 있다.
"""

from __future__ import annotations

from jobis_ai.agents import coverletter_draft as cl

PROFILE = {
    "projects": [{"title": "재고 API", "role": "백엔드", "summary": "Django 기반 재고 관리",
                  "techStack": ["Python", "Django"], "achievements": ["응답시간 40% 개선"]}],
    "skills": [{"name": "Python"}, {"name": "Django"}],
    "skillEvidence": {"Python": ["p1"]},
    "experiences": [], "certifications": [], "awards": [],
}
ANALYSIS = {
    "requirements": [{"text": "Python 백엔드 개발 경험"}, {"text": "Kafka 기반 스트리밍 처리"}],
    "gaps": [{"requirementId": "req-2", "missingSkills": ["Kafka"]}],
}
SESSION = {"profile": PROFILE, "analysis": ANALYSIS,
           "resume": {"sourceType": "text", "value": "무관 — profile 캐시 사용"}}


def _stub_decisions(monkeypatch, decisions):
    seq = iter(decisions)

    def fake(schema, system, user_content, *, node, tier="default"):
        try:
            return schema(**next(seq)), []
        except StopIteration:
            return None, [{"code": "test_exhausted", "message": "결정 시퀀스 소진"}]

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake)


def _draft_arg(strengths: str = "재고 API 에서 백엔드를 맡아 Django 로 구현했습니다. "
                                "응답시간을 40% 개선했습니다. 재고 도메인을 직접 설계했습니다.") -> str:
    return ("동기: 공고의 Python 백엔드 요구와 제 경험이 맞닿아 지원합니다. "
            "재고 API 를 만들며 서버 개발을 익혔습니다. 같은 문제를 더 큰 규모에서 풀고 싶습니다.\n"
            f"강점: {strengths}\n"
            "보완: Kafka 경험은 아직 없습니다. 학습 계획을 세워 메우고 있습니다. "
            "토이 프로젝트로 적용해 볼 계획입니다.")


# --- 도구 (결정론) ---------------------------------------------------------------
def test_find_evidence_is_the_only_source_of_resume_facts():
    """이력서 근거는 도구만 준다. 없는 것은 없다고 말한다(지어낼 여지를 주지 않는다)."""

    state = cl._draft_state({}, PROFILE, ANALYSIS)

    everything, _ = cl._tool_find_evidence(state, "")
    assert "재고 API" in everything and "응답시간 40% 개선" in everything

    hit, _ = cl._tool_find_evidence(state, "Django")
    assert "재고 API" in hit

    miss, _ = cl._tool_find_evidence(state, "Kafka")
    assert "확인되지 않습니다" in miss


def test_save_draft_updates_only_given_paragraphs():
    """적어 보낸 문단만 갱신된다 — 부분 수정이 성립하는 지점."""

    state = cl._draft_state({}, PROFILE, ANALYSIS)
    cl._tool_save_draft(state, _draft_arg())
    before_motivation = state["motivation"]

    obs, _ = cl._tool_save_draft(state, "강점: 재고 API 를 혼자 설계하고 구현했습니다.")
    assert state["motivation"] == before_motivation, "안 적은 문단을 지우면 안 된다"
    assert state["strengthsParagraph"] == "재고 API 를 혼자 설계하고 구현했습니다."
    assert state["revisions"] == 2
    assert "강점" in obs


def test_save_draft_rejects_unlabeled_text():
    """라벨이 없으면 저장하지 않고 형식을 알려 준다 — 루프가 스스로 고친다."""

    state = cl._draft_state({}, PROFILE, ANALYSIS)
    obs, _ = cl._tool_save_draft(state, "그냥 줄글로 자소서를 씁니다.")
    assert "저장하지 않았습니다" in obs
    assert not cl._has_draft(state)


def test_check_draft_counts_instead_of_judging():
    """점검은 세는 일이다 — 금지표현·근거 없는 기술·분량·요건 커버리지·부족 역량."""

    state = cl._draft_state({}, PROFILE, ANALYSIS)
    cl._tool_save_draft(state, "강점: Kubernetes 운영에 능숙하며 반드시 성과를 냅니다.")
    obs, _ = cl._tool_check_draft(state, "")

    report = state["lastCheck"]
    assert "Kubernetes" in report["ungroundedSkills"], "이력서에 없는 기술을 잡아야 한다"
    assert "반드시" in report["forbidden"]
    assert report["emptyParagraphs"] == ["지원 동기", "보완 계획"]
    # 요건 2건 중 초안이 다룬 것은 0건(Python·Kafka 모두 언급 없음)
    assert report["requirementCoverage"] == {
        "covered": 0, "measurable": 2,
        "uncovered": ["Python 백엔드 개발 경험", "Kafka 기반 스트리밍 처리"],
    }
    assert report["uncoveredGaps"] == ["Kafka"]
    assert "금지표현" in obs and "커버리지" in obs


def test_check_draft_passes_a_grounded_draft():
    state = cl._draft_state({}, PROFILE, ANALYSIS)
    cl._tool_save_draft(state, _draft_arg())
    obs, _ = cl._tool_check_draft(state, "")
    assert "지적 사항 없음" in obs
    assert state["lastCheck"]["requirementCoverage"]["covered"] == 2


# --- 루프 (초안 → 점검 → 재작성) --------------------------------------------------
def test_loop_critiques_and_rewrites(monkeypatch):
    """점검에서 걸린 문단을 스스로 고쳐 다시 쓴다 — 한 번 생성으로 끝나지 않는다."""

    _stub_decisions(monkeypatch, [
        {"action": "use_tool", "tool": "find_evidence", "arg": ""},
        {"action": "use_tool", "tool": "save_draft",
         "arg": _draft_arg(strengths="Kubernetes 클러스터를 운영했습니다.")},   # 근거 없는 기술
        {"action": "use_tool", "tool": "check_draft", "arg": ""},
        {"action": "use_tool", "tool": "save_draft",
         "arg": "강점: 재고 API 에서 Django 로 백엔드를 구현했습니다. "
                "응답시간을 40% 개선했습니다. 재고 도메인을 직접 설계했습니다."},
        {"action": "reply", "reply": "점검에서 지적된 근거 없는 기술 언급을 빼고 다시 썼습니다."},
    ])
    result = cl.run(dict(SESSION))

    assert result.data["revisions"] == 2, "자기비판 후 다시 쓴 것이 기록돼야 한다"
    assert "Kubernetes" not in result.data["strengthsParagraph"]
    assert "재고 API" in result.data["strengthsParagraph"]
    assert result.data["status"] == "draft_pending_review"      # P5 게이트
    # 도구 궤적이 남는다(관찰 가능성)
    assert [s["tool"] for s in result.data["loopSteps"]] == [
        "find_evidence", "save_draft", "check_draft", "save_draft"]


def test_final_check_measures_the_shipped_draft(monkeypatch):
    """산출물에 붙는 수치는 **산출물을 잰 값**이다.

    실측(2026-07-29): 점검이 "보완 2문장"을 지적해 3문장으로 고쳐 놓고도, 저장된 payload 에는
    고치기 전 점검값(2문장)이 남았다. 루프 도중의 마지막 점검은 재작성 이전 상태다.
    """

    _stub_decisions(monkeypatch, [
        {"action": "use_tool", "tool": "save_draft", "arg": "보완: 한 문장뿐입니다."},
        {"action": "use_tool", "tool": "check_draft", "arg": ""},          # 이 시점 보완 1문장
        {"action": "use_tool", "tool": "save_draft",
         "arg": "보완: 첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다."},
        {"action": "reply", "reply": "보완 문단 분량을 늘렸습니다."},
    ])
    result = cl.run(dict(SESSION))
    assert result.data["check"]["sentenceCounts"]["improvementParagraph"] == 3


def test_reply_shows_the_verified_draft(monkeypatch):
    """화면에 나가는 본문 = 검증 통과본. 제거된 문장이 화면에만 남으면 안 된다."""

    _stub_decisions(monkeypatch, [
        {"action": "use_tool", "tool": "save_draft",
         "arg": _draft_arg(strengths="재고 API 를 Django 로 구현했습니다. "
                                     "Kubernetes 로 운영했습니다.")},
        {"action": "reply", "reply": "초안을 만들었습니다."},
    ])
    result = cl.run(dict(SESSION))

    assert "[강점]" in result.reply and "재고 API" in result.reply
    assert "Kubernetes" not in result.reply, "검증에서 지운 문장이 화면에 남으면 안 된다"
    assert result.data["strengthsParagraph"] in result.reply
    assert any(w["code"] == "ungrounded_skill_removed" for w in result.warnings)
    assert "검토" in result.reply                                # 사용자 검토 게이트


def test_loop_reply_failure_keeps_the_draft(monkeypatch):
    """마무리 문장을 못 만들어도 기록된 초안은 살린다 — 이유는 warnings 에 남는다."""

    calls = {"n": 0}

    def fake(schema, system, user_content, *, node, tier="default"):
        calls["n"] += 1
        if calls["n"] == 1:
            return schema(action="use_tool", tool="save_draft", arg=_draft_arg()), []
        return None, [{"code": "llm_call_failed", "message": "호출 실패"}]

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake)
    result = cl.run(dict(SESSION))

    assert "재고 API" in result.reply
    assert result.sessionUpdates["coverletter"]["strengthsParagraph"]
    assert any(w["code"] == "llm_call_failed" for w in result.warnings)
    assert any(w["code"] == "coverletter_note_missing" for w in result.warnings)


def test_loop_failure_without_draft_is_honest(monkeypatch):
    """초안을 하나도 못 쓴 채 실패하면 가짜 초안을 내지 않는다."""

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured",
                        lambda *a, **k: (None, [{"code": "llm_call_failed", "message": "호출 실패"}]))
    result = cl.run(dict(SESSION))

    assert "실패" in result.reply
    assert not result.data
    assert any(w["code"] == "coverletter_no_draft" for w in result.warnings)


def test_prior_draft_is_revised_not_rewritten(monkeypatch):
    """이전 턴 초안을 이어받아 지목된 문단만 고친다."""

    prior = {"status": "draft_pending_review",
             "motivation": "이전 턴의 지원 동기 문단입니다.",
             "strengthsParagraph": "이전 턴의 강점 문단입니다.",
             "improvementParagraph": "이전 턴의 보완 문단입니다.",
             "revisions": 1}
    seen: dict = {}

    def stepper(schema, system, user_content, *, node, tier="default"):
        seen.setdefault("payload", user_content)
        if "save" not in seen:
            seen["save"] = True
            return schema(action="use_tool", tool="save_draft",
                          arg="강점: 재고 API 에서 Django 로 구현했습니다."), []
        return schema(action="reply", reply="강점 문단만 다시 썼습니다."), []

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", stepper)
    result = cl.run({**SESSION, "coverletter": prior,
                     "last_message": "강점 문단만 다시 써줘"})

    assert "이전 턴의 지원 동기" in result.data["motivation"], "안 건드린 문단은 유지된다"
    assert "재고 API" in result.data["strengthsParagraph"]
    assert result.data["revisions"] == 2
    # 이전 초안이 프롬프트에 실려야 부분 수정이 가능하다
    assert "currentDraft" in seen["payload"] and "이전 턴의 강점 문단" in seen["payload"]


def test_no_evidence_refuses_to_write(monkeypatch):
    """근거가 없으면 루프를 돌리지 않는다 — 지어낼 재료가 없다."""

    called = {"n": 0}
    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured",
                        lambda *a, **k: (called.update(n=called["n"] + 1), (None, []))[1])
    result = cl.run({"profile": {"projects": [], "experiences": [], "skills": [],
                                 "certifications": [], "awards": []},
                     "analysis": ANALYSIS, "resume": {"sourceType": "text", "value": "x"}})
    assert called["n"] == 0, "근거가 없으면 LLM 을 부르지도 않는다"
    assert any(w["code"] == "no_coverletter_facts" for w in result.warnings)
