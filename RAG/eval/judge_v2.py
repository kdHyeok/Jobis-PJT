# -*- coding: utf-8 -*-
"""pool_v2 본판정 러너 — claude CLI judge, 재개형.

판정 캐시는 judgments_v2.json (구 GMS/v1 프롬프트 판정과 절대 혼용 금지).
중단돼도 재실행하면 미판정분만 이어서 판정한다.

실행: python -m eval.judge_v2
"""
from __future__ import annotations

import json
from pathlib import Path

from jobrag.store import connect

from . import judge

EVAL_DIR = Path(__file__).parent
POOL_PATH = EVAL_DIR / "pool_v2.json"

# 판정 캐시를 v2 전용 파일로 강제 — measure_v2도 judge.JUDGMENTS_PATH를 읽으므로
# 이 모듈을 import하는 쪽 모두 같은 파일을 보게 된다.
judge.JUDGMENTS_PATH = EVAL_DIR / "judgments_v2.json"


def main():
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    if judge.JUDGE_BACKEND != "claude_cli":
        print(f"[경고] JUDGE_BACKEND={judge.JUDGE_BACKEND} — 사전등록 §5는 claude_cli 단일 판정자")
    print(f"백엔드: {judge.backend_id()} / 캐시: {judge.JUDGMENTS_PATH.name}")
    total = sum(q["n_pool"] for q in pool["queries"].values())
    print(f"판정 대상 {total}쌍 / {len(pool['queries'])}질의")

    conn = connect()
    try:
        judge.judge_all(conn, {
            qid: {"query": q["query"], "uids": q["uids"]}
            for qid, q in pool["queries"].items()
        })
    finally:
        conn.close()

    cov = judge.coverage({qid: {"query": q["query"], "uids": q["uids"]}
                          for qid, q in pool["queries"].items()})
    incomplete = {qid: f"{c:.1%}" for qid, c in cov.items() if c < 1.0}
    if incomplete:
        print(f"[미완료] {incomplete} — 재실행하면 이어서 판정")
    else:
        print("커버리지 100% — 게이트 1 충족")


if __name__ == "__main__":
    main()
