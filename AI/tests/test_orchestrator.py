"""대화 오케스트레이터 테스트 — 하네스와 에이전트 동작.

**추론은 자율, 행동과 상태 전이는 하네스로 좁힌다.** 무엇을 할지 고르는 것은 플래너 LLM 의
일이라 (발화 × 자산) 대응표가 코드에 없다 — 그 판단 품질은 evals/planner_dataset.json +
eval/planner_harness.py 가 측정한다. 여기서는 플래너의 선택을 주입해 두고
**그 뒤 하네스가 무엇을 하는지**를 결정적으로 검증한다.

LLM 은 conftest 가 강제 미설정하므로 에이전트들은 결정론 폴백 문구로 답한다.
"""

from __future__ import annotations

import pytest

from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.orchestrator import session as session_mod
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.orchestrator.planner import AgentPlan
from jobis_ai.orchestrator.session import SessionStore


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch):
    """테스트 간 세션 격리 — 전역 스토어를 매 테스트 새로 만든다."""

    store = SessionStore()
    monkeypatch.setattr(session_mod, "_STORE", store)
    return store


def stub_planner(monkeypatch, agents, ack: str = ""):
    """플래너의 선택을 주입한다 — LLM 추론을 대신하되 뒤 단계는 실제 코드가 돈다."""

    # requestedAgents=agents — 이 스텁은 "사용자가 이 기능을 청했다"는 뜻이다(게이트 동작은
    # test_planner.py 가 따로 본다).
    plan = AgentPlan(agents=list(agents), requestedAgents=list(agents),
                     confidence=0.9, ack=ack)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def _resume_attachment() -> ChatAttachment:
    return ChatAttachment(kind="resume", sourceType=SourceType.text,
                          value="Python Django 백엔드 개발 3년")


def _posting_attachment(value: str = "백엔드 개발자 모집. 필수: Python, Django 3년.") -> ChatAttachment:
    return ChatAttachment(kind="job_posting", sourceType=SourceType.text, value=value)


# --- 세션 스토어 --------------------------------------------------------------
def test_session_isolation_and_key_guard(fresh_session_store):
    fresh_session_store.update("a", {"resume": {"v": 1}})
    assert fresh_session_store.get("b") == {}          # 세션 격리
    with pytest.raises(KeyError):
        fresh_session_store.update("a", {"hacked": True})  # 미허용 키 차단


# --- 대화 왕복 ----------------------------------------------------------------
def test_chat_without_planner_opens_conversation():
    """플래너가 없어도(LLM 미설정) **대화로 받는다** — 기능 목록만 읽어주고 끝내지 않는다."""

    res = handle_chat(ChatRequest(sessionId="s1", message="안녕하세요"))
    assert res.dispatched == ["career_chat"]
    assert res.reply.strip()


def test_chat_preference_intake_opens_dialog(monkeypatch):
    """이력서 없는 추천 요청에 플래너가 선호 파악을 고르면 → 닫힌 되묻기 없이 대화가 열린다."""

    stub_planner(monkeypatch, ["preference_intake"])
    res = handle_chat(ChatRequest(sessionId="s2", message="공고 추천해줘"))
    assert res.dispatched == ["preference_intake"]
    assert "직군" in res.reply            # 어떤 공고를 원하는지 묻는다
    assert res.followUpQuestions          # 대화가 이어질 신호


def test_chat_attachment_only_continues():
    """자료만 준 턴도 **멈추지 않는다** — 접수 확인 + 실행까지 이어진다."""

    res = handle_chat(ChatRequest(sessionId="s3", attachments=[_resume_attachment()]))
    assert "이력서를 받았어요" in res.reply   # 접수 확인은 유지
    assert res.dispatched                    # 그리고 실행까지 이어진다


# 공고 표지어 없는 이력서 원문 — 혼합 메시지 인테이크 시험용 (실측 2026-07-31 재현).
_PASTED_RESUME = (
    "성명: 신율. 지원 직무: AI Engineer.\n"
    "Key Summary: LLM Agent 및 RAG 시스템 구축 경험 — LangChain, LangGraph 기반 복합 "
    "에이전트 개발 프로젝트 총괄.\n"
    "학력: OO대학교 학사 졸업 (4년제).\n"
    "교육: SSAFY AI/SW 개발자 과정 집중 수료.\n"
    "주요 프로젝트 경험: 멀티 에이전트 기반 문서 분석·보고서 자동 생성 시스템 — Stateful "
    "Multi-Agent 워크플로우 설계, RAG 파이프라인 구축, Langfuse 모니터링 체계 구축."
)


def test_mixed_message_url_and_resume_are_both_staged(fresh_session_store, monkeypatch):
    """공고 URL + 이력서 원문 + 요청 문장이 **한 메시지**에 섞여 온 턴(실측 2026-07-31):
    URL 은 공고 자산으로, 이력서 원문은 이력서 자산으로 각각 승격되고, 요청 문장이 담긴
    메시지는 플래너 입력으로 보존된다 — 이력서를 못 알아보고 '이력서가 없다'로 흐르면 안 된다."""

    seen: dict = {}

    def _spy_planner(message, session):
        seen["message"] = message
        seen["submitted"] = list(session.get("_submittedThisTurn") or [])
        return None, []   # 플래너 불가 → career_chat 폴백(인테이크만 본다)

    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents", _spy_planner)
    # 오케스트레이터가 posting_fetch 를 결정론 삽입하므로 수집기(네트워크)를 no-op 으로 막는다.
    monkeypatch.setattr("jobis_ai.agents.posting_fetch.ensure_posting_text",
                        lambda session: (session.get("job_posting"), []))
    message = (
        "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=54532265 이게 내 목표공고이고, "
        + _PASTED_RESUME + " 이게 내 이력서야. 공고와 이력서 각각 분석하고 적합도 분석 진행해줘"
    )
    res = handle_chat(ChatRequest(sessionId="s-mixed", message=message))

    saved = fresh_session_store.get("s-mixed")
    assert saved["job_posting"]["sourceType"] == "url"          # URL → 공고 자산
    assert "SSAFY" in saved["resume"]["value"]                  # 원문 → 이력서 자산
    assert "https://" not in saved["resume"]["value"]           # URL 은 이력서에 섞지 않는다
    assert "공고 링크를 받았어요" in res.reply and "이력서를 받았어요" in res.reply
    assert sorted(seen["submitted"]) == ["job_posting", "resume"]   # 플래너 그라운딩 입력
    assert "적합도 분석 진행해줘" in seen["message"]            # 요청 문장은 플래너가 읽는다


def test_ambiguous_long_message_is_not_staged_as_resume(fresh_session_store):
    """긴 상담 발화는 이력서로 승격하지 않는다 — 확신 있을 때만 뒤집는다는 원칙 유지."""

    long_chat = (
        "요즘 백엔드 직군 준비를 하면서 고민이 많습니다. 스프링을 먼저 깊게 파야 할지, "
        "아니면 CS 기초(운영체제, 네트워크, 데이터베이스)를 다시 정리해야 할지 순서를 못 정하겠어요. "
        "코딩 테스트 준비도 병행해야 해서 하루를 어떻게 나눠 써야 할지 모르겠습니다. "
        "지금 상황에서 무엇부터 하는 게 좋을까요? 조언 부탁드립니다."
    )
    handle_chat(ChatRequest(sessionId="s-chat", message=long_chat))
    assert not fresh_session_store.get("s-chat").get("resume")


def test_chat_recommend_flow_without_rag_is_honest(monkeypatch):
    """이력서 첨부 + 추천 실행 → RAG 미연결이면 허구 추천 없이 정직한 응답."""

    stub_planner(monkeypatch, ["job_recommend"])
    res = handle_chat(ChatRequest(
        sessionId="s4", message="내 이력서로 갈 수 있는 곳 추천해줘",
        attachments=[_resume_attachment()],
    ))
    assert res.dispatched == ["job_recommend"]
    assert res.intent == "job_recommend"
    assert "추천" in res.reply
    # NullRagAdapter 환경 — 추천을 지어내지 않는다
    assert res.results["job_recommend"]["recommendations"] == []


def test_chat_posting_only_runs_posting_analysis(monkeypatch):
    """공고만 있는 상태 — 공고 정리 결과를 주고 이력서를 자연스럽게 요청한다."""

    stub_planner(monkeypatch, ["posting_analysis"])
    res = handle_chat(ChatRequest(
        sessionId="s6", message="이 공고 나 되나?", attachments=[_posting_attachment()],
    ))
    assert res.dispatched == ["posting_analysis"]
    assert "이력서" in res.reply                      # 결과를 주고 자연스럽게 요청
    assert res.followUpQuestions                      # 다음 입력 유도
    assert res.results["posting_analysis"]["postingAnalysis"]


