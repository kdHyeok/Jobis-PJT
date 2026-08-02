"""공고 URL 수집 게이트 — 공고가 아닌 페이지는 자산으로 승격되지 않는다(D102)."""

from __future__ import annotations

import pytest

from jobis_ai.agents import _common, posting_fetch, tool_render


class _Extracted:
    def __init__(self, text: str) -> None:
        self.text = text
        self.warnings: list[dict] = []


@pytest.fixture
def stub_extract(monkeypatch):
    """extract_text 를 갈아끼운다 — 이 테스트는 네트워크가 아니라 게이트를 본다."""

    def _install(page_text: str) -> None:
        monkeypatch.setattr("jobis_ai.extract.extract_text",
                            lambda source: _Extracted(page_text))

    return _install


def _session(url: str = "https://example.com/jobs/1") -> dict:
    return {"job_posting": {"sourceType": "url", "value": url}}


def test_공고_페이지는_원문으로_승격된다(stub_extract):
    stub_extract("백엔드 개발자 채용\n자격요건: Java 3년\n우대사항: Kafka")
    session = _session()

    promoted, warnings = _common.ensure_posting_text(session)

    assert promoted["sourceType"] == "text"
    assert session["job_posting"]["sourceType"] == "text"
    assert not [w for w in warnings if w["code"] == "not_a_posting"]


def test_공고가_아닌_페이지는_URL_자산을_그대로_둔다(stub_extract):
    stub_extract("회사 소개 — 우리는 2015년에 설립된 기술 기업입니다. 연혁과 비전을 소개합니다.")
    session = _session()

    promoted, warnings = _common.ensure_posting_text(session)

    # 승격하지 않는다 = 다음 턴 재시도 여지가 남고, 뒤 단계가 엉뚱한 텍스트를 판정하지 않는다
    assert promoted["sourceType"] == "url"
    assert session["job_posting"]["sourceType"] == "url"
    assert [w for w in warnings if w["code"] == "not_a_posting"]


def test_거절은_수집_실패와_다른_문구로_말한다(stub_extract):
    stub_extract("회사 소개 — 연혁과 비전을 소개합니다.")

    result = posting_fetch.run(_session())

    assert result.data["fetched"] is False
    assert result.data["notPosting"] is True
    # 사용자가 대신 줄 수 있는 것을 청하는 카드는 그대로 나간다
    assert result.followUpQuestions

    text, _ = tool_render.render_posting_fetch(result.data, {})
    assert "공고 페이지로 보이지 않" in text


def test_열리지_않은_경우는_기존_문구를_유지한다(stub_extract):
    stub_extract("")

    result = posting_fetch.run(_session())

    assert result.data["fetched"] is False
    assert result.data["notPosting"] is False

    text, _ = tool_render.render_posting_fetch(result.data, {})
    assert "읽어오지 못했어요" in text
