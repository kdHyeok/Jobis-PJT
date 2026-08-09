"""전담 에이전트 로스터 테스트 — resume_diagnosis / interview_prep / fit_analysis 대화 경로.

전부 LLM 미설정(conftest) 환경에서 결정적으로 돈다.
"""

from __future__ import annotations

from jobis_ai.agents import get_agent_registry
from jobis_ai.agents.interview_prep import run as run_interview
from jobis_ai.agents.resume_diagnosis import run as run_diagnosis


def test_registry_names_match_specs():
    registry = get_agent_registry()
    assert set(registry) == {
        "fit_analysis", "posting_analysis", "posting_fetch", "job_recommend",
        "preference_intake", "career_chat", "resume_diagnosis", "interview_prep",
        "coverletter_draft", "roadmap_manager", "application_plan",
    }
    for name, spec in registry.items():
        assert spec.name == name
        assert callable(spec.entry)


def test_produced_assets_are_storable():
    """에이전트가 만든다고 선언한 자산은 **세션 저장소가 받는 키여야 한다.**

    실측으로 겪은 결함: interview_prep 가 `produces=("interview",)` 로 다중 턴 상태를
    냈는데 ASSET_KEYS 에 없어서, 턴 끝 write-back 이 KeyError 로 터졌다(면접 연습 턴이
    통째로 실패). 선언과 저장 허용 목록이 갈라지면 이런 식으로 조용히 어긋난다.
    """

    from jobis_ai.orchestrator.session import ASSET_KEYS

    for name, spec in get_agent_registry().items():
        for asset in spec.produces:
            assert asset in ASSET_KEYS, f"{name} 가 만드는 '{asset}' 을 세션이 저장할 수 없다"


def test_resume_diagnosis_reports_evidence_split():
    """근거 있는 스킬/없는 스킬을 skillEvidence 기준으로 갈라 말해야 한다."""

    session = {
        "profile": {
            "skills": [{"name": "Python"}, {"name": "Kubernetes"}],
            "skillEvidence": {"Python": ["exp-1"]},
            "projects": [{"id": "p1", "title": "API 서버"}],
            "education": [], "experiences": [], "certifications": [],
            "languages": [], "awards": [],
        },
    }
    result = run_diagnosis(session)
    # 대화형 승격(D97 의 짝) 후에도 **데이터는 그대로**다 — 루프는 이 사실을 근거로 말할 뿐
    # 사실을 바꾸지 않는다. LLM 미설정(conftest)이라 문장은 결정론 폴백이 만든다.
    assert result.reply, "승격 후에도 LLM 없이 답해야 한다(tool_render 폴백)"
    assert result.data["evidencedSkills"] == ["Python"]
    assert result.data["unverifiedSkills"] == ["Kubernetes"]
    assert "학력" in result.data["emptySections"]

    from jobis_ai.agents.tool_render import render_resume_diagnosis

    rendered, _ = render_resume_diagnosis(result.data, session)
    assert "Python" in rendered and "Kubernetes" in rendered
    assert "기재만 된 것" in rendered, "근거 없는 스킬은 그렇다고 말한다"


def test_resume_diagnosis_loop_grounding(monkeypatch):
    """D97 짝: 루프가 답하면 그 답이 전부고, **근거는 항목화 사실로 봉인**된다.

    강점을 말할 근거는 `evidencedSkills`(경험 서술로 뒷받침되는 것)여야 한다 — 이력서에
    이름만 적힌 스킬을 강점으로 세면 없는 근거를 만드는 것이다(§2-5).
    """

    from jobis_ai.agents import resume_diagnosis
    from jobis_ai.agents.agent_loop import LoopOutcome

    seen: dict = {}

    def fake_loop(**kw):
        seen.update(kw["facts"])
        return LoopOutcome(reply="Python 강점이 프로젝트로 뒷받침돼요.")

    monkeypatch.setattr("jobis_ai.agents.resume_diagnosis.run_agent_loop", fake_loop)
    session = {"profile": {
        "skills": [{"name": "Python"}, {"name": "Kubernetes"}],
        "skillEvidence": {"Python": ["exp-1"]},
        "projects": [{"id": "p1", "title": "API 서버"}],
        "education": [], "experiences": [], "certifications": [],
        "languages": [], "awards": [],
    }}
    result = resume_diagnosis.run(session)
    assert result.reply == "Python 강점이 프로젝트로 뒷받침돼요."   # 항목 표를 덧붙이지 않는다
    assert seen["evidencedSkills"] == ["Python"]
    assert seen["unverifiedSkills"] == ["Kubernetes"]
    assert seen["firstLook"] is False        # 프로필이 이미 있었다 = 후속 질문 턴

    # 원문 검색 도구 — 없는 것은 없다고 돌려준다(빈 관찰이면 LLM 이 지어낸다).
    from jobis_ai.agents.resume_diagnosis import _tool_read_resume

    state = {"_text": "프로젝트: 결제 API 서버. 성과: 응답시간 40% 개선."}
    assert "40%" in _tool_read_resume(state, "성과")[0]
    assert "찾지 못했습니다" in _tool_read_resume(state, "Kafka")[0]


