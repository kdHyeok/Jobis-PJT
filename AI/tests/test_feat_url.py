"""feat_url 공고 URL 수집기 — 분기(텍스트 iframe / 이미지 iframe / 실패) 검증.

네트워크·Clova 호출은 전부 monkeypatch. 실제 API 계약은 여기서 검증하지 않는다.
"""

import jobis_ai.feat_url as feat_url

PAGE_URL = "https://www.jobkorea.example/Recruit/GI_Read/49664777"
IFRAME_HTML_TEXT = "<html><body><p>" + "우대사항 상세 내용. " * 30 + "</p></body></html>"
IFRAME_HTML_IMG = '<html><body><img src="/img/posting_01.png"></body></html>'
PAGE_HTML = '<html><body><iframe src="/Recruit/GI_Read_Comt_Ifrm?Gno=49664777"></iframe></body></html>'


def _fake_get(pages):
    def get(url, headers=None, timeout=30):
        for key, html in pages.items():
            if key in url:
                return html
        raise OSError(f"unexpected fetch: {url}")

    return get


def test_text_iframe_merged(monkeypatch):
    monkeypatch.setattr(feat_url, "_jina_text", lambda url, result: "공고 제목과 기본 정보")
    monkeypatch.setattr(
        feat_url, "_get", _fake_get({"GI_Read_Comt_Ifrm": IFRAME_HTML_TEXT, PAGE_URL: PAGE_HTML})
    )
    result = feat_url.fetch_job_posting(PAGE_URL)
    assert "공고 제목과 기본 정보" in result.text
    assert "우대사항 상세 내용" in result.text


def test_image_iframe_uses_vlm(monkeypatch):
    monkeypatch.setattr(feat_url, "_jina_text", lambda url, result: "기본 텍스트")
    monkeypatch.setattr(
        feat_url, "_get", _fake_get({"GI_Read_Comt_Ifrm": IFRAME_HTML_IMG, PAGE_URL: PAGE_HTML})
    )
    called = []
    monkeypatch.setattr(
        feat_url,
        "_clova_vlm_text",
        lambda image_url, result: called.append(image_url) or "이미지에서 추출한 우대사항",
    )
    result = feat_url.fetch_job_posting(PAGE_URL)
    assert called == ["https://www.jobkorea.example/img/posting_01.png"]  # 상대경로 절대화 확인
    assert "이미지에서 추출한 우대사항" in result.text


def test_script_injected_iframe_found(monkeypatch):
    """잡코리아: <iframe> 태그 없이 스크립트 JSON 문자열에만 iframe URL 이 있는 경우."""
    page = (
        '<html><script>{"src":"/Recruit/GI_Read_Comt_Ifrm?Gno=49664777'
        '\\u0026isHiringCenter=false\\"}</script></html>'
    )
    monkeypatch.setattr(feat_url, "_jina_text", lambda url, result: "기본")
    monkeypatch.setattr(
        feat_url, "_get", _fake_get({"GI_Read_Comt_Ifrm": IFRAME_HTML_TEXT, PAGE_URL: page})
    )
    result = feat_url.fetch_job_posting(PAGE_URL)
    assert "우대사항 상세 내용" in result.text


def test_ad_teaser_block_dropped(monkeypatch):
    """잡코리아 "…공고를 확인해 보세요!" 이후의 추천공고 티저는 본문에서 잘린다.

    실측(Gno=49546576/49675900): 티저 수십 건("경력2년↑" 등)이 연차 근거·기술스택을
    오염시켰다. iframe 상세는 별도로 뒤에 붙으므로 절단의 영향을 받지 않는다.
    """

    main = ("공고 제목과 기본 정보\n\n"
            "로그인 하고 비슷한 조건의 AI추천공고를 확인해 보세요!\n\n"
            "[타사] 주식TM 영업 채용 경력12년↑")
    monkeypatch.setattr(feat_url, "_jina_text", lambda url, result: main)
    monkeypatch.setattr(
        feat_url, "_get", _fake_get({"GI_Read_Comt_Ifrm": IFRAME_HTML_TEXT, PAGE_URL: PAGE_HTML})
    )
    result = feat_url.fetch_job_posting(PAGE_URL)
    assert "공고 제목과 기본 정보" in result.text
    assert "주식TM" not in result.text
    assert "우대사항 상세 내용" in result.text          # iframe 상세는 살아 있다
    assert any(w["code"] == "unrelated_tail_dropped" for w in result.warnings)


def test_all_fail_warns_not_raises(monkeypatch):
    monkeypatch.setattr(feat_url, "_jina_text", lambda url, result: "")
    monkeypatch.setattr(feat_url, "_get", _fake_get({}))
    result = feat_url.fetch_job_posting(PAGE_URL)
    assert result.text == ""
    assert any(w["code"] == "empty_extract" for w in result.warnings)


def test_ascii_url_encodes_korean_but_keeps_reserved_chars():
    """한글 검색어가 인코딩 없이 섞인 실제 붙여넣기 주소 — urllib 즉사 방지 (2026-07-30 실측)."""

    from jobis_ai.feat_url import _ascii_url

    url = "https://saramin.co.kr/zf_user/jobs/view?rec_idx=1&searchword=ai엔지니어&t_ref=search"
    encoded = _ascii_url(url)
    encoded.encode("ascii")   # 요청 가능해야 한다
    assert "searchword=ai%EC%97%94%EC%A7%80%EB%8B%88%EC%96%B4" in encoded
    assert encoded.startswith("https://saramin.co.kr/zf_user/jobs/view?rec_idx=1&")
    # 이미 ASCII 인 주소는 그대로 — 이중 인코딩하지 않는다
    plain = "https://example.com/jobs?id=1&q=a%20b"
    assert _ascii_url(plain) == plain
