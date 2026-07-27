"""고용24의 텍스트 기반 개발 공고를 소량 시험 수집한다."""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin
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


BASE = "https://www.work24.go.kr"
DB = Path("data/work24_job_postings/work24_job_postings.db")
OUT = Path("exports/work24_job_postings.json")

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

DETAIL_SECTIONS = ("주요업무", "주요 업무", "담당업무", "모집분야")
QUALIFICATION_SECTIONS = ("자격요건", "자격 요건", "지원자격")
def fetch(url: str, data: dict | None = None) -> str:
    body = urlencode(data).encode() if data else None
    request = Request(url, data=body, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=12) as response:
        return response.read().decode("utf-8", "replace")


def candidates(keywords: list[str], pages_per_keyword: int) -> list[tuple[str, str]]:
    """모든 공통 검색어에서 중복 없는 고용24 공고 링크를 모은다."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []

    exhausted_keywords: set[str] = set()
    for page_number in range(1, pages_per_keyword + 1):
        for keyword in keywords:
            if keyword in exhausted_keywords:
                continue
            page = fetch(
                BASE + "/wk/a/b/1200/retriveDtlEmpSrchListInPost.do",
                {
                    "srcKeyword": keyword,
                    "searchYn": "Y",
                    "searchMode": "Y",
                    "pageIndex": str(page_number),
                    "currentPageNo": str(page_number),
                    # 고용24 화면의 '최근등록일순' 선택값이다.
                    "sortField": "DATE",
                    "sortOrderBy": "DESC",
                },
            )
            links = re.findall(
                r'href="([^"]*empDetailAuthView\.do\?wantedAuthNo=[^"]+)"', page
            )
            added = 0
            for href in links:
                url = urljoin(BASE, href)
                if url in seen:
                    continue
                seen.add(url)
                added += 1
                result.append((url, keyword))

            log_search("work24", keyword, page_number, len(seen))
            if added == 0:
                exhausted_keywords.add(keyword)
            time.sleep(0.3)
    return result


def strip_html(value: str) -> str:
    value = re.sub(
        r"<(?:script|style)[^>]*>.*?</(?:script|style)>",
        "",
        value,
        flags=re.I | re.S,
    )
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", value)))


def iframe_detail_url(page: str) -> str | None:
    """고용24가 외부 채용 사이트의 모집요강을 표시하는 iframe 주소를 찾는다."""
    for tag in re.findall(r"<iframe\b[^>]*>", page, re.I | re.S):
        if "상세모집요강 내용창" not in tag:
            continue
        match = re.search(r'''\bsrc=["']([^"']+)''', tag, re.I)
        if match:
            return html.unescape(match.group(1))
    return None


def table_value(page: str, label: str) -> str | None:
    match = re.search(
        rf"<th[^>]*>\s*{re.escape(label)}\s*</th>\s*<td[^>]*>(.*?)</td>",
        page,
        re.I | re.S,
    )
    return strip_html(match.group(1)) if match else None


def deadline(page: str) -> str | None:
    match = re.search(
        r"접수\s*기간.*?(\d{4}\.\d{2}\.\d{2}).*?~\s*(\d{4}\.\d{2}\.\d{2})",
        page,
        re.S,
    )
    return match.group(2) if match else None


def record(url: str) -> tuple[dict | None, dict | None]:
    page = fetch(url)
    outer_text = plain_text(page)
    title_match = re.search(r"<title[^>]*>\s*(.*?)\s*\|", page, re.S | re.I)
    title = clean(re.sub(r"<[^>]+>", "", title_match.group(1))) if title_match else ""
    lines = [clean(line) for line in outer_text.splitlines() if clean(line)]

    # 고용24의 <title>은 보통 '채용정보 상세'라서, 본문 기업명 다음의 실제 공고명을 사용한다.
    company = ""
    for index, line in enumerate(lines[:-1]):
        if line in {"일반기업", "공공기관", "외국계기업"}:
            title = lines[index + 1]
            company = lines[index - 1] if index else ""
            break

    iframe_url = iframe_detail_url(page)
    if not title or not iframe_url:
        return None, None

    # 바깥 고용24 페이지는 전체 메뉴가 섞이므로, 연결된 실제 모집요강만 본문으로 사용한다.
    detail_page = fetch(iframe_url)
    detail_text = plain_text(detail_page)
    compact = re.sub(r"\s+", "", detail_text)
    if not is_developer_role(title, detail_text):
        return None, None

    company_match = re.search(r"기업명\s*([^\n]+)", outer_text)
    if company_match:
        company = clean(company_match.group(1).replace("일반기업", ""))

    posting_id = re.search(r"wantedAuthNo=([^&]+)", url).group(1)
    base = {
        "source": "고용24",
        "posting_id": posting_id,
        "company": company,
        "title": title,
        "url": url,
        "employment_type": table_value(page, "고용형태"),
        "experience": table_value(page, "경력"),
        "education": table_value(page, "학력"),
        "location": table_value(page, "근무 예정지"),
        "posted_date": None,
        "deadline": deadline(page),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if (
        len(detail_text) >= 400
        and any(value in compact for value in DETAIL_SECTIONS)
        and any(value in compact for value in QUALIFICATION_SECTIONS)
    ):
        return {**base, "detail_text": detail_text, "image_urls": [], "need_ocr": "X"}, None
    image_urls = detail_image_urls(detail_page, iframe_url)
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


def load_existing() -> list[dict]:
    """중단된 대량 수집을 이어갈 때 이미 저장한 공고를 불러온다."""
    if not OUT.exists():
        return []
    return [
        {
            **row,
            "image_urls": row.get("image_urls", []),
            "need_ocr": row.get("need_ocr", "X"),
        }
        for row in json.loads(OUT.read_text(encoding="utf-8"))
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--max-ocr-pending-results", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument(
        "--pages-per-keyword",
        type=int,
        default=1,
        help="검색어별로 조회할 고용24 결과 페이지 수(한 페이지당 10개 후보)",
    )
    parser.add_argument("--resume", action="store_true", help="기존 JSON 결과에서 이어서 수집")
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=5,
        help="이 수만큼 저장될 때마다 JSON·DB에 중간 저장",
    )
    args = parser.parse_args()

    rows = load_existing() if args.resume else []
    known_ids = {str(row["posting_id"]) for row in rows}
    text_count = sum(row["need_ocr"] == "X" for row in rows)
    ocr_count = sum(row["need_ocr"] == "O" for row in rows)
    if rows:
        print(f"[work24] status=resumed records={len(rows)}", flush=True)

    for index, (url, _keyword) in enumerate(candidates(SEARCH_KEYWORDS, args.pages_per_keyword), 1):
        if text_count >= args.max_results:
            break
        try:
            posting_id = re.search(r"wantedAuthNo=([^&]+)", url).group(1)
            if posting_id in known_ids:
                log_item(
                    "work24", index, posting_id, url, "skipped", reason="already_saved"
                )
                continue

            row, ocr_row = record(url)
            if row:
                rows.append(row)
                known_ids.add(str(row["posting_id"]))
                text_count += 1
                log_item(
                    "work24", index, row["posting_id"], url, "saved",
                    text=f"{text_count}/{args.max_results}", title=row["title"],
                )
                if len(rows) % args.checkpoint_every == 0:
                    save(rows)
                    print(f"[work24] status=checkpoint records={len(rows)}", flush=True)
            elif ocr_row and (
                args.max_ocr_pending_results is None
                or ocr_count < args.max_ocr_pending_results
            ):
                rows.append(ocr_row)
                known_ids.add(str(ocr_row["posting_id"]))
                ocr_count += 1
                log_item(
                    "work24", index, ocr_row["posting_id"], url, "ocr_pending",
                    ocr_pending=ocr_count, title=ocr_row["title"],
                )
            else:
                log_item(
                    "work24", index, posting_id, url, "skipped",
                    reason="not_eligible_or_insufficient_detail",
                )
        except Exception as exc:
            posting_id = re.search(r"wantedAuthNo=([^&]+)", url).group(1)
            log_item("work24", index, posting_id, url, "error", error=type(exc).__name__)
        time.sleep(args.delay)

    save(rows)
    log_summary("work24", len(rows), text_count, ocr_count, DB, OUT)


if __name__ == "__main__":
    main()