def test_downstream_agents_read_posting_identity_from_whiteboard():
    """하류 생성 에이전트가 **어느 회사·직무인지** 화이트보드에서 읽는다(D97 §4).

    실측 결핍: `coverletter_draft` 의 facts 에 회사명·직무가 아예 없어 지원 대상을 모른 채
    초안을 썼고, `application_plan` 은 `job_posting.get("company")` 로 찾아 늘 빈 값이었다
    (그 자산은 {sourceType, value} 원천이라 회사명 칸이 없다).
    """

    from jobis_ai.agents._common import posting_identity

    # 판정 전 — 공고만 정리된 상태에서도 회사·직무를 안다(파싱 결과가 출처).
    assert posting_identity({
        "posting_summary": {"companyName": "회사A", "jobTitle": "백엔드"},
    }) == ("회사A", "백엔드")
    # 판정 산출만 있어도 폴백한다.
    assert posting_identity({
        "analysis": {"companyName": "회사B", "roleTitle": "데이터"},
    }) == ("회사B", "데이터")
    # 원천 자산만 있으면 모른다 — 지어내지 않는다(회사명 추측 금지).
    assert posting_identity({"job_posting": {"sourceType": "text", "value": "채용"}}) == ("", "")


def test_interview_prep_consumes_analysis_only():
    """질문은 analysis 의 gaps/strengths 에서만 나와야 한다 (근거 제한)."""

    session = {
        "analysis": {
            "gaps": [{"requirementId": "req-1", "severity": "high",
                      "reason": "요구 기술 미충족", "missingSkills": ["Kafka"]}],
            "strengths": [{"matchedSkills": ["Python", "Django"], "text": "req-2"}],
        },
    }
    result = run_interview(session)
    questions = result.data["questions"]
    assert len(questions) == 2
    topics = {q["topic"] for q in questions}
    assert "Kafka" in topics
    assert any("Python" in t for t in topics)


def test_interview_prep_without_analysis_is_honest():
    result = run_interview({"analysis": {"gaps": [], "strengths": []}})
    assert not result.data.get("questions")
    assert any(w["code"] == "no_interview_basis" for w in result.warnings)


def test_coverletter_draft_uses_facts_only_and_gates():
    """LLM 미설정 → 창작 없는 템플릿 초안. 산출물은 항상 draft_pending_review 상태."""

    from jobis_ai.agents.coverletter_draft import run as run_coverletter

    session = {
        "profile": {
            "projects": [{"title": "재고 API", "role": "백엔드", "summary": "Django 기반 재고 관리",
                          "techStack": ["Python", "Django"], "achievements": ["응답시간 40% 개선"]}],
            "skills": [{"name": "Python"}, {"name": "Django"}],
            "skillEvidence": {"Python": ["p1"]},
            "experiences": [], "certifications": [], "awards": [],
        },
        "analysis": {
            "requirements": [{"text": "Python 백엔드 개발 경험"}],
            "gaps": [{"requirementId": "req-2", "missingSkills": ["Kafka"]}],
        },
        "resume": {"sourceType": "text", "value": "무관 — profile 캐시 사용"},
    }
    result = run_coverletter(session)
    draft = result.data
    assert draft["status"] == "draft_pending_review"          # P5 게이트
    assert "재고 API" in draft["strengthsParagraph"]           # facts 에서만
    assert "검토" in result.reply                               # 사용자 검토 요구
    assert result.sessionUpdates["coverletter"] == draft


