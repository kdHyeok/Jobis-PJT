"""멀티에이전트 개선방안(_docs/agent) 반영분 테스트.

- 재계획 루프(§2-1): 에이전트 하나 실행 후 결과를 보고 계속/중단/수정을 다시 정한다.
- 세션 write-back(§3-5): 턴에 읽기 1회·쓰기 1회.
- 입력 절단 휴리스틱(§4): 후반부 자격요건/우대사항을 버리지 않는다.
- MemorySessionStore 깊은 복사(§4): 복사본 규약이 중첩 dict 에도 성립.
- intent 라벨(§4): 검증기가 계획을 바꾸면 라벨도 실제 실행 시퀀스를 따른다.
"""

from __future__ import annotations

import pytest

from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.orchestrator import session as session_mod
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.orchestrator.planner import AgentPlan
from jobis_ai.orchestrator.session import SessionStore
from jobis_ai.structured import _truncate


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch):
    store = SessionStore()
    monkeypatch.setattr(session_mod, "_STORE", store)
    return store


def stub_planner(monkeypatch, agents, ack: str = ""):
    # requestedAgents=agents — 이 스텁은 "사용자가 이 기능을 청했다"는 뜻이다. 비우면
    # 동의 게이트가 fail-closed 로 걸린다(그 동작은 test_planner.py 가 따로 본다).
    plan = AgentPlan(agents=list(agents), requestedAgents=list(agents),
                     confidence=0.9, ack=ack)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def _resume() -> ChatAttachment:
    return ChatAttachment(kind="resume", sourceType=SourceType.text,
                          value="Python Django 백엔드 개발 3년")


def _posting() -> ChatAttachment:
    return ChatAttachment(kind="job_posting", sourceType=SourceType.text,
                          value="백엔드 개발자 모집. 필수: Python, Django 3년.")


# --- 관찰 후 재선택 루프 (ReAct — Agent_Test 패턴 이식) ------------------------
def test_rules_keep_original_sequence_when_nothing_to_change(monkeypatch):
    """규칙이 손댈 것이 없으면 예정대로 계속 — 관찰이 LLM 이던 때의 동작이 그대로 보존된다."""

    stub_planner(monkeypatch, ["career_chat", "resume_diagnosis"])
    res = handle_chat(ChatRequest(
        sessionId="ob2", message="고민 들어주고 이력서도 진단해줘",
        attachments=[_resume()],
    ))
    assert res.dispatched == ["career_chat", "resume_diagnosis"]


def test_rules_finish_when_preconditions_broke(monkeypatch):
    """전제가 무너지면 뒤 단계를 실행하지 않고 끝낸다 — 예전 관찰 LLM 이 못 막던 자리.

    실측(2026-07-29): `fit_analysis` 가 `analysis` 를 못 만들었는데 `coverletter_draft` 가
    그대로 돌아 **analysis=None 위에서 초안을 썼다.** 규칙이 그 자리를 지킨다.
    """

    from jobis_ai.agents import AgentResult

    stub_planner(monkeypatch, ["fit_analysis", "coverletter_draft"])
    # 판정이 등급을 못 냈다: analysis 미승격 + 되묻는 질문도 없음
    monkeypatch.setattr("jobis_ai.agents.fit_analysis.run",
                        lambda s: AgentResult(reply="", data={"status": "failed"}))
    ran = []
    monkeypatch.setattr("jobis_ai.agents.coverletter_draft.run",
                        lambda s: ran.append(1) or AgentResult(reply="초안"))

    res = handle_chat(ChatRequest(sessionId="ob1", message="분석하고 자소서 써줘",
                                  attachments=[_resume(), _posting()]))

    # D71: 이번 턴 제출 자료의 정리 단계가 판정 앞에 끼워진다. 핵심 주장은 그대로다 —
    # 판정이 실패해 analysis 가 없으면 자소서는 돌지 않는다.
    assert res.dispatched == ["posting_analysis", "resume_diagnosis", "fit_analysis"], \
        "전제가 없는 뒤 단계는 실행되지 않는다"
    assert not ran
    assert "진행하지 못했" in res.reply, "왜 못 했는지 사용자에게 말한다"


