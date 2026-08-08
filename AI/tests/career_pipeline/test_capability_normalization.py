from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import pytest

from jobis_ai.career_pipeline.contracts.normalization import (
    CapabilityCatalogEntry,
    CapabilityCatalogSnapshot,
    CapabilityKind,
    CapabilityNormalizationRequest,
    NormalizationDecision,
    NormalizationReviewDecision,
    ReviewAction,
    ReviewStatus,
    RoadmapDisposition,
)
from jobis_ai.career_pipeline.contracts.posting import StructuredPosting
from jobis_ai.career_pipeline.contracts.project_planning import (
    CompanyProjectBlueprint,
    ProjectPlanningAudit,
)
from jobis_ai.career_pipeline.llm import StructuredGenerator
from jobis_ai.career_pipeline.normalization import (
    CapabilityNormalizationFailure,
    CapabilityNormalizationService,
    compile_project_normalization,
)


class StaticProvider:
    name = "scripted"
    model = "normalization-fixture"

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload
        self.calls = 0

    def complete_json(self, **_kwargs) -> str:
        self.calls += 1
        if self.payload is None:
            raise AssertionError("the LLM must not be called for deterministic normalization")
        return json.dumps(self.payload, ensure_ascii=False)


def catalog() -> CapabilityCatalogSnapshot:
    return CapabilityCatalogSnapshot(
        catalog_version="catalog-test-1",
        entries=[
            CapabilityCatalogEntry(
                canonical_key="lang.java",
                display_name="Java",
                kind=CapabilityKind.PROGRAMMING_LANGUAGE,
                scope_definition="Java syntax, types, collections, exceptions, and OOP",
                aliases=["자바"],
                version=1,
            ),
            CapabilityCatalogEntry(
                canonical_key="lang.javascript",
                display_name="JavaScript",
                kind=CapabilityKind.PROGRAMMING_LANGUAGE,
                scope_definition="JavaScript language and browser or server runtime fundamentals",
                aliases=["JS"],
                version=1,
            ),
            CapabilityCatalogEntry(
                canonical_key="framework.spring",
                display_name="Spring Framework",
                kind=CapabilityKind.FRAMEWORK,
                scope_definition="Spring dependency injection and application framework",
                aliases=["Spring"],
                version=1,
            ),
            CapabilityCatalogEntry(
                canonical_key="framework.spring-boot",
                display_name="Spring Boot",
                kind=CapabilityKind.FRAMEWORK,
                scope_definition="Spring Boot configuration, web applications, and production conventions",
                aliases=[],
                version=1,
            ),
            CapabilityCatalogEntry(
                canonical_key="database.mysql",
                display_name="MySQL",
                kind=CapabilityKind.DATABASE,
                scope_definition="MySQL schema, CRUD, JOIN, grouping, indexing, and transaction basics",
                aliases=[],
                version=1,
            ),
        ],
    )


def posting_with(structured_posting, text: str, category: str = "TECHNOLOGY") -> StructuredPosting:
    payload = copy.deepcopy(structured_posting.model_dump(mode="json"))
    requirement = payload["positions"][0]["requirements"][0]
    requirement["source_text"] = text
    requirement["atomic_text"] = text
    requirement["category"] = category
    return StructuredPosting.model_validate(payload)


def request_for(structured_posting, text: str, category: str = "TECHNOLOGY"):
    return CapabilityNormalizationRequest(
        common_analysis_id="analysis-normalize-1",
        structured_posting=posting_with(structured_posting, text, category),
        selected_position_id="pos-backend",
        catalog=catalog(),
    )


def run(request, payload: dict | None = None):
    provider = StaticProvider(payload)
    service = CapabilityNormalizationService(
        StructuredGenerator(provider, max_attempts=1)
    )
    return service.normalize(request), provider


