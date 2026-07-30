"""취업공고 URL 수집기 (입력 어댑터 계층의 url 경로 확장).

공고 페이지는 세 층으로 나뉜다:
1. 기본 텍스트(제목·마감·근무지 등)  → jina.ai reader 로 수집
2. iframe 안의 상세(우대사항·회사소개 등)
   - 텍스트 소스인 경우 → iframe HTML 직접 크롤링
   - 이미지 한 장으로 올린 경우 → Clova VLM 으로 텍스트 추출
3. 위 전부를 하나의 비정형 텍스트로 합쳐 반환 — 파싱은 하류(기존 로직)가 담당한다.

extract.extract_text 의 url 분기가 이 모듈을 부른다. 실패는 예외 대신 warning 으로
남긴다(extract.py 와 같은 규약).

환경변수: JINA_API_KEY(선택, 없으면 무키 호출), CLOVA_API_KEY, CLOVA_VLM_URL(선택)
"""

from __future__ import annotations

import json
import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..config import get_settings
from ..extract import _MIN_MEANINGFUL_CHARS, _USER_AGENT, ExtractResult, _HTMLTextExtractor

_JINA_BASE = "https://r.jina.ai/"
# ponytail: 이미지 VLM 호출 상한 — 공고 하나에 수십 장 박힌 페이지의 비용 폭주 방지.
_MAX_VLM_IMAGES = 10
_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

_VLM_PROMPT = (
    "이 이미지는 채용공고의 일부다. 이미지에 있는 모든 텍스트를 빠짐없이, "
    "레이아웃 순서대로 그대로 옮겨 적어라. 요약하거나 해석하지 마라."
)


