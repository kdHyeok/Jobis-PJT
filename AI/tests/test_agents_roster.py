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
    # 도구는 말하지 않는다 — 데이터만 낸다(0729 표현 분리).
    assert result.reply == ""
    assert result.data["evidencedSkills"] == ["Python"]
    assert result.data["unverifiedSkills"] == ["Kubernetes"]
    assert "학력" in result.data["emptySections"]

    from jobis_ai.agents.tool_render import render_resume_diagnosis

    rendered, _ = render_resume_diagnosis(result.data, session)
    assert "Python" in rendered and "Kubernetes" in rendered
    assert "기재만 된 것" in rendered, "근거 없는 스킬은 그렇다고 말한다"


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
    assert "Kafka 기초 강의" in rendered

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


