"""사이트별 채용 공고 JSON을 중복 제거해 하나의 JSON·SQLite 파일로 저장한다."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


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
SOURCES = (
    ("잡코리아", Path("exports/jobkorea_job_postings.json")),
    ("사람인", Path("exports/saramin_job_postings.json")),
    ("원티드", Path("exports/wanted_job_postings.json")),
    ("인크루트", Path("exports/incruit_job_postings.json")),
    ("고용24", Path("exports/work24_job_postings.json")),
)
OUT_JSON = Path("exports/all_job_postings.json")
OUT_DB = Path("data/all_job_postings/all_job_postings.db")


def normalized_text(value: object) -> str:
    """사이트별 표기 차이를 줄여 같은 회사·공고명 비교에 사용한다."""
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").lower())


def normalize_row(source: str, row: dict) -> dict:
    """입력 JSON의 키 순서와 누락 필드를 공통 스키마로 맞춘다."""
    return {
        field: (source if field == "source" else row.get(field))
        for field in FIELDS
    }


def duplicate_key(row: dict) -> tuple[str, ...]:
    """같은 회사의 같은 공고명을 사이트 간 중복 공고로 본다."""
    company = normalized_text(row["company"])
    title = normalized_text(row["title"])
    if company and title:
        return "company_title", company, title
    return "source_posting_id", normalized_text(row["source"]), str(row["posting_id"])


def quality(row: dict) -> tuple[int, int, int, str]:
    """중복 시 텍스트 상세·메타데이터가 더 풍부한 공고를 남긴다."""
    metadata_count = sum(
        bool(row.get(field))
        for field in ("employment_type", "experience", "education", "location", "deadline")
    )
    return (
        row.get("need_ocr") == "X",
        len(row.get("detail_text") or ""),
        metadata_count,
        row.get("collected_at") or "",
    )


def load_rows() -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    missing: list[str] = []
    for source, path in SOURCES:
        if not path.exists():
            missing.append(str(path))
            continue
        source_rows = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(normalize_row(source, row) for row in source_rows)
    return rows, missing


def deduplicate(rows: list[dict]) -> tuple[list[dict], int]:
    selected: dict[tuple[str, ...], dict] = {}
    duplicates = 0
    for row in rows:
        key = duplicate_key(row)
        existing = selected.get(key)
        if existing is None:
            selected[key] = row
        else:
            duplicates += 1
            if quality(row) > quality(existing):
                selected[key] = row
    return list(selected.values()), duplicates


def save(rows: list[dict]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    ordered_rows = sorted(rows, key=lambda row: (row["source"], row["posting_id"]))
    OUT_JSON.write_text(json.dumps(ordered_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    with sqlite3.connect(OUT_DB) as connection:
        connection.execute("DROP TABLE IF EXISTS job_postings")
        connection.execute(
            "CREATE TABLE job_postings (" + ", ".join(f"{field} TEXT" for field in FIELDS) + ")"
        )
        connection.executemany(
            "INSERT INTO job_postings VALUES (" + ", ".join("?" for _ in FIELDS) + ")",
            [
                [
                    json.dumps(row[field], ensure_ascii=False)
                    if field == "image_urls"
                    else row[field]
                    for field in FIELDS
                ]
                for row in ordered_rows
            ],
        )


def main() -> int:
    rows, missing = load_rows()
    if missing:
        print(f"[merge] status=failed missing={','.join(missing)}", flush=True)
        return 1
    merged, duplicates = deduplicate(rows)
    save(merged)
    print(
        f"[merge] status=completed input_records={len(rows)} "
        f"duplicates_removed={duplicates} records={len(merged)} db={OUT_DB} json={OUT_JSON}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