def _get(url: str, headers: dict | None = None, timeout: int = 30) -> str:
    """GET → 디코딩된 본문. 실패는 호출부가 warning 으로 처리하도록 예외 그대로 던진다."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (사용자 지정 URL)
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")


# ---------------------------------------------------------------------------
# 1층: jina.ai — 기본 텍스트
# ---------------------------------------------------------------------------
def _jina_text(url: str, result: ExtractResult) -> str:
    headers = {}
    key = get_settings().jina_api_key
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        return _get(_JINA_BASE + url, headers=headers, timeout=60).strip()
    except Exception as exc:
        result.warn("jina_fetch_error", f"jina.ai 수집 실패: {exc}")
        return ""


# 이 마커부터는 대상 공고와 무관한 꼬리(타사 공고 광고·미리 로드된 다음 공고)다.
# iframe 상세는 jina 출력과 별도로 뒤에 붙으므로 여기서 잘려도 본문은 안전하다.
_TAIL_MARKERS = (
    "## 스마트픽",         # 잡코리아: 기업정보·근무환경 뒤의 타사 공고 광고 블록
    "[기업정보 전체보기]",  # 사람인: 이 링크 아래로 스토어 광고 + 미리 로드된 다음 공고
    # 잡코리아 로그인 유도 + 추천공고 티저 블록("로그인 하고 합격축하금/비슷한 조건의
    # AI추천공고를 확인해 보세요!"). 실측(Gno=49546576/49675900): 티저 수십 건이 통째로
    # 들어와 연차 근거·기술스택을 오염시켰다. 이 문구 뒤로 대상 공고 고유 정보는
    # 사이드바 요약(마감일 등)뿐이라, 광고 오염을 막는 값으로 지불한다.
    "공고를 확인해 보세요",
)


def _drop_unrelated_tail(text: str, result: ExtractResult) -> str:
    """jina 본문에서 기업정보 섹션 이후의 타사 공고·광고 꼬리를 잘라낸다.

    iframe 상세요강은 jina 출력과 별도로 뒤에 붙이므로 이 절단의 영향을 받지 않는다.
    """
    cuts = [i for m in _TAIL_MARKERS if (i := text.find(m)) != -1]
    if not cuts:
        return text
    cut = min(cuts)
    result.warn(
        "unrelated_tail_dropped",
        f"기업정보 이후 타사 공고/광고 꼬리 {len(text) - cut}자를 본문에서 제거함",
    )
    return text[:cut].rstrip()


# ---------------------------------------------------------------------------
# 2층: iframe — src 수집 → 텍스트 크롤링 or 이미지 VLM
# ---------------------------------------------------------------------------
class _AttrCollector(HTMLParser):
    """지정 태그의 지정 속성값만 모으는 최소 파서 (iframe src / img src 공용)."""

    def __init__(self, tag: str, attr: str) -> None:
        super().__init__()
        self._tag, self._attr = tag, attr
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == self._tag:
            value = dict(attrs).get(self._attr)
            if value:
                self.values.append(value)


# 공고 내용과 무관한 트래킹/광고 iframe (사람인 GTM 등에서 실측)
_JUNK_HOSTS = ("googletagmanager.com", "doubleclick.net", "google.com/recaptcha")


def _collect_srcs(html: str, base_url: str, tag: str) -> list[str]:
    parser = _AttrCollector(tag, "src")
    parser.feed(html)
    out: list[str] = []
    for src in parser.values:
        if src.startswith(("about:", "javascript:", "data:")):
            continue
        absolute = urljoin(base_url, src)
        if any(host in absolute for host in _JUNK_HOSTS):
            continue
        if absolute not in out:
            out.append(absolute)
    return out


# 잡코리아처럼 iframe 을 JS 로 주입하는 사이트: <iframe> 태그가 정적 HTML 에 없고,
# 스크립트/JSON 문자열 안에 iframe URL 이 이스케이프(&='&')로 박혀 있다.
# 사이트별 상세 iframe 경로 패턴을 여기 추가한다.
_SCRIPT_IFRAME_PATTERNS = [
    re.compile(r"/Recruit/GI_Read_Comt_Ifrm\?[^\s\"'<]+"),  # 잡코리아 상세 모집 요강
]


def _script_iframe_urls(html: str, base_url: str) -> list[str]:
    out: list[str] = []
    for pattern in _SCRIPT_IFRAME_PATTERNS:
        for match in pattern.findall(html):
            url = urljoin(base_url, match.replace("\\u0026", "&").rstrip("\\"))
            if url not in out:
                out.append(url)
    return out


def _derived_iframe_urls(page_url: str) -> list[str]:
    """iframe URL 이 정적 HTML 어디에도 없는 사이트: 페이지 URL 에서 규칙으로 파생.

    사람인은 상세요강 iframe(view-detail)을 JS 로 조립해서 원본 소스에 문자열조차 없다.
    다행히 페이지 URL 의 rec_idx 만으로 iframe URL 이 결정된다 (실측 2026-07).
    """
    m = re.search(r"saramin\.co\.kr/zf_user/jobs/relay/view\?[^#]*?rec_idx=(\d+)", page_url)
    if m:
        return [
            "https://www.saramin.co.kr/zf_user/jobs/relay/view-detail"
            f"?rec_idx={m.group(1)}&rec_seq=0"
        ]
    return []


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    # &nbsp;(U+00A0)를 일반 공백으로 — 키워드 매칭·파싱이 어긋나지 않게
    text = parser.text.replace("\xa0", " ")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _clova_vlm_text(image_url: str, result: ExtractResult) -> str:
    """공개 URL 이미지 한 장 → Clova VLM 텍스트."""
    return _clova_vlm({"type": "image_url", "imageUrl": {"url": image_url}}, result, image_url)


def _clova_vlm(image_content: dict, result: ExtractResult, label: str) -> str:
    """이미지 콘텐츠 한 개 → Clova VLM 텍스트. 키 없음/실패는 warning 후 빈 문자열.

    image_content 는 공개 URL(imageUrl) 또는 base64(dataUri — clova_vlm_file). label 은
    경고에 남길 출처 표시(데이터 URI 는 수천 자라 그대로 적으면 경고가 읽히지 않는다).
    """
    settings = get_settings()
    if not settings.clova_api_key:
        result.warn("clova_no_key", "CLOVA_API_KEY 미설정 — 이미지 공고 텍스트를 건너뜁니다.")
        return ""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    image_content,
                    {"type": "text", "text": _VLM_PROMPT},
                ],
            }
        ],
        "maxTokens": 2048,
    }
    try:
        req = urllib.request.Request(
            settings.clova_vlm_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.clova_api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        content = (data.get("result", {}).get("message", {}).get("content") or "").strip()
        # Clova 가 안전필터로 거부하면 거부 안내문이 content 로 온다 — 공고 텍스트에 섞이면 안 된다
        if "답변을 제공해 드릴 수 없" in content or "답변할 수 없" in content:
            result.warn("clova_vlm_refused", f"Clova VLM 이 응답을 거부함({label})")
            return ""
        return content
    except Exception as exc:
        result.warn("clova_vlm_error", f"Clova VLM 호출 실패({label}): {exc}")
        return ""


# 캡쳐 이미지로 받는 형식 — extract._extract_file 의 이미지 분기와 함께 쓰인다.
_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp"}


def clova_vlm_file(path: str, result: ExtractResult) -> str:
    """로컬 이미지 파일(공고 캡쳐) → Clova VLM 텍스트. data URI 로 보낸다(공개 URL 불필요).

    크롤링이 막힌 공고의 우회로다 — 사용자가 공고 화면을 캡쳐해 올리면 이 경로로 읽는다.
    """
    from pathlib import Path
    import base64

    p = Path(path)
    mime = _MIME_BY_EXT.get(p.suffix.lower())
    if mime is None:
        result.warn("unsupported_image_type", f"지원하지 않는 이미지 형식: {p.suffix}")
        return ""
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    # 실측(2026-07-30): dataUri.data 는 "data:<mime>;base64," 접두를 **포함**해야 한다.
    # bare base64(문서 예시 모양)와 imageUrl.url 에 data URI 를 넣는 것은 모두 400.
    return _clova_vlm(
        {"type": "image_url", "dataUri": {"data": f"data:{mime};base64,{encoded}"}},
        result, label=p.name,
    )


def _iframe_text(iframe_url: str, page_url: str, result: ExtractResult) -> str:
    """iframe 하나 → 텍스트. 텍스트 소스면 크롤링, 이미지뿐이면 VLM.

    Referer 필수: 잡코리아 상세요강 iframe(/Recruit/GI_Read_Comt_Ifrm)은
    Referer 없는 직접 요청을 차단할 수 있다.
    """
    try:
        html = _get(iframe_url, headers={"Referer": page_url})
    except Exception as exc:
        result.warn("iframe_fetch_error", f"iframe 요청 실패({iframe_url}): {exc}")
        return ""

    text = _html_to_text(html)
    if len(text) >= _MIN_MEANINGFUL_CHARS:
        return text

    # 텍스트가 얇다 → 이미지 공고로 간주하고 VLM 경로
    images = [u for u in _collect_srcs(html, iframe_url, "img") if u.lower().endswith(_IMG_EXTS)]
    if not images:
        if text:
            return text  # 얇지만 있는 텍스트라도 살린다
        result.warn("iframe_empty", f"iframe 에서 텍스트/이미지를 찾지 못함: {iframe_url}")
        return ""
    if len(images) > _MAX_VLM_IMAGES:
        result.warn("vlm_images_capped", f"이미지 {len(images)}장 중 {_MAX_VLM_IMAGES}장만 VLM 처리")
        images = images[:_MAX_VLM_IMAGES]
    parts = [t for t in (_clova_vlm_text(u, result) for u in images) if t]
    return "\n\n".join([text, *parts] if text else parts)


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------
def _ascii_url(url: str) -> str:
    """IRI → URI. 주소에 한글이 그대로 섞여 오면(사람인 검색 링크의 searchword=ai엔지니어 등)
    urllib 이 요청 전에 UnicodeEncodeError 로 즉사한다(실측 2026-07-30 — 네트워크 시도조차
    없이 수집 실패). 비ASCII 만 퍼센트 인코딩하고 예약 문자·기존 인코딩(%)은 보존한다."""

    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")


def fetch_job_posting(url: str) -> ExtractResult:
    """공고 URL → 비정형 텍스트(기본 + iframe 상세) + warnings."""

    url = _ascii_url(url)
    result = ExtractResult(text="")
    main_text = _drop_unrelated_tail(_jina_text(url, result), result)

    # iframe 은 원본 HTML 에서 찾는다 (jina 출력엔 iframe 태그가 없다)
    try:
        raw_html = _get(url)
    except Exception as exc:
        result.warn("url_fetch_error", f"원본 HTML 요청 실패: {exc}")
        raw_html = ""

    # 세 경로 합집합: <iframe> 태그(정적) + 스크립트 문자열(잡코리아) + URL 파생(사람인)
    iframe_urls = list(
        dict.fromkeys(
            _collect_srcs(raw_html, url, "iframe")
            + _script_iframe_urls(raw_html, url)
            + _derived_iframe_urls(url)
        )
    )
    detail_parts = [
        t for iframe_url in iframe_urls if (t := _iframe_text(iframe_url, url, result))
    ]

    result.text = "\n\n".join(p for p in [main_text, *detail_parts] if p).strip()
    if not result.text:
        result.warn("empty_extract", "URL 에서 추출된 텍스트가 없습니다.")
    elif len(result.text) < _MIN_MEANINGFUL_CHARS:
        result.warn("url_content_thin", "수집된 공고 본문이 얇습니다. 원문 확인을 권장합니다.")
    return result