def test_project_normalization_preserves_catalog_gap_as_user_scoped_candidate(
    structured_posting,
) -> None:
    posting = posting_with(
        structured_posting,
        "FluxionDB 스트림 저장소를 운영하고 장애를 복구하는 능력",
        "TECHNICAL_CAPABILITY",
    )
    blueprint = CompanyProjectBlueprint(
        blueprint_id="project-blueprint-catalog-gap",
        common_analysis_id="analysis-normalize-1",
        selected_position_id="pos-backend",
        title="스트림 저장소 운영 프로젝트",
        objective="스트림 저장소의 운영과 장애 복구를 검증한다.",
        domain_context="실시간 데이터 플랫폼",
        tasks=[],
        unresolved_requirement_ids=["req-java"],
        audit=ProjectPlanningAudit(
            planner_version="planner-test",
            graph_version="graph-test",
            graph_content_hash="sha256:" + "a" * 64,
            provider="scripted",
            model="fixture",
            generation_attempts=1,
            generation_duration_ms=1,
        ),
    )

    result = compile_project_normalization(
        common_analysis_id="analysis-normalize-1",
        structured_posting=posting,
        selected_position_id="pos-backend",
        catalog=catalog(),
        blueprint=blueprint,
    )

    item = result.items[0]
    assert item.decision is NormalizationDecision.NEW_CANDIDATE_PROPOSED
    assert item.review_status is ReviewStatus.OPERATOR_REVIEW_REQUIRED
    assert item.new_candidate is not None
    assert item.new_candidate.candidate_id.startswith("capability-candidate-")
    assert item.new_candidate.display_name == (
        "FluxionDB 스트림 저장소를 운영하고 장애를 복구하는 능력"
    )
    assert item.new_candidate.evidence_ids == ["seg-req"]


def test_unique_exact_alias_is_selected_without_model_call(structured_posting) -> None:
    result, provider = run(request_for(structured_posting, "Java"))

    item = result.items[0]
    assert item.decision is NormalizationDecision.AUTO_SELECTED
    assert item.selected_canonical_key == "lang.java"
    assert item.review_status is ReviewStatus.NOT_REQUIRED
    assert provider.calls == 0


def test_java_does_not_match_inside_javascript(structured_posting) -> None:
    result, provider = run(request_for(structured_posting, "JavaScript"))

    assert result.items[0].selected_canonical_key == "lang.javascript"
    assert provider.calls == 0


def test_longest_alias_wins_for_spring_boot(structured_posting) -> None:
    result, provider = run(request_for(structured_posting, "Spring Boot"))

    assert result.items[0].selected_canonical_key == "framework.spring-boot"
    assert provider.calls == 0


def test_multiple_independent_exact_capabilities_require_source_split(structured_posting) -> None:
    result, provider = run(request_for(structured_posting, "Java와 Spring Boot 개발 경험"))

    item = result.items[0]
    assert item.decision is NormalizationDecision.SPLIT_REQUIRED
    assert item.review_status is ReviewStatus.SOURCE_RESTRUCTURE_REQUIRED
    assert {candidate.canonical_key for candidate in item.candidates} == {
        "lang.java", "framework.spring-boot"
    }
    assert provider.calls == 0


def test_sql_join_stays_inside_mysql_scope_after_scope_review(structured_posting) -> None:
    payload = {
        "items": [{
            "requirementId": "req-java",
            "splitRequired": False,
            "candidates": [{
                "canonicalKey": "database.mysql",
                "partialScope": False,
                "confidence": 0.97,
                "reason": "The approved MySQL scope explicitly includes JOIN queries.",
            }],
            "newCandidate": None,
            "reason": "JOIN is a subtopic covered by the existing MySQL capability.",
        }]
    }
    result, provider = run(
        request_for(structured_posting, "MySQL JOIN 작성 경험"),
        payload,
    )

    assert result.items[0].candidates[0].canonical_key == "database.mysql"
    assert result.items[0].decision is NormalizationDecision.CANDIDATES_PROPOSED
    assert provider.calls == 1


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("BEHAVIORAL", RoadmapDisposition.FIT_ONLY),
        ("RESPONSIBILITY", RoadmapDisposition.PROJECT_CONTEXT),
        ("EXPERIENCE", RoadmapDisposition.CAREER_GATE),
        ("CREDENTIAL", RoadmapDisposition.CAREER_GATE),
        ("EMPLOYMENT_CONDITION", RoadmapDisposition.EMPLOYMENT_INFORMATION),
    ],
)
def test_non_capability_requirements_do_not_become_skill_nodes(
    structured_posting,
    category,
    expected,
) -> None:
    result, provider = run(request_for(
        structured_posting,
        "Java를 좋아하고 책임감 있게 프로젝트를 수행",
        category,
    ))

    item = result.items[0]
    assert item.disposition is expected
    assert item.decision is NormalizationDecision.NOT_APPLICABLE
    assert item.candidates == []
    assert provider.calls == 0