def test_short_resume_attachment_cannot_replace_stored_resume(monkeypatch, fresh_session_store):
    """D98: 자료 요청 슬롯으로 들어온 **짧은 대답**이 저장된 이력서를 교체하지 못한다.

    사고 경로: 카드가 `field="resume"` 슬롯을 열어 둔 동안 사용자가 "네" 라고 답하면 그것이
    `kind="resume"` 첨부로 온다. `resolve_kind` 는 MIN_ASSET_CHARS 미만이면 판정을 포기하고
    claimed 를 그대로 돌려주므로, 저장 단계가 그걸 믿으면 한 줄이 이력서 + 파생 자산
    (profile·analysis)을 통째로 지운다.

    되돌린 텍스트는 **버리지 않고 발화로** 돌아가야 한다 — 버리면 사용자의 동의가 사라져
    플래너가 다음 단계를 못 고른다.
    """

    resume = {"sourceType": "text",
              "value": "Python Django 백엔드 3년. 프로젝트: 결제 시스템 개선, 정산 배치 재작성."}
    fresh_session_store.update("s_d98", {
        "resume": resume,
        "profile": {"skills": [{"name": "Python"}]},
        "analysis": {"status": "completed"},
    })
    stub_planner(monkeypatch, ["career_chat"])

    res = handle_chat(ChatRequest(
        sessionId="s_d98", message="",
        attachments=[ChatAttachment(kind="resume", sourceType=SourceType.text, value="네")],
    ))
    stored = fresh_session_store.get("s_d98")
    assert stored["resume"] == resume                 # 교체되지 않았다
    assert stored["profile"] and stored["analysis"]    # 파생 자산도 무효화되지 않았다
    assert stored["last_message"] == "네"              # 발화로 되돌아갔다
    # §2-6 — 폴백이 이유를 삼키지 않는다
    assert any(w["code"] == "short_resume_demoted" for w in res.warnings)

    # 반대 방향: 이력서 길이의 텍스트는 그대로 교체한다(가드가 정상 경로를 막지 않는다).
    new_resume = "Java Spring 백엔드 5년. 프로젝트: 사내 결제 게이트웨이 설계 및 운영, 트래픽 3배 처리."
    handle_chat(ChatRequest(
        sessionId="s_d98", message="",
        attachments=[ChatAttachment(kind="resume", sourceType=SourceType.text, value=new_resume)],
    ))
    assert fresh_session_store.get("s_d98")["resume"]["value"] == new_resume


def test_posting_analysis_does_not_ask_for_resume_it_already_has(monkeypatch, fresh_session_store):
    """D98 의 짝 — 이미 있는 이력서를 다시 청하지 않는다(요청 슬롯을 열지 않는다).

    저장 가드만 닫고 이 카드를 남기면 다음 턴에 같은 슬롯이 다시 열린다.
    """

    from jobis_ai.agents import posting_analysis

    monkeypatch.setattr(
        "jobis_ai.agents.posting_analysis.parse_job_posting",
        lambda state: {"normalizedJobPosting": {"jobTitle": "백엔드", "techStack": ["Python"]},
                       "warnings": []})
    posting = {"job_posting": {"sourceType": "text", "value": "백엔드 채용. 자격요건: Python."}}

    assert posting_analysis.run(dict(posting)).followUpQuestions       # 이력서 없음 → 청한다
    with_resume = {**posting, "resume": {"sourceType": "text", "value": "Python 3년"}}
    assert posting_analysis.run(with_resume).followUpQuestions == []   # 있음 → 청하지 않는다


def test_chat_infeasible_choice_falls_back_to_conversation(monkeypatch):
    """플래너가 지금 못 할 일을 골라도 실행하지 않는다 — 대화형 에이전트가 턴을 받는다.

    액션 스페이스 제한의 사후 검증: 상태 전이는 실행 가능한 것만 일으킨다.
    """

    stub_planner(monkeypatch, ["fit_analysis"])   # 이력서 없음 → 실행 불가
    res = handle_chat(ChatRequest(
        sessionId="s8", message="이 공고 나 되나?", attachments=[_posting_attachment()],
    ))
    assert res.dispatched == ["career_chat"]
    assert res.reply.strip()


def test_chat_heavy_precondition_asks_consent(monkeypatch):
    """무거운 생산자(fit_analysis)가 자동 삽입될 상황 — 말없이 시작하지 않고 먼저 묻는다.

    수십 초·LLM 여러 회짜리 파이프라인은 note 로 알리며 시작하는 게 아니라,
    실행 전에 동의를 받는다(동의 게이트). 동의하면 다음 턴 플래너가 명시적으로 고른다.
    """

    stub_planner(monkeypatch, ["coverletter_draft"])
    res = handle_chat(ChatRequest(
        sessionId="s9", message="자소서 써줘",
        attachments=[_resume_attachment(), _posting_attachment()],
    ))
    assert res.dispatched == []                       # 아직 아무것도 실행하지 않았다
    assert "진행할까요" in res.reply                   # 먼저 묻는다
    assert any(q.get("field") == "confirm_pipeline" for q in res.followUpQuestions)


def test_chat_explicit_heavy_producer_runs_without_gate(monkeypatch):
    """플래너가 fit_analysis 를 명시적으로 골랐으면(동의 턴) 게이트 없이 그대로 실행한다."""

    stub_planner(monkeypatch, ["fit_analysis", "coverletter_draft"])
    res = handle_chat(ChatRequest(
        sessionId="s9b", message="응 진행해줘",
        attachments=[_resume_attachment(), _posting_attachment()],
    ))
    # D71: 이번 턴에 제출된 자료의 정리 단계(공고 분석·이력서 진단)가 판정 앞에 끼워진다 —
    # 게이트 없이 실행되는 것은 그대로다.
    assert res.dispatched[:3] == ["posting_analysis", "resume_diagnosis", "fit_analysis"]


def test_blocked_request_is_remembered_asked_and_resumed(monkeypatch, fresh_session_store):
    """D72 요청 완수 보장: 공고만 있는 턴에 적합도를 청하면 — ① 요청을 기억하고
    ② 부족한 자료(이력서)의 되묻기를 구조로 보장하며 ③ 자료가 오는 턴에 플래너 선택과
    무관하게 결정론으로 이어서 완수한다."""

    plan1 = AgentPlan(agents=["posting_analysis"], requestedAgents=["posting_analysis"],
                      blockedRequests=["fit_analysis"], confidence=0.9)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan1, []))
    first = handle_chat(ChatRequest(
        sessionId="pr-1", message="이 공고에 나 되는지 적합도 분석해줘",
        attachments=[_posting_attachment()]))
    saved = fresh_session_store.get("pr-1")
    assert saved["pendingRequest"]["agent"] == "fit_analysis"          # ① 기억
    assert saved["pendingRequest"]["missing"] == "resume"
    assert any(q.get("field") == "resume" for q in first.followUpQuestions)   # ② 되묻기 보장

    # 다음 턴 — 이력서 제출. 플래너는 제출 정리(rule 3)만 골라도 적합도가 이어진다.
    plan2 = AgentPlan(agents=["resume_diagnosis"], requestedAgents=[], confidence=0.9)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan2, []))
    second = handle_chat(ChatRequest(
        sessionId="pr-1", message="", attachments=[_resume_attachment()]))
    assert "fit_analysis" in second.dispatched                          # ③ 결정론 재큐
    assert "이어서 진행할게요" in second.reply
    assert not fresh_session_store.get("pr-1").get("pendingRequest")   # 완수 후 잊는다


def test_blocked_request_expires_after_budget(monkeypatch, fresh_session_store):
    """자료가 끝내 오지 않으면 수명(턴)이 소진되고 잊는다 — 오래된 요청이 엉뚱한 턴에
    무거운 작업을 말없이 되살리지 않는다."""

    fresh_session_store.update("pr-2", {
        "pendingRequest": {"agent": "fit_analysis", "missing": "resume", "turnsLeft": 1}})
    stub_planner(monkeypatch, ["career_chat"])
    handle_chat(ChatRequest(sessionId="pr-2", message="취업 너무 어렵다"))
    assert not fresh_session_store.get("pr-2").get("pendingRequest")


def test_multiple_posting_urls_are_all_accepted(fresh_session_store, monkeypatch):
    """D94: 한 발화의 공고 URL 여러 개를 전부 접수한다 — 첫 URL 은 활성 공고, 나머지는
    posting_analysis 가 같은 턴에 병렬 수집·파싱해 라이브러리로 승격한다.
    실측(16:01): URL 두 개 중 두 번째가 조용히 버려졌다."""

    from jobis_ai.orchestrator.chat import detect_posting_urls

    msg = ("https://www.jobkorea.co.kr/Recruit/GI_Read/49657965?sc=552 /  "
           "https://www.jobkorea.co.kr/Recruit/GI_Read/49567531?sc=630 나 이두개 공고 관심있어")
    urls = detect_posting_urls(msg, {})
    assert len(urls) == 2 and "49657965" in urls[0] and "49567531" in urls[1]

    # 턴 통합: 활성=첫 URL, 나머지는 턴 마커로 posting_analysis 에 전달
    seen: dict = {}

    def _spy_planner(message, session):
        seen["extra"] = list(session.get("_extraPostingUrls") or [])
        return None, []

    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents", _spy_planner)
    monkeypatch.setattr("jobis_ai.agents.posting_fetch.ensure_posting_text",
                        lambda session: (session.get("job_posting"), []))
    res = handle_chat(ChatRequest(sessionId="multi-url", message=msg))
    saved = fresh_session_store.get("multi-url")
    assert "49657965" in saved["job_posting"]["value"]            # 첫 URL = 활성
    assert seen["extra"] and "49567531" in seen["extra"][0]       # 나머지 = 병렬 처리 대상
    assert "공고 링크 2개를 받았어요" in res.reply


