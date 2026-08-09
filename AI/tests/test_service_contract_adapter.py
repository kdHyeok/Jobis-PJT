from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from jobis_ai.v2bridge import mapping, service
from jobis_ai.v2bridge.app import app
from jobis_ai.v2bridge.models import AnalysisRequest, ChatRequest, ExistingNode
from jobis_ai.contracts.api import ChatAttachment, SourceType


def _analysis_request() -> AnalysisRequest:
    return AnalysisRequest.model_validate({
        "analysisJobId": str(uuid4()),
        "posting": {
            "id": str(uuid4()),
            "sourceType": "TEXT",
            "rawText": "Backend developer requirements: Java and Spring, 2+ years.",
        },
        "career": {
            "graphId": str(uuid4()),
            "version": 1,
            "nodes": [],
            "fragments": [],
            "goals": {},
        },
        "questionCount": 0,
        "answers": [],
        "sharedAnalysis": None,
    })


def test_legacy_graph_without_project_is_rejected() -> None:
    request = _analysis_request()
    posting = {
        "companyName": "Example",
        "jobTitle": "Backend Developer",
        "roleCategory": "backend",
        "seniority": "experienced",
        "minYears": 2,
        "maxYears": 5,
        "yearsEvidence": "2-5 years",
    }
    statuses = [{
        "requirementId": "req-1",
        "type": "required",
        "text": "Java and Spring experience",
        "status": "not_met",
        "confidence": 0.9,
    }]

    legacy = mapping.build_change_proposal(
        request.career, posting, statuses, [], str(request.posting.id))
    job = mapping.build_job_context(posting)

    assert job.primary_track == "BACKEND"
    assert job.experience_requirement.minimum_months == 24
    assert job.experience_requirement.maximum_months == 60
    with pytest.raises(ValueError, match="without a project"):
        mapping.build_competency_proposal(legacy)


def test_selected_service_assets_become_real_engine_attachments() -> None:
    request = ChatRequest.model_validate({
        "conversationId": str(uuid4()),
        "displayName": "tester",
        "messages": [{"role": "USER", "content": "Compare them."}],
        "career": {},
        "task": {
            "mode": "POSTING_COMPARE",
            "postings": [
                {"id": str(uuid4()), "rawText": "Company A backend posting body."},
                {"id": str(uuid4()), "rawText": "Company B backend posting body."},
            ],
            "careerSources": [],
        },
    })

    attachments = service._selected_asset_attachments(request)

    assert [attachment.kind for attachment in attachments] == [
        "job_posting", "job_posting"]
    assert [attachment.value for attachment in attachments] == [
        "Company A backend posting body.",
        "Company B backend posting body.",
    ]


def test_current_posting_can_exclude_auto_selected_previous_postings() -> None:
    request = ChatRequest.model_validate({
        "conversationId": str(uuid4()),
        "displayName": "tester",
        "messages": [{
            "role": "USER",
            "content": "https://www.jobkorea.co.kr/Recruit/GI_Read/49434191 분석해줘",
        }],
        "career": {},
        "task": {
            "mode": "AUTO",
            "postings": [{
                "id": str(uuid4()),
                "rawText": "이전에 분석한 카카오 백엔드 공고 본문",
            }],
            "careerSources": [{
                "id": str(uuid4()),
                "sourceType": "TEXT",
                "title": "내 프로젝트",
                "rawText": "Spring Boot 프로젝트 경험",
                "fragments": [],
            }],
        },
    })

    attachments = service._selected_asset_attachments(
        request, include_postings=False)

    assert [attachment.kind for attachment in attachments] == ["resume"]
    assert all("카카오" not in attachment.value for attachment in attachments)


