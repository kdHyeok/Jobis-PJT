from __future__ import annotations

import json
from pathlib import Path

from jobis_ai_v3.contracts.posting import StructuredPosting
from jobis_ai_v3.contracts.resolution import PostingResolutionRequest
from jobis_ai_v3.resolution import PostingResolutionService


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "contract-fixtures"
    / "d047"
    / "multi-role-analysis-baseline.json"
)
JOURNEY_FIXTURE = FIXTURE.with_name("career-journey-acceptance.json")


def test_d047_v3_boundary_preserves_positions_and_stable_question() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    boundary = fixture["v3Boundary"]
    posting = StructuredPosting.model_validate(boundary["structuredPosting"])

    assert [position.position_id for position in posting.positions] == [
        "pos-frontend",
        "pos-backend",
    ]
    assert posting.positions[1].responsibilities[0].atomic_text == (
        "프론트엔드 개발자와 협업"
    )

    resolution = PostingResolutionService().resolve(
        PostingResolutionRequest(structured_posting=posting)
    )
    actual = resolution.model_dump(mode="json", by_alias=True)
    expected = boundary["resolutionProjection"]

    assert {
        key: actual[key]
        for key in (
            "status",
            "selectedPositionId",
            "selectedExperienceTrack",
            "activeAmbiguity",
            "resolvedAmbiguityIds",
        )
    } == expected


def test_d047_v3_target_journey_keeps_career_gate_semantics() -> None:
    fixture = json.loads(JOURNEY_FIXTURE.read_text(encoding="utf-8"))
    scenario = fixture["scenarios"]["entryToExperiencedBackend"]

    assert scenario["expectedJourney"]["nodeKinds"] == [
        "OPPORTUNITY",
        "EMPLOYMENT_EVENT",
        "EXPERIENCE_INTERVAL",
        "OPPORTUNITY",
    ]
    assert scenario["expectedJourney"]["experienceGate"]["maximumMonths"] == 48


def test_d047_v3_target_security_journey_rejects_backend_collapse() -> None:
    fixture = json.loads(JOURNEY_FIXTURE.read_text(encoding="utf-8"))
    scenario = fixture["scenarios"]["experiencedSecurity"]

    assert scenario["posting"]["specialization"] == "AI_SECURITY"
    assert scenario["expectedJourney"]["projectBeforeOpportunity"] is True
    assert any("WEB_BACKEND" in item for item in scenario["prohibitedResults"])