def test_posting_analysis_processes_extra_urls_in_parallel(monkeypatch):
    """D94: 추가 URL 들이 수집·파싱돼 라이브러리로 승격되고, 답변에 각 공고 정리가 실린다."""

    from jobis_ai.agents import posting_analysis, tool_render

    class _Extracted:
        def __init__(self, text): self.text, self.warnings = text, []

    monkeypatch.setattr("jobis_ai.extract.extract_text",
                        lambda src: _Extracted(f"원문 {src.get('value')}"))
    parsed = iter([
        {"normalizedJobPosting": {"jobTitle": "A직무", "companyName": "회사A",
                                  "techStack": ["Python"]}, "warnings": []},
        {"normalizedJobPosting": {"jobTitle": "B직무", "companyName": "회사B",
                                  "techStack": ["Java"]}, "warnings": []},
    ])
    monkeypatch.setattr("jobis_ai.agents.posting_analysis.parse_job_posting",
                        lambda state: next(parsed))

    session = {"job_posting": {"sourceType": "text", "value": "활성 공고 원문"},
               "_extraPostingUrls": ["https://x/2"]}
    out = posting_analysis.run(session)
    library = out.sessionUpdates["posting_library"]
    assert {p["companyName"] for p in library} == {"회사A", "회사B"}   # 둘 다 승격
    assert out.data["extraPostings"][0]["companyName"] == "회사B"

    monkeypatch.setattr("jobis_ai.agents.tool_render.run_streaming_text",
                        lambda s, u, node: ("다음으로 무엇을 볼까요?", []))
    reply, _ = tool_render.render_posting_analysis(out.data, session)
    assert "회사A" in reply and "회사B" in reply                    # 두 공고 모두 답변에


def test_schemeless_job_site_url_in_sentence_is_detected():
    """D80: 문장 속 스킴 없는 채용 사이트 주소도 공고로 승격한다(한글 쿼리 포함).
    일반 도메인 언급은 받지 않는다 — 언급만 한 링크가 공고 자산을 덮으면 안 된다."""

    from jobis_ai.orchestrator.chat import detect_posting_url

    msg = ("saramin.co.kr/zf_user/jobs/relay/view?rec_idx=54517546&searchword=ai엔지니어"
           "&t_ref_content=generic 공고분석해줘")
    assert detect_posting_url(msg, {}).startswith("https://saramin.co.kr/zf_user/jobs")
    assert "공고분석해줘" not in detect_posting_url(msg, {})   # 주소 토큰만 취한다

    assert detect_posting_url("github.com/example/repo 코드는 여기 올렸어요", {}) == ""
    # 발화 전체가 주소 한 토큰이면 기존 규칙대로 도메인 제한 없음
    assert detect_posting_url("company.example.com/careers/123", {}).startswith("https://")


def test_posting_analysis_reuses_cached_parse(monkeypatch):
    """D79: 같은 공고 원문은 다시 파싱하지 않는다 — 파싱 결과를 세션에 캐시(해시 대조)하고,
    조회성 재실행은 캐시로 즉답한다. 원문이 바뀌면 다시 파싱한다."""

    from jobis_ai.agents import posting_analysis

    calls = {"n": 0}

    def fake_parse(state):
        calls["n"] += 1
        return {"normalizedJobPosting": {"jobTitle": "백엔드", "techStack": ["Python"]},
                "warnings": []}

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.parse_job_posting", fake_parse)
    session = {"job_posting": {"sourceType": "text", "value": "백엔드 채용. 자격요건: Python."}}

    first = posting_analysis.run(session)
    assert calls["n"] == 1
    assert first.sessionUpdates.get("posting_summary", {}).get("_sourceHash")
    session.update(first.sessionUpdates)          # 오케스트레이터의 sessionUpdates 반영

    second = posting_analysis.run(session)
    assert calls["n"] == 1                        # 재파싱 없음 — 캐시 재사용
    assert second.data["postingAnalysis"]["jobTitle"] == "백엔드"

    session["job_posting"] = {"sourceType": "text", "value": "다른 공고. 자격요건: Java."}
    posting_analysis.run(session)
    assert calls["n"] == 2                        # 원문이 바뀌면 다시 파싱


def test_posting_analysis_loop_owns_the_reply(monkeypatch):
    """D97 승격: 루프가 답하면 **그 답이 전부다** — 결정론 요약 표를 덧붙이지 않는다.

    실측(2026-08-01): 표를 앞에 붙였더니 루프가 같은 요건을 611자로 다시 정리한 뒤 제안을
    이어 붙여 사용자가 같은 목록을 두 번 봤다. 한 문장의 생산자가 둘이면 프롬프트로 못
    막는다(§2-2 금지는 구조로) — 그래서 표를 폴백 경로에만 남겼다. 이 테스트가 그 경계다.

    루프가 문장을 못 만들면 승격 **전과 같은** 결정론 표현으로 폴백해야 한다 —
    LLM 미설정 환경에서 기능이 죽지 않는 것이 승격의 전제였다.
    """

    from jobis_ai.agents import posting_analysis
    from jobis_ai.agents.agent_loop import LoopOutcome

    monkeypatch.setattr(
        "jobis_ai.agents.posting_analysis.parse_job_posting",
        lambda state: {"normalizedJobPosting": {"jobTitle": "백엔드", "companyName": "회사A",
                                                "techStack": ["Python", "Kafka"]},
                       "warnings": []})
    session = {"job_posting": {"sourceType": "text", "value": "백엔드 채용. 자격요건: Python, Kafka."}}

    seen: dict = {}

    def fake_loop(**kw):
        seen.update(kw["facts"])
        return LoopOutcome(reply="Kafka부터 보시면 좋아요.")

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.run_agent_loop", fake_loop)
    first = posting_analysis.run(session)
    assert first.reply == "Kafka부터 보시면 좋아요."   # 표를 덧붙이지 않는다
    assert seen["firstLook"] is True
    # 근거는 도구가 준 파싱 결과다 — 루프가 요건을 볼 수 있어야 학습 순서를 세운다(§2-5).
    assert seen["posting"]["techStack"] == ["Python", "Kafka"]
    session.update(first.sessionUpdates)

    second = posting_analysis.run(session)         # 같은 원문 = 후속 질문 턴
    assert second.data["fromCache"] is True
    assert seen["firstLook"] is False
    assert second.reply == "Kafka부터 보시면 좋아요."

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.run_agent_loop",
                        lambda **kw: LoopOutcome(reply="", warnings=[{"code": "llm_call_failed"}]))
    fallback = posting_analysis.run(session)
    assert "**요구 기술**" in fallback.reply        # 결정론 표현으로 폴백
    assert any(w["code"] == "llm_call_failed" for w in fallback.warnings)  # 이유를 삼키지 않는다


def test_posting_analysis_read_posting_tool():
    """루프의 근거는 공고 원문이다 — 못 찾으면 **못 찾았다고** 돌려준다(§2-5).

    빈 관찰을 주면 LLM 이 그 자리를 사전지식으로 채운다. 그래서 실패도 사실로 말한다.
    """

    from jobis_ai.agents.posting_analysis import _tool_read_posting

    state = {"_text": "전형 절차: 서류 → 코딩테스트 → 면접\n복리후생: 재택 근무\n자격요건: Python"}
    hit, _ = _tool_read_posting(state, "전형")
    assert "코딩테스트" in hit
    assert "복리후생" not in hit                    # 물은 줄만
    miss, _ = _tool_read_posting(state, "연봉")
    assert "찾지 못했습니다" in miss
    assert "없습니다" in _tool_read_posting({}, "전형")[0]   # 원문 자체가 없을 때


def test_career_chat_receives_stored_facts(monkeypatch):
    """D79: 공고 요건·분석 결과 조회 질문은 저장된 정형 사실로 답한다 — career_chat 입력에
    postingFacts/analysisFacts 가 실린다(재분석 없음)."""

    import json as json_mod

    from jobis_ai.agents import career_chat

    seen: dict = {}

    def fake_stream(system, user_content, node):
        seen["context"] = json_mod.loads(user_content)["context"]
        return "필수 요건은 Python 실무 경험 1건이었어요.", []

    monkeypatch.setattr("jobis_ai.agents.career_chat.run_streaming_text", fake_stream)
    career_chat.run({
        "last_message": "공고에서 필요로 하는 항목들이 뭐뭐 있었지?",
        "posting_summary": {"_sourceHash": "x", "jobTitle": "AI 엔지니어",
                            "requiredRequirements": [{"text": "Python 실무"}],
                            "techStack": ["Python"]},
        "analysis": {"fitGrade": "중", "gaps": [{"reason": "K8s 근거 부족"}]},
    })
    facts = seen["context"]["postingFacts"]
    assert facts["requiredRequirements"] == ["Python 실무"]
    assert seen["context"]["analysisFacts"]["fitGrade"] == "중"