def test_coverletter_verify_removes_ungrounded_skill_sentence():
    """P4 VERIFY — 프로필에 없는 스킬을 주장하는 문장은 제거되고 경고가 남는다."""

    from jobis_ai.agents.coverletter_draft import _DraftRead, _verify_draft

    draft = _DraftRead(
        motivation="지원 동기입니다.",
        strengthsParagraph="Python 프로젝트 경험이 있습니다. Kubernetes 운영에 능숙합니다.",
        improvementParagraph="",
    )
    verified, warnings = _verify_draft(draft, allowed={"python"})
    assert "Kubernetes" not in verified.strengthsParagraph
    assert "Python" in verified.strengthsParagraph
    assert any(w["code"] == "ungrounded_skill_removed" for w in warnings)


def test_coverletter_refuses_without_facts():
    """근거 사실이 없으면 초안을 지어내지 않는다."""

    from jobis_ai.agents.coverletter_draft import run as run_coverletter

    session = {
        "profile": {"projects": [], "experiences": [], "skills": [],
                    "certifications": [], "awards": []},
        "analysis": {"requirements": [], "gaps": []},
        "resume": {"sourceType": "text", "value": "x"},
    }
    result = run_coverletter(session)
    assert not result.data
    assert any(w["code"] == "no_coverletter_facts" for w in result.warnings)


def test_roadmap_manager_reads_session_roadmap():
    from jobis_ai.agents.roadmap_manager import run as run_roadmap

    session = {"roadmap": [
        {"title": "Kafka 기초 강의", "startDate": "2026-08-01", "endDate": "2026-08-14",
         "priority": "high"},
        {"title": "토이 프로젝트", "startDate": "2026-08-15", "endDate": "2026-09-01",
         "priority": "medium"},
    ]}
    result = run_roadmap(session)
    # 도구는 말하지 않는다 — 데이터만 낸다. 문장은 표현 계층이 만든다.
    assert result.reply == ""
    assert len(result.data["roadmap"]) == 2

    from jobis_ai.agents.tool_render import render_roadmap_manager

    rendered, _ = render_roadmap_manager(result.data, session)
    assert "2개 항목" in rendered
    # **반전(D142, 2026-08-03)**: 전에는 항목 제목("Kafka 기초 강의")이 답변에 나오는 것을
    # 박아 뒀다. 로드맵은 커리어지도에서 그리기로 정해졌고, 지도에 생긴 것을 채팅이 다시
    # 읊으면 사용자는 같은 내용을 두 번 보고 지도를 열 이유가 없어진다. 채팅은 개수와 어디서
    # 보는지까지만 말한다 — 그래서 이제 제목이 **없어야** 한다.
    assert "Kafka 기초 강의" not in rendered
    assert "커리어 지도" in rendered
    # 지도의 상태를 모르므로 "이미 그려져 있다"고 단정하지 않는다(채우는 것은 분석 작업이다).
    assert "준비 중" not in rendered

    empty = run_roadmap({})
    assert any(w["code"] == "no_roadmap" for w in empty.warnings)


def test_fit_analysis_tool_runs_pipeline_and_stores_analysis():
    """대화 경로 fit_analysis — 세션 자산으로 판정 엔진을 돌리고 결과를 세션 갱신으로 낸다.

    **도구다** — 계산만 하고 말은 표현 계층이 한다(A-잔여, 2026-07-29).
    """

    from jobis_ai.agents.fit_analysis import run as run_fit
    from jobis_ai.agents.tool_render import render_fit_analysis

    session = {
        "resume": {"sourceType": "text", "value": "Python Django 백엔드 3년"},
        "job_posting": {"sourceType": "text",
                        "value": "백엔드 개발자 채용. 자격요건: Python, Django 3년 이상"},
    }
    result = run_fit(session)
    assert "analysis" in result.sessionUpdates
    assert result.reply == "", "도구는 문장을 만들지 않는다"
    # 판정 결과를 가공 없이 그대로 전달한다
    assert result.data.get("analysisId")
    # 판정 산출물(세션 자산)은 표현용 힌트로 오염되지 않는다
    assert "assumedPeriod" in result.data
    assert "assumedPeriod" not in result.sessionUpdates["analysis"]

    rendered, _ = render_fit_analysis(result.data, session)
    assert "적합도 등급" in rendered
    assert "8주" in rendered, "준비 기간을 가정했으면 그렇다고 말한다"