def test_not_started_nodes_are_preserved_as_state_not_owned_skills() -> None:
    request = _analysis_request()
    request.career.nodes.append(ExistingNode.model_validate({
        "id": uuid4(),
        "canonicalKey": "foundation.cs",
        "title": "CS fundamentals",
        "domain": "COMMON",
        "kind": "FOUNDATION",
        "scopeDefinition": "Data structures, algorithms, and networks",
        "level": 1,
        "progressStatus": "NOT_STARTED",
    }))

    text = mapping.career_text(request.career)

    assert "[역량 상태: NOT_STARTED] CS fundamentals" in text
    assert "[보유 역량] CS fundamentals" not in text


def test_free_text_analysis_answer_keeps_full_evidence() -> None:
    request = _analysis_request()
    request.answers = request.__class__.model_validate({
        **request.model_dump(by_alias=True),
        "answers": [{
            "questionKey": "project_evidence",
            "questionText": "프로젝트 경험을 알려주세요.",
            "answerValue": "Spring Boot로 주문 API를 만들고 Git으로 협업했습니다.",
            "answerLabel": "Spring Boot로 주문 API를 만들고 Git으로 협업했습니다.",
            "inputType": "TEXT",
        }],
    }).answers

    assert request.answers[0].input_type == "TEXT"
    assert "Git으로 협업" in request.answers[0].answer_label


def test_real_posting_intent_proposes_consent_action_without_executing_it() -> None:
    request = ChatRequest.model_validate({
        "conversationId": str(uuid4()),
        "displayName": "tester",
        "messages": [{"role": "USER", "content": "이 공고를 분석해줘"}],
        "career": {},
        "task": {
            "mode": "AUTO",
            "postings": [{
                "id": str(uuid4()),
                "companyName": "기존 회사",
                "roleTitle": "기존 백엔드 공고",
                "sourceUrl": None,
                "experienceText": None,
                "lifecycleStatus": "OPEN",
                "rawText": "이미 저장된 기존 공고 본문",
                "analysisSummary": None,
            }],
            "careerSources": [],
        },
    })
    raw_text = "채용 공고\n주요 업무: Java Spring 백엔드 API 개발\n자격 요건: Git과 SQL 경험"

    actions = service._posting_analysis_actions(
        request,
        [ChatAttachment(kind="job_posting", sourceType=SourceType.text, value=raw_text)],
        ["posting_analysis"],
        results={"posting_analysis": {"postingAnalysis": {
            "companyName": "테스트 회사",
            "jobTitle": "백엔드 개발자",
            "responsibilities": ["Java Spring 백엔드 API 개발"],
            "requiredRequirements": [{"text": "Git과 SQL 경험"}],
            "preferredRequirements": [],
            "techStack": ["Java", "Spring", "SQL"],
        }}},
    )

    assert len(actions) == 1
    assert actions[0].action_type == "ANALYZE_POSTING"
    assert actions[0].requires_consent is True
    assert actions[0].payload["rawText"] == raw_text
    assert "## 담당 업무" in actions[0].payload["reviewText"]
    assert "Git과 SQL 경험" in actions[0].payload["reviewText"]


def test_posting_action_is_not_proposed_without_real_posting_agent_decision() -> None:
    request = ChatRequest.model_validate({
        "conversationId": str(uuid4()),
        "displayName": "tester",
        "messages": [{"role": "USER", "content": "내용만 요약해줘"}],
        "career": {},
        "task": {"mode": "AUTO", "postings": [], "careerSources": []},
    })

    actions = service._posting_analysis_actions(
        request,
        [ChatAttachment(
            kind="job_posting",
            sourceType=SourceType.text,
            value="채용 공고 본문입니다. Java와 Spring 개발자를 모집합니다.",
        )],
        ["career_chat"],
    )

    assert actions == []


