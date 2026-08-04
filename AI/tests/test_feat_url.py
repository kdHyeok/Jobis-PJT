"""feat_url 공고 URL 수집기 — 분기(텍스트 iframe / 이미지 iframe / 실패) 검증.

네트워크·Clova 호출은 전부 monkeypatch. 실제 API 계약은 여기서 검증하지 않는다.
"""

import io

import pytest

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
    # 이미지는 이제 **우리가 받아서 쪼개** 넘긴다(`_image_text`) — 전에는 URL 을 Clova 에
    # 그대로 줬는데, 세로로 긴 공고가 40063 Invalid image size 로 통째로 버려졌다(§3-5).
    monkeypatch.setattr(
        feat_url,
        "_image_text",
        lambda image_url, page_url, result: (
            called.append(image_url) or "이미지에서 추출한 우대사항"),
    )
    result = feat_url.fetch_job_posting(PAGE_URL)
    assert called == ["https://www.jobkorea.example/img/posting_01.png"]  # 상대경로 절대화 확인
    assert "이미지에서 추출한 우대사항" in result.text


def test_extensionless_image_url_is_accepted():
    """확장자 없는 `<img src>` 도 이미지로 받는다.

    실측(2026-08-04, 잡코리아 Gno=49525099): 공고 본문이 세로로 긴 이미지 한 장이었는데 그 URL 이
    `…/DownImage/CorpEditor?file_No=1787352` — 확장자가 없어서 걸러졌고, 필수요건·우대사항이
    통째로 사라진 채 806자 껍데기로 공고를 정리했다.
    """

    assert feat_url._looks_like_image(
        "https://file2.jobkorea.co.kr/Net/Mng/DownImage/CorpEditor?file_No=1787352")
    assert feat_url._looks_like_image("https://x.test/a/posting.png")
    # 이미지가 아닌 것이 분명한 둘만 거른다.
    assert not feat_url._looks_like_image("data:image/gif;base64,R0lGOD")
    assert not feat_url._looks_like_image("https://x.test/logo.svg")
    # 쿼리에 확장자가 섞여도 경로 확장자가 기준이다.
    assert feat_url._looks_like_image("https://x.test/download?name=a.png")


def test_tall_image_is_sliced_into_tiles():
    """세로로 긴 이미지는 여러 타일로 쪼갠다 — 한 장으로는 Clova 가 거부한다(40063)."""

    from jobis_ai.extract import ExtractResult

    Image = pytest.importorskip("PIL.Image")
    result = ExtractResult(text="")
    buffer = io.BytesIO()
    # 실측 공고와 같은 모양(폭보다 10배 이상 긴 이미지).
    Image.new("RGB", (940, 9400), (255, 255, 255)).save(buffer, "PNG")

    tiles = feat_url._vlm_tiles(buffer.getvalue(), result, "tall.png")

    assert len(tiles) > 1, "한 장으로 보내면 크기 초과로 거부된다"
    assert len(tiles) <= feat_url._MAX_VLM_TILES
    assert all(t.startswith("data:image/jpeg;base64,") for t in tiles)
    # 폭이 상한 아래면 축소하지 않는다 — 줄이면 글자가 안 읽힌다.
    assert 940 <= feat_url._VLM_TILE_MAX_WIDTH


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


def test_meta_description_prepended(monkeypatch):
    """잡코리아 헤더 요약(경력·학력)은 JS 렌더라 jina 본문에 없다 — 정적 meta description
    을 본문 맨 앞에 붙여 파서가 공고 대표 연차를 먼저 보게 한다(실측 Gno=49564982)."""

    page = (
        '<html><head><meta name="description" content="채용 - 운영개발, 경력 1~5년, 학력무관">'
        "</head><body></body></html>"
    )
    monkeypatch.setattr(feat_url, "_jina_text", lambda url, result: "본문. RDBMS 8년 이상 경험")
    monkeypatch.setattr(feat_url, "_get", _fake_get({PAGE_URL: page}))
    result = feat_url.fetch_job_posting(PAGE_URL)
    assert result.text.startswith("채용 - 운영개발, 경력 1~5년")
    assert "8년 이상" in result.text


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
