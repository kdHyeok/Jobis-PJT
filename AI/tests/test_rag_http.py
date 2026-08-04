"""HttpRagAdapter(D89) — 실 RAG HTTP 서비스 어댑터의 계약 매핑과 폴백."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from jobis_ai.rag import HttpRagAdapter


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self, *args):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_http_adapter_maps_posting_contract(monkeypatch):
    """명세서 출력({"postings": [원본+score+match_reason]}) → 노드 소비 계약(items) 매핑."""

    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"postings": [{
            "source": "잡코리아", "posting_id": "49638148", "company": "㈜무투스랩",
            "title": "SW 개발자 채용", "url": "https://jobkorea.co.kr/49638148",
            "experience": "경력", "detail_text": "원본 전문",
            "score": 0.82, "match_reason": {"matched_skills": ["React"]},
        }]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = HttpRagAdapter("http://127.0.0.1:8765").search("백엔드 개발자", top_k=3)

    assert captured["url"] == "http://127.0.0.1:8765/search"
    assert captured["body"] == {"input": "백엔드 개발자", "top_k": 3, "evaluate": False}
    item = result.items[0]
    assert item["companyName"] == "㈜무투스랩"
    assert item["jobPostingId"] == "49638148"
    assert item["seniority"] == "경력"
    assert item["score"] == 0.82
    assert item["matchReason"] == {"matched_skills": ["React"]}
    assert result.sources[0]["company"] == "㈜무투스랩"
    assert not result.warnings


def test_http_adapter_accepts_profile_json(monkeypatch):
    """입력 B(profile JSON)도 그대로 전달된다 — 이력서 기반 의미 검색."""

    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"postings": []})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    profile = {"skills": [{"name": "Python"}], "projects": []}
    result = HttpRagAdapter("http://x").search(profile, top_k=5)
    assert captured["body"]["input"] == profile
    assert result.warnings and result.warnings[0]["code"] == "rag_no_results"


def test_fallback_is_disclosed_in_replies(monkeypatch):
    """D90: RAG 폴백으로 찾은 결과는 답변에 명시된다 — 추천·대안 공고 표현 둘 다."""

    from jobis_ai.agents.tool_render import _alternatives_block, render_job_recommend

    reply, _ = render_job_recommend({
        "recommendations": [{"companyName": "회사", "title": "백엔드", "url": "",
                             "matchedSkills": ["Python"], "matchedPreferences": [],
                             "experience": ""}],
        "profileKnown": True, "ragFallback": True,
    }, {})
    assert "실시간 검색 서버(RAG)가 연결되지 않아" in reply

    block = _alternatives_block([{"type": "similar_role", "companyName": "회사",
                                  "title": "백엔드", "url": "", "reducedGaps": []}],
                                rag_fallback=True)
    assert "실시간 검색 서버(RAG)가 연결되지 않아" in block
    # 실 RAG 정상 경로에는 문구가 붙지 않는다
    assert "연결되지 않아" not in _alternatives_block(
        [{"type": "similar_role", "companyName": "회사", "title": "백엔드",
          "url": "", "reducedGaps": []}])


def test_warm_search_fires_in_background_and_discards_result(monkeypatch):
    """D96: 자산이 채워지면 그 기반 쿼리로 캐시를 예열한다 — 비차단, 결과 폐기, 실패 무시.
    HTTP provider 가 아니면 아무것도 하지 않는다."""

    import jobis_ai.rag as rag_mod

    calls: list = []
    adapter = rag_mod.HttpRagAdapter("http://x")
    monkeypatch.setattr(rag_mod.HttpRagAdapter, "search",
                        lambda self, q, top_k=5: calls.append((q, top_k)))

    def _fake_get_adapter():
        return adapter

    _fake_get_adapter.cache_clear = lambda: None   # conftest teardown(lru_cache 규약) 호환
    monkeypatch.setattr(rag_mod, "get_rag_adapter", _fake_get_adapter)

    thread = rag_mod.warm_search_async("백엔드 개발자 Python Django")
    assert thread is not None
    thread.join(timeout=5)
    assert calls == [("백엔드 개발자 Python Django", 3)]

    # HTTP provider 가 아니면 예열하지 않는다
    def _fake_null():
        return rag_mod.NullRagAdapter()

    _fake_null.cache_clear = lambda: None
    monkeypatch.setattr(rag_mod, "get_rag_adapter", _fake_null)
    assert rag_mod.warm_search_async("아무 쿼리") is None


def test_http_adapter_falls_back_with_warning(monkeypatch):
    """서버 미기동·실패 시 — 이유를 삼키지 않고(rag_http_failed) 키워드 폴백으로 내려간다."""

    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = HttpRagAdapter("http://127.0.0.1:1").search("백엔드 개발자")
    assert result.warnings[0]["code"] == "rag_http_failed"
    assert "폴백" in result.warnings[0]["message"]


def test_dedupe_postings_collapses_cross_site_duplicates():
    """같은 공고가 사이트별로 크롤된 중복을 지운다 — 실측 세션 c1470d00(2026-08-03)의 값.

    같은 posting_id 가 두 사이트에 있거나(인트브릿지), id 는 다르고 회사 표기·마감 표기만
    다른 경우(에버엑스·피트인)를 둘 다 잡아야 한다. 반면 회사가 같고 직무가 다른 공고는 남는다.
    """

    from jobis_ai.rag import dedupe_postings

    items = [
        {"companyName": "(주)인트브릿지", "title": "[R&D Center] 백엔드 개발자", "jobPostingId": "54133661"},
        {"companyName": "(주)인트브릿지", "title": "[R&D Center] 백엔드 개발자(채용시 마감)",
         "jobPostingId": "54133661"},
        {"companyName": "에버엑스㈜", "title": "[개발팀] Backend Engineer", "jobPostingId": "49594447"},
        {"companyName": "에버엑스 주식회사", "title": "[개발팀] Backend Engineer(채용시 마감)",
         "jobPostingId": "54483510"},
        {"companyName": "(주)피트인", "title": "백엔드 엔지니어 경력자 모집", "jobPostingId": "54503886"},
        {"companyName": "피트인", "title": "백엔드 엔지니어 경력자 모집", "jobPostingId": "49608958"},
        # 같은 회사의 다른 공고 — 지우면 안 된다
        {"companyName": "(주)인트브릿지", "title": "[기업부설연구소] 백엔드 개발자",
         "jobPostingId": "54133629"},
    ]
    kept = dedupe_postings(items)
    assert [i["jobPostingId"] for i in kept] == ["54133661", "49594447", "54503886", "54133629"]


def test_connected_adapters_do_not_claim_rag_disconnected():
    """검색이 붙어 있는데 기업 맥락 경고가 'RAG 미연결'이면 없는 장애를 좇게 된다."""

    from jobis_ai.rag import HttpRagAdapter, LocalPostingsRagAdapter, NullRagAdapter

    for adapter in (HttpRagAdapter("http://x"), LocalPostingsRagAdapter()):
        warning = adapter.fetch_company_context("SK일렉링크", []).warnings[0]
        assert warning["code"] == "company_context_unsupported"
        assert "미연결" not in warning["message"]
    # 진짜 미연결은 그대로 rag_not_connected 다
    assert NullRagAdapter().fetch_company_context("SK일렉링크", []).warnings[0][
        "code"] == "rag_not_connected"