def test_roadmap_build_request_binds_the_selected_stored_posting() -> None:
    posting_id = uuid4()
    raw_text = "채용 공고\n주요 업무: Java Spring 백엔드 API 개발\n자격 요건: Git과 SQL 경험"
    request = ChatRequest.model_validate({
        "conversationId": str(uuid4()),
        "displayName": "tester",
        "messages": [{"role": "USER", "content": "이 공고 기준 준비 로드맵을 세워줘"}],
        "career": {},
        "task": {
            "mode": "AUTO",
            "postings": [{"id": str(posting_id), "rawText": raw_text}],
            "careerSources": [],
        },
    })
    session = {
        "job_posting": {"sourceType": "text", "value": raw_text},
        "posting_summary": {
            "companyName": "테스트 회사",
            "jobTitle": "백엔드 개발자",
            "responsibilities": ["Java Spring 백엔드 API 개발"],
            "requiredRequirements": [{"text": "Git과 SQL 경험"}],
            "preferredRequirements": [],
            "techStack": ["Java", "Spring", "SQL"],
        },
    }

    actions = service._posting_analysis_actions(
        request,
        [],
        ["roadmap_manager"],
        "이 공고 기준 준비 로드맵을 세워줘",
        session=session,
    )

    assert len(actions) == 1
    assert actions[0].requires_consent is False
    assert actions[0].payload["postingId"] == str(posting_id)
    assert actions[0].payload["userInitiated"] is True


def test_roadmap_build_reply_does_not_claim_action_succeeded_before_backend() -> None:
    reply = service._roadmap_build_public_reply(
        automatic_action_ready=True,
        has_posting_review=True,
    )

    assert "확인하고 있어요" in reply
    assert "초안 생성을 요청했어요" not in reply


def test_roadmap_query_does_not_start_a_new_analysis() -> None:
    request = ChatRequest.model_validate({
        "conversationId": str(uuid4()),
        "displayName": "tester",
        "messages": [{"role": "USER", "content": "현재 로드맵 보여줘"}],
        "career": {},
        "task": {"mode": "AUTO", "postings": [], "careerSources": []},
    })

    assert service._posting_analysis_actions(
        request,
        [],
        ["roadmap_manager"],
        "현재 로드맵 보여줘",
    ) == []


def test_posting_review_keeps_hiring_requirements_and_excludes_noise() -> None:
    review = service._posting_review_text({
        "companyName": "이스트게임즈",
        "jobTitle": "웹 개발자",
        "yearsEvidence": "신입 또는 경력 3년 이상",
        "responsibilities": ["Java/Kotlin 기반 백엔드 서비스 개발"],
        "requiredRequirements": [{"text": "Spring 기반 개발 경험"}],
        "preferredRequirements": [{"text": "JPA 사용 경험"}],
        "techStack": ["Java", "Kotlin", "Spring"],
        "conditions": ["정규직", "마감 2026-08-31"],
        "hiringProcess": ["서류 접수 이메일 recruit@example.com"],
        "benefits": ["간식 무제한", "복지 포인트"],
    })

    assert "신입 또는 경력 3년 이상" in review
    assert "Java/Kotlin 기반 백엔드 서비스 개발" in review
    assert "Spring 기반 개발 경험" in review
    assert "JPA 사용 경험" in review
    assert "recruit@example.com" not in review
    assert "간식 무제한" not in review
    assert "복지 포인트" not in review


def test_posting_review_does_not_collapse_combined_web_roles_to_fullstack() -> None:
    review = service._posting_review_text(
        {
            "companyName": "Example Games",
            "jobTitle": "Web developer",
            "roleCategory": "fullstack",
            "requiredRequirements": [{
                "text": "Frontend or backend development fundamentals",
            }],
            "preferredRequirements": [],
            "techStack": ["TypeScript", "Next.js", "Java", "Spring"],
        },
        raw_text=(
            "Frontend: TypeScript and Next.js\n"
            "Backend: Java, Kotlin, and Spring Boot\n"
            "Applicants choose one position."
        ),
    )

    assert "## 직무 구분 확인" in review
    assert "Frontend: TypeScript and Next.js" in review
    assert "Backend: Java, Kotlin, and Spring Boot" in review
    assert "- 직무 분야: fullstack" not in review


