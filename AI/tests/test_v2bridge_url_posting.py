"""URL 만 준 공고는 **URL 자산**으로 엔진에 들어간다 (`v2bridge.service.analyze`).

전에는 `sourceType` 을 무시하고 항상 `text` 로 넣어서, 사용자가 주소만 준 경우
**주소 문자열 자체를 공고 원문으로 파싱했다** — 내용은 한 글자도 없는데 분석이 돌았다.
URL 자산이어야 오케스트레이터가 `posting_fetch` 를 큐 맨 앞에 끼워 내용을 수집한다(D64).

대화창에 공고 주소를 붙여넣는 흐름이 실사용의 다수라, 이 경로가 조용히 틀리면
"분석은 됐다는데 내용이 없다"가 된다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from jobis_ai.v2bridge import service
from jobis_ai.v2bridge.models import AnalysisRequest

_URL = "https://example.test/jobs/1234"


def _request(**posting) -> AnalysisRequest:
    return AnalysisRequest(
        analysisJobId=uuid4(),
        posting={"id": uuid4(), **posting},
        career={"graphId": uuid4(), "version": 1, "nodes": [], "fragments": []},
    )


@pytest.fixture
def captured(monkeypatch):
    """엔진을 돌리지 않고 세션에 심긴 자산만 가로챈다."""

    seen: dict = {}

    class _Store:
        def clear(self, _sid): pass

        def update(self, _sid, assets): seen.update(assets)

        def get(self, _sid): return {}

    monkeypatch.setattr(
        "jobis_ai.orchestrator.session.get_session_store", lambda: _Store())

    def _stop(*_a, **_k):
        raise service.EngineFailed("여기까지만 — 자산만 본다")

    monkeypatch.setattr("jobis_ai.orchestrator.chat.handle_chat", _stop)
    return seen


def test_url_only_posting_becomes_a_url_asset(captured):
    with pytest.raises(service.EngineFailed):
        service.analyze(_request(sourceType="URL", sourceUrl=_URL, rawText=_URL))
    assert captured["job_posting"] == {"sourceType": "url", "value": _URL}


def test_url_with_pasted_body_keeps_the_body(captured):
    """원문이 함께 왔으면 그걸 쓴다 — 이미 있는 내용을 다시 받아올 이유가 없다."""

    body = "가나테크 백엔드 개발자\n자격요건\n- Java 3년 이상"
    with pytest.raises(service.EngineFailed):
        service.analyze(_request(sourceType="URL", sourceUrl=_URL, rawText=body))
    assert captured["job_posting"] == {"sourceType": "text", "value": body}


def test_text_posting_is_unchanged(captured):
    body = "가나테크 백엔드 개발자 자격요건 Java 3년 이상"
    with pytest.raises(service.EngineFailed):
        service.analyze(_request(sourceType="TEXT", rawText=body))
    assert captured["job_posting"] == {"sourceType": "text", "value": body}