# --- 세션 write-back (§3-5) ----------------------------------------------------
def test_turn_reads_once_and_writes_once(monkeypatch, fresh_session_store):
    """한 턴에 저장소 읽기 1회·쓰기 1회 — 첨부·last_message·이력이 한 번에 저장된다."""

    reads, writes = [], []
    orig_get, orig_update = fresh_session_store.get, fresh_session_store.update
    monkeypatch.setattr(fresh_session_store, "get",
                        lambda sid: reads.append(sid) or orig_get(sid))
    monkeypatch.setattr(fresh_session_store, "update",
                        lambda sid, u: writes.append(sorted(u)) or orig_update(sid, u))

    stub_planner(monkeypatch, ["resume_diagnosis"])
    handle_chat(ChatRequest(sessionId="wb1", message="이력서 진단해줘",
                            attachments=[_resume()]))
    assert len(reads) == 1
    assert len(writes) == 1
    # 첨부·발화·이력이 마지막 한 번의 쓰기에 전부 실려 있다
    assert {"resume", "last_message", "history"} <= set(writes[0])

    # 저장 결과도 온전하다 — 다음 턴이 이 자산을 읽는다
    saved = orig_get("wb1")
    assert saved.get("resume") and saved.get("history")


# --- 입력 절단 휴리스틱 (§4) ---------------------------------------------------
def test_truncate_preserves_requirement_sections():
    """긴 공고를 자를 때 후반부의 자격요건/우대사항을 버리지 않는다."""

    filler = "회사 소개와 복지 이야기. " * 2000            # 앞부분 노이즈 (>16000자)
    tail = "자격요건: Python 3년, Django 실무. 우대사항: AWS."
    warnings: list[dict] = []
    out = _truncate(filler + tail, "test", warnings)
    assert "자격요건: Python 3년" in out
    assert warnings and warnings[0]["code"] == "input_truncated"


def test_truncate_short_input_untouched():
    warnings: list[dict] = []
    assert _truncate("짧은 입력", "test", warnings) == "짧은 입력"
    assert not warnings


# --- MemorySessionStore 깊은 복사 (§4) -----------------------------------------
def test_memory_store_returns_deep_copies(fresh_session_store):
    """get() 복사본의 중첩 dict 를 고쳐도 저장분이 오염되지 않는다 — SQLite 와 동일 규약."""

    fresh_session_store.update("dc1", {"resume": {"sourceType": "text", "value": "원본"}})
    copy1 = fresh_session_store.get("dc1")
    copy1["resume"]["value"] = "오염 시도"
    assert fresh_session_store.get("dc1")["resume"]["value"] == "원본"


# --- intent 라벨 (§4) ----------------------------------------------------------
def test_intent_label_follows_actual_dispatch(monkeypatch):
    """검증기가 실행 불가 에이전트를 빼면 intent 라벨도 실제 실행을 따른다.

    이력서 없이 fit_analysis 를 골랐다 → posting_analysis 만 실행 →
    프론트에 나가는 intent 도 posting_analysis (원안 fit_analysis 가 아니라).
    """

    stub_planner(monkeypatch, ["fit_analysis", "posting_analysis"])
    res = handle_chat(ChatRequest(
        sessionId="lb1", message="이 공고 나 되나?", attachments=[_posting()],
    ))
    assert res.dispatched == ["posting_analysis"]
    assert res.intent == "posting_analysis"


# --- 선호만으로 실공고 추천 (이력서 없이도 도달 가능) --------------------------
def _stub_rag(monkeypatch, items):
    """job_recommend 가 쓰는 RAG 어댑터를 고정 후보로 대체한다(데이터 파일 비의존)."""

    from jobis_ai.rag import RagResult

    monkeypatch.setattr(
        "jobis_ai.agents.job_recommend.get_rag_adapter",
        lambda: type("A", (), {
            "search": staticmethod(lambda _q, **_kw: RagResult(items=items)),
        })(),
    )


def _render_recommend(result):
    """job_recommend 는 도구다 — 문장은 표현 계층이 만든다(계약 변경 반영)."""

    from jobis_ai.agents.tool_render import render_job_recommend

    assert result.reply == "", "도구는 사용자향 문장을 만들지 않는다"
    return render_job_recommend(result.data, {})[0]


_RAG_CANDIDATE = {
    "text": "백엔드 개발자를 찾습니다. 필요 기술: Java, Spring 경험.",
    "title": "백엔드 개발자 (신입)",
    "companyName": "커머스컴퍼니",
    "jobPostingId": "jk-1",
    "url": "https://www.jobkorea.co.kr/Recruit/GI_Read/1",
    "score": 0.9,
}


