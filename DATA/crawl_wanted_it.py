"""원티드의 텍스트 기반 IT 개발 공고를 수집한다."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from crawl_jobkorea_it import (
    SEARCH_KEYWORDS,
    clean,
    detail_image_urls,
    is_developer_role,
    log_item,
    log_search,
    log_summary,
    plain_text,
)


BASE = "https://www.wanted.co.kr"
DB = Path("data/wanted_job_postings/wanted_job_postings.db")
OUT = Path("exports/wanted_job_postings.json")

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

DETAIL_SECTIONS = ("주요업무", "담당업무")
QUALIFICATION_SECTIONS = ("자격요건", "지원자격")


def get(url: str) -> str:
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def job_text_and_metadata(raw: str) -> tuple[str, dict[str, str | None]]:
    """원티드 페이지의 내비게이션·주의사항·푸터를 제외한 공고 본문만 남긴다."""
    start = raw.find("포지션 상세")
    text = raw[start + len("포지션 상세") :] if start >= 0 else raw

    # 공고 본문 뒤에 붙는 기술 스택·태그·지원 안내와 법적 고지는 저장하지 않는다.
    cutoffs = [text.find(marker) for marker in ("상세 정보 더 보기", "유의사항", "주의사항")]
    cutoffs = [position for position in cutoffs if position >= 0]
    if cutoffs:
        text = text[: min(cutoffs)]

    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    deadline_match = re.search(r"마감일\s*(상시채용|\d{4}\.\d{2}\.\d{2})", raw)
    location_match = re.search(r"근무지역\s*\n?([^\n]+)", raw)
    experience_match = re.search(
        r"∙(신입(?:\s*-\s*경력\s*\d+년)?|경력\s*\d+(?:-\d+)?년)", raw
    )

    return text, {
        "deadline": deadline_match.group(1) if deadline_match else None,
        "location": clean(location_match.group(1)) if location_match else None,
        "experience": experience_match.group(1) if experience_match else None,
    }


def record(item: dict) -> tuple[dict | None, dict | None]:
    posting_id = str(item["id"])
    url = f"{BASE}/wd/{posting_id}"
    page = get(url)
    detail_text, metadata = job_text_and_metadata(plain_text(page))
    title = clean(item.get("position"))
    compact = "".join(detail_text.split())

    if not is_developer_role(title, detail_text):
        return None, None

    company = (item.get("company") or {}).get("name", "")
    address = item.get("address") or {}
    base = {
        "source": "원티드",
        "posting_id": posting_id,
        "company": clean(company),
        "title": title,
        "url": url,
        "employment_type": None,
        "experience": metadata["experience"],
        "education": None,
        "location": metadata["location"] or clean(address.get("location")),
        "posted_date": None,
        "deadline": metadata["deadline"] or item.get("due_time"),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if (
        len(detail_text) >= 300
        and any(value in compact for value in DETAIL_SECTIONS)
        and any(value in compact for value in QUALIFICATION_SECTIONS)
    ):
        return {**base, "detail_text": detail_text, "image_urls": [], "need_ocr": "X"}, None
    image_urls = detail_image_urls(page, url)
    if image_urls and len(detail_text) < 300:
        return None, {**base, "detail_text": "", "image_urls": image_urls, "need_ocr": "O"}
    return None, None


def save(rows: list[dict]) -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB) as connection:
        connection.execute("DROP TABLE IF EXISTS job_postings")
        connection.execute(
            "CREATE TABLE job_postings (" + ", ".join(f"{field} TEXT" for field in FIELDS) + ")"
        )
        if rows:
            db_rows = [
                {**row, "image_urls": json.dumps(row["image_urls"], ensure_ascii=False)}
                for row in rows
            ]
            connection.executemany(
                "INSERT INTO job_postings VALUES (" + ", ".join("?" for _ in FIELDS) + ")",
                [[row[field] for field in FIELDS] for row in db_rows],
            )

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def candidates() -> list[tuple[dict, str]]:
    """공통 개발 직무 검색어별 원티드 후보를 중복 없이 모은다."""
    result: list[tuple[dict, str]] = []
    seen: set[str] = set()
    for keyword in SEARCH_KEYWORDS:
        url = (
            f"{BASE}/api/v4/jobs?country=kr&locations=all&years=-1&limit=20&offset=0"
            f"&job_sort=job.latest_order&query={quote_plus(keyword)}"
        )
        data = json.loads(get(url))
        for item in data.get("data", []):
            posting_id = str(item.get("id", ""))
            if posting_id and posting_id not in seen:
                seen.add(posting_id)
                result.append((item, keyword))
        log_search("wanted", keyword, 1, len(result))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--max-ocr-pending-results", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    rows: list[dict] = []
    text_count = 0
    ocr_count = 0
    for index, (item, _keyword) in enumerate(candidates(), 1):
        if text_count >= args.max_results:
            break
        posting_id = str(item.get("id", ""))
        url = f"{BASE}/wd/{posting_id}"
        try:
            if not is_developer_role(clean(item.get("position")), ""):
                log_item(
                    "wanted", index, posting_id, url, "skipped", reason="not_developer_role"
                )
                continue

            row, ocr_row = record(item)
            if row:
                rows.append(row)
                text_count += 1
                log_item(
                    "wanted", index, posting_id, url, "saved",
                    text=f"{text_count}/{args.max_results}", title=row["title"],
                )
            elif ocr_row and ocr_count < args.max_ocr_pending_results:
                rows.append(ocr_row)
                ocr_count += 1
                log_item(
                    "wanted", index, posting_id, url, "ocr_pending",
                    ocr_pending=ocr_count, title=ocr_row["title"],
                )
            else:
                log_item(
                    "wanted", index, posting_id, url, "skipped",
                    reason="not_eligible_or_insufficient_detail",
                )
        except Exception as exc:
            log_item("wanted", index, posting_id, url, "error", error=type(exc).__name__)
        time.sleep(args.delay)

    save(rows)
    log_summary("wanted", len(rows), text_count, ocr_count, DB, OUT)


if __name__ == "__main__":
    main()
