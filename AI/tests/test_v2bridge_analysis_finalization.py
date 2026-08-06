from __future__ import annotations

from uuid import uuid4

from jobis_ai.graph import nodes as graph_nodes
from jobis_ai.v2bridge import service
from jobis_ai.v2bridge.models import AnalysisRequest


def _request() -> AnalysisRequest:
    return AnalysisRequest.model_validate({
        "analysisJobId": str(uuid4()),
        "posting": {
            "id": str(uuid4()),
            "sourceType": "TEXT",
            "rawText": "경력 3년 이상의 Java 백엔드 개발자를 채용합니다.",
        },
        "career": {
            "graphId": str(uuid4()),
            "version": 1,
            "nodes": [],
        },
        "questionCount": 1,
        "answers": [{
            "questionKey": "q-general",
            "questionText": "프로젝트나 업무 경험을 한 가지 알려주세요.",
            "answerValue": "없습니다.",
            "answerLabel": "없습니다.",
            "inputType": "TEXT",
            "answerStatus": "CONFIRMED_ABSENT",
            "absenceScope": "GENERAL_EXPERIENCE",
        }],
    })


def test_general_absence_finishes_with_known_information(monkeypatch):
    monkeypatch.setattr(graph_nodes, "analyze_gap", lambda state: {
        "gapAnalysisResult": {"companyContext": [], "sources": []},
        "warnings": [], "sources": [], "toolLog": [],
    })
    monkeypatch.setattr(graph_nodes, "_build_comparison_requirements", lambda posting: [
        {"requirementId": "req-java", "text": "Java", "type": "required"},
        {"requirementId": "req-years", "text": "경력 3년 이상", "type": "required",
         "kind": "seniority", "seniority": "mid", "minYears": 3,
         "roleCategory": "backend", "yearsEvidence": "경력 3년 이상"},
    ])
    monkeypatch.setattr(graph_nodes, "plan_roadmap", lambda state: {
        "roadmapResult": {"roadmap": []}, "warnings": [], "toolLog": [],
    })
    monkeypatch.setattr(graph_nodes, "find_alternatives", lambda state: {
        "alternativeJobs": [], "warnings": [], "sources": [], "toolLog": [],
    })
    monkeypatch.setattr(graph_nodes, "verify_result", lambda state: {
        "verification": {"passed": True, "retrySignal": {"required": False}},
        "gapAnalysisResult": state["gapAnalysisResult"],
        "warnings": [], "toolLog": [],
    })
    monkeypatch.setattr(graph_nodes, "assemble_output", lambda state: {
        "analysisResult": {
            "status": "completed",
            "fitGrade": state["gapAnalysisResult"]["fitGrade"],
            "summary": "확인된 정보로 분석했습니다.",
        },
        "warnings": [], "toolLog": [],
    })

    captured = {}

    def completed(request, state, session_id):
        captured.update(state)
        return "completed"

    monkeypatch.setattr(service, "_completed", completed)

    result = service._finalize_with_known_information(
        _request(),
        {
            "normalizedJobPosting": {"jobTitle": "백엔드", "roleCategory": "backend"},
            "normalizedUserProfile": {
                "skills": [], "experiences": [], "projects": [],
                "evidenceMap": [], "skillEvidence": {},
            },
        },
        "test-session",
    )

    assert result == "completed"
    statuses = {
        item["requirementId"]: item["status"]
        for item in captured["gapAnalysisResult"]["requirementStatus"]
    }
    assert statuses == {"req-java": "not_met", "req-years": "not_met"}
    assert captured["analysisResult"]["status"] == "completed"
    assert captured["followUpQuestions"] == []
