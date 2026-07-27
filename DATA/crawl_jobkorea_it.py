"""잡코리아의 텍스트 기반 IT 개발 직무 공고를 SQLite와 JSON으로 수집한다.

이미지 안에만 모집 내용이 있는 공고는 OCR 없이는 신뢰성 있게 읽을 수 없으므로
저장하지 않는다. 사이트 정책과 요청 빈도를 준수하기 위해 요청 사이에 지연을 둔다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://www.jobkorea.co.kr"
SEARCH_KEYWORDS = [
    "백엔드 개발자", "프론트엔드 개발자", "소프트웨어 엔지니어", "앱 개발자", "개발자",
    "Java 개발자", "Python 개발자", "DevOps 엔지니어", "풀스택 개발자", "데이터 엔지니어",
]
ROLE_WORDS = ("개발", "엔지니어", "프로그래머", "programmer", "developer", "devops")
EXCLUDE_WORDS = (
    "사업개발", "부동산 개발", "메뉴개발", "상품개발", "교육과정 개발",
    "기획", "디자이너", "마케터", "홍보", "영업", "서비스 운영", "콘텐츠",
    "helpdesk", "헬프데스크", "it support", "it지원",
)
USER_AGENT = "Mozilla/5.0 (compatible; JobisResearchBot/1.0; +local-study)"
DEFAULT_DB = Path("data/jobkorea_job_postings/jobkorea_job_postings.db")
DEFAULT_JSON = Path("exports/jobkorea_job_postings.json")
FIELDS = (
    "source",
    "posting_id",
    "company",
    "title",
    "url",
    "employment_type",
    "experience",
    "education",
    "location",
    "posted_date",
    "deadline",
    "detail_text",
    "image_urls",
    "need_ocr",
    "collected_at",
)


def log_search(source: str, keyword: str, page: int, unique_candidates: int) -> None:
    print(
        f"[{source}] search={keyword!r} page={page} "
        f"unique_candidates={unique_candidates}",
        flush=True,
    )


def log_item(
    source: str,
    index: int,
    posting_id: str,
    url: str,
    status: str,
    **details: object,
) -> None:
    """모든 크롤러가 같은 형식으로 개별 공고 처리 결과를 출력한다."""
    message = (
        f"[{source}] item={index} posting_id={posting_id!r} status={status} url={url}"
    )
    for key, value in details.items():
        if value is not None:
            message += f" {key}={value!r}"
    print(message, flush=True)


def log_summary(
    source: str, records: int, text_records: int, ocr_pending: int, db: Path, json_path: Path
) -> None:
    print(
        f"[{source}] status=completed records={records} text={text_records} "
        f"ocr_pending={ocr_pending} db={db} json={json_path}",
        flush=True,
    )


class VisibleText(HTMLParser):
    """script/style을 제외한 페이지의 표시 텍스트를 평문으로 만든다."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden_depth += 1
        elif tag in {"div", "p", "li", "br", "h1", "h2", "h3", "section"} and not self.hidden_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