def test_posting_library_keeps_previous_postings(monkeypatch):
    """D86: 새 공고가 활성 슬롯을 교체해도 정리했던 공고들의 지식은 라이브러리에 남고,
    career_chat 이 이전 공고 질문에 그 사실로 답할 수 있다(실측: '무관한 회사' 오답)."""

    import json as json_mod

    from jobis_ai.agents import career_chat, posting_analysis
    from jobis_ai.agents._common import upsert_posting_library

    # 라이브러리 upsert — 같은 원문은 교체, 상한(5) 초과는 오래된 것부터 제거
    session: dict = {}
    for i in range(7):
        summary = {"_sourceHash": f"h{i}", "companyName": f"회사{i}"}
        session["posting_library"] = upsert_posting_library(session, summary)
    assert len(session["posting_library"]) == 5
    assert session["posting_library"][0]["companyName"] == "회사2"   # 오래된 것 제거

    # posting_analysis 가 파싱을 라이브러리에도 올린다
    monkeypatch.setattr("jobis_ai.agents.posting_analysis.parse_job_posting",
                        lambda state: {"normalizedJobPosting": {
                            "jobTitle": "AI 엔지니어", "companyName": "에이아이스페라",
                            "techStack": ["AWS"]}, "warnings": []})
    out = posting_analysis.run(
        {"job_posting": {"sourceType": "text", "value": "에이아이스페라 채용"}})
    assert any(p.get("companyName") == "에이아이스페라"
               for p in out.sessionUpdates["posting_library"])

    # career_chat 이 활성 공고(포티투마루)와 무관한 이전 공고(에이아이스페라)의 사실을 받는다
    seen: dict = {}

    def fake_stream(system, user_content, node):
        seen["context"] = json_mod.loads(user_content)["context"]
        return "에이아이스페라 공고의 요구 기술에는 AWS 가 있었어요.", []

    monkeypatch.setattr("jobis_ai.agents.career_chat.run_streaming_text", fake_stream)
    career_chat.run({
        "last_message": "에이아이스페라에서는?",
        "posting_summary": {"_sourceHash": "b", "companyName": "포티투마루"},
        "posting_library": [
            {"_sourceHash": "a", "companyName": "에이아이스페라", "techStack": ["AWS"]},
            {"_sourceHash": "b", "companyName": "포티투마루", "techStack": ["React"]},
        ],
    })
    companies = [p["companyName"] for p in seen["context"]["postingLibrary"]]
    assert companies == ["에이아이스페라", "포티투마루"]


def test_independent_trio_runs_in_parallel(monkeypatch):
    """P3(확장 계획) 재현: 제출 턴의 정리 2개+판정은 서로 독립이라 **한 병렬 배치**로 묶인다
    — parallel_group 이 실제 대화 경로에서 발동하는지 결정적으로 고정한다."""

    from jobis_ai import trace

    stub_planner(monkeypatch, ["fit_analysis"])
    events: list = []
    with trace.recording(sink=events.append):
        handle_chat(ChatRequest(
            sessionId="par-1", message="적합도 분석해줘",
            attachments=[_resume_attachment(), _posting_attachment()]))
    parallel = [e for e in events if e.get("kind") == "parallel"]
    assert parallel, "병렬 배치가 잡히지 않았다"
    assert set(parallel[0]["detail"]["agents"]) == {
        "posting_analysis", "resume_diagnosis", "fit_analysis"}


def test_application_plan_delegates_to_job_recommend(monkeypatch):
    """P1-a(D91): '유사공고 병행' 경로에 job_recommend 의 실공고가 읽기 전용 위임으로 실린다.
    전제(resume|preferences)가 없으면 실행하지 않고 거부만 관찰로 남긴다."""

    from jobis_ai import trace
    from jobis_ai.agents import AgentResult as _AR
    from jobis_ai.agents import application_plan

    monkeypatch.setattr(
        "jobis_ai.agents.job_recommend.run",
        lambda sess: _AR(reply="", data={"recommendations": [
            {"companyName": "회사A", "title": "백엔드 개발자", "url": "http://a"},
        ]}, sessionUpdates={"recommendations": []}))

    analysis = {"status": "completed", "overallScore": 0.5, "requirements": [],
                "gaps": [], "strengths": [], "roadmap": []}
    session = {"analysis": analysis,
               "resume": {"sourceType": "text", "value": "Python 3년"}}
    events: list = []
    with trace.recording(sink=events.append):
        out = application_plan.run(session)
    parallel_route = next(r for r in out.data["applicationPlan"]["routes"]
                          if r["id"] == "parallel")
    assert parallel_route["relatedPostings"][0]["companyName"] == "회사A"
    assert "회사A" in out.reply                                   # 대화 답변에도 실린다
    assert any(e["kind"] == "delegate" for e in events)           # 위임 성공 관찰

    # 전제 없는 세션 — 거부가 분모로 남고, 경로는 기존 문구로 폴백
    events.clear()
    with trace.recording(sink=events.append):
        out = application_plan.run({"analysis": analysis})
    parallel_route = next(r for r in out.data["applicationPlan"]["routes"]
                          if r["id"] == "parallel")
    assert parallel_route["relatedPostings"] == []
    assert any(e["kind"] == "delegate_refused" for e in events)


def test_fit_analysis_judges_multiple_targets(monkeypatch):
    """D88: '두 공고 각각 적합도' — targets 인자로 라이브러리 공고들을 대상별 판정하고,
    analysis 자산은 활성 공고의 판정일 때만 승격한다(근거-대상 불일치 방지)."""

    import hashlib as _hashlib

    from jobis_ai.agents import fit_analysis, tool_render

    seeded: list = []

    class _Resp:
        status = "completed"
        roadmap: list = []
        warnings: list = []
        followUpQuestions: list = []

        @staticmethod
        def model_dump():
            return {"status": "completed", "fitGrade": "중", "overallScore": 0.6,
                    "summary": "요약", "gaps": [{"reason": "격차1"}], "roadmap": []}

    def fake_pipeline(state):
        seeded.append(state["normalizedJobPosting"]["companyName"])
        return _Resp(), dict(state)

    monkeypatch.setattr("jobis_ai.agents.fit_analysis.run_pipeline_with_state", fake_pipeline)
    active_value = "원더스랩 공고 원문"
    active_hash = _hashlib.md5(active_value.encode("utf-8")).hexdigest()
    session = {
        "job_posting": {"sourceType": "text", "value": active_value},
        "resume": {"sourceType": "text", "value": "이력서"},
        "posting_library": [
            {"_sourceHash": active_hash, "companyName": "원더스랩"},
            {"_sourceHash": "other", "companyName": "오로라월드㈜"},
        ],
        "_agentArgs": {"fit_analysis": {"targets": "원더스랩, 오로라월드, 없는회사"}},
    }
    out = fit_analysis.run(session)

    assert seeded == ["원더스랩", "오로라월드㈜"]                 # 대상별 시드·반복 판정
    assert [r["company"] for r in out.data["multiFit"]] == ["원더스랩", "오로라월드㈜"]
    assert out.data["unmatchedTargets"] == ["없는회사"]
    assert out.sessionUpdates.get("analysis")                     # 활성(원더스랩) 판정만 승격

    reply, _ = tool_render.render_fit_analysis(out.data, session)
    assert "**원더스랩**" in reply and "**오로라월드㈜**" in reply   # 회사별 블록
    assert "없는회사" in reply and "다시 보내주시면" in reply       # 미매칭 복구 안내


def test_fit_analysis_shares_blackboard_knowledge(monkeypatch):
    """D84 화이트보드: fit_analysis 는 보드의 지식(공고 파싱·프로필)을 그래프에 실어
    재생산을 막고(웜), 그래프가 새로 만든 지식은 보드로 승격한다(콜드)."""

    import hashlib as _hashlib

    from jobis_ai.agents import fit_analysis

    captured: dict = {}

    class _Resp:
        status = "completed"
        roadmap: list = []
        warnings: list = []
        followUpQuestions: list = []

        @staticmethod
        def model_dump():
            return {"status": "completed", "fitGrade": "중", "roadmap": []}

    def fake_pipeline(state):
        captured["state"] = dict(state)
        return _Resp(), {
            "normalizedJobPosting": {"jobTitle": "백엔드", "techStack": ["Python"]},
            "normalizedUserProfile": {"skills": [{"name": "Python"}]},
        }

    monkeypatch.setattr("jobis_ai.agents.fit_analysis.run_pipeline_with_state", fake_pipeline)
    posting_value = "백엔드 채용. 자격요건: Python."
    session = {"job_posting": {"sourceType": "text", "value": posting_value},
               "resume": {"sourceType": "text", "value": "Python 3년"}}

    out = fit_analysis.run(session)                       # 콜드 — 그래프 산출을 보드로 승격
    assert out.sessionUpdates["posting_summary"]["jobTitle"] == "백엔드"
    assert out.sessionUpdates["posting_summary"]["_sourceHash"]
    assert out.sessionUpdates["profile"]["skills"]
    assert "normalizedJobPosting" not in captured["state"]   # 보드가 비어 있었으니 시드 없음

    src_hash = _hashlib.md5(posting_value.encode("utf-8")).hexdigest()
    session["posting_summary"] = {"_sourceHash": src_hash, "jobTitle": "백엔드"}
    session["profile"] = {"skills": [{"name": "Python"}]}
    out = fit_analysis.run(session)                       # 웜 — 보드의 지식을 그래프에 시드
    assert captured["state"]["normalizedJobPosting"]["jobTitle"] == "백엔드"
    assert captured["state"]["normalizedUserProfile"]["skills"]
    assert "posting_summary" not in out.sessionUpdates    # 이미 보드에 있는 것은 재승격 없음
    assert "profile" not in out.sessionUpdates