def test_competency_assessment_generates_scoped_question(monkeypatch) -> None:
    def fake_run_structured(model, system, prompt, node):
        assert "Java language fundamentals" in prompt
        assert node == "v2_competency_question"
        return model(
            prompt="인터페이스와 추상 클래스의 차이를 Java 범위에서 설명하세요.",
            core_criteria=["계약의 역할", "구현 상속과의 차이"],
            future_extensions=["Spring 빈 설계는 별도 노드에서 학습"],
        ), []

    monkeypatch.setattr("jobis_ai.structured.run_structured", fake_run_structured)
    client = TestClient(app)
    response = client.post(
        "/v1/competency-assessments",
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
        json={
            "sessionId": str(uuid4()),
            "competency": {
                "canonicalKey": "skill.java",
                "title": "Java",
                "domain": "BACKEND",
                "scopeDefinition": "Java language fundamentals",
                "requiredLevel": 2,
                "levelDefinition": {},
                "assessmentBlueprint": {},
            },
            "target": {},
            "turns": [],
            "retainedScores": {},
            "requiredQuestionKind": "CONCEPT",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["nextQuestion"]["kind"] == "CONCEPT"
    assert "인터페이스" in payload["nextQuestion"]["prompt"]
    assert payload["answerEvaluation"] is None


def test_competency_assessment_retries_when_java_question_uses_transaction(monkeypatch) -> None:
    calls = []

    def fake_run_structured(model, system, prompt, node):
        calls.append(system)
        if len(calls) == 1:
            return model(
                prompt="Java 트랜잭션 전파 방식의 차이를 설명하세요.",
                core_criteria=["전파 속성", "롤백 조건"],
            ), []
        assert "트랜잭션" in system
        return model(
            prompt="Java의 기본 자료형과 참조 자료형의 차이를 설명하세요.",
            core_criteria=["값 저장 방식", "참조의 의미"],
        ), []

    monkeypatch.setattr("jobis_ai.structured.run_structured", fake_run_structured)
    response = TestClient(app).post(
        "/v1/competency-assessments",
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
        json={
            "sessionId": str(uuid4()),
            "competency": {
                "canonicalKey": "skill.java",
                "title": "Java",
                "domain": "BACKEND",
                "scopeDefinition": "Java 언어의 기본 문법, 자료형, 제어문",
                "requiredLevel": 1,
                "levelDefinition": {},
                "assessmentBlueprint": {},
            },
            "target": {},
            "turns": [],
            "retainedScores": {},
            "requiredQuestionKind": "CONCEPT",
        },
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert "기본 자료형" in response.json()["nextQuestion"]["prompt"]


def test_competency_learning_retries_when_python_guide_uses_web_server(monkeypatch) -> None:
    calls = []

    def fake_run_structured(model, system, prompt, node):
        calls.append(system)
        common = {
            "title": "Python 기초 학습",
            "summary": "Python 기초 범위를 학습합니다.",
            "modules": [{
                "title": "기초",
                "objective": "기초 문법을 이해합니다.",
                "concepts": ["변수", "조건문"],
                "practice": "짧은 코드를 작성합니다.",
                "completion_criteria": ["조건문을 설명할 수 있다"],
            }],
        }
        if len(calls) == 1:
            common["modules"][0]["title"] = "FastAPI 웹 서버 아키텍처"
        else:
            assert "fastapi" in system.lower()
        return model(**common), []

    monkeypatch.setattr("jobis_ai.structured.run_structured", fake_run_structured)
    response = TestClient(app).post(
        "/v1/competency-learning",
        headers={"X-JOBISS-AI-SECRET": "local-ai-secret"},
        json={
            "competency": {
                "canonicalKey": "skill.python",
                "title": "Python",
                "domain": "BACKEND",
                "scopeDefinition": "Python 기본 문법, 변수, 조건문과 반복문",
                "requiredLevel": 1,
                "levelDefinition": {},
                "assessmentBlueprint": {},
            },
            "target": {},
        },
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert response.json()["modules"][0]["title"] == "기초"