def test_unknown_technology_is_preserved_as_reviewable_new_candidate(structured_posting) -> None:
    payload = {
        "items": [{
            "requirementId": "req-java",
            "splitRequired": False,
            "candidates": [],
            "newCandidate": {
                "displayName": "FluxionDB stream operations",
                "proposedKind": "DATABASE",
                "scopeDefinition": "Operating FluxionDB stream retention, partitions, recovery, and monitoring",
                "aliases": ["FluxionDB"],
                "confidence": 0.94,
            },
            "reason": "No approved catalog entry represents this database.",
        }]
    }
    result, provider = run(
        request_for(structured_posting, "FluxionDB 스트림 저장소 운영"),
        payload,
    )

    item = result.items[0]
    assert item.decision is NormalizationDecision.NEW_CANDIDATE_PROPOSED
    assert item.new_candidate.candidate_id.startswith("capability-candidate-")
    assert item.new_candidate.display_name == "FluxionDB stream operations"
    assert item.review_status is ReviewStatus.OPERATOR_REVIEW_REQUIRED
    assert provider.calls == 1


def test_ai_catalog_match_is_never_auto_approved(structured_posting) -> None:
    payload = {
        "items": [{
            "requirementId": "req-java",
            "splitRequired": False,
            "candidates": [{
                "canonicalKey": "database.mysql",
                "partialScope": False,
                "confidence": 0.91,
                "reason": "The requirement scope is covered by the MySQL capability.",
            }],
            "newCandidate": None,
            "reason": "A catalog capability covers the database scope.",
        }]
    }
    result, _provider = run(
        request_for(structured_posting, "관계형 데이터베이스 쿼리와 인덱스 활용"),
        payload,
    )

    item = result.items[0]
    assert item.decision is NormalizationDecision.CANDIDATES_PROPOSED
    assert item.selected_canonical_key is None
    assert item.review_status is ReviewStatus.OPERATOR_REVIEW_REQUIRED


def test_model_cannot_invent_catalog_key(structured_posting) -> None:
    payload = {
        "items": [{
            "requirementId": "req-java",
            "splitRequired": False,
            "candidates": [{
                "canonicalKey": "database.fabricated",
                "partialScope": False,
                "confidence": 0.9,
                "reason": "Invented candidate",
            }],
            "newCandidate": None,
            "reason": "Invalid fixture",
        }]
    }
    service = CapabilityNormalizationService(
        StructuredGenerator(StaticProvider(payload), max_attempts=1)
    )

    with pytest.raises(CapabilityNormalizationFailure, match="unknown catalog keys"):
        service.normalize(request_for(
            structured_posting,
            "관계형 데이터베이스 역량",
        ))


def test_operator_review_decision_is_an_append_only_audit_contract() -> None:
    decision = NormalizationReviewDecision(
        review_id="review-2",
        normalization_id="normalization-1",
        requirement_id="req-java",
        action=ReviewAction.REVERT,
        operator_ref="operator-1",
        decided_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
        reason="The prior merge combined capabilities with different scopes.",
        supersedes_review_id="review-1",
    )

    assert decision.action is ReviewAction.REVERT
    assert decision.supersedes_review_id == "review-1"
