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

import contextvars
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..config import get_settings
from ..extract import _MIN_MEANINGFUL_CHARS, _USER_AGENT, ExtractResult, _HTMLTextExtractor

_JINA_BASE = "https://r.jina.ai/"
# ponytail: 이미지 VLM 호출 상한 — 공고 하나에 수십 장 박힌 페이지의 비용 폭주 방지.
_MAX_VLM_IMAGES = 10
_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# 이미지 공고를 VLM 이 받는 크기로 만드는 상수 — **실측값이다(2026-08-04)**.
# 잡코리아 이미지 공고가 940×10951 · 5.2MB PNG 였고 Clova 는 그대로 넣으면
# `40063 Invalid image size` 로 거부했다. 940×1880 타일은 통과했다.
_VLM_TILE_MAX_WIDTH = 1440      # 이보다 넓으면 비율 유지로 축소
_VLM_TILE_ASPECT = 2            # 타일 높이 = 너비 × 2 (통과 확인된 비율)
# 타일 경계에서 글자가 반으로 잘리지 않게 겹쳐 자른다. 겹치면 같은 줄이 두 타일에 나오지만,
# 잘려서 사라지는 것보다 중복이 낫다(뒤 파서는 중복 문장에 강하고, 결손에는 약하다).
_VLM_TILE_OVERLAP = 100
# ponytail: 타일 총량 상한 — 세로로 매우 긴 공고에서 호출·지연이 폭주하지 않게.
# 넘치면 앞쪽부터 버리지 않고 뒤쪽을 버린다(공고는 위에서부터 중요하다) + 경고를 남긴다.
_MAX_VLM_TILES = 8

_VLM_PROMPT = (
    "이 이미지는 채용공고의 일부다. 이미지에 있는 모든 텍스트를 빠짐없이, "
    "레이아웃 순서대로 그대로 옮겨 적어라. 요약하거나 해석하지 마라."
)