def test_job_recommend_runs_on_preferences_without_resume(monkeypatch):
    """이력서가 없어도 선호만으로 실공고를 추천한다.

    전에는 전제가 ("resume",) 뿐이라 이력서 없는 사용자는 공고 추천에 **영구히 도달 못 했다**
    (resume 은 사용자 첨부라 생산자가 없어 자동 삽입으로도 못 채운다). 그 결과 플래너가
    career_chat 으로 흘러 "공고 데이터가 없어서 특정 회사를 짚기 어렵다"고, 실공고 DB 가
    있는데도 사실과 다르게 안내하는 사례가 실측됐다.
    """

    from jobis_ai.agents import job_recommend

    _stub_rag(monkeypatch, [_RAG_CANDIDATE])
    session = {"preferences": {"roles": ["백엔드"], "techStack": ["Java", "Spring"],
                               "regions": ["서울"]}}
    result = job_recommend.run(session)
    recommendations = result.data["recommendations"]

    assert recommendations, "선호만으로도 실공고 추천이 나와야 한다"
    # 검색 쿼리는 선호에서 나온다 (프로필이 없어도 비지 않는다)
    assert "백엔드" in result.data["query"]
    # 실공고에서 온 것이므로 URL 이 붙는다 — 붙여넣으면 적합도 분석으로 이어진다
    assert all(r["url"] for r in recommendations)
    # 이력서가 없으니 역량 일치는 계산하지 않는다 — 0 건을 "일치 0" 으로 말하지 않는다
    assert all(r["matchedSkills"] == [] for r in recommendations)
    rendered = _render_recommend(result)
    assert "계산하지 않았" in rendered
    assert "0개 역량 일치" not in rendered


def test_job_recommend_without_resume_does_not_build_profile(monkeypatch):
    """이력서가 없으면 프로필을 만들지 않는다 — 빈 프로필밖에 못 내면서 LLM 만 쓰는 낭비."""

    from jobis_ai.agents import job_recommend

    _stub_rag(monkeypatch, [_RAG_CANDIDATE])
    called = []
    monkeypatch.setattr("jobis_ai.agents.job_recommend.ensure_profile",
                        lambda s: called.append(1) or ({}, []))
    job_recommend.run({"preferences": {"roles": ["백엔드"]}})
    assert not called, "이력서 없는 턴에 ensure_profile 을 부르면 안 된다"


def test_job_recommend_with_resume_still_matches_skills(monkeypatch):
    """이력서가 있으면 기존대로 보유 역량 일치를 근거로 쓴다(회귀 방어)."""

    from jobis_ai.agents import job_recommend

    _stub_rag(monkeypatch, [_RAG_CANDIDATE])
    session = {"profile": {"skills": [{"name": "Java"}, {"name": "Spring"}],
                           "experiences": [{"role": "백엔드 개발자"}], "projects": []}}
    result = job_recommend.run(session)

    assert result.data["recommendations"], "이력서가 있으면 추천이 나와야 한다"
    for r in result.data["recommendations"]:
        assert r["matchedSkills"], "이력서가 있으면 역량 일치가 근거로 나와야 한다"
    assert "계산하지 않았" not in _render_recommend(result)


# --- 후속 질문이 남은 큐를 죽이지 않는다 ---------------------------------------
def test_followup_does_not_kill_runnable_next_step(monkeypatch):
    """앞 단계가 (뒤에 불필요한) 자료를 물어도, 지금 돌 수 있는 뒤 단계는 실행한다.

    실측: "백엔드 신입 공고 추천해줘" → 계획 [선호 파악, 공고 추천]. 선호 파악이 공고 URL 을
    물으면서 followUpQuestions 를 냈고, 오케스트레이터가 무조건 break 해서 **바로 실행 가능한
    공고 추천이 사라졌다**. 사용자는 추천을 두 번 요청하고도 추천을 못 받았다.
    """

    from jobis_ai.agents import AgentResult

    _stub_rag(monkeypatch, [_RAG_CANDIDATE])
    stub_planner(monkeypatch, ["preference_intake", "job_recommend"])

    def fake_intake(session):
        # 선호는 채워 주면서, 뒤 단계에 필요 없는 공고 URL 을 묻는다
        return AgentResult(
            reply="선호 확인했어요.",
            followUpQuestions=[{"field": "job_posting", "question": "공고 URL 을 주세요."}],
            sessionUpdates={"preferences": {"roles": ["백엔드"], "techStack": ["Java"]}},
        )

    monkeypatch.setattr("jobis_ai.agents.preference_intake.run", fake_intake)

    res = handle_chat(ChatRequest(sessionId="fq1", message="백엔드 신입 공고 추천해줘"))
    assert res.dispatched == ["preference_intake", "job_recommend"]
    # 물어본 질문은 그대로 사용자에게 나간다 — 계속 갔다고 질문을 삼키지 않는다
    assert any(q["field"] == "job_posting" for q in res.followUpQuestions)


