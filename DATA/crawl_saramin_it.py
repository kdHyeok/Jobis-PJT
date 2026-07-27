"""사람인의 텍스트 기반 IT 개발 공고만 별도 수집한다."""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from crawl_jobkorea_it import (
    SEARCH_KEYWORDS,
    clean,
    detail_image_urls,
    fetch,
    has_complete_text_detail,
    is_ocr_pending_detail,
    is_developer_role,
    log_item,
    log_search,
    log_summary,
    plain_text,
)

BASE = "https://www.saramin.co.kr"
MOBILE = "https://m.saramin.co.kr"
DB_PATH = Path("data/saramin_job_postings/saramin_job_postings.db")
JSON_PATH = Path("exports/saramin_job_postings.json")
TRAILING_NOTICE_MARKERS = (
    "🛎️ 유의사항",
    "유의사항\n•",
    "사람인 공고 상세요강 입니다.",
)


def candidates(limit: int, delay: float) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str, str]] = []
    for keyword in SEARCH_KEYWORDS:
        # 사람인 화면의 '등록일순' 요청값이다.
        page = fetch(
            f"{BASE}/zf_user/search?searchword={quote_plus(keyword)}"
            "&recruitSort=reg_dt"
        )
        for posting_id in re.findall(r"rec_idx=(\d+)", html.unescape(page)):
            if posting_id not in seen:
                seen.add(posting_id)
                result.append(
                    (posting_id, keyword, f"{BASE}/zf_user/jobs/relay/view?rec_idx={posting_id}")
                )
        log_search("saramin", keyword, 1, len(result))
        time.sleep(delay)
    return result


def detail_html(posting_id: str) -> str:
    page = fetch(f"{MOBILE}/job-search/view?rec_idx={posting_id}")
    match = re.search(r"contents:\s*'([A-Za-z0-9+/=]+)'", page)
    if not match:
        return ""
    try:
        return base64.b64decode(match.group(1)).decode("utf-8", errors="replace")
    except ValueError:
        return ""


def job_detail_text(page: str) -> str:
    """공고 본문 뒤의 사람인 유의사항·저작권 고지를 제거한다."""
    detail = plain_text(page)
    cutoffs = [detail.find(marker) for marker in TRAILING_NOTICE_MARKERS]
    cutoffs = [position for position in cutoffs if position >= 0]
    return detail[: min(cutoffs)].rstrip() if cutoffs else detail


def value_after_label(text: str, *labels: str) -> str | None:
    """본문의 `항목 : 값` 또는 `항목` 다음 줄 형태에서 값을 찾는다."""
    lines = [clean(line.lstrip("•·- ")) for line in text.splitlines() if clean(line)]
    for index, line in enumerate(lines):
        for label in labels:
            match = re.match(rf"^{re.escape(label)}\s*[:：]\s*(.+)$", line, re.I)
            if match:
                return clean(match.group(1))
            if line.lower() == label.lower() and index + 1 < len(lines):
                return lines[index + 1]
    return None


def detail_metadata(detail: str) -> dict[str, str | None]:
    """사람인 상세 본문의 근무 조건·지원 조건을 공통 필드로 추출한다."""
    employment_type = value_after_label(detail, "고용형태")
    location = value_after_label(detail, "근무지", "근무지역")
    deadline = value_after_label(detail, "접수기간", "마감일")

    experience = value_after_label(detail, "경력")
    if not experience:
        match = re.search(
            r"(경력\s*(?:무관|\d+\s*년\s*(?:이상|이하|~\s*\d+\s*년)?))",
            detail,
        )
        experience = clean(match.group(1)) if match else None

    education = value_after_label(detail, "학력")
    if not education:
        match = re.search(
            r"(?:^|\n)\s*[•·-]?\s*((?:학력\s*무관)|(?:고등학교|대학교|대학원)[^\n]*)",
            detail,
        )
        education = clean(match.group(1)) if match else None

    return {
        "employment_type": employment_type,
        "experience": experience,
        "education": education,
        "location": location,
        "deadline": deadline,
    }


