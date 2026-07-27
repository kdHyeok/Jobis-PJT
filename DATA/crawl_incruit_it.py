"""인크루트의 텍스트 기반 IT 개발 공고를 수집한다."""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin
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


BASE = "https://job.incruit.com"
SEARCH_BASE = "https://search.incruit.com"
DB = Path("data/incruit_job_postings/incruit_job_postings.db")
OUT = Path("exports/incruit_job_postings.json")

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

DETAIL_SECTIONS = ("주요업무", "주요 업무", "담당업무", "직무소개", "모집직무")
QUALIFICATION_SECTIONS = ("자격요건", "자격 요건", "지원자격")
DEVELOPMENT_TERMS = (
    "소프트웨어",
    "SW",
    "웹",
    "앱",
    "프로그래밍",
    "Python",
    "Java",
    "React",
    "백엔드",
    "프론트엔드",
    "서버",
    "AI",
    "데이터",
    "LLM",
    "개발자",
)


def get(url: str) -> str:
    """일시적인 연결 실패 시 재시도하여 HTML을 가져온다."""
    for attempt in range(3):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            with urlopen(request, timeout=30) as response:
                charset = response.headers.get_content_charset() or "cp949"
                return response.read().decode(charset, "replace")
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def candidate_urls(
    keywords: list[str], pages_per_keyword: int
) -> list[tuple[str, str, str, str]]:
    """인크루트 통합검색 결과의 여러 페이지에서 실제 채용 카드만 수집한다."""
    result: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    for keyword in keywords:
        for page_number in range(pages_per_keyword):
            startno = page_number * 30
            page = get(
                f"{SEARCH_BASE}/list/search.asp?col=job&kw={quote_plus(keyword)}"
                # 인크루트 화면의 '최근 등록순' 선택값이다.
                f"&SortCd=reg&psize=30&startno={startno}"
            )
            added = 0

            for job_id, card in re.findall(
                r'<ul class="c_row"\s+jobno="(\d+)">(.*?)</ul>', page, re.I | re.S
            ):
                title_match = re.search(
                    rf"jobpost\.asp\?job={job_id}[^>]*>(.*?)</a>", card, re.I | re.S
                )
                company_match = re.search(
                    r'<a[^>]+class="cpname"[^>]*>(.*?)</a>', card, re.I | re.S
                )
                url = f"{BASE}/jobdb_info/jobpost.asp?job={job_id}"

                if not title_match or url in seen:
                    continue

                seen.add(url)
                added += 1
                title = clean(re.sub("<[^>]+>", "", html.unescape(title_match.group(1))))
                company = (
                    clean(re.sub("<[^>]+>", "", html.unescape(company_match.group(1))))
                    if company_match
                    else ""
                )
                result.append((url, title, company, keyword))

            log_search("incruit", keyword, page_number + 1, len(result))
            if added == 0:
                break
            time.sleep(0.4)

    return result


def detail_iframe_url(page: str, base_url: str) -> str | None:
    """상세 페이지에서 실제 공고 본문 iframe 주소를 찾는다."""
    for tag in re.findall(r"<iframe\b[^>]*>", page, re.I | re.S):
        src = re.search(r'''\bsrc=["']([^"']+)''', tag, re.I)
        if src and "jobpostcont.asp" in src.group(1):
            return urljoin(base_url, html.unescape(src.group(1)))
    return None


def record(url: str, title: str, company: str) -> tuple[dict | None, dict | None]:
    page = get(url)
    frame_url = detail_iframe_url(page, url)
    if not frame_url:
        return None, None

    frame_page = get(frame_url)
    detail_text = plain_text(frame_page)
    lines = [clean(line) for line in plain_text(page).splitlines() if clean(line)]
    compact = "".join(detail_text.split())

    if not is_developer_role(title, detail_text):
        return None, None

    def after(label: str) -> str | None:
        try:
            return lines[lines.index(label) + 1]
        except (ValueError, IndexError):
            return None

    frame_title = clean(
        re.sub(r"\s*-\s*인크루트 채용\s*$", "", detail_text.splitlines()[0])
    ) if detail_text.splitlines() else ""

    base = {
        "source": "인크루트",
        "posting_id": re.search(r"job=(\d+)", url).group(1),
        "company": company,
        "title": frame_title or title,
        "url": url,
        "employment_type": after("고용형태"),
        "experience": after("경력"),
        "education": after("학력"),
        "location": after("근무지역"),
        "posted_date": None,
        "deadline": after("마감"),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if (
        len(detail_text) >= 400
        and any(value in compact for value in DETAIL_SECTIONS)
        and any(value in compact for value in QUALIFICATION_SECTIONS)
        and any(value.lower() in detail_text.lower() for value in DEVELOPMENT_TERMS)
    ):
        return {**base, "detail_text": detail_text, "image_urls": [], "need_ocr": "X"}, None
    image_urls = detail_image_urls(frame_page, frame_url)
    if image_urls and len(detail_text) < 400:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--max-ocr-pending-results", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument(
        "--pages-per-keyword",
        type=int,
        default=1,
        help="검색어별로 조회할 결과 페이지 수(한 페이지당 30개 후보)",
    )
    args = parser.parse_args()

    rows: list[dict] = []
    text_count = 0
    ocr_count = 0
    for index, (url, title, company, _keyword) in enumerate(
        candidate_urls(SEARCH_KEYWORDS, args.pages_per_keyword), 1
    ):
        if text_count >= args.max_results:
            break
        try:
            row, ocr_row = record(url, title, company)
            if row:
                rows.append(row)
                text_count += 1
                log_item(
                    "incruit", index, row["posting_id"], url, "saved",
                    text=f"{text_count}/{args.max_results}", title=row["title"],
                )
            elif ocr_row and (
                args.max_ocr_pending_results is None
                or ocr_count < args.max_ocr_pending_results
            ):
                rows.append(ocr_row)
                ocr_count += 1
                log_item(
                    "incruit", index, ocr_row["posting_id"], url, "ocr_pending",
                    ocr_pending=ocr_count, title=ocr_row["title"],
                )
            else:
                posting_id = re.search(r"job=(\d+)", url).group(1)
                log_item(
                    "incruit", index, posting_id, url, "skipped",
                    reason="not_eligible_or_insufficient_detail",
                )
        except Exception as exc:
            posting_id = re.search(r"job=(\d+)", url).group(1)
            log_item("incruit", index, posting_id, url, "error", error=type(exc).__name__)
        time.sleep(args.delay)

    save(rows)
    log_summary("incruit", len(rows), text_count, ocr_count, DB, OUT)


if __name__ == "__main__":
    main()
