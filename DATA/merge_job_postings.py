"""사이트별 채용 공고 JSON을 중복 제거해 하나의 JSON·SQLite 파일로 저장한다."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
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
    # 사이트마다 제각각인 deadline 원본을 YYYY-MM-DD로 통일한 파생 필드.
    # 쓰는 쪽(RAG·백엔드)이 각자 파서를 만들면 팀마다 다른 버그를 갖게 되므로
    # 여기서 한 번만 파싱해 넘긴다. 날짜가 없으면(상시채용 등) None.
    "deadline_date",
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


def clean_deadline(source: str, value: object) -> object:
    """인크루트 deadline에 붙는 요일·시각·안내문을 제거하고 날짜만 남긴다.

    인크루트 크롤러는 마감일 칸의 화면 텍스트를 그대로 저장해
    '2026.07.31 (금) 23:59 마감일은 기업의 사정으로...'처럼 들어온다.
    날짜 비교가 가능하도록 맨 앞의 YYYY.MM.DD만 남긴다. 다른 사이트는 건드리지 않는다.
    """
    if source == "인크루트" and value:
        match = re.match(r"\s*(\d{4}\.\d{2}\.\d{2})", str(value))
        if match:
            return match.group(1)
    return value


def normalize_row(source: str, row: dict) -> dict:
    """입력 JSON의 키 순서와 누락 필드를 공통 스키마로 맞춘다."""
    normalized = {
        field: (source if field == "source" else row.get(field))
        for field in FIELDS
    }
    normalized["deadline"] = clean_deadline(source, normalized["deadline"])
    # 정리된 deadline을 기준으로 파싱한다(인크루트는 뒤에 붙은 안내문을 먼저 떼야 함).
    normalized["deadline_date"] = parse_deadline_date(normalized["deadline"])
    return normalized


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


def load_rows() -> tuple[list[dict], list[str], list[str]]:
    """존재하는 사이트 JSON만 읽어 합친다. 없는 사이트는 건너뛰고 알려준다."""
    rows: list[dict] = []
    missing: list[str] = []
    present: list[str] = []
    for source, path in SOURCES:
        if not path.exists():
            missing.append(f"{source}({path})")
            continue
        source_rows = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(normalize_row(source, row) for row in source_rows)
        present.append(f"{source}={len(source_rows)}")
    return rows, missing, present


# 마감일 표기가 사이트마다 다르다. 실측된 형태:
#   2026.08.26 / 2026-08-26 / 2026-08-26T23:59 / 2026년 08월 21일
#   2026년 07월 01일 ~ 2026년 07월 31일 23시 59분, 채용 시 마감  (범위형)
#   상시채용 / 채용시 마감  (날짜 없음)
DEADLINE_DATE_PATTERN = re.compile(
    r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})"
)


def parse_deadline_date(deadline: object) -> str | None:
    """마감일 원본에서 YYYY-MM-DD를 뽑는다. '상시채용' 등 날짜가 없으면 None.

    실측(2026-08-03)에서 확인한 두 가지를 반영한다.
    - 사람인은 '2026-05-28 09시 ~ 2026-07-27 24시'처럼 게시기간을 범위로 준다.
      앞에서부터 찾으면 **시작일**을 마감일로 잡아, 아직 유효한 공고가 마감된 것으로
      뒤집힌다. 그래서 발견된 날짜 중 **마지막 것**을 마감일로 본다.
    - '2026년 08월 21일'처럼 한글 구분자를 쓰는 표기가 사람인에 상당수 있는데,
      구분자를 [.-]로만 보면 전부 날짜 없음으로 떨어진다.
    """
    matches = DEADLINE_DATE_PATTERN.findall(str(deadline or ""))
    if not matches:
        return None
    year, month, day = matches[-1]
    try:  # '2026.13.45' 같은 잘못된 값이 날짜로 둔갑하지 않게 실제 날짜인지 확인한다.
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def drop_empty_body(rows: list[dict]) -> tuple[list[dict], int]:
    """본문이 빈 공고를 통합본에서 제외한다.

    OCR로도 채우지 못한 공고(이미지가 사이트 템플릿 장식뿐이거나 내용이 없는 경우)를
    공고 ID로 제외 목록에 넣어 왔는데, 같은 회사가 **같은 공고를 새 ID로 다시 올리면**
    그대로 다시 들어온다(실측: 고용24 '분당 하이닉스 JAVA REACT 개발자 모집'이
    51303600 → 51337402로 재등록). ID를 쫓아다니는 방식으로는 막을 수 없어, 통합
    단계에서 본문 유무로 한 번 더 거른다.

    자동 실행 순서가 크롤링 → OCR → 통합이라 이 시점에는 OCR이 이미 기회를 다 쓴
    뒤다. 원본 사이트별 JSON은 그대로 두므로 데이터가 사라지는 것은 아니며, 나중에
    OCR이 성공하면 다음 통합 때 자연히 포함된다.
    """
    kept = [row for row in rows if (row.get("detail_text") or "").strip()]
    return kept, len(rows) - len(kept)


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
    rows, missing, present = load_rows()
    if missing:
        # 일부 사이트를 아직 수집하지 않았어도, 있는 사이트만으로 병합을 진행한다.
        print(f"[merge] status=warning skipped_missing={','.join(missing)}", flush=True)
    if not rows:
        print("[merge] status=failed reason=no_source_json_found", flush=True)
        return 1
    filled, empty = drop_empty_body(rows)
    merged, duplicates = deduplicate(filled)
    save(merged)
    print(
        f"[merge] status=completed sources=[{', '.join(present)}] "
        f"input_records={len(rows)} empty_body_dropped={empty} "
        f"duplicates_removed={duplicates} "
        f"records={len(merged)} db={OUT_DB} json={OUT_JSON}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
