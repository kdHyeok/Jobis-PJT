"""특정 날짜에 새로 수집된 공고가 무엇인지 확인한다(일일 실행 결과 점검용).

run_daily_update.py 를 돌린 뒤 "오늘 뭐가 들어왔지?"를 보기 위한 조회 전용 스크립트다.
데이터를 고치지 않으므로 언제 실행해도 안전하다(수집이 도는 중에도 가능).

주의 — 시간대: 각 공고의 collected_at 은 UTC로 저장된다. 한국 시간 오전에 수집한 건은
UTC로는 '전날 23시'라 날짜 문자열만 잘라서 비교하면 오늘 수집분을 통째로 놓친다.
그래서 여기서는 UTC를 한국 시간(KST, UTC+9)으로 변환한 뒤 날짜를 비교한다.

실행:
    python3 report_collection.py                 # 오늘(한국 시간) 수집분
    python3 report_collection.py --date 2026-08-02
    python3 report_collection.py --days 3        # 최근 3일
    python3 report_collection.py --list          # 공고 제목까지 전부 나열
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

SITES = (
    ("잡코리아", Path("exports/jobkorea_job_postings.json")),
    ("사람인", Path("exports/saramin_job_postings.json")),
    ("원티드", Path("exports/wanted_job_postings.json")),
    ("인크루트", Path("exports/incruit_job_postings.json")),
    ("고용24", Path("exports/work24_job_postings.json")),
)

# 본문에서 뽑아 볼 대표 기술 키워드. 어떤 기술을 요구하는 공고가 들어왔는지 감을 잡는 용도.
TECH_WORDS = (
    "Java", "Python", "JavaScript", "TypeScript", "Kotlin", "Swift", "C++", "C#", "Go", "Rust", "PHP",
    "Spring", "React", "Vue", "Node", "Django", "FastAPI", "Flutter", "Android", "iOS",
    "AWS", "Docker", "Kubernetes", "MySQL", "PostgreSQL", "Oracle", "MongoDB", "Redis",
    "Git", "Linux", "Jenkins", "Kafka", "Elasticsearch", "GraphQL", "REST API",
)


def collected_kst_date(row: dict) -> date | None:
    """공고의 수집 시각(UTC)을 한국 시간 날짜로 바꾼다."""
    raw = row.get("collected_at")
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if moment.tzinfo is None:  # 시간대 표기가 없으면 UTC로 간주해 저장 규칙과 맞춘다.
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).date()


def tech_keywords(text: str) -> set[str]:
    """본문에서 대표 기술 키워드를 찾는다(대소문자 무시, 단어 경계 기준)."""
    found = set()
    for word in TECH_WORDS:
        # C++/C# 처럼 정규식 특수문자가 들어간 키워드가 있어 escape 한다.
        if re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text, re.I):
            found.add(word)
    return found


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="조회할 날짜(YYYY-MM-DD, 한국 시간). 기본: 오늘")
    parser.add_argument("--days", type=int, default=1, help="지정일부터 거슬러 조회할 일수 (기본: 1)")
    parser.add_argument("--list", action="store_true", help="공고 제목을 전부 나열")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days < 1:
        raise SystemExit("--days 는 1 이상이어야 합니다.")
    end = date.fromisoformat(args.date) if args.date else datetime.now(KST).date()
    start = end - timedelta(days=args.days - 1)
    label = str(end) if args.days == 1 else f"{start} ~ {end}"

    print(f"■ 수집 현황 — {label} (한국 시간 기준)\n")

    collected: list[tuple[str, dict]] = []
    print(f"{'사이트':<8} {'신규':>6} {'누적':>7}")
    print("-" * 24)
    for source, path in SITES:
        if not path.exists():
            print(f"{source:<8} {'파일없음':>6}")
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        fresh = [r for r in rows if (d := collected_kst_date(r)) and start <= d <= end]
        collected.extend((source, r) for r in fresh)
        print(f"{source:<8} {len(fresh):>6} {len(rows):>7}")
    print("-" * 24)
    print(f"{'합계':<8} {len(collected):>6}\n")

    if not collected:
        print("이 기간에 새로 수집된 공고가 없습니다.")
        return 0

    # 본문 출처: 사이트 원문 텍스트인지, 이미지에서 OCR로 뽑았는지
    ocr = sum(1 for _, r in collected if r.get("image_urls"))
    print(f"본문 출처: 사이트 원문 {len(collected) - ocr}건 / 이미지 OCR {ocr}건")

    lengths = sorted(len(r.get("detail_text") or "") for _, r in collected)
    print(f"본문 길이: 중간값 {lengths[len(lengths) // 2]:,}자 "
          f"(최소 {lengths[0]:,} / 최대 {lengths[-1]:,})\n")

    counter: Counter[str] = Counter()
    for _, row in collected:
        counter.update(tech_keywords(row.get("detail_text") or ""))
    if counter:
        print("자주 언급된 기술 (신규 공고 기준)")
        for word, n in counter.most_common(15):
            print(f"  {word:<14} {n:>4}건 ({n / len(collected) * 100:.0f}%)")
        print()

    print("신규 공고" + ("" if args.list else " (일부)"))
    shown = collected if args.list else collected[:15]
    for source, row in shown:
        mark = "[OCR]" if row.get("image_urls") else "     "
        print(f"  {mark} [{source}] {(row.get('title') or '')[:55]}")
        print(f"          {row.get('company')} | {row.get('url')}")
    if not args.list and len(collected) > len(shown):
        print(f"\n  ... 외 {len(collected) - len(shown)}건 (전부 보려면 --list)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