# --- Tool / Agent 구분 (A단계) --------------------------------------------------
def test_tools_do_not_speak_and_always_have_renderer():
    """구분의 기준은 하나다 — 말을 하는가.

    도구는 사용자향 문장을 만들지 않고(계산만) 반드시 render 를 갖는다. 에이전트는 반대다.
    이 규약이 깨지면 도구가 조용히 벙어리가 되거나(render 누락) 계산 코드에 문구가 다시
    섞인다.
    """

    from jobis_ai.agents import get_agent_registry

    registry = get_agent_registry()
    tools = [s for s in registry.values() if s.kind == "tool"]
    agents = [s for s in registry.values() if s.kind == "agent"]

    assert tools and agents, "둘 다 하나 이상 있어야 구분이 의미가 있다"
    for spec in tools:
        assert spec.render is not None, f"{spec.name}: 도구는 render 가 있어야 말할 수 있다"
    for spec in agents:
        assert spec.render is None, f"{spec.name}: 에이전트는 자기 문장을 직접 만든다"


def test_declared_tools_return_no_reply():
    """도구로 선언된 것들이 실제로 reply 를 비우는지 — 선언과 구현이 어긋나지 않게."""

    from jobis_ai.agents import get_agent_registry

    sessions = {
        "job_recommend": {"preferences": {"roles": ["백엔드"]}},
        "roadmap_manager": {"roadmap": [{"title": "x", "priority": "high"}]},
        "fit_analysis": {
            "resume": {"sourceType": "text", "value": "Python Django 백엔드 3년"},
            "job_posting": {"sourceType": "text",
                            "value": "백엔드 개발자 채용. 자격요건: Python, Django 3년 이상"},
        },
        "posting_analysis": {
            "job_posting": {"sourceType": "text",
                            "value": "백엔드 개발자 채용. 자격요건: Python, Django 3년 이상"},
        },
        "resume_diagnosis": {
            "resume": {"sourceType": "text", "value": "Python Django 백엔드 3년"},
        },
    }
    for name, spec in get_agent_registry().items():
        if spec.kind != "tool":
            continue
        result = spec.entry(sessions.get(name, {}))
        assert result.reply == "", f"{name}: 도구가 문장을 만들었다"
        # render 는 그 데이터로 문장을 만들 수 있어야 한다.
        # posting_fetch 는 성공을 침묵하는 도구(뒤 파싱 단계가 결과로 말한다) — 말할 수
        # 있는지는 실패 표현으로 검사한다(엔트리를 실패시키려면 네트워크가 필요해서).
        data = {"fetched": False} if name == "posting_fetch" else result.data
        rendered, _ = spec.render(data, sessions.get(name, {}))
        assert rendered.strip(), f"{name}: render 가 빈 문장을 냈다"




def test_fit_analysis_reuses_the_judgment_when_nothing_changed(monkeypatch):
    """같은 공고·같은 이력서면 다시 판정하지 않는다.

    판정은 (공고 × 이력서)의 함수이고 결정론 계층은 같은 입력에 같은 값을 낸다 — 다시 도는
    것은 수십 초와 LLM 콜 여러 건을 태워 같은 결론을 얻는 일이다. 실측(2026-08-03): 한 대화에서
    적합도 판정이 두 번 돌았다(채팅 턴 + 분석 작업). 재사용 사실은 경고로 남는다(§2-6).
    """

    from jobis_ai.agents import fit_analysis as fit_mod

    session = {
        "resume": {"sourceType": "text", "value": "Python Django 백엔드 3년"},
        "job_posting": {"sourceType": "text",
                        "value": "백엔드 개발자 채용. 자격요건: Python, Django 3년 이상"},
    }
    first = fit_mod.run(session)
    session = {**session, **first.sessionUpdates}
    assert "analysis_key" in first.sessionUpdates, "무엇으로부터 판정했는지 남겨야 재사용할 수 있다"

    def _must_not_run(*_a, **_k):
        raise AssertionError("같은 입력인데 판정 파이프라인이 다시 돌았다")

    monkeypatch.setattr(fit_mod, "run_pipeline_with_state", _must_not_run)
    again = fit_mod.run(session)
    assert any(w["code"] == "analysis_reused" for w in again.warnings)
    assert again.data.get("analysisId") == first.data.get("analysisId")
    # 재사용 턴은 판정 자산을 다시 쓰지 않는다(이미 그 값이다)
    assert "analysis" not in again.sessionUpdates

    # 이력서가 바뀌면 다시 판정한다 — 판정은 이력서의 함수다
    changed = {**session, "resume": {"sourceType": "text", "value": "Java Spring 백엔드 5년"}}
    try:
        fit_mod.run(changed)
    except AssertionError as exc:
        assert "다시 돌았다" in str(exc), exc
    else:
        raise AssertionError("이력서가 바뀌었는데 옛 판정을 재사용했다")
