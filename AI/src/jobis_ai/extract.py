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


# 공고 캡쳐 이미지로 받는 형식 — 크롤링이 막힌 공고의 우회로(Clova VLM 텍스트화, D64)
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


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
        if suffix in _IMAGE_SUFFIXES:
            # 이미지(공고 캡쳐 등) → Clova VLM 텍스트화. 키 없음/실패는 warning 으로 남는다.
            from .feat_url import clova_vlm_file  # 지연 임포트: 이미지 경로에서만 필요

            return clova_vlm_file(str(path), result)
    except Exception as exc:  # 추출기 내부 오류도 그래프를 멈추지 않는다
        result.warn("file_extract_error", f"{suffix} 추출 실패: {exc}")
        return ""
    result.warn("unsupported_file_type", f"지원하지 않는 파일 형식: {suffix}")
    return ""


# ---------------------------------------------------------------------------
# URL 추출
# ---------------------------------------------------------------------------
class _HTMLTextExtractor(HTMLParser):
    """script/style/nav 등을 버리고 본문 텍스트를 **블록 단위 줄**로 모으는 최소 파서.

    텍스트 노드마다 줄을 만들지 않는다 — 한글/워드 내보내기 공고는 한 문장이 수십 개
    <span> 으로 쪼개져 있어(숫자·괄호가 별도 노드) 노드 단위로 줄을 만들면 파싱 불가능한
    낱말 더미가 된다(실측 잡코리아 Gno=49638104). 줄바꿈은 블록 태그에서만 일어나고,
    표의 행은 셀을 " | " 로 이어 컬럼 구조를 보존한다(_extract_docx 와 같은 규약 —
    "필수사항 | 자격요건 | 우대사항" 3컬럼 표가 낱줄로 흩어지면 구분이 사라진다).

    주의: meta/link 같은 void 요소(닫는 태그 없음)를 _SKIP 에 넣으면 안 된다 —
    _skip_depth 가 내려오지 않아 이후 본문 전체가 버려진다(사람인 iframe 실측).
    void 요소는 어차피 텍스트를 가질 수 없어 skip 이 불필요하다.
    """

    _SKIP = {"script", "style", "noscript", "head", "svg"}
    _BLOCK = {"p", "div", "br", "li", "ul", "ol", "table", "thead", "tbody", "tfoot",
              "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header",
              "footer", "dt", "dd", "blockquote", "hr", "form"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._lines: list[str] = []
        self._buf: list[str] = []
        self._rows: list[list[str]] = []      # 열린 <tr> 마다 한 층(중첩 표 대응)

    def _flush_buf(self) -> str:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        return text

    def _break_line(self) -> None:
        if self._rows:
            # 셀 안의 블록 경계는 줄이 아니라 공백 — 행이 완성될 때 셀 단위로 나간다.
            self._buf.append(" ")
            return
        text = self._flush_buf()
        if text:
            self._lines.append(text)

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "tr":
            self._break_line()
            self._rows.append([])
        elif tag in self._BLOCK:
            self._break_line()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif tag in ("td", "th"):
            if self._rows:
                self._rows[-1].append(self._flush_buf())
        elif tag == "tr":
            if self._rows:
                cells = [c for c in self._rows.pop() if c]
                row_text = " | ".join(cells)
                if row_text:
                    if self._rows:          # 중첩 표의 행 → 바깥 셀의 내용으로 흡수
                        self._buf.append(row_text + " ")
                    else:
                        self._lines.append(row_text)
        elif tag in self._BLOCK:
            self._break_line()

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._buf.append(data)

    @property
    def text(self) -> str:
        tail = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        return "\n".join([*self._lines, tail] if tail else self._lines)


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
        # 사용자가 URL 을 주면 **그 URL 을 직접 수집·파싱한다.** 크롤링 DB 를 먼저 조회하지
        # 않는다 — 프로토타입(Agent_Test)은 DB 키 조회로 갔지만 우리 제품 방향은 다르다:
        # 사용자가 특정 공고를 가리킨 것이므로 DB 에 있든 없든 그 공고의 현재 내용을 봐야 한다
        # (DB 는 크롤링 시점 스냅샷이고, 마감·수정이 반영되지 않는다).
        # 공고 DB 는 **검색·추천**(job_recommend / find_alternatives) 쪽에서만 쓴다.
        # 직접 HTML/iframe을 먼저 읽고, 결과가 부족할 때만 Jina를 쓰는 공통
        # SourceAcquisition 계약을 호출한다. 별도 정적 수집 폴백을 두지 않는다.
        from .feat_url import fetch_job_posting  # 지연 임포트: url 경로에서만 필요

        fetched = fetch_job_posting(value)
        result.warnings.extend(fetched.warnings)
        result.text = fetched.text
    else:
        result.warn("unknown_source_type", f"알 수 없는 sourceType: {source_type}")
        result.text = value.strip()

    if not result.text and not any(
        warning.get("code") == "source_fetch_failed" for warning in result.warnings
    ):
        result.warn("empty_extract", "추출된 텍스트가 없습니다.")
    return result