def fetch(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def normalize_url(url: str) -> str:
    match = re.search(r"/Recruit/GI_Read/(\d+)", html.unescape(url), re.I)
    return f"{BASE_URL}/Recruit/GI_Read/{match.group(1)}" if match else ""


def collect_candidates(limit: int, delay: float) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for keyword in SEARCH_KEYWORDS:
        # 잡코리아 화면의 '등록일순' 선택값(ord=RegDtDesc)을 명시한다.
        page = fetch(
            f"{BASE_URL}/Search/?stext={quote_plus(keyword)}&ord=RegDtDesc"
        )
        for href in re.findall(r"(?:https?:)?//[^\"']*/Recruit/GI_Read/\d+[^\"']*|/Recruit/GI_Read/\d+[^\"']*", page, re.I):
            url = normalize_url(href)
            if url and url not in seen:
                seen.add(url)
                candidates.append((url, keyword))
        log_search("jobkorea", keyword, 1, len(candidates))
        time.sleep(delay)
    return candidates


def job_posting_json(page: str) -> dict | None:
    for raw in re.findall(r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page, re.I | re.S):
        try:
            value = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def plain_text(page: str) -> str:
    parser = VisibleText()
    parser.feed(page)
    return parser.text()


def detail_image_urls(page: str, base_url: str) -> list[str]:
    """상세 iframe의 본문 이미지 URL을 중복 없이 추출한다."""
    urls: list[str] = []
    seen: set[str] = set()
    for raw_url in re.findall(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', page, re.I):
        image_url = urljoin(base_url, html.unescape(raw_url).strip())
        if image_url.startswith(("http://", "https://")) and image_url not in seen:
            seen.add(image_url)
            urls.append(image_url)
    return urls


def detail_iframe_url(posting_url: str) -> str:
    posting_id = re.search(r"(\d+)$", posting_url).group(1)
    return f"{BASE_URL}/Recruit/GI_Read_Comt_Ifrm?Gno={posting_id}&isHiringCenter=false&hideMapView=false"


def has_complete_text_detail(text: str) -> bool:
    """OCR 없이 사용할 수 있는 상세 본문인지 엄격히 판정한다.

    잡코리아 바깥 페이지의 모집요강은 요약 정보이므로 사용하지 않는다. 실제 상세
    iframe에서 담당업무·자격요건·우대사항이 모두 텍스트로 제공되는 경우만 통과한다.
    이미지 태그가 있더라도 이 세 항목의 텍스트가 있으면 OCR이 필요하지 않다.
    """
    compact = re.sub(r"\s+", "", text)
    has_responsibility = any(word in compact for word in ("담당업무", "주요업무", "직무내용"))
    has_requirement = any(word in compact for word in ("자격요건", "지원자격", "필수요건", "필요역량"))
    has_preferred = any(word in compact for word in ("우대사항", "우대조건", "우대요건"))
    return len(text) >= 350 and has_responsibility and has_requirement and has_preferred


def is_ocr_pending_detail(text: str, image_urls: list[str]) -> bool:
    """본문 텍스트가 부족하고 이미지가 있는 공고만 OCR 대기 대상으로 분류한다."""
    return bool(image_urls) and len(text) < 350


def is_developer_role(title: str, text: str) -> bool:
    lowered_title = title.lower()
    if any(word in lowered_title for word in EXCLUDE_WORDS):
        return False
    # 검색어에 '앱' 등이 들어가더라도 기획·마케팅 직무를 개발 직무로 오인하지 않는다.
    return any(word in lowered_title for word in ROLE_WORDS)


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def employment_type_in_korean(value: object) -> str | None:
    """JobPosting의 영문 employmentType을 화면용 한국어 고용형태로 바꾼다."""
    values = value if isinstance(value, list) else [value]
    labels = {
        "FULL_TIME": "정규직",
        "FULLTIME": "정규직",
        "CONTRACTOR": "계약직",
        "CONTRACT": "계약직",
        "TEMPORARY": "계약직",
        "PART_TIME": "시간제",
        "PARTTIME": "시간제",
        "INTERN": "인턴",
        "FREELANCE": "프리랜서",
    }
    result: list[str] = []
    for item in values:
        for raw_type in re.split(r"[\s,]+", str(item or "").strip()):
            label = labels.get(raw_type.upper())
            if label and label not in result:
                result.append(label)
    return ", ".join(result) or None


def base_record(url: str, structured: dict) -> dict:
    """텍스트·OCR 공고가 공통으로 갖는 메타데이터를 만든다."""
    organization = structured.get("hiringOrganization") or {}
    address = ((structured.get("jobLocation") or {}).get("address") or {})
    identifier = structured.get("identifier") or {}
    return {
        "source": "잡코리아",
        "posting_id": clean(identifier.get("value")) or re.search(r"(\d+)$", url).group(1),
        "company": clean(organization.get("name")),
        "title": clean(structured.get("title")),
        "url": url,
        "employment_type": employment_type_in_korean(structured.get("employmentType")),
        "experience": clean(structured.get("experienceRequirements")),
        "education": clean(structured.get("educationRequirements")),
        "location": clean(address.get("streetAddress")),
        "posted_date": clean(structured.get("datePosted")),
        "deadline": clean(structured.get("validThrough")),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def text_record(url: str, structured: dict, detail_text: str) -> dict | None:
    """검증된 텍스트 본문이 있는 공고의 저장 레코드를 만든다."""
    if not has_complete_text_detail(detail_text):
        return None
    title = clean(structured.get("title"))
    if not title or not is_developer_role(title, detail_text):
        return None
    return {
        **base_record(url, structured),
        "detail_text": detail_text,
        "image_urls": [],
        "need_ocr": "X",
    }


def ocr_pending_record(
    url: str, structured: dict, detail_text: str, image_urls: list[str]
) -> dict | None:
    """OCR 처리 전에는 이미지 URL과 공고 메타데이터만 별도 보관한다."""
    title = clean(structured.get("title"))
    if not title or not is_developer_role(title, detail_text):
        return None
    if not is_ocr_pending_detail(detail_text, image_urls):
        return None
    return {
        **base_record(url, structured),
        "detail_text": "",
        "image_urls": image_urls,
        "need_ocr": "O",
    }


def classify_record(url: str, page: str) -> tuple[dict | None, dict | None]:
    """공고를 텍스트 저장·OCR 대기·제외 중 하나로 분류한다."""
    structured = job_posting_json(page)
    source_url = detail_iframe_url(url)
    detail_page = fetch(source_url)
    detail_text = plain_text(detail_page)
    if not structured:
        return None, None
    record = text_record(url, structured, detail_text)
    if record:
        return record, None
    return None, ocr_pending_record(
        url, structured, detail_text, detail_image_urls(detail_page, source_url)
    )


def init_db(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS job_postings ("
        + ", ".join(f"{field} TEXT" for field in FIELDS)
        + ")"
    )
    connection.commit()


def save_records(records: list[dict], db_path: Path, json_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE IF EXISTS job_postings")
        init_db(connection)
        # 기존 실행에서 만들어진 저정확도 결과를 남기지 않고 현재 검증 스냅샷으로 교체한다.
        connection.execute("DELETE FROM job_postings")
        if records:
            db_records = [
                {**record, "image_urls": json.dumps(record["image_urls"], ensure_ascii=False)}
                for record in records
            ]
            connection.executemany(
                "INSERT INTO job_postings VALUES (" + ", ".join("?" for _ in FIELDS) + ")",
                [[record[field] for field in FIELDS] for record in db_records],
            )
            connection.commit()
        connection.row_factory = sqlite3.Row
        saved = [
            {**dict(row), "image_urls": json.loads(row["image_urls"])}
            for row in connection.execute(
                "SELECT " + ", ".join(FIELDS) + " FROM job_postings "
                "ORDER BY collected_at, posting_id"
            )
        ]
    json_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.0, help="HTTP 요청 사이 대기 시간(초)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument(
        "--max-ocr-pending-results",
        type=int,
        default=0,
        help="OCR 대기 공고 최대 수(기본값: 후보에서 발견된 모든 이미지형 공고)",
    )
    args = parser.parse_args()
    if (
        args.max_results < 1
        or args.delay < 0.5
        or args.max_ocr_pending_results is not None
        and args.max_ocr_pending_results < 0
    ):
        raise SystemExit("결과 수는 0 이상, --max-results는 1 이상, --delay는 0.5 이상이어야 합니다.")

    records: list[dict] = []
    text_record_count = 0
    ocr_pending_count = 0
    for index, (url, keyword) in enumerate(collect_candidates(args.max_results, args.delay), start=1):
        if text_record_count >= args.max_results:
            break
        try:
            record, ocr_record = classify_record(url, fetch(url))
            if record:
                records.append(record)
                text_record_count += 1
                log_item(
                    "jobkorea", index, record["posting_id"], url, "saved",
                    text=f"{text_record_count}/{args.max_results}", title=record["title"],
                )
            elif ocr_record and (
                args.max_ocr_pending_results is None
                or ocr_pending_count < args.max_ocr_pending_results
            ):
                records.append(ocr_record)
                ocr_pending_count += 1
                log_item(
                    "jobkorea", index, ocr_record["posting_id"], url, "ocr_pending",
                    ocr_pending=ocr_pending_count, title=ocr_record["title"],
                )
            else:
                log_item(
                    "jobkorea", index, re.search(r"(\d+)$", url).group(1), url, "skipped",
                    reason="not_eligible_or_insufficient_detail",
                )
        except Exception as exc:  # 한 공고의 실패가 전체 수집을 중단시키지 않도록 한다.
            log_item(
                "jobkorea", index, re.search(r"(\d+)$", url).group(1), url, "error",
                error=type(exc).__name__,
            )
        time.sleep(args.delay)
    save_records(records, args.db, args.json)
    log_summary(
        "jobkorea", len(records), text_record_count, ocr_pending_count, args.db, args.json
    )
    return 0 if text_record_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
