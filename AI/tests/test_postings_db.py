"""공고 DB 도구 테스트 — Agent_Test 프로토타입의 도구 계약 이식분.

LLM 없음(결정적). 데이터는 sample_data/"db내 공고파일" 크롤링 JSON 을 그대로 쓴다 —
데이터팀 실제 DB 파일이 와도 같은 형식이므로 이 테스트가 그대로 계약 검증이 된다.
"""

from __future__ import annotations

import pytest

from jobis_ai.postings_db import db_available, load_posting, posting_to_text, search_postings
from jobis_ai.rag import LocalPostingsRagAdapter


@pytest.fixture(scope="module")
def any_url() -> str:
    from jobis_ai.postings_db import _load

    index, _ = _load()
    if not index:
        pytest.skip("공고 DB 샘플 데이터 없음")
    return next(iter(index))


def test_db_loads_sample_postings():
    assert db_available()


def test_load_posting_exact_url(any_url):
    posting = load_posting(any_url)
    assert posting is not None and posting.get("url") == any_url
    text = posting_to_text(posting)
    assert posting.get("company", "") in text or posting.get("title", "") in text


def test_load_posting_unknown_url_returns_none():
    assert load_posting("https://example.com/없는공고/999999") is None


def test_search_postings_contract():
    """검색 결과는 원본 필드 + score + match_reason(3필드) — RAG 입출력 명세 계약."""

    hits = search_postings(["백엔드"], top_k=3)
    assert hits, "샘플 DB 에 '백엔드' 공고가 있어야 한다"
    for h in hits:
        assert 0.0 <= h["score"] <= 1.0
        mr = h["match_reason"]
        assert set(mr) == {"matched_skills", "matched_keywords", "matched_fields"}
        assert h.get("url")


def test_search_postings_empty_terms():
    assert search_postings([]) == []


def test_local_rag_adapter_maps_items_contract():
    """어댑터 items 는 노드 소비 계약(text/title/companyName/jobPostingId/url/score)을 지킨다."""

    res = LocalPostingsRagAdapter().search("백엔드 개발자", top_k=3)
    assert res.items, "샘플 DB 기준 결과가 있어야 한다"
    for item in res.items:
        assert {"text", "title", "companyName", "jobPostingId", "url", "score"} <= set(item)
    assert len(res.sources) == len(res.items)


def test_extract_url_does_not_read_postings_db(any_url, monkeypatch):
    """URL 공고는 **DB 를 조회하지 않는다** — 그 URL 을 직접 수집·파싱한다.

    프로토타입(Agent_Test)은 URL → DB 키 조회였지만 제품 방향이 다르다: 사용자가 특정
    공고를 가리킨 것이므로 DB 스냅샷이 아니라 현재 내용을 봐야 한다(마감·수정 반영).
    공고 DB 는 검색·추천 경로에서만 쓴다.
    """

    from jobis_ai import extract as extract_mod
    from jobis_ai import feat_url as feat_url_mod

    calls = []
    monkeypatch.setattr(
        feat_url_mod,
        "fetch_job_posting",
        lambda url: calls.append(url) or extract_mod.ExtractResult(text="수집한 공고 본문"),
    )
    result = extract_mod.extract_text({"sourceType": "url", "value": any_url})

    assert calls == [any_url], "DB 에 있는 URL 이어도 웹 수집 경로로 가야 한다"
    assert result.text == "수집한 공고 본문"