def test_fit_analysis_single_target_switches_active_posting(monkeypatch):
    """지목이 하나면 그 공고가 **활성 공고**가 된다 — 하류 자소서·면접은 활성 하나만 본다.

    실측 결함(2026-08-02): `targets` 가 하나면 반복 판정 경로에 들어가지도 못하고 활성 공고가
    그대로 판정돼, "예전에 본 그 공고로 자소서"가 다른 회사 자소서를 냈다.
    """

    import hashlib as _hashlib

    from jobis_ai.agents import fit_analysis
    from jobis_ai.agents._common import posting_identity

    seeded: list = []

    class _Resp:
        status = "completed"
        roadmap: list = []
        warnings: list = []
        followUpQuestions: list = []

        @staticmethod
        def model_dump():
            return {"status": "completed", "fitGrade": "중", "roadmap": []}

    def fake_pipeline(state):
        seeded.append(dict(state["normalizedJobPosting"]))
        return _Resp(), dict(state)

    monkeypatch.setattr("jobis_ai.agents.fit_analysis.run_pipeline_with_state", fake_pipeline)
    active_value, old_value = "원더스랩 공고 원문", "오로라월드 공고 원문"
    session = {
        "job_posting": {"sourceType": "text", "value": active_value},
        "resume": {"sourceType": "text", "value": "이력서"},
        "posting_summary": {
            "_sourceHash": _hashlib.md5(active_value.encode("utf-8")).hexdigest(),
            "companyName": "원더스랩", "jobTitle": "백엔드"},
        "posting_library": [{
            "_sourceHash": _hashlib.md5(old_value.encode("utf-8")).hexdigest(),
            "_sourceText": old_value, "companyName": "오로라월드㈜", "jobTitle": "프론트엔드"}],
        "_agentArgs": {"fit_analysis": {"targets": "오로라월드"}},
    }
    out = fit_analysis.run(session)

    assert [p["companyName"] for p in seeded] == ["오로라월드㈜"]       # 지목한 공고로 판정
    assert not any(k.startswith("_") for k in seeded[0])               # 밑줄 키는 그래프로 안 샌다
    assert out.sessionUpdates["job_posting"]["value"] == old_value     # 원문까지 되돌린다
    assert out.sessionUpdates["posting_summary"]["companyName"] == "오로라월드㈜"
    assert out.sessionUpdates.get("analysis")                          # 활성이므로 승격된다
    # 하류 생성 에이전트가 보는 대상이 바뀌었다 — 여기가 자소서 회사명이 갈리던 지점.
    assert posting_identity({**session, **out.sessionUpdates})[0] == "오로라월드㈜"

    # 라이브러리에 없는 이름이면 활성 공고 그대로 — 조용히 틀리지 않게 이유를 남긴다.
    seeded.clear()
    session["_agentArgs"] = {"fit_analysis": {"targets": "없는회사"}}
    out = fit_analysis.run(session)
    assert [p["companyName"] for p in seeded] == ["원더스랩"]
    assert "job_posting" not in out.sessionUpdates
    assert any(w["code"] == "fit_target_not_found" for w in out.warnings)


def test_build_user_profile_reuses_seeded_profile():
    """D84: 그래프의 프로필 노드는 멱등 — 보드에서 실어 준 프로필이 있으면 재추출하지 않는다."""

    from jobis_ai.graph.read_nodes import build_user_profile

    seeded = {"skills": [{"name": "Python"}], "projects": []}
    out = build_user_profile({
        "normalizedUserProfile": seeded,
        "resumeInput": {"sourceType": "text", "value": "Python 3년"},
    })
    assert out["normalizedUserProfile"] == seeded
    assert not out.get("warnings")                        # LLM 추출이 돌지 않았다


def test_agent_loop_receives_user_facts(monkeypatch):
    """D84: 자기 루프 에이전트(자소서·면접·선호)도 사용자가 한 말(user_facts)을 본다."""

    import json as json_mod

    from jobis_ai.agents.agent_loop import delegate_tool, run_agent_loop

    seen: dict = {}

    class _Decision:
        action = "reply"
        tool = None
        reply = "9월 목표에 맞춰 준비 방향을 잡았어요."

    def fake_rs(schema, system, payload, **kwargs):
        seen["payload"] = json_mod.loads(payload)
        return _Decision(), []

    monkeypatch.setattr("jobis_ai.agents.agent_loop.run_structured", fake_rs)
    out = run_agent_loop(
        goal_system="테스트 목표", facts={"topic": "자소서"},
        tools={"ask_agent": delegate_tool(("resume_diagnosis",))},
        state={"_session": {"user_facts": ["9월까지 취업 희망"]}}, node="t-loop")
    assert seen["payload"]["userFacts"] == ["9월까지 취업 희망"]
    assert out.reply


def test_new_posting_invalidates_summary_cache(fresh_session_store):
    """새 공고가 오면 이전 공고의 파싱 캐시(posting_summary)도 무효화된다 — 남기면 다음
    분석 전까지 조회 질문이 이전 공고의 사실로 답한다(D79 캐시의 짝)."""

    fresh_session_store.update("pc-1", {
        "posting_summary": {"_sourceHash": "old", "jobTitle": "이전 공고"}})
    handle_chat(ChatRequest(sessionId="pc-1", attachments=[_posting_attachment()]))
    assert not fresh_session_store.get("pc-1").get("posting_summary")


def test_cached_posting_recall_answers_selectively(monkeypatch):
    """D81: 이미 보여준 공고(fromCache)의 조회 질문은 전체 목록 재낭독 대신 물은 것만
    골라 답한다. 선별 답변이 실패하면 전체 목록으로 폴백한다."""

    from jobis_ai.agents import tool_render

    import json as json_mod

    posting = {"companyName": "스패이드", "jobTitle": "백엔드",
               "requiredRequirements": [{"text": "Python 실무"}], "techStack": ["Python"]}
    session = {"last_message": "이 공고에서 필수요건 뭐라 했지?",
               "posting_library": [
                   {"_sourceHash": "old", "companyName": "오로라월드", "techStack": ["Figma"]},
                   {"_sourceHash": "cur", "companyName": "스패이드", "techStack": ["Python"]},
               ]}
    seen: dict = {}

    def _capture(s, u, node):
        seen["payload"] = json_mod.loads(u)
        return "필수 요건은 Python 실무 경험 1건이에요.", []

    monkeypatch.setattr("jobis_ai.agents.tool_render.run_streaming_text", _capture)
    reply, _ = tool_render.render_posting_analysis(
        {"postingAnalysis": posting, "readable": True, "fromCache": True}, session)
    assert reply == "필수 요건은 Python 실무 경험 1건이에요."
    assert "공고를 정리했어요" not in reply                     # 재낭독 없음
    # 활성 공고만이 아니라 라이브러리(이전 공고들)도 조회 근거로 실린다(D86 실측 수정)
    companies = [p["companyName"] for p in seen["payload"]["postingLibrary"]]
    assert "오로라월드" in companies

    # 선별 답변 실패(빈 답) → 전체 목록 폴백
    monkeypatch.setattr("jobis_ai.agents.tool_render.run_streaming_text",
                        lambda s, u, node: ("", []))
    reply, _ = tool_render.render_posting_analysis(
        {"postingAnalysis": posting, "readable": True, "fromCache": True}, session)
    assert "공고를 정리했어요" in reply

    # 새로 파싱한 턴(fromCache=False)은 기존대로 전체 목록
    monkeypatch.setattr("jobis_ai.agents.tool_render.run_streaming_text",
                        lambda s, u, node: ("마무리 문장이에요. 어떤 걸 볼까요?", []))
    reply, _ = tool_render.render_posting_analysis(
        {"postingAnalysis": posting, "readable": True, "fromCache": False}, session)
    assert "공고를 정리했어요" in reply


