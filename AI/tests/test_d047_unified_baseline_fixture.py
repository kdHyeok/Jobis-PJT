from __future__ import annotations

import json
from pathlib import Path

from jobis_ai.v2bridge.models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStreamEvent,
)


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "contract-fixtures"
    / "d047"
    / "multi-role-analysis-baseline.json"
)
JOURNEY_FIXTURE = FIXTURE.with_name("career-journey-acceptance.json")


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_d047_latest_boundary_requires_role_selection_before_analysis() -> None:
    boundary = _fixture()["latestTeamBoundary"]

    request = AnalysisRequest.model_validate(boundary["analysisRequest"])
    response = AnalysisResponse.model_validate(boundary["analysisResponse"])

    assert response.status == "NEEDS_INPUT"
    assert response.question is not None
    assert [option.value for option in response.question.options] == [
        "frontend",
        "backend",
    ]
    assert response.job is None
    assert response.evaluation is None
    assert response.competency_proposal is None
    assert "프론트엔드 개발자와 협업" in request.posting.raw_text


def test_d047_latest_progress_events_keep_run_and_sequence_contract() -> None:
    boundary = _fixture()["latestTeamBoundary"]
    request = AnalysisRequest.model_validate(boundary["analysisRequest"])
    events = [
        AnalysisStreamEvent.model_validate(event)
        for event in boundary["progressEvents"]
    ]

    assert events[0].type == "RUN_STARTED"
    assert events[-1].type == "RESULT"
    assert [event.sequence for event in events] == [1, 2, 3]
    assert all(event.run_id == request.analysis_job_id for event in events)
    assert events[1].stage is not None
    assert events[1].stage.status == "WAITING"
    assert events[-1].result == AnalysisResponse.model_validate(
        boundary["analysisResponse"]
    )


def test_d047_career_journey_preserves_experience_range_and_role_scope() -> None:
    fixture = json.loads(JOURNEY_FIXTURE.read_text(encoding="utf-8"))
    scenario = fixture["scenarios"]["entryToExperiencedBackend"]
    gate = scenario["expectedJourney"]["experienceGate"]

    assert gate["minimumMonths"] == 24
    assert gate["maximumMonths"] == 48
    assert "Spring Boot" in gate["relatedRoleScope"]
    assert gate["evidenceRequired"] is True
    assert [relation["type"] for relation in scenario["expectedJourney"]["relations"]] == [
        "POTENTIAL_CAREER_ENTRY",
        "STARTS_EXPERIENCE",
        "SATISFIES_EXPERIENCE_GATE",
    ]


def test_d047_security_posting_stays_in_security_journey() -> None:
    fixture = json.loads(JOURNEY_FIXTURE.read_text(encoding="utf-8"))
    scenario = fixture["scenarios"]["experiencedSecurity"]

    assert scenario["posting"]["roleFamily"] == "SECURITY_ENGINEERING"
    assert scenario["posting"]["experience"]["minimumMonths"] == 48
    assert scenario["expectedJourney"]["sectionKey"] == "section.security_engineering"
    assert "TARGET_PROJECT" in scenario["expectedJourney"]["requiredNodeKinds"]
