"""기존 postings에 role_category 채우기 (컬럼 추가 후 1회성 백필).

schema.sql 적용(ALTER TABLE ... ADD COLUMN IF NOT EXISTS role_category)이
선행되어야 한다. title/raw->>'detail_text'/tech로 재분류하므로 원본 JSON 없이
DB만으로 돈다 — run_embed.py 전체 재실행보다 가볍다.

사용: python run_backfill_roles.py [--dry-run]
"""
from __future__ import annotations

import sys

from jobrag.role_taxonomy import classify
from jobrag.store import connect


def main():
    dry_run = "--dry-run" in sys.argv
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SELECT uid, title, raw->>'detail_text', tech FROM postings")
        rows = cur.fetchall()

    updates = []
    counts: dict[str, int] = {}
    for uid, title, detail_text, tech in rows:
        cat = classify(title or "", detail_text or "", tech or [])
        counts[cat or "(미분류)"] = counts.get(cat or "(미분류)", 0) + 1
        updates.append((cat or None, uid))

    print(f"대상 {len(rows)}건")
    for cat, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:14} {n}")

    if dry_run:
        print("(--dry-run: DB 갱신 없음)")
        conn.close()
        return

    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE postings SET role_category = %s, updated_at = now() WHERE uid = %s",
            updates,
        )
    conn.commit()
    print(f"갱신 완료: {len(updates)}건")
    conn.close()


if __name__ == "__main__":
    main()
