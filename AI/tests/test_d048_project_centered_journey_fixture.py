from __future__ import annotations

import json
from pathlib import Path


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "contract-fixtures"
    / "scenarios"
    / "d048-estgames-naver-career-journey.json"
)


def test_d048_fixture_defines_one_project_per_opportunity_and_hidden_tasks() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    projection = fixture["expectedJourneyProjection"]

    assert fixture["expectedCanonicalGraph"]["singleUserRoadmap"] is True
    assert projection["overviewProjectNodeCountByOpportunity"] == 1
    assert projection["projectTasksRenderedOnOverview"] is False
    assert projection["atomicCapabilitiesExpandedByDefault"] is False


def test_d048_fixture_preserves_entry_to_experience_to_target_semantics() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    relations = {
        relation["type"] for relation in fixture["expectedCanonicalGraph"]["requiredRelations"]
    }
    interval = fixture["expectedCanonicalGraph"]["experienceInterval"]

    assert {
        "POTENTIAL_CAREER_ENTRY",
        "STARTS_EXPERIENCE",
        "SATISFIES_EXPERIENCE_GATE",
        "REQUIRES_GATE",
    }.issubset(relations)
    assert interval["minimumMonths"] == 24
    assert interval["maximumMonths"] == 48
    assert interval["evidenceRequired"] is True