def test_followup_still_halts_when_next_step_needs_it(monkeypatch):
    """반대로, 물어본 자료가 뒤 단계의 전제면 그대로 멈춘다(기존 규율 유지)."""

    from jobis_ai.agents import AgentResult

    stub_planner(monkeypatch, ["posting_analysis", "fit_analysis"])

    def fake_posting(session):
        return AgentResult(
            reply="이력서가 필요해요.",
            followUpQuestions=[{"field": "resume", "question": "이력서를 주세요."}],
        )

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.run", fake_posting)
    res = handle_chat(ChatRequest(sessionId="fq2", message="이 공고 나 되나?",
                                  attachments=[_posting()]))
    # fit_analysis 는 이력서가 없어 지금 못 돈다 → 멈춘다
    assert res.dispatched == ["posting_analysis"]


# --- 연차 불일치 공고 제외 (신입에게 경력 8년 공고가 가던 문제) -------------------
@pytest.mark.parametrize("text,expected", [
    ("신입", 0.0),
    ("경력무관", 0.0),
    ("신입·경력", 0.0),
    ("신입-경력 3년", 0.0),      # 신입부터 받는 공고
    ("경력", 1.0),               # 연차 미표기 경력 채용 — 데이터 최다 유형
    ("경력 3년", 3.0),
    ("경력 3-8년", 3.0),         # 범위는 하한. 상한(8)을 잡으면 3년차를 잘못 걸러낸다
    ("경력 5-15년", 5.0),
    ("", None),                  # 모르면 None → 거르지 않는다
    (None, None),
    ("알 수 없음", None),
])
def test_experience_floor_years(text, expected):
    from jobis_ai.postings_db import experience_floor_years

    assert experience_floor_years(text) == expected


@pytest.mark.parametrize("posting_floor,user_years,fits", [
    (8.0, 0.0, False),    # 신입에게 8년 요구 — 이 버그의 원본 사례
    (1.0, 0.0, False),    # 신입에게 연차 미표기 '경력' 공고
    (0.0, 0.0, True),     # 신입에게 신입 가능 공고
    (4.0, 3.0, True),     # 3년차에게 4년 요구 — 1년 관용 안에서 허용
    (8.0, 3.0, False),    # 3년차에게 8년 요구
    (8.0, None, True),    # 사용자 연차를 모르면 거르지 않는다
    (None, 0.0, True),    # 공고 표기를 못 읽으면 거르지 않는다
])
def test_fits_experience(posting_floor, user_years, fits):
    # 판정은 postings_db 한 곳에 있다(D115) — job_recommend·find_alternatives 공용.
    from jobis_ai.postings_db import fits_experience

    assert fits_experience(posting_floor, user_years) is fits


def test_job_recommend_excludes_experience_mismatch(monkeypatch):
    """"신입" 이라고 말한 사용자에게 경력 요구 공고를 추천하지 않는다."""

    from jobis_ai.agents import job_recommend

    senior = {**_RAG_CANDIDATE, "title": "시니어 백엔드", "seniority": "경력 8년",
              "url": "https://example.com/senior"}
    junior = {**_RAG_CANDIDATE, "title": "백엔드 신입", "seniority": "신입·경력",
              "url": "https://example.com/junior"}
    _stub_rag(monkeypatch, [senior, junior])

    session = {"preferences": {"roles": ["백엔드"], "techStack": ["Java"],
                               "experienceLevel": "신입"}}
    result = job_recommend.run(session)
    urls = [r["url"] for r in result.data["recommendations"]]

    assert urls == ["https://example.com/junior"], "경력 8년 공고가 신입에게 가면 안 된다"
    assert any(w["code"] == "experience_filtered" for w in result.warnings)
    assert "연차가 맞지 않는 공고 1건은 제외" in _render_recommend(result)


def test_job_recommend_keeps_all_when_experience_unknown(monkeypatch):
    """연차를 말하지 않았고 이력서도 없으면 거르지 않는다 — 모르면 판단하지 않는다."""

    from jobis_ai.agents import job_recommend

    senior = {**_RAG_CANDIDATE, "seniority": "경력 8년", "url": "https://example.com/s"}
    _stub_rag(monkeypatch, [senior])
    result = job_recommend.run({"preferences": {"roles": ["백엔드"], "techStack": ["Java"]}})
    assert len(result.data["recommendations"]) == 1


def test_job_recommend_all_filtered_says_so(monkeypatch):
    """전부 연차로 걸러지면 "검색 결과 없음" 이 아니라 걸러냈다고 정직하게 말한다."""

    from jobis_ai.agents import job_recommend

    _stub_rag(monkeypatch, [{**_RAG_CANDIDATE, "seniority": "경력 8년"}])
    result = job_recommend.run({"preferences": {"roles": ["백엔드"], "techStack": ["Java"],
                                                "experienceLevel": "신입"}})
    assert not result.data["recommendations"]
    rendered = _render_recommend(result)
    assert "신입 조건과 맞지 않아" in rendered
    assert "검색에서 결과를 얻지 못해" not in rendered


