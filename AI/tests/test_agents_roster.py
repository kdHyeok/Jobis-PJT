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
        "fit_analysis", "posting_analysis", "job_recommend", "preference_intake",
        "career_chat", "resume_diagnosis", "interview_prep", "coverletter_draft",
        "roadmap_manager", "application_plan",
    }
    for name, spec in registry.items():
        assert spec.name == name
        assert callable(spec.entry)


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
    assert result.data["evidencedSkills"] == ["Python"]
    assert result.data["unverifiedSkills"] == ["Kubernetes"]
    assert "학력" in result.data["emptySections"]
    assert "Python" in result.reply


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
    assert "2개 항목" in result.reply
    assert "Kafka 기초 강의" in result.reply

    empty = run_roadmap({})
    assert any(w["code"] == "no_roadmap" for w in empty.warnings)


def test_fit_analysis_agent_runs_pipeline_and_stores_analysis():
    """대화 경로 fit_analysis — 세션 자산으로 판정 엔진을 돌리고 결과를 세션 갱신으로 낸다."""

    from jobis_ai.agents.fit_analysis import run as run_fit

    session = {
        "resume": {"sourceType": "text", "value": "Python Django 백엔드 3년"},
        "job_posting": {"sourceType": "text",
                        "value": "백엔드 개발자 채용. 자격요건: Python, Django 3년 이상"},
    }
    result = run_fit(session)
    assert "analysis" in result.sessionUpdates
    assert result.reply
    # 판정 결과를 가공 없이 그대로 전달한다
    assert result.data.get("analysisId")