def test_user_facts_extract_merges_and_dedups(monkeypatch):
    """D82: 발화의 지속 사실은 기존 목록에 병합·중복 제거로 누적된다. 실패하면 기존 유지."""

    from jobis_ai.orchestrator import user_facts as uf

    class _Read:
        facts = ["9월까지 취업 희망", "부산 거주"]

    monkeypatch.setattr("jobis_ai.orchestrator.user_facts.run_structured",
                        lambda *a, **k: (_Read(), []))
    merged, _ = uf.extract_user_facts("9월까지는 취업해야 하고 부산에 살아요",
                                      ["부산 거주", "야간 근무 불가"])
    assert merged == ["부산 거주", "야간 근무 불가", "9월까지 취업 희망"]   # 중복 병합

    monkeypatch.setattr("jobis_ai.orchestrator.user_facts.run_structured",
                        lambda *a, **k: (None, [{"code": "llm_call_failed", "message": "x"}]))
    kept, warnings = uf.extract_user_facts("아무 말", ["부산 거주"])
    assert kept == ["부산 거주"] and warnings                     # 실패해도 기존 유지 + 경고

    long_doc = "가" * 700
    kept, warnings = uf.extract_user_facts(long_doc, ["부산 거주"])
    assert kept == ["부산 거주"] and not warnings                 # 문서 붙여넣기는 건너뜀


def test_user_facts_are_staged_and_fed_to_chat(monkeypatch, fresh_session_store):
    """D82: 턴 종료에 지속 사실이 세션에 쌓이고, career_chat 컨텍스트로 전달된다."""

    import json as json_mod

    monkeypatch.setattr("jobis_ai.orchestrator.chat.extract_user_facts",
                        lambda message, existing: (["9월까지 취업 희망"], []))
    handle_chat(ChatRequest(sessionId="uf-1", message="9월까지는 꼭 취업하고 싶어요"))
    assert fresh_session_store.get("uf-1")["user_facts"] == ["9월까지 취업 희망"]

    from jobis_ai.agents import career_chat

    seen: dict = {}

    def fake_stream(system, user_content, node):
        seen["context"] = json_mod.loads(user_content)["context"]
        return "네, 9월 목표로 함께 준비해요.", []

    monkeypatch.setattr("jobis_ai.agents.career_chat.run_streaming_text", fake_stream)
    career_chat.run({"last_message": "내가 언제까지 취업한다고 했지?",
                     "user_facts": ["9월까지 취업 희망"]})
    assert seen["context"]["userFacts"] == ["9월까지 취업 희망"]


def test_career_chat_clips_long_pasted_input(monkeypatch):
    """M6: 자산으로 승격되지 못한 긴 원문은 대화 LLM 에 통째로 가지 않는다 — 구조 격리(§2-5).
    일반 상담 발화(상한 이하)는 그대로 간다."""

    import json as json_mod

    from jobis_ai.agents import career_chat

    seen: dict = {}

    def fake_stream(system, user_content, node):
        seen["message"] = json_mod.loads(user_content)["userMessage"]
        return "네, 자료로 등록해 주시면 분석해 드릴게요.", []

    monkeypatch.setattr("jobis_ai.agents.career_chat.run_streaming_text", fake_stream)

    long_doc = "이력서 원문 " * 500   # 상한(1000자) 초과
    career_chat.run({"last_message": long_doc})
    assert len(seen["message"]) < len(long_doc)
    assert "앞부분만 제공됨" in seen["message"]

    career_chat.run({"last_message": "취업 준비 순서를 모르겠어요."})
    assert seen["message"] == "취업 준비 순서를 모르겠어요."   # 짧은 발화는 그대로


def test_router_tier_picks_strongest_model(monkeypatch):
    """D74: claude_code 에서 라우팅 티어는 CLAUDE_CODE_MODEL_ROUTER, 미지정이면 default 폴백."""

    from jobis_ai.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "claude_code")
    monkeypatch.setenv("CLAUDE_CODE_MODEL", "sonnet")
    monkeypatch.setenv("CLAUDE_CODE_MODEL_ROUTER", "claude-opus-5")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.active_model("router") == "claude-opus-5"
        assert s.active_model() == "sonnet"

        monkeypatch.setenv("CLAUDE_CODE_MODEL_ROUTER", "")
        get_settings.cache_clear()
        assert get_settings().active_model("router") == "sonnet"   # 미지정 → default 폴백
    finally:
        get_settings.cache_clear()


def test_unfulfilled_request_is_flagged(monkeypatch):
    """M3: 청한 에이전트가 실행되지도, 기억되지도 않으면 request_not_fulfilled 경고 —
    어느 층도 '청한 것이 답에 담겼나'를 보지 않던 구멍의 마지막 그물."""

    # 플래너가 신고(blockedRequests)를 빼먹은 상황을 재현 — 자소서를 청했지만 공고가 없어
    # 검증기가 떨구고, 어디에도 기억되지 않는다.
    plan = AgentPlan(agents=["coverletter_draft"], requestedAgents=["coverletter_draft"],
                     confidence=0.9)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))
    res = handle_chat(ChatRequest(
        sessionId="m3-1", message="자소서 써줘", attachments=[_resume_attachment()]))
    assert "coverletter_draft" not in res.dispatched
    assert any(w.get("code") == "request_not_fulfilled" for w in res.warnings)


def test_unreadable_review_tools_emit_structural_warnings(monkeypatch):
    """M5: 정리 도구가 아무것도 못 읽었으면 조용히 완료로 흐르지 않는다 — 구조 경고.

    파서는 빈 결과로 고정한다 — conftest 의 LLM 차단이 파서를 mock 샘플로 폴백시키므로
    (readable=True 가 되어 버림), 여기서 검증할 것은 파서가 아니라 **경고 배선**이다.
    """

    from jobis_ai.agents import posting_analysis, resume_diagnosis

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.parse_job_posting",
                        lambda state: {"normalizedJobPosting": {}, "warnings": []})
    out = posting_analysis.run(
        {"job_posting": {"sourceType": "text", "value": "오늘 점심 뭐 먹을지 고민이다."}})
    assert out.data["readable"] is False
    assert any(w.get("code") == "posting_unreadable" for w in out.warnings)

    monkeypatch.setattr("jobis_ai.agents.resume_diagnosis.ensure_profile",
                        lambda session: ({}, []))
    out = resume_diagnosis.run(
        {"resume": {"sourceType": "text", "value": "안녕하세요 반갑습니다."}})
    assert out.data["readable"] is False
    assert any(w.get("code") == "resume_unreadable" for w in out.warnings)


def test_submitted_assets_are_reviewed_before_fit(monkeypatch):
    """공고·이력서를 내며 적합도를 청한 턴(D71) — 판정으로 직행하지 않고 제출 자료의
    정리(공고 분석·이력서 진단)를 먼저 보여준 뒤 판정한다. 반대로, 자료 제출이 없는 턴은
    끼우지 않는다(이미 보여준 정리를 반복하지 않는다)."""

    stub_planner(monkeypatch, ["fit_analysis"])
    res = handle_chat(ChatRequest(
        sessionId="s-review", message="공고와 이력서 각각 분석하고 적합도 분석 진행해줘",
        attachments=[_resume_attachment(), _posting_attachment()],
    ))
    assert res.dispatched == ["posting_analysis", "resume_diagnosis", "fit_analysis"]

    second = handle_chat(ChatRequest(sessionId="s-review", message="다시 분석해줘"))
    assert "posting_analysis" not in second.dispatched   # 제출 없는 턴 — 정리 반복 없음


def test_chat_planner_ack_is_visible_when_it_explains_a_plan(monkeypatch):
    """ack 는 **계획을 설명할 때** 실린다 — 여러 에이전트를 돌면 순서를 알려야 한다."""

    stub_planner(monkeypatch, ["posting_analysis", "resume_diagnosis"],
                 ack="공고를 먼저 정리하고 이력서를 진단할게요.")
    res = handle_chat(ChatRequest(
        sessionId="s5b", message="공고랑 이력서 다 봐줘",
        attachments=[_resume_attachment(), _posting_attachment()],
    ))
    assert len(res.dispatched) > 1
    assert "공고를 먼저 정리하고 이력서를 진단할게요." in res.reply


def test_chat_ack_dropped_when_single_agent_speaks_for_itself(monkeypatch):
    """에이전트 하나가 스스로 말하면 ack 를 싣지 않는다 — 같은 말을 두 번 하게 된다.

    실측(2026-07-29): 면접 턴이 "면접 연습을 시작하겠습니다. 면접 연습을 시작하겠습니다.
    첫 질문입니다: …" 로 나갔다. ack(플래너)와 에이전트 첫 문장이 같은 말이었다.
    라우팅 가시화는 ack 가 아니라 `intent` 가 맡는다(프론트가 에이전트 이름을 표시한다).
    """

    stub_planner(monkeypatch, ["resume_diagnosis"], ack="이력서 진단으로 이해했어요.")
    res = handle_chat(ChatRequest(
        sessionId="s5", message="이력서 진단해줘", attachments=[_resume_attachment()],
    ))
    assert res.dispatched == ["resume_diagnosis"]
    assert "이력서 진단으로 이해했어요." not in res.reply
    assert res.reply.strip(), "에이전트의 말은 그대로 남는다"
    assert res.intent == "resume_diagnosis", "라우팅 가시화는 intent 로 유지된다"