@pytest.mark.parametrize("experience,title,expected", [
    # 정형 표기에 연차가 없고 제목에만 있는 공고 — 실측: 5년차에게 7년 요구 공고가 갔다
    ("경력", "백엔드 개발자 (Java/Spring) 경력 7년 이상", 7.0),
    ("경력", "통신 소프트웨어 개발자 (경력2년이상) 모집", 2.0),
    # 제목은 **올릴 때만** 쓴다 — 정형 표기가 더 높으면 그대로
    ("경력 10년", "백엔드 개발자 (경력 3년 이상)", 10.0),
    # 신입 표기는 제목 때문에 뒤집히지 않는다
    ("신입·경력", "백엔드 개발자 (경력 5년 이상 우대)", 0.0),
    # '경력' 이 숫자에 붙지 않은 숫자는 연차가 아니다 — 오탐 방어
    ("경력", "창립 20년 기업의 백엔드 개발자", 1.0),
    ("경력", "2026년 상반기 백엔드 개발자", 1.0),
    ("", "백엔드 개발자", None),
])
def test_posting_floor_years_uses_title_only_to_raise(experience, title, expected):
    from jobis_ai.postings_db import posting_floor_years

    assert posting_floor_years(experience, title) == expected


def test_job_recommend_excludes_title_only_experience(monkeypatch):
    """정형 표기가 '경력' 이어도 제목에 명시된 연차로 걸러낸다."""

    from jobis_ai.agents import job_recommend

    senior = {**_RAG_CANDIDATE, "title": "백엔드 개발자 (Java/Spring) 경력 7년 이상",
              "seniority": "경력", "url": "https://example.com/senior7"}
    fit = {**_RAG_CANDIDATE, "title": "백엔드 개발자 (Java/Spring)",
           "seniority": "경력 3년", "url": "https://example.com/fit"}
    _stub_rag(monkeypatch, [senior, fit])

    session = {"preferences": {"roles": ["백엔드"], "techStack": ["Java"],
                               "experienceLevel": "경력 3년"}}
    result = job_recommend.run(session)
    assert [r["url"] for r in result.data["recommendations"]] == ["https://example.com/fit"]


# --- 관찰 낭비 제거 + 궤적 기록 (평가 §5-1, §5-2) -------------------------------
def test_observe_records_continue_in_trace(monkeypatch):
    """아무것도 바꾸지 않은 continue 도 궤적에 남는다 — 안 남기면 재선택을 증명할 수 없다.

    이제 판단자가 규칙이라 **어느 규칙이 정했는지**(rule)까지 남는다. LLM 의 자유 문장보다
    사후에 읽기 쉽다.
    """

    from jobis_ai import trace

    stub_planner(monkeypatch, ["preference_intake", "job_recommend"])
    with trace.recording() as rec:
        handle_chat(ChatRequest(sessionId="ob6", message="조건 정리하고 공고 찾아줘",
                                attachments=[_resume()]))

    observed = [e for e in rec.events if e["kind"] == "observe"]
    actions = [e["detail"]["action"] for e in observed]
    assert "continue" in actions, "continue 결정이 궤적에 남아야 한다"
    assert all(e["detail"].get("reason") for e in observed), "이유 없는 관찰 기록은 쓸모없다"
    assert all(e["detail"].get("rule") for e in observed), "어느 규칙이 정했는지 남아야 한다"


def test_dispatch_trace_marks_validator_change(monkeypatch):
    """다중 시퀀스가 LLM 판단인지 검증기 삽입인지 궤적으로 구분된다.

    실측에서 플래너 원안은 ['job_recommend'] 하나였고 preference_intake 는 검증기가
    끼운 것이었다 — 이 구분이 없으면 "LLM 이 다중 에이전트를 계획했다"고 오독하게 된다.
    """

    from jobis_ai import trace

    stub_planner(monkeypatch, ["job_recommend"])          # 원안은 하나
    with trace.recording() as rec:
        handle_chat(ChatRequest(sessionId="ob8", message="공고 추천해줘"))

    planner = next(e for e in rec.events if e["kind"] == "planner")
    dispatch = next(e for e in rec.events if e["kind"] == "dispatch")
    assert planner["detail"]["selectedAgents"] == ["job_recommend"]
    assert dispatch["detail"]["agents"] == ["preference_intake", "job_recommend"]
    assert dispatch["detail"]["planChanged"] is True