def title_company_and_posted_date(posting_id: str) -> tuple[str, str, str | None]:
    page = fetch(f"{BASE}/zf_user/jobs/relay/view?rec_idx={posting_id}")
    match = re.search(
        r'<meta\s+property="og:title"\s+content="\[([^]]+)\]\s*(.*?)\s*'
        r'(?:\(D-?\d+\))?\s*-\s*사람인"',
        page,
        re.I | re.S,
    )
    if not match:
        return "", "", None
    posted_date = value_after_label(plain_text(page), "등록일", "등록일시")
    return (
        clean(html.unescape(match.group(2))),
        clean(html.unescape(match.group(1))),
        posted_date,
    )


def record(posting_id: str, keyword: str, url: str) -> tuple[dict | None, dict | None]:
    detail_page = detail_html(posting_id)
    detail = job_detail_text(detail_page)
    title, company, posted_date = title_company_and_posted_date(posting_id)
    if not title or not is_developer_role(title, detail):
        return None, None
    metadata = detail_metadata(detail)
    base = {
        "source": "사람인",
        "posting_id": posting_id,
        "company": company,
        "title": title,
        "url": url,
        **metadata,
        "posted_date": posted_date,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if has_complete_text_detail(detail):
        return {
            **base,
            "detail_text": detail,
            "image_urls": [],
            "need_ocr": "X",
        }, None
    image_urls = detail_image_urls(
        detail_page, f"{MOBILE}/job-search/view?rec_idx={posting_id}"
    )
    if is_ocr_pending_detail(detail, image_urls):
        return None, {
            **base,
            "detail_text": "",
            "image_urls": image_urls,
            "need_ocr": "O",
        }
    return None, None


def save(records: list[dict]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS job_postings")
        conn.execute(
            """CREATE TABLE job_postings (
            source TEXT NOT NULL, posting_id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
            url TEXT NOT NULL, employment_type TEXT, experience TEXT, education TEXT, location TEXT,
            posted_date TEXT, deadline TEXT, detail_text TEXT NOT NULL, image_urls TEXT NOT NULL,
            need_ocr TEXT NOT NULL CHECK(need_ocr IN ('O', 'X')), collected_at TEXT NOT NULL
            )"""
        )
        if records:
            db_records = [
                {**record, "image_urls": json.dumps(record["image_urls"], ensure_ascii=False)}
                for record in records
            ]
            columns = list(db_records[0])
            values = ", ".join(f":{column}" for column in columns)
            conn.executemany(
                f"INSERT INTO job_postings ({', '.join(columns)}) VALUES ({values})",
                db_records,
            )
        conn.row_factory = sqlite3.Row
        saved = [
            {**dict(row), "image_urls": json.loads(row["image_urls"])}
            for row in conn.execute("SELECT * FROM job_postings ORDER BY posting_id")
        ]
    JSON_PATH.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--max-ocr-pending-results", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    records: list[dict] = []
    text_count = 0
    ocr_count = 0
    for index, (posting_id, keyword, url) in enumerate(candidates(args.max_results, args.delay), 1):
        if text_count >= args.max_results:
            break
        try:
            item, ocr_item = record(posting_id, keyword, url)
            if item:
                records.append(item)
                text_count += 1
                log_item(
                    "saramin", index, posting_id, url, "saved",
                    text=f"{text_count}/{args.max_results}", title=item["title"],
                )
            elif ocr_item and (
                args.max_ocr_pending_results is None
                or ocr_count < args.max_ocr_pending_results
            ):
                records.append(ocr_item)
                ocr_count += 1
                log_item(
                    "saramin", index, posting_id, url, "ocr_pending",
                    ocr_pending=ocr_count, title=ocr_item["title"],
                )
            else:
                log_item(
                    "saramin", index, posting_id, url, "skipped",
                    reason="not_eligible_or_insufficient_detail",
                )
        except Exception as exc:
            log_item("saramin", index, posting_id, url, "error", error=type(exc).__name__)
        time.sleep(args.delay)
    save(records)
    log_summary("saramin", len(records), text_count, ocr_count, DB_PATH, JSON_PATH)
    return 0 if text_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
