"""extract.py 유닛 테스트 (문서/URL 입력 어댑터).

실패해도 예외 없이 warning 으로 흡수하는 철학을 검증한다. 네트워크는 타지 않는다.
"""

from pathlib import Path

from jobis_ai.extract import _HTMLTextExtractor, extract_text

_RESUME = Path(__file__).parent / "docs" / "user1" / "이력서_김도현_백엔드.docx"


def _codes(result):
    return {w["code"] for w in result.warnings}


def test_text_passthrough():
    r = extract_text({"sourceType": "text", "value": "  안녕하세요  "})
    assert r.text == "안녕하세요"
    assert r.warnings == []


def test_empty_source_warns():
    r = extract_text(None)
    assert "no_source" in _codes(r)


def test_missing_file_warns_not_raises():
    r = extract_text({"sourceType": "file", "value": "C:/nope/does_not_exist.docx"})
    assert r.text == ""
    assert "file_not_found" in _codes(r)


def test_unsupported_file_type_warns(tmp_path):
    p = tmp_path / "data.xyz"
    p.write_text("hello", encoding="utf-8")
    r = extract_text({"sourceType": "file", "value": str(p)})
    assert "unsupported_file_type" in _codes(r)


def test_docx_extraction_reads_persona_fixture():
    assert _RESUME.exists(), "user1 이력서 픽스처가 있어야 한다"
    r = extract_text({"sourceType": "file", "value": str(_RESUME)})
    assert len(r.text) > 500
    assert "세종대학교" in r.text
    assert r.warnings == []


def test_unknown_source_type_warns():
    r = extract_text({"sourceType": "carrier_pigeon", "value": "x"})
    assert "unknown_source_type" in _codes(r)


def test_html_extractor_drops_script_and_style():
    parser = _HTMLTextExtractor()
    parser.feed(
        "<html><head><style>.a{color:red}</style></head>"
        "<body><script>var x=1;</script><p>본문 텍스트</p></body></html>"
    )
    text = parser.text
    assert "본문 텍스트" in text
    assert "color:red" not in text
    assert "var x" not in text


def test_html_extractor_joins_inline_spans():
    """한글/워드 내보내기 공고는 문장이 수십 개 <span> 으로 쪼개져 있다(실측
    Gno=49638104: "(4" 와 "년제 대졸…" 이 별도 노드). 인라인 노드는 한 줄로 잇고
    블록 태그(p·br·div)에서만 줄을 바꾼다."""

    parser = _HTMLTextExtractor()
    parser.feed(
        '<p><span lang="EN-US">(4</span><span>년제 대졸 또는 산업기사 이상</span>)</p>'
        "<p><b>경력</b> : <span>1년</span></p>"
    )
    assert parser.text == "(4년제 대졸 또는 산업기사 이상)\n경력 : 1년"


def test_html_extractor_preserves_table_columns():
    """표의 행은 셀을 " | " 로 이어 컬럼 구조를 보존한다 — "필수사항|자격요건|우대사항"
    3컬럼 표가 낱줄로 흩어지면 필수/우대 구분이 사라진다(실측 Gno=49638104)."""

    parser = _HTMLTextExtractor()
    parser.feed(
        "<table><tr><td><p>1.</p><p>필수사항</p></td><td>2. 자격요건</td></tr>"
        "<tr><td>- 비자 결격 없음</td><td>- 학력: 대졸</td></tr></table>"
    )
    assert "1. 필수사항 | 2. 자격요건" in parser.text
    assert "- 비자 결격 없음 | - 학력: 대졸" in parser.text


def test_image_file_extracts_via_clova_vlm(tmp_path, monkeypatch):
    """공고 캡쳐 이미지(png 등)는 Clova VLM 텍스트화로 읽는다(D64) — 크롤링이 막힌
    공고의 우회로. 실 API 계약(dataUri 접두 포함)은 2026-07-30 라이브로 검증했다."""

    img = tmp_path / "capture.png"
    img.write_bytes(b"\x89PNG-fake")
    monkeypatch.setattr("jobis_ai.feat_url.clova_vlm_file",
                        lambda path, result: "자격요건: Python 3년 이상")
    result = extract_text({"sourceType": "file", "value": str(img)})
    assert result.text == "자격요건: Python 3년 이상"


def test_image_unsupported_extension_warns():
    from jobis_ai.extract import ExtractResult
    from jobis_ai.feat_url import clova_vlm_file

    r = ExtractResult(text="")
    assert clova_vlm_file("capture.gif", r) == ""
    assert any(w["code"] == "unsupported_image_type" for w in r.warnings)


# --- 연차 상한 보존 (2026-08-01 리뷰 지적: grep maxYears → 0건이었다) ------------------
def test_years_range_keeps_the_upper_bound():
    """범위 표기의 **상한을 잃지 않는다** — "3~7년" 이 "3년 이상"으로만 남으면 안 된다.

    상한이 있다는 것은 정보다("시니어는 안 뽑는다"). 전에는 하한만 남기고 버렸다.
    """

    from jobis_ai.rule_extractor import extract_rules

    r = extract_rules("데이터 엔지니어 채용\n자격요건\n- 데이터 엔지니어링 경력 3~7년")
    assert (r.minYears, r.maxYears) == (3, 7)
    assert "3~7년" in r.yearsEvidence


def test_open_ended_years_have_no_upper_bound():
    """"이상"·"+" 는 상한이 **없는** 것이다 — 없는 상한을 만들면 없는 제약을 판정에 들인다(§2-1)."""

    from jobis_ai.rule_extractor import extract_rules

    assert extract_rules("자격요건\n- Java 경력 3년 이상").maxYears is None
    assert extract_rules("자격요건\n- 백엔드 5년+").maxYears is None
    assert extract_rules("자격요건\n- 신입 지원 가능").maxYears is None
    # 연차 근거가 아예 없으면 둘 다 None (미상을 0 으로 찍지 않는다)
    none_years = extract_rules("자격요건\n- 성실한 분")
    assert (none_years.minYears, none_years.maxYears) == (None, None)


def test_seniority_requirement_carries_max_years():
    """합성 연차 요건까지 상한이 도달해야 판정·표현이 읽을 수 있다.

    (파싱 전체를 태우는 검증은 LLM 이 필요하다 — conftest 가 미설정이라 mock 이 나온다.
    그래서 룰 추출과 요건 조립을 각각 결정론으로 잠근다.)
    """

    from jobis_ai.graph.nodes import _seniority_requirement

    reqs = _seniority_requirement({
        "seniority": "mid", "minYears": 3, "maxYears": 7,
        "yearsEvidence": "경력 3~7년", "roleCategory": "data",
    })
    assert len(reqs) == 1
    assert reqs[0]["minYears"] == 3
    assert reqs[0]["maxYears"] == 7, "상한이 요건 조립에서 사라졌다"
    # 표기는 공고가 한 말을 그대로 쓴다 — 상한이 문장에 살아 있다.
    assert "3~7년" in reqs[0]["text"]
