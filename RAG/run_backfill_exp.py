"""기존 postings의 exp_min/exp_max 재계산 (parse_exp_range 버그 수정 후 1회성 백필).

이전 parse_exp_min()은 "3-8년" 같은 범위 표현에서 "년" 바로 앞 숫자(상한 8)를
exp_min으로 잘못 저장했다. parse_exp_range()로 하한/상한을 분리해 재계산하고,
raw->>'experience' 원문(재크롤링 없이 DB에 이미 있는 값)으로 다시 채운다.
schema.sql 적용(ALTER TABLE ... ADD COLUMN IF NOT EXISTS exp_max)이 선행되어야 한다.

사용: python run_backfill_exp.py [--dry-run]
"""
from __future__ import annotations

import sys

from jobrag.sources import parse_exp_from_body, parse_exp_range
from jobrag.store import connect


def main():
    dry_run = "--dry-run" in sys.argv
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT uid, exp_min, exp_max, needs_review,
                              raw->>'experience', title, raw->>'detail_text'
                       FROM postings""")
        rows = cur.fetchall()

    updates = []
    changed = from_body = 0
    for uid, old_min, old_max, old_review, raw_exp, title, body in rows:
        raw_exp = raw_exp or ""
        new_min, new_max, suspect = parse_exp_range(raw_exp)
        # 크롤러가 experience에 라벨만 담은 공고("경력") 구제 — to_posting과 동일 규칙.
        # "무관"/"신입"은 파서가 의도적으로 준 값이므로 덮지 않는다.
        if new_min is None and "무관" not in raw_exp and "신입" not in raw_exp:
            b = parse_exp_from_body(f"{title or ''}\n{body or ''}")
            if b is not None:
                new_min, suspect = b, True
                from_body += 1
        if (new_min, new_max) != (old_min, old_max):
            changed += 1
            print(f"  {uid}: exp_min {old_min}->{new_min}, exp_max {old_max}->{new_max}"
                  f"  (experience={raw_exp!r}{', 본문추정' if suspect and new_min is not None else ''})")
        updates.append((new_min, new_max, suspect or bool(old_review), uid))

    print(f"\n대상 {len(rows)}건 중 변경 {changed}건 (본문 보강 {from_body}건)")

    if dry_run:
        print("(--dry-run: DB 갱신 없음)")
        conn.close()
        return

    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE postings SET exp_min = %s, exp_max = %s, needs_review = %s, "
            "updated_at = now() WHERE uid = %s",
            updates,
        )
    conn.commit()
    print(f"갱신 완료: {len(updates)}건")
    conn.close()


if __name__ == "__main__":
    main()