def _get_bytes(url: str, headers: dict | None = None, timeout: int = 60) -> bytes:
    """GET → 원본 바이트. 이미지처럼 디코딩하면 안 되는 것에 쓴다."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (사용자 지정 URL)
        return resp.read()


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
class _MetaDescCollector(HTMLParser):
    """<meta name="description"|property="og:description"> 의 content 를 줍는다."""

    def __init__(self) -> None:
        super().__init__()
        self.desc = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag != "meta" or self.desc:
            return
        d = dict(attrs)
        if d.get("name") == "description" or d.get("property") == "og:description":
            self.desc = (d.get("content") or "").strip()


def meta_description(html: str) -> str:
    """페이지 메타 설명 — 잡코리아는 헤더 요약(경력·학력·급여)을 JS 로 그려서 jina 본문에
    빠지는데, 정적 meta description 에 같은 요약이 있다(실측 Gno=49564982: 헤더 "경력
    1~5년"이 본문에 없어 프로젝트 나열 속 "8년 이상"이 요구 연차로 나갔다). 본문 맨 앞에
    붙여 파서가 공고 대표 정보를 먼저 보게 한다."""

    parser = _MetaDescCollector()
    parser.feed(html)
    return parser.desc


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


def _vlm_tiles(data: bytes, result: ExtractResult, label: str) -> list[str]:
    """이미지 바이트 → VLM 에 넣을 data URI 목록(세로로 쪼갠 타일).

    **왜 쪼개나**: 이미지 공고는 세로로 매우 길다(실측 940×10951). 그대로 보내면 Clova 가
    `40063 Invalid image size` 로 거부하고, 필수요건·우대사항이 통째로 사라진다. 억지로 한 장에
    맞추려고 축소하면 글자가 읽히지 않으므로 **해상도를 지키고 잘라서 여러 번** 묻는다.

    **왜 URL 대신 바이트인가**: Clova 가 이미지를 직접 받아오는 경로(imageUrl)는 크기 검사도
    Clova 몫이라 우리가 줄일 수 없고, Referer 를 요구하는 이미지도 못 가져온다.
    """

    import base64
    import io

    try:
        from PIL import Image
    except ImportError:                     # 선택 의존성이 빠진 환경 — 조용히 실패하지 않는다
        result.warn("pillow_missing", "pillow 미설치 — 이미지 공고를 쪼갤 수 없어 건너뜁니다.")
        return []
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:                # noqa: BLE001 — 깨진 이미지가 수집을 멈추지 않는다
        result.warn("image_decode_error", f"이미지를 읽지 못했습니다({label}): {exc}")
        return []

    # RGBA·팔레트 이미지는 JPEG 로 저장할 수 없다(투명 채널). 흰 배경에 합성한다 —
    # 공고 이미지는 흰 바탕이 기본이고, 검정으로 깔면 글자가 사라진다.
    if image.mode not in ("RGB", "L"):
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.convert("RGBA").split()[-1])
        image = flat
    else:
        image = image.convert("RGB")

    width, height = image.size
    if width > _VLM_TILE_MAX_WIDTH:
        height = round(height * _VLM_TILE_MAX_WIDTH / width)
        width = _VLM_TILE_MAX_WIDTH
        image = image.resize((width, height), Image.LANCZOS)

    tile_height = width * _VLM_TILE_ASPECT
    step = max(1, tile_height - _VLM_TILE_OVERLAP)
    tops = list(range(0, height, step)) or [0]
    # 마지막 타일이 겹침보다 얇으면 앞 타일에 이미 다 들어 있다 — 한 번 더 묻지 않는다.
    if len(tops) > 1 and height - tops[-1] <= _VLM_TILE_OVERLAP:
        tops.pop()
    if len(tops) > _MAX_VLM_TILES:
        result.warn("vlm_tiles_capped",
                    f"이미지 공고를 {len(tops)}조각으로 잘라야 하는데 앞 {_MAX_VLM_TILES}조각만 "
                    f"읽습니다({label}) — 공고 뒷부분이 빠질 수 있습니다.")
        tops = tops[:_MAX_VLM_TILES]

    uris: list[str] = []
    for top in tops:
        buffer = io.BytesIO()
        image.crop((0, top, width, min(top + tile_height, height))).save(
            buffer, "JPEG", quality=80)
        uris.append("data:image/jpeg;base64,"
                    + base64.b64encode(buffer.getvalue()).decode("ascii"))
    return uris


def _image_text(image_url: str, page_url: str, result: ExtractResult) -> str:
    """이미지 공고 한 장 → 텍스트. 우리가 받아서 쪼갠 뒤 타일마다 VLM 에 묻는다.

    타일은 **병렬로** 묻는다 — 세로로 긴 공고는 조각이 여럿이라 순차로는 분석이 몇 분씩 걸린다.
    워커에 contextvars 를 복사해 trace·LLM 집계가 끊기지 않게 한다(`posting_analysis` 와 같은 규율).
    """

    try:
        raw = _get_bytes(image_url, headers={"Referer": page_url})
    except Exception as exc:                # noqa: BLE001
        result.warn("image_fetch_error", f"이미지 요청 실패({image_url}): {exc}")
        return ""

    tiles = _vlm_tiles(raw, result, image_url)
    if not tiles:
        return ""
    with ThreadPoolExecutor(max_workers=min(4, len(tiles))) as pool:
        futures = [
            pool.submit(contextvars.copy_context().run, _clova_vlm,
                        {"type": "image_url", "dataUri": {"data": uri}}, result,
                        f"{image_url} 조각{i + 1}/{len(tiles)}")
            for i, uri in enumerate(tiles)
        ]
        parts = [f.result() for f in futures]
    return "\n\n".join(p for p in parts if p)


def _looks_like_image(url: str) -> bool:
    """`<img src>` 를 VLM 에 넘길 이미지로 볼 것인가.

    **확장자를 요구하면 안 된다.** 실측(2026-08-04, 잡코리아 Gno=49525099): 공고 본문이 세로로
    긴 이미지 한 장이었는데 그 URL 이
    `…/Net/Mng/DownImage/CorpEditor?file_No=1787352` — **확장자가 없는 쿼리스트링 다운로드
    엔드포인트**였다. `endswith(_IMG_EXTS)` 가 이걸 버려서 필수요건·우대사항이 통째로
    사라지고, 806자 껍데기(제목·급여·마감)만으로 공고를 정리했다.

    그래서 판정을 뒤집었다: `<img>` 태그의 src 는 **기본적으로 이미지다**(태그가 이미 그렇게
    말한다). 거르는 것은 이미지가 아닌 것이 분명한 둘뿐이다 —
      · 데이터 URI: 인라인 아이콘·스페이서이고, 공개 URL 을 받는 Clova 경로에 넣을 수 없다.
      · 이미지가 아닌 확장자(.svg·.gif 등): 로고·구분선·추적 픽셀이다. VLM 을 쓸 값이 없다.
    확장자가 **없으면 통과시킨다** — 그게 이 사고의 형태였다. 잘못 넘겨도 대가는 VLM 호출
    한 번이고(`_MAX_VLM_IMAGES` 가 상한을 잡는다), 버리는 대가는 공고 본문 전체다.
    """

    low = url.lower()
    if low.startswith("data:"):
        return False
    # 경로의 마지막 조각에서만 확장자를 본다 — 쿼리에 ".png" 가 섞여도 경로 확장자가 아니다.
    path = low.split("?", 1)[0].split("#", 1)[0]
    tail = path.rsplit("/", 1)[-1]
    if "." not in tail:
        return True                      # 확장자 없음 = 쿼리 기반 배달. 통과시킨다.
    return tail.endswith(_IMG_EXTS)


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
    found = _collect_srcs(html, iframe_url, "img")
    images = [u for u in found if _looks_like_image(u)]
    if not images:
        if text:
            return text  # 얇지만 있는 텍스트라도 살린다
        # **이미지가 있었는데 전부 걸러졌으면 그렇게 말한다.** 전에는 둘을 같은
        # `iframe_empty`("찾지 못함")로 뭉갰다 — 실측(2026-08-04, 잡코리아 Gno=49525099):
        # 본문이 세로로 긴 이미지 한 장이었고 그 URL 이 걸러졌는데 경고는 "이미지가 없다"고
        # 말해서, 필터가 원인이라는 것이 로그에서 보이지 않았다(§2-6).
        if found:
            result.warn("iframe_images_filtered",
                        f"iframe 이미지 {len(found)}장이 모두 이미지로 인정되지 않았습니다: "
                        f"{found[:3]}")
        else:
            result.warn("iframe_empty", f"iframe 에서 텍스트/이미지를 찾지 못함: {iframe_url}")
        return ""
    if len(images) > _MAX_VLM_IMAGES:
        result.warn("vlm_images_capped", f"이미지 {len(images)}장 중 {_MAX_VLM_IMAGES}장만 VLM 처리")
        images = images[:_MAX_VLM_IMAGES]
    # 이미지는 **우리가 받아서 쪼개** 넘긴다(_image_text) — Clova 에 URL 을 주면 크기 검사를
    # 우리가 못 하고, 세로로 긴 공고가 40063 으로 통째로 버려진다(실측 2026-08-04).
    parts = [t for t in (_image_text(u, page_url, result) for u in images) if t]
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

    result.text = "\n\n".join(
        p for p in [meta_description(raw_html), main_text, *detail_parts] if p
    ).strip()
    if not result.text:
        result.warn("empty_extract", "URL 에서 추출된 텍스트가 없습니다.")
    elif len(result.text) < _MIN_MEANINGFUL_CHARS:
        result.warn("url_content_thin", "수집된 공고 본문이 얇습니다. 원문 확인을 권장합니다.")
    return result
