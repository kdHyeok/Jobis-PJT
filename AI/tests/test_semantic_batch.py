"""LLM 의미 판정 배치화·캐시 테스트 (2026-07-23 성능 개선).

성능 개선의 핵심 계약 두 가지를 고정한다:
1. topic 이 몇 개든 LLM 호출은 **한 번**이다 (콜당 수십 초 모델에서 N배 차이).
2. 같은 (topics, 근거) 조합의 재호출은 캐시로 끝난다 — check_sufficiency 와
   analyze_gap 이 같은 판정을 두 번 시키는 구조라 이게 곧 노드 하나 비용이다.
"""

from __future__ import annotations

import pytest

from jobis_ai import semantic_judge
from jobis_ai.gap_matcher import GapMatcher
from jobis_ai.semantic_judge import (
    _BatchRelevance,
    _TopicRelevance,
    judge_domain_relevance,
    judge_topics_relevance,
)


@pytest.fixture(autouse=True)
def clear_semantic_cache():
    semantic_judge.clear_cache()
    yield
    semantic_judge.clear_cache()


@pytest.fixture()
def fake_batch_llm(monkeypatch):
    """run_structured 를 흉내 — 호출 횟수를 세고, topic 0/1만 판정하고 2는 무응답."""

    calls = {"count": 0}

    def _fake(schema, system, content, *, node, tier="default"):
        calls["count"] += 1
        return _BatchRelevance(topics=[
            _TopicRelevance(topicIndex=0, relatedIndexes=[0]),   # 관련 있음
            _TopicRelevance(topicIndex=1, relatedIndexes=[]),    # 관련 없음
            # topicIndex=2 는 의도적으로 무응답 (LLM 이 빼먹은 경우)
        ]), []

    monkeypatch.setattr(semantic_judge, "run_structured", _fake)
    return calls


def test_batch_single_call_and_omission_is_undecided(fake_batch_llm):
    topics = ["이벤트 드리븐 아키텍처", "핀테크 도메인", "게임 서버"]
    texts = ["Kafka 기반 주문 이벤트 파이프라인 구축", "Django API 개발"]

    result = judge_topics_relevance(topics, texts)

    assert fake_batch_llm["count"] == 1          # topic 3개 → LLM 호출 1번
    assert result[0] == [0]
    assert result[1] == []
    assert 2 not in result                        # 무응답 topic 은 빈 배열로 채우지 않는다


def test_batch_cache_hits_on_second_call(fake_batch_llm):
    topics = ["이벤트 드리븐 아키텍처", "핀테크", "게임"]
    texts = ["Kafka 파이프라인"]

    first = judge_topics_relevance(topics, texts)
    second = judge_topics_relevance(topics, texts)  # check_sufficiency → analyze_gap 재호출 상황

    assert fake_batch_llm["count"] == 1
    assert first == second


def test_single_topic_wrapper_uses_batch(fake_batch_llm):
    assert judge_domain_relevance("이벤트 드리븐", ["Kafka 파이프라인"]) == [0]
    assert fake_batch_llm["count"] == 1


def test_blank_topics_or_texts_return_none():
    assert judge_topics_relevance([], ["문장"]) is None
    assert judge_topics_relevance(["topic"], []) is None
    assert judge_topics_relevance(["", "  "], ["문장"]) is None


def test_gap_matcher_batches_all_semantic_requirements(monkeypatch):
    """서술형 2건 + 도메인 키워드(포함 매칭 실패) 1건 → 의미 판정 호출은 1번."""

    calls = {"count": 0, "topics": None}

    def _fake_judge(topics, texts):
        calls["count"] += 1
        calls["topics"] = list(topics)
        return {0: [0], 1: [], 2: [0]}

    import jobis_ai.gap_matcher as gm
    monkeypatch.setattr(gm, "judge_topics_relevance", _fake_judge)

    profile = {
        "skills": [], "skillEvidence": {},
        "evidenceMap": [{"evidenceId": "ev-1", "text": "Kafka 기반 이벤트 처리 경험"}],
    }
    requirements = [
        {"requirementId": "r1", "text": "이벤트 드리븐 아키텍처 설계 경험", "type": "required"},
        {"requirementId": "r2", "text": "대규모 트래픽 대응 경험", "type": "required"},
        {"requirementId": "r3", "text": "핀테크", "type": "preferred", "kind": "domain_keyword"},
    ]

    report = GapMatcher().match(requirements, profile)
    by_id = {m.requirementId: m for m in report.matches}

    assert calls["count"] == 1                       # 3건 모두 배치 1콜
    assert len(calls["topics"]) == 3
    assert by_id["r1"].status == "met" and by_id["r1"].matchedEvidenceIds == ["ev-1"]
    assert by_id["r2"].status == "not_met"
    assert by_id["r3"].status == "met" and by_id["r3"].method == "llm_semantic"


def test_gap_matcher_keeps_uncertain_when_batch_unavailable(monkeypatch):
    """배치 판정 불가(None) → not_met 이 아니라 uncertain + 경고 (모른다/아니다 구분)."""

    import jobis_ai.gap_matcher as gm
    monkeypatch.setattr(gm, "judge_topics_relevance", lambda topics, texts: None)

    profile = {"skills": [], "skillEvidence": {},
               "evidenceMap": [{"evidenceId": "ev-1", "text": "경험"}]}
    requirements = [
        {"requirementId": "r1", "text": "서술형 요구사항", "type": "required"},
    ]

    report = GapMatcher().match(requirements, profile)
    assert report.matches[0].status == "uncertain"
    assert any(w["code"] == "undecidable_requirements" for w in report.warnings)
