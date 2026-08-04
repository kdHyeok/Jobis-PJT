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


def test_text_declared_posting_whose_body_is_a_url_is_still_fetched(captured):
    """**선언된 sourceType 보다 본문 내용이 사실이다.**

    실측(2026-08-03): 백엔드가 `sourceType=TEXT` 로 보낸 공고의 raw_text 가 잡코리아 주소
    한 줄(124자)이었다 — 사용자가 첨부 본문 칸에 URL 을 붙인 것이다. 그것을 원문으로 파싱해
    요건 0건 → `fitGrade=판정불가` → verdict 매핑 불가 → 분석이 통째로 실패했고, 커리어지도에는
    아무것도 생기지 않았다(`analysis_jobs` FAILED, `roadmap_targets` 0행).
    """

    with pytest.raises(service.EngineFailed):
        service.analyze(_request(sourceType="TEXT", rawText=_URL))
    assert captured["job_posting"] == {"sourceType": "url", "value": _URL}


def test_url_in_a_sentence_is_not_treated_as_a_bare_url(captured):
    """본문 안에 주소가 섞여 있는 것은 공고 원문이다 — 주소 하나일 때만 수집으로 보낸다."""

    body = f"이 공고 봐주세요 {_URL} 자격요건은 Java 3년 이상입니다"
    with pytest.raises(service.EngineFailed):
        service.analyze(_request(sourceType="TEXT", rawText=body))
    assert captured["job_posting"] == {"sourceType": "text", "value": body}


def test_asset_request_ends_the_turn_instead_of_answering_for_the_user(monkeypatch):
    """자료를 달라는 되묻기를 **우리가 대신 대답하지 않는다** (D145).

    실측(2026-08-03, 이력서 없는 계정): 에이전트가 이력서를 청할 때마다 어댑터가
    "요청에 담긴 커리어 자료가 제가 가진 전부예요"를 사용자 발화로 지어 넣고 다시 돌려서
    `posting_analysis` 가 **4번** 돌고 왕복 상한에서 죽었다. 사용자는 그 말을 한 적이 없고,
    화면에는 "AI 서비스 응답이 지연되었습니다"만 남아 정작 할 일(자료 등록)이 안 보였다.
    """

    from jobis_ai.contracts.api import ChatResponse as EngineChatResponse

    calls: list[str] = []

    def fake_handle_chat(engine_request):
        calls.append(engine_request.message)
        return EngineChatResponse(
            sessionId=engine_request.sessionId,
            reply="이력서를 주시면 이 공고와 대조해 드릴게요.",
            followUpQuestions=[{"field": "resume",
                                "question": "커리어 자료(이력서)를 먼저 등록해 주시겠어요?"}],
        )

    monkeypatch.setattr("jobis_ai.orchestrator.chat.handle_chat", fake_handle_chat)

    with pytest.raises(service.EngineFailed) as caught:
        service.analyze(_request(sourceType="TEXT", rawText="백엔드 개발자 채용. 자격요건: Java 3년"))

    assert len(calls) == 1, f"자료 요청 뒤에 다시 돌면 안 된다(실행 {len(calls)}회)"
    # 에이전트가 쓴 문장 그대로 올린다 — 어댑터가 문구를 지어내지 않는다.
    assert "이력서" in str(caught.value)
    # 백엔드 safeMessage 가 덮지 않는 코드라 그 문장이 화면까지 간다.
    assert caught.value.code == service.CAREER_DATA_REQUIRED


def test_stream_error_keeps_the_failure_code(monkeypatch):
    """스트림 `ERROR` 이벤트가 **실패가 들고 온 코드**를 그대로 싣는다 (D145 의 짝).

    실측(2026-08-03): 자료 요청 종료는 제대로 됐는데 `analyze_events` 가 코드를 두 개로 접어
    `CAREER_DATA_REQUIRED` 를 `AI_PROVIDER_UNAVAILABLE` 로 뭉갰고, 백엔드 `safeMessage` 가 그
    코드를 보고 "AI 서비스 응답이 지연되었습니다"로 덮어썼다 — 사용자가 할 일(자료 등록)이
    화면에서 다시 사라졌다. **스트림이 실제 경로**라 이 한 줄이 D145 의 절반을 무효로 만들었다.
    """

    def _raise(request):
        raise service.EngineFailed("이력서를 주시겠어요?", code=service.CAREER_DATA_REQUIRED)

    monkeypatch.setattr(service, "analyze", _raise)

    events = list(service.analyze_events(_request(sourceType="TEXT", rawText="백엔드 채용")))
    errors = [e for e in events if e.type == "ERROR"]
    assert len(errors) == 1
    assert errors[0].error_code == service.CAREER_DATA_REQUIRED
    assert "이력서" in (errors[0].error_message or "")