def test_chat_forbidden_ack_is_dropped(monkeypatch):
    """표현 계층도 검증을 면제받지 않는다 — 금지표현이 섞인 ack 는 버린다."""

    stub_planner(monkeypatch, ["resume_diagnosis"], ack="합격 가능성이 낮습니다. 진단할게요.")
    res = handle_chat(ChatRequest(
        sessionId="s10", message="이력서 진단해줘", attachments=[_resume_attachment()],
    ))
    assert "합격 가능성" not in res.reply


def test_posting_analysis_seniority_shows_posting_wording():
    """연차 표기는 공고가 한 말(yearsEvidence)을 그대로 — 사다리 라벨("주니어 신입")은
    공고에 없는 단어("신입")를 만들 수 있어 숫자 근거가 있으면 쓰지 않는다."""

    from jobis_ai.agents.tool_render import _seniority_line

    line = _seniority_line({
        "jobTitle": "백엔드 개발자",
        "seniority": "junior",
        "minYears": 2,
        "yearsEvidence": "경력 2년 이상",
    })
    assert "경력 2년 이상" in line
    assert "junior" not in line and "신입" not in line


def test_posting_analysis_seniority_evidence_fallback_from_text():
    """옛 캐시(yearsEvidence 없음)면 원문 항목에서 표기를 찾아 쓴다."""

    from jobis_ai.agents.tool_render import _seniority_line

    line = _seniority_line({
        "jobTitle": "백엔드 개발자",
        "seniority": "junior",
        "requiredRequirements": [{"text": "Python 실무 경험 2년 이상"}],
    })
    assert "2년 이상" in line and "신입" not in line


def test_posting_analysis_seniority_without_evidence():
    """숫자 근거가 아예 없으면(키워드만) 사다리 라벨을 키워드 기준으로 표기한다."""

    from jobis_ai.agents.tool_render import _seniority_line

    line = _seniority_line({"jobTitle": "백엔드", "seniority": "senior",
                            "requiredRequirements": [{"text": "Kubernetes 운영"}]})
    assert "시니어" in line and "키워드 기준" in line


def test_preference_intake_conversation_loop():
    """선호 수집 대화 — 열린 질문 → 직군 인지·되묻기 → 분기점 후 이력서 자연 요청.

    LLM 미설정(conftest)이라 직군은 role_taxonomy 룰로만 잡힌다. 분기점은 결정론:
    차원 2개 이상 또는 (차원 1개 이상 AND 되묻기 2턴 소진).
    """

    from jobis_ai.agents.preference_intake import run

    session: dict = {"last_message": "이력서는 없는데 공고 추천받고 싶어"}
    r1 = run(session)
    assert "직군" in r1.reply                              # 열린 질문 — 원하는 공고부터 묻는다
    assert r1.followUpQuestions[0]["field"] == "preferences"
    session.update(r1.sessionUpdates)

    session["last_message"] = "백엔드 개발자 쪽으로 가고 싶어요"
    r2 = run(session)
    assert "백엔드" in r2.reply            # 들은 것을 받아준다
    assert r2.sessionUpdates["preferences"]["roles"] == ["백엔드"]
    session.update(r2.sessionUpdates)

    session["last_message"] = "음 잘 모르겠어요"
    r3 = run(session)                      # 되묻기 예산 소진 → 분기점 통과
    assert "관심이 있으시군요" in r3.reply
    assert "이력서" in r3.reply            # 자연스러운 이력서 요청으로 전환
    assert r3.followUpQuestions[0]["field"] == "resume"


def test_preference_intake_two_dimensions_transitions_immediately():
    """직군+도메인을 한 번에 말하면 바로 분기점 — 불필요한 되묻기가 없다."""

    from jobis_ai.agents.preference_intake import run

    result = run({
        "last_message": "백엔드요",
        "preferences": {"roles": [], "companies": [], "domains": ["커머스"], "turns": 0},
    })
    assert "관심이 있으시군요" in result.reply and "이력서" in result.reply


def test_career_chat_falls_back_honestly_without_llm():
    """진로 대화 — LLM 미설정이면 지어내지 않고 기능 안내 폴백."""

    from jobis_ai.agents.career_chat import run

    result = run({"last_message": "취업 너무 어렵다"})
    assert "도와드릴 수 있어요" in result.reply     # 결정론 폴백
    assert "적합도 분석" in result.reply




# --- 발화 소유자 하나 (compose_reply) — show_lead 4중 불리언 대체 (2026-07-29) --------
def test_compose_reply_lead_is_silent_when_an_agent_already_spoke():
    """계획 하나를 에이전트가 스스로 말했으면 계획 설명은 침묵한다(같은 말 두 번 금지)."""

    from jobis_ai.orchestrator.chat import compose_reply

    out = compose_reply([], ["진단 결과입니다."], ack="이력서 진단할게요.", steps=1)
    assert out == "진단 결과입니다."


def test_compose_reply_lead_explains_multi_step_and_silence():
    """알려 줄 순서가 있거나(둘 이상) 아무도 말하지 않았으면 계획 설명이 실린다."""

    from jobis_ai.orchestrator.chat import compose_reply

    assert compose_reply([], ["A", "B"], ack="둘 다 볼게요.", steps=2).startswith("둘 다 볼게요.")
    assert compose_reply([], [], ack="둘 다 볼게요.", steps=1) == "둘 다 볼게요."


def test_compose_reply_validator_change_speaks_the_reason_not_the_plan():
    """검증기가 계획을 바꿨으면 원안 설명(ack)이 아니라 **바뀐 이유**(note)를 말한다."""

    from jobis_ai.orchestrator.chat import compose_reply

    out = compose_reply(["이력서를 받았어요."], ["공고 정리 결과"],
                        ack="적합도 분석을 진행하겠습니다.", note="공고가 없어서 이력서 진단부터 할게요.",
                        steps=1, changed_by="validator")
    assert "적합도 분석" not in out, "하지 않은 일을 하겠다고 말하지 않는다"
    assert out.startswith("이력서를 받았어요. 공고가 없어서")


def test_compose_reply_rule_change_stays_silent_because_the_rule_explained():
    """실행 중 규칙이 바꿨으면 이유는 규칙이 이미 said 에 말했다 — 계획 설명은 침묵."""

    from jobis_ai.orchestrator.chat import compose_reply

    out = compose_reply([], ["등급이 하라서 자소서는 미뤘어요."],
                        ack="자기소개서 초안을 작성하겠습니다.", note="무시됨",
                        steps=2, changed_by="rule")
    assert out == "등급이 하라서 자소서는 미뤘어요."


# --- 동의 게이트 왕복: 물어본 것을 세션에 적고, 다음 턴에 통과시킨다 --------------------
def test_consent_gate_records_what_it_asked_and_passes_next_turn(monkeypatch, fresh_session_store):
    """게이트가 물은 이름을 `pendingConsent` 에 적고, 다음 턴 계획에 다시 들어오면 실행한다.

    전에는 이 통과 경로가 "동의하면 다음 턴 플래너가 명시적으로 고를 것"이라는 **모델에 대한
    기대**였고 동의는 어디에도 기록되지 않았다.
    """

    plan = AgentPlan(agents=["fit_analysis", "coverletter_draft"],
                     requestedAgents=["coverletter_draft"], confidence=0.9)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))

    first = handle_chat(ChatRequest(
        sessionId="consent-1", message="자소서 써줘",
        attachments=[_resume_attachment(), _posting_attachment()]))
    assert first.dispatched == [], "청하지 않은 무거운 작업은 먼저 묻는다"
    assert "진행할까요" in first.reply
    assert fresh_session_store.get("consent-1")["pendingConsent"] == ["fit_analysis"]

    # 다음 턴 — 사용자가 "응"이라 하고 플래너가 같은 계획을 낸다(requested 는 여전히 자소서뿐).
    second = handle_chat(ChatRequest(sessionId="consent-1", message="응 진행해줘"))
    assert second.dispatched[0] == "fit_analysis", "동의했으므로 게이트를 통과한다"
    assert fresh_session_store.get("consent-1")["pendingConsent"] == [], "동의는 한 번 쓰면 소진된다"


# ---------------------------------------------------------------------------
# 확신 문턱 면제 — 이번 턴 제출물이 계획 첫 에이전트의 전제를 채우면 강등하지 않는다 (D66)
# ---------------------------------------------------------------------------
def stub_planner_unrequested(monkeypatch, agents, confidence):
    """청함 없는 낮은 확신 계획 — 말없이 자료만 붙여넣은 턴의 플래너 출력을 재현한다."""

    plan = AgentPlan(agents=list(agents), requestedAgents=[], confidence=confidence)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def test_low_confidence_with_posting_submission_is_exempt(monkeypatch):
    """공고를 방금 제출한 턴 — 확신 0.55 여도 posting_analysis 가 강등되지 않는다.

    실측(2026-07-30): 말없이 공고만 붙여넣으면 합성 발화 탓에 확신이 문턱(0.6) 아래로
    나와 career_chat 으로 강등됐고, 사용자는 항목화를 기대했다.
    """

    stub_planner_unrequested(monkeypatch, ["posting_analysis"], 0.55)
    response = handle_chat(ChatRequest(sessionId="s-conf-exempt", message="",
                                       attachments=[_posting_attachment()]))
    assert "posting_analysis" in response.dispatched