# --- LLM 이 인자까지 정한다 (평가 §5-3) ----------------------------------------
def test_agent_args_validated_against_declaration():
    """선언된 인자만 통과한다 — 이름 환각·미등록 에이전트·빈 값은 버린다."""

    from jobis_ai.orchestrator.planner import AgentArg
    from jobis_ai.orchestrator.router import validate_agent_args

    ok = validate_agent_args([AgentArg(agent="job_recommend", name="job_name",
                                       value="데이터 엔지니어")])
    assert ok == {"job_recommend": {"job_name": "데이터 엔지니어"}}

    # 선언되지 않은 인자 이름 / 빈 값 / 인자를 받지 않는 에이전트
    assert validate_agent_args([AgentArg(agent="job_recommend", name="지어낸인자",
                                         value="x")]) == {}
    assert validate_agent_args([AgentArg(agent="job_recommend", name="job_name",
                                         value="  ")]) == {}
    assert validate_agent_args([AgentArg(agent="career_chat", name="job_name",
                                         value="백엔드")]) == {}


def test_manifest_exposes_agent_params():
    """플래너 프롬프트에 인자가 노출된다 — 안 보이면 LLM 은 넘길 수 있음을 모른다."""

    from jobis_ai.orchestrator.planner import _build_manifest

    manifest = _build_manifest()
    assert "인자 job_name" in manifest


def test_explicit_job_name_skips_preference_intake():
    """발화에 직군이 명시되면 선호 수집을 앞에 끼우지 않는다 (params_satisfy).

    이 통로가 없으면 "데이터 엔지니어 공고 찾아줘" 가 선호 수집 턴을 한 번 더 거쳤다.
    """

    from jobis_ai.orchestrator.router import validate_plan

    session = {"_agentArgs": {"job_recommend": {"job_name": "데이터 엔지니어"}}}
    assert validate_plan(["job_recommend"], session).agents == ("job_recommend",)
    # 인자가 없으면 기존대로 생산자를 끼운다
    assert validate_plan(["job_recommend"], {}).agents == ("preference_intake", "job_recommend")


def test_job_recommend_uses_job_name_arg(monkeypatch):
    """넘겨받은 직군이 검색 쿼리 앞자리에 들어간다."""

    from jobis_ai.agents import job_recommend

    _stub_rag(monkeypatch, [_RAG_CANDIDATE])
    session = {"_agentArgs": {"job_recommend": {"job_name": "데이터 엔지니어"}},
               "preferences": {"roles": ["백엔드"]}}
    result = job_recommend.run(session)
    assert result.data["query"].startswith("데이터 엔지니어")


# --- 대안 공고를 답변에 싣는다 (평가 §5-4) --------------------------------------
def test_alternatives_block_shows_url_and_kind():
    """계산만 하고 버리던 대안 공고를 보여준다 — 실공고는 URL 까지."""

    from jobis_ai.agents.tool_render import _alternatives_block

    block = _alternatives_block([
        {"type": "lower_seniority", "title": "주니어 백엔드", "companyName": "커머스컴퍼니",
         "reducedGaps": ["Kafka", "MSA"], "url": "https://example.com/jr"},
        {"type": "stepping_stone", "title": "QA 엔지니어", "companyName": "", "url": ""},
    ])
    assert "요구 연차가 낮은 자리" in block
    assert "https://example.com/jr" in block
    assert "부족했던 2개 요건" in block
    assert "징검다리 경로" in block


def test_alternatives_block_empty_when_none():
    """대안이 없으면 아무 말도 하지 않는다 — 없는 걸 있다고 하지 않는다."""

    from jobis_ai.agents.tool_render import _alternatives_block

    assert _alternatives_block([]) == ""


# --- career_chat 폴백은 이유를 남긴다 (§2-6) -------------------------------------
@pytest.mark.parametrize("reply,code_expected,in_message", [
    ("이 공고는 합격 가능성이 높아요", True, "합격 가능"),   # 금지표현 강등
    ("", True, "비어"),                                    # 빈 응답 강등
    ("천천히 준비해 보면 좋겠어요.", False, ""),             # 정상 — 경고 없음
])
def test_career_chat_fallback_reports_reason(monkeypatch, reply, code_expected, in_message):
    """고정 안내문으로 강등할 때 원인을 warnings 에 남긴다.

    실측(sessions.sqlite3 275턴): 이 폴백이 7건 나갔는데 전부 정상 요청이었고, 원인
    셋(미설정·실패·금지표현) 중 무엇이었는지 사후에 알 수 없었다 — 금지표현·빈 응답
    강등만 무음이었기 때문이다. 처방이 원인마다 다르므로 세는 것이 먼저다.
    """

    from jobis_ai.agents import career_chat

    monkeypatch.setattr(career_chat, "run_streaming_text",
                        lambda *a, **k: (reply, []))
    result = career_chat.run({"last_message": "위로해줘"})

    codes = [w["code"] for w in result.warnings]
    assert ("career_chat_fallback" in codes) is code_expected
    if code_expected:
        assert result.reply == career_chat._FALLBACK
        assert in_message in next(w["message"] for w in result.warnings
                                  if w["code"] == "career_chat_fallback")
    else:
        assert result.reply == reply


