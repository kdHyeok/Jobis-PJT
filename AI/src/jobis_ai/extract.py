"""입력 텍스트 추출 (부품 교체식 모듈화의 '입력 어댑터' 계층).

설계 8.3 / 9.3 의 Text Extract 단계를 담당한다.
공통 툴 `document_text_extract`(설계 5장)의 구현으로, Job Posting Parser 와
User Profile Builder 가 함께 쓴다.

지원 소스:
- text : 원문 그대로 통과
- file : .docx / .pdf / .txt 파일에서 텍스트 추출
- url  : 정적 페이지 본문 추출 (JS 렌더링 페이지는 본문이 얇게 나올 수 있어 warning 기록)

반환은 (text, warnings) 튜플. 실패해도 예외를 던지지 않고 warning 으로 남겨,
상위 노드가 그래도 진행하거나 폴백하도록 한다.
"""

from __future__ import annotations

import io
import re
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

# 본문이 이보다 짧으면 "추출 실패 의심" 으로 보고 warning 을 남긴다.
_MIN_MEANINGFUL_CHARS = 200

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class ExtractResult:
    text: str
    warnings: list[dict] = field(default_factory=list)

    def warn(self, code: str, message: str) -> None:
        self.warnings.append({"code": code, "message": message})


# ---------------------------------------------------------------------------
# 파일 추출
# ---------------------------------------------------------------------------
def _extract_docx(path: Path) -> str:
    from docx import Document  # 지연 임포트: url/text 경로엔 불필요

    doc = Document(str(path))
    parts: list[str] = []
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    return "\n".join(parts)


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_file(value: str, result: ExtractResult) -> str:
    path = Path(value)
    if not path.exists():
        result.warn("file_not_found", f"파일을 찾을 수 없습니다: {value}")
        return ""
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            return _extract_docx(path)
        if suffix == ".pdf":
            return _extract_pdf(path)
        if suffix in (".txt", ".md"):
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:  # 추출기 내부 오류도 그래프를 멈추지 않는다
        result.warn("file_extract_error", f"{suffix} 추출 실패: {exc}")
        return ""
    result.warn("unsupported_file_type", f"지원하지 않는 파일 형식: {suffix}")
    return ""


# ---------------------------------------------------------------------------
# URL 추출
# ---------------------------------------------------------------------------
class _HTMLTextExtractor(HTMLParser):
    """script/style/nav 등을 버리고 본문 텍스트만 모으는 최소 파서."""

    _SKIP = {"script", "style", "noscript", "head", "meta", "link", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._chunks.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self._chunks)


def _extract_url(value: str, result: ExtractResult) -> str:
    try:
        req = urllib.request.Request(value, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (신뢰 입력)
            charset = resp.headers.get_content_charset() or "utf-8"
            html = resp.read().decode(charset, errors="ignore")
    except Exception as exc:
        result.warn("url_fetch_error", f"URL 요청 실패: {exc}")
        return ""

    parser = _HTMLTextExtractor()
    parser.feed(html)
    text = re.sub(r"\n{3,}", "\n\n", parser.text).strip()
    if len(text) < _MIN_MEANINGFUL_CHARS:
        result.warn(
            "url_content_thin",
            "URL 본문이 얇습니다. JS 렌더링 페이지(예: 잡코리아 상세)일 수 있어 "
            "text 소스타입으로 공고 본문을 직접 넣는 것을 권장합니다.",
        )
    return text


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def extract_text(source: dict | None) -> ExtractResult:
    """{sourceType, value} → 추출 텍스트 + warnings.

    sourceType: "text" | "file" | "url" (그 외/누락이면 text 로 간주)
    """

    result = ExtractResult(text="")
    if not source:
        result.warn("no_source", "입력 소스가 비어 있습니다.")
        return result

    source_type = (source.get("sourceType") or "text").lower()
    value = source.get("value") or ""

    if source_type == "text":
        result.text = value.strip()
    elif source_type == "file":
        result.text = _extract_file(value, result)
    elif source_type == "url":
        result.text = _extract_url(value, result)
    else:
        result.warn("unknown_source_type", f"알 수 없는 sourceType: {source_type}")
        result.text = value.strip()

    if not result.text:
        result.warn("empty_extract", "추출된 텍스트가 없습니다.")
    return result