def test_low_confidence_without_submission_still_falls_back(monkeypatch):
    """제출물이 없는 낮은 확신 턴은 기존대로 대화가 받는다 — 면제는 제출 턴에만."""

    from jobis_ai.orchestrator.session import get_session_store

    # 세션에 공고가 *이미* 있어도(지난 턴 제출) 이번 턴 제출이 아니면 면제가 아니다.
    get_session_store().update("s-conf-fallback", {
        "job_posting": {"sourceType": "text", "value": "백엔드 모집. 필수: Python."}})
    stub_planner_unrequested(monkeypatch, ["posting_analysis"], 0.55)
    response = handle_chat(ChatRequest(sessionId="s-conf-fallback", message="음 글쎄요"))
    assert response.dispatched == ["career_chat"]


def test_submission_grounds_plan_matrix():
    from jobis_ai.orchestrator.chat import _submission_grounds_plan

    assert _submission_grounds_plan(("posting_analysis",), ["job_posting"])
    assert _submission_grounds_plan(("resume_diagnosis",), ["resume_extra"])
    assert not _submission_grounds_plan(("career_chat",), ["job_posting"])   # 전제 무관
    assert not _submission_grounds_plan(("posting_analysis",), [])           # 제출 없음
    assert not _submission_grounds_plan((), ["job_posting"])                 # 계획 없음


def test_agents_are_told_who_else_runs_this_turn(monkeypatch, fresh_session_store):
    """이번 턴의 계획을 에이전트에게 알린다 — 모르면 자기가 턴을 독점한다고 답한다.

    실측(2026-08-01): 사용자가 적합도를 청한 턴에 정리 단계로 들어간 `resume_diagnosis` 가
    "적합도는 제가 못 해요"라고 선언한 **직후** `fit_analysis` 가 등급을 냈다 — 사용자 눈에
    모순이다. 프롬프트로 못 고친다(에이전트가 계획을 **모른다**), 그래서 사실을 넘긴다.
    """

    from jobis_ai.agents._common import others_this_turn

    seen: dict = {}

    def spy(session):
        from jobis_ai.agents import AgentResult
        seen["others"] = others_this_turn(session, "resume_diagnosis")
        return AgentResult(reply="정리했어요.", data={"readable": True})

    monkeypatch.setattr("jobis_ai.agents.resume_diagnosis.run", spy)
    stub_planner(monkeypatch, ["resume_diagnosis", "career_chat"])
    fresh_session_store.update("s_plan", {"resume": {"sourceType": "text", "value": "Python 3년"}})

    handle_chat(ChatRequest(sessionId="s_plan", message="적합도 봐줘"))
    assert seen["others"] == ["진로 대화"], "같은 턴의 다른 담당을 라벨로 알아야 한다"

    # 혼자 도는 턴이면 빈 목록 — 넘길 상대가 없으니 자기가 답을 끝낸다.
    assert others_this_turn({"_planThisTurn": ["resume_diagnosis"]}, "resume_diagnosis") == []
    assert others_this_turn({}, "resume_diagnosis") == []


def test_save_plan_rejects_proposals_without_posting_grounding():
    """제안은 **커버하는 요구사항 ID 를 대야** 기록된다(D104) — 근거 없는 제안은 거부한다.

    외부 리뷰(2026-08-01)의 지적("제안된 프로젝트가 거의 모든 AI/데이터 공고에 나올 답")의
    구조적 처방이다. 리뷰의 처방은 "프롬프트에 근거 명시를 강제하라"였는데 그 방식은
    §2-2·§3-1 이 실측으로 부정했다 — 도구가 검증하면 프롬프트를 부탁할 필요가 없다.
    """

    from jobis_ai.agents.posting_analysis import _tool_save_plan, requirement_index

    posting = {
        "requiredRequirements": [
            {"requirementId": "req-1", "text": "Python 데이터 처리", "type": "required"},
            {"requirementId": "req-2", "text": "Airflow 운영", "type": "required"},
        ],
        "preferredRequirements": [
            {"requirementId": "pref-1", "text": "LangChain 활용", "type": "preferred"},
        ],
    }
    index = requirement_index(posting)
    assert index == {"req-1": "Python 데이터 처리", "req-2": "Airflow 운영",
                     "pref-1": "LangChain 활용"}

    def _state():
        return {"_requirements": index, "plan": []}

    # 근거를 대면 기록된다.
    state = _state()
    obs, _ = _tool_save_plan(state, "프로젝트: 문서 적재 파이프라인\n설명: Airflow 로 주기 수집\n"
                                    "커버: req-1, req-2\n완료: DAG 가 매일 성공한다")
    assert "기록했습니다" in obs
    assert state["plan"] == [{
        "title": "문서 적재 파이프라인", "detail": "Airflow 로 주기 수집",
        "covers": ["req-1", "req-2"], "done": "DAG 가 매일 성공한다"}]

    # 커버가 비면 거부 — 어느 요건을 증명하는지 못 대는 제안은 그 공고의 제안이 아니다.
    state = _state()
    obs, _ = _tool_save_plan(state, "프로젝트: 무언가\n설명: 뭔가 만든다")
    assert "거부" in obs and "요구사항 ID 가 없습니다" in obs
    assert state["plan"] == []

    # 공고에 없는 ID 는 거부 + 쓸 수 있는 ID 를 알려준다(고쳐 다시 부를 수 있게).
    state = _state()
    obs, _ = _tool_save_plan(state, "프로젝트: 무언가\n커버: req-9")
    assert "거부" in obs and "req-9" in obs and "req-1" in obs
    assert state["plan"] == []

    # 요구사항을 못 읽은 공고에서는 기록 자체가 성립하지 않는다.
    obs, _ = _tool_save_plan({"_requirements": {}, "plan": []}, "프로젝트: x\n커버: req-1")
    assert "읽어내지 못해" in obs


def test_saved_plan_is_assembled_deterministically(monkeypatch):
    """기록된 제안은 **결정론으로** 답변에 붙는다 — 커버 요건을 문장으로 펼쳐 보여준다.

    루프가 자유 문장으로 다시 쓰면 근거 표시가 흐려진다(D97 의 요약 표 중복과 같은 병).
    """

    from jobis_ai.agents import posting_analysis
    from jobis_ai.agents.agent_loop import LoopOutcome

    monkeypatch.setattr(
        "jobis_ai.agents.posting_analysis.parse_job_posting",
        lambda state: {"normalizedJobPosting": {
            "jobTitle": "데이터 엔지니어", "techStack": ["Python"],
            "requiredRequirements": [
                {"requirementId": "req-1", "text": "Python 데이터 처리", "type": "required"}],
        }, "warnings": []})

    def fake_loop(**kw):
        # 루프가 도구를 부른 것과 같은 효과 — 상태에 제안이 기록된 채 답한다.
        kw["state"]["plan"] = [{"title": "적재 파이프라인", "detail": "주기 수집",
                                "covers": ["req-1"], "done": "매일 성공"}]
        return LoopOutcome(reply="필수 요건부터 보시면 좋아요.")

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.run_agent_loop", fake_loop)
    out = posting_analysis.run(
        {"job_posting": {"sourceType": "text", "value": "데이터 엔지니어 채용. 자격요건: Python."}})
    assert "필수 요건부터 보시면 좋아요." in out.reply
    assert "**적재 파이프라인**" in out.reply
    # 커버는 ID 가 아니라 **요건 문장**으로 펼친다 — 사용자가 근거를 눈으로 확인해야 한다.
    assert "커버하는 요건: Python 데이터 처리" in out.reply
    assert "완료 기준: 매일 성공" in out.reply
    assert out.data["planProposals"][0]["covers"] == ["req-1"]


def test_seniority_requirements_are_not_coverable_by_a_project():
    """연차 요건은 커버 목록에서 **빠진다** — 프로젝트로 경력 연차를 채울 수는 없다.

    실측(2026-08-01): 루프가 "상담 데이터 RAG 파이프라인" 이 req-1("데이터 엔지니어링 또는 ML
    엔지니어링 경력 3~7년")을 커버한다고 적었다. 외부 리뷰가 지적한 "포트폴리오가 연차를
    대체할 수 없다"가 그것이다. 커버 대상에서 빼면 그렇게 적을 수 없다(§2-2).
    """

    from jobis_ai.agents.posting_analysis import requirement_index

    index = requirement_index({
        "yearsEvidence": "경력 3~7년",
        "techStack": ["Python", "Airflow"],
        "requiredRequirements": [
            {"requirementId": "req-1", "text": "데이터 엔지니어링 경력 3~7년"},
            {"requirementId": "req-2", "text": "Python 기반 데이터 처리 실무 경험"},
            # 기술이 섞인 연차 줄은 **남는다** — 기술 요건이기도 하다.
            {"requirementId": "req-3", "text": "Airflow 운영 경력 3~7년"},
        ],
    })
    assert "req-1" not in index, "순수 연차 줄이 커버 가능으로 남았다"
    assert "req-2" in index and "req-3" in index
