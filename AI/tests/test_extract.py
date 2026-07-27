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
