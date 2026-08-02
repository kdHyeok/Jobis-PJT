"""전면 재평가 오케스트레이터 — 순서·의존성이 있는 8단계를 한 번에 돌린다.

왜 스크립트로 묶는가: 단계 사이에 산출물 의존이 있다(합동 풀 -> 판정 -> 채택 ->
승격 -> 본평가 -> RAGAS). 손으로 순서를 밟으면 어느 단계를 빼먹었는지, 어떤 코퍼스
스냅샷에서 돌았는지 사후에 알 수 없다. 각 단계의 소요 시간과 종료 코드를 남긴다.

단계
----
 1 qtext_pool      4변형 합동 풀 구성 (60질의 × 4변형 × 5arm × depth10)
 2 qtext_judge     합동 풀 1회 판정
 3 qtext_measure   변형별 채점 + 사전등록 기준 판정 (eval/PREREG_query_text.md)
 4 confirm         채택 변형을 입력 B 실입력 경로(골든 36건)에서 확인
 5 promote         채택 변형 -> pool_spec.json / judgments_spec.json
 6 run_spec        본평가 (다중 k, judge/human-patched 두 qrels)
 7 io_tracks       입력 A / 입력 B 트랙 재측정
 8 judge_rel       판정자 자기일관성 + 사람 라벨 이전율
 9 ragas           RAGAS 4축 (동결 15종, 프로덕션 생성 포함)
10 dashboard       대시보드 재생성

사용:
  python run_eval_all.py                # 1번부터 전부
  python run_eval_all.py --from 6       # 6번부터 (앞 단계 산출물 재사용)
  python run_eval_all.py --only 3,4     # 특정 단계만
  python run_eval_all.py --list
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
RUN_LOG = LOG_DIR / "eval_all_run.json"

PY = [sys.executable, "-X", "utf8", "-u"]

STEPS: list[tuple[str, list[str]]] = [
    ("qtext_pool",    ["-m", "eval.query_text_ab", "--pool"]),
    ("qtext_judge",   ["-m", "eval.query_text_ab", "--judge"]),
    ("qtext_measure", ["-m", "eval.query_text_ab", "--measure"]),
    ("confirm",       ["-m", "eval.query_text_ab", "--confirm-pool",
                       "--confirm-judge", "--confirm-measure"]),
    ("promote",       ["-m", "eval.query_text_ab", "--promote"]),
    ("run_spec",      ["-m", "eval.run_spec"]),
    ("io_tracks",     ["-m", "eval.io_tracks", "--pool", "--judge", "--measure"]),
    ("judge_rel",     ["-m", "eval.judge_reliability", "--retest", "--measure"]),
    ("ragas",         ["-m", "eval.ragas_all"]),
    ("dashboard",     ["-m", "eval.make_dashboard"]),
]


def _run(idx: int, name: str, argv: list[str]) -> dict:
    log = LOG_DIR / f"step{idx:02d}_{name}.log"
    print(f"\n{'=' * 70}\n[{idx}/{len(STEPS)}] {name}\n  -> {log.name}", flush=True)
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.run(PY + argv, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
    print("\n".join("    " + t for t in tail), flush=True)
    print(f"  종료코드 {p.returncode} · {dt / 60:.1f}분", flush=True)
    return {"step": idx, "name": name, "argv": argv, "returncode": p.returncode,
            "minutes": round(dt / 60, 2), "log": log.name}


def main() -> int:
    args = sys.argv[1:]
    if "--list" in args:
        for i, (n, a) in enumerate(STEPS, 1):
            print(f"{i:2} {n:14} {' '.join(a)}")
        return 0

    start = 1
    only: set[int] | None = None
    for i, a in enumerate(args):
        if a == "--from":
            start = int(args[i + 1])
        elif a.startswith("--from="):
            start = int(a.split("=", 1)[1])
        elif a == "--only":
            only = {int(x) for x in args[i + 1].split(",")}
        elif a.startswith("--only="):
            only = {int(x) for x in a.split("=", 1)[1].split(",")}

    LOG_DIR.mkdir(exist_ok=True)
    results = []
    t0 = time.time()
    for idx, (name, argv) in enumerate(STEPS, 1):
        if only is not None and idx not in only:
            continue
        if only is None and idx < start:
            continue
        r = _run(idx, name, argv)
        results.append(r)
        if r["returncode"] != 0:
            # 뒤 단계가 앞 산출물에 의존하므로 실패하면 멈춘다 — 반쪽 리포트가
            # 나오는 것이 조용히 잘못된 수치를 남기는 것보다 낫다.
            print(f"\n!! {name} 실패 — 중단. logs/{r['log']} 확인", flush=True)
            break

    total = round((time.time() - t0) / 60, 2)
    RUN_LOG.write_text(json.dumps(
        {"finished_at": datetime.now(timezone.utc).isoformat(),
         "total_minutes": total, "steps": results},
        ensure_ascii=False, indent=2), encoding="utf-8")
    ok = all(r["returncode"] == 0 for r in results)
    print(f"\n{'=' * 70}\n총 {total}분 · {'전 단계 성공' if ok else '실패 있음'}")
    for r in results:
        print(f"  {'OK ' if r['returncode'] == 0 else 'FAIL'} {r['name']:14} "
              f"{r['minutes']:>6.1f}분")
    print(f"실행 기록: {RUN_LOG}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