# --- 수확기 지문이 소스와 함께 늙지 않게 ------------------------------------------
def test_harvest_fingerprints_still_exist_in_source():
    """`scripts/harvest_sessions.py` 의 문구 지문이 소스에 실재하는지.

    수확기는 답변 **문구**로 신호를 센다(warnings 는 응답과 함께 사라지고 로그는 stdout
    전용이라, 발화와 답변이 함께 영속하는 곳은 세션 history 뿐이다). 문구가 바뀌면 지문이
    죽어 **조용히 0을 보고**하고, 0 은 "괜찮다"로 읽힌다 — 그게 이 스크립트 최대의 실패다.
    그래서 지문 검사를 여기 묶는다: 문구를 고치면 이 테스트가 먼저 깨진다.
    """

    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "harvest_sessions.py"
    spec = importlib.util.spec_from_file_location("harvest_sessions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._assert_fingerprints_alive()      # 지문이 죽었으면 SystemExit


# --- 로스터 밖 요청을 센다 (D117) -------------------------------------------------
def test_unsupported_request_is_recorded_without_changing_routing(monkeypatch,
                                                                  fresh_session_store):
    """플래너가 신고한 로스터 밖 요청은 **세션에 남고 라우팅은 그대로**다.

    로그는 stdout 전용이라 휘발하고 warnings 는 응답과 함께 사라진다 — 출시 뒤 무엇이
    오는지 알려면 영속하는 곳에 남아야 하고, 그 자리가 세션이다(수확기가 읽는다).
    라우팅을 바꾸지 않는 이유: 무엇이 오는지 모르는 채로 갈래를 만들면 근거 없는 판단을
    코드로 못 박게 된다. 먼저 센다.
    """

    stub_planner(monkeypatch, ["career_chat"])
    plan = AgentPlan(agents=["career_chat"], confidence=0.9,
                     unsupportedRequest="연봉 협상 어떻게 하는지 알려줘")
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))

    res = handle_chat(ChatRequest(sessionId="oos-1", message="연봉 협상 어떻게 하는지 알려줘"))

    assert res.dispatched == ["career_chat"]        # 라우팅 불변
    assert fresh_session_store.get("oos-1")["unsupported_requests"] == [
        "연봉 협상 어떻게 하는지 알려줘"]
    assert any(w["code"] == "unsupported_request" for w in res.warnings)


def test_unsupported_requests_are_capped(monkeypatch, fresh_session_store):
    """무한 성장 방지 — 수확용이라 전부 필요하지 않다."""

    from jobis_ai.orchestrator.session import UNSUPPORTED_MAX_ITEMS

    fresh_session_store.update("oos-2", {"unsupported_requests":
                                         [f"요청{i}" for i in range(UNSUPPORTED_MAX_ITEMS)]})
    plan = AgentPlan(agents=["career_chat"], confidence=0.9, unsupportedRequest="새 요청")
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))
    handle_chat(ChatRequest(sessionId="oos-2", message="새 요청"))

    stored = fresh_session_store.get("oos-2")["unsupported_requests"]
    assert len(stored) == UNSUPPORTED_MAX_ITEMS
    assert stored[-1] == "새 요청" and stored[0] == "요청1"     # 오래된 것부터 버린다


# --- 장애 격리 (D122): 멤버 하나의 예외가 턴 전체를 죽이지 않는다 ------------------
def test_agent_crash_is_isolated(monkeypatch):
    """에이전트가 예외로 죽어도 턴은 계속된다 — 경고 + 사용자향 안내 + 다음 멤버 실행."""

    from dataclasses import replace

    from jobis_ai.agents import get_agent_registry

    stub_planner(monkeypatch, ["resume_diagnosis", "career_chat"])

    real = get_agent_registry()

    def boom(sess):
        raise RuntimeError("의도된 폭발")

    broken = dict(real)
    broken["resume_diagnosis"] = replace(real["resume_diagnosis"], entry=boom)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.get_agent_registry", lambda: broken)

    res = handle_chat(ChatRequest(
        sessionId="crash-1", message="이력서 진단하고 커리어 고민도 들어줘",
        attachments=[_resume()],
    ))

    # 턴이 살아서 다음 멤버까지 돌았다 — 예외가 500 으로 새지 않는다.
    assert res.dispatched == ["resume_diagnosis", "career_chat"]
    # 격리는 은폐가 아니다(§2-6): 경고 코드와 원인이 남는다.
    crashed = [w for w in res.warnings if w["code"] == "agent_crashed"]
    assert crashed and "의도된 폭발" in crashed[0]["message"]
    # 사용자도 그 단계가 건너뛰어졌음을 듣는다.
    assert "건너뛰었어요" in res.reply


# --- 금지표현 문장 단위 완화 (D123): 한 단어가 답변 전체를 강등시키지 않는다 -----------
def test_drop_forbidden_sentences_keeps_clean_text():
    from jobis_ai.verify_rules import drop_forbidden_sentences

    text = ("면접 전에 회사 리서치를 하세요. 이건 반드시 합니다.\n"
            "1. CS 기초를 복습하세요.\n"
            "2. 합격 보장 코스를 들으세요.\n"
            "\n"
            "포트폴리오는 두 개면 충분해요.")
    kept, hits = drop_forbidden_sentences(text)

    assert "회사 리서치" in kept and "CS 기초" in kept and "포트폴리오" in kept
    assert "반드시" not in kept and "보장" not in kept
    assert "2." not in kept                      # 문장이 전부 걸린 줄은 줄째 사라진다
    assert set(hits) == {"반드시", "보장"}


def test_drop_forbidden_sentences_empty_when_all_forbidden():
    from jobis_ai.verify_rules import drop_forbidden_sentences

    kept, hits = drop_forbidden_sentences("무조건 붙습니다.")
    assert kept == "" and hits


def test_career_chat_softens_instead_of_full_fallback(monkeypatch):
    """정상 문장이 남아 있으면 고정 메뉴 문구로 강등하지 않는다 — 실측 2.5% 강등의 처방."""

    from jobis_ai.agents import career_chat

    monkeypatch.setattr(
        career_chat, "run_streaming_text",
        lambda *a, **k: ("공감합니다, 힘드시겠어요. 반드시 붙습니다.", []))
    res = career_chat.run({"last_message": "취업 너무 어렵다"})

    assert "공감합니다" in res.reply
    assert "반드시" not in res.reply
    assert res.reply != career_chat._FALLBACK
    assert any(w["code"] == "career_chat_softened" for w in res.warnings)


def test_career_chat_falls_back_when_nothing_survives(monkeypatch):
    from jobis_ai.agents import career_chat

    monkeypatch.setattr(
        career_chat, "run_streaming_text", lambda *a, **k: ("무조건 합격 가능해요.", []))
    res = career_chat.run({"last_message": "나 붙을까?"})

    assert res.reply == career_chat._FALLBACK
    assert any(w["code"] == "career_chat_fallback" for w in res.warnings)


# --- 저확신 계획 보존 (D124): 버리되 잃지 않는다 -------------------------------------
def test_low_confidence_plan_kept_as_confirm(monkeypatch, fresh_session_store):
    """확신 미달 계획은 실행하지 않되(기존 유지) 확인 버튼·동의권·계수로 남는다."""

    plan = AgentPlan(agents=["fit_analysis"], requestedAgents=["fit_analysis"],
                     confidence=0.4)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))

    res = handle_chat(ChatRequest(sessionId="lc-1", message="음 그거 어떻게 되려나"))

    assert res.dispatched == ["career_chat"]            # 저확신 실행 금지는 그대로
    assert any(q["field"] == "confirm_plan" for q in res.followUpQuestions)
    assert any(w["code"] == "low_confidence_plan" for w in res.warnings)
    # 다음 턴 동의 한마디로 이어지도록 동의 게이트 통과권이 남는다.
    assert fresh_session_store.get("lc-1")["pendingConsent"] == ["fit_analysis"]


def test_low_confidence_career_chat_guess_adds_no_button(monkeypatch, fresh_session_store):
    """추측이 career_chat 뿐이면 확인할 것이 없다 — 버튼·경고를 만들지 않는다."""

    plan = AgentPlan(agents=["career_chat"], requestedAgents=[], confidence=0.3)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))

    res = handle_chat(ChatRequest(sessionId="lc-2", message="에휴"))

    assert res.dispatched == ["career_chat"]
    assert not any(q.get("field") == "confirm_plan" for q in res.followUpQuestions)
    assert not any(w["code"] == "low_confidence_plan" for w in res.warnings)
