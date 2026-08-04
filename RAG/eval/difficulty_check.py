# -*- coding: utf-8 -*-
"""게이트 3b — 난이도 축 신규 앵커 15쌍 (사전등록 §4-3b).

본판정 완료 후:
  python -m eval.difficulty_check --make    # 04_난이도앵커_15쌍.csv 생성 (사람 채점용, 블라인드)
사람이 CSV의 '사람라벨' 칸을 채운 뒤:
  python -m eval.difficulty_check --score   # 12/15 이상 일치 → PASS

블라인드 원칙: 시트에는 judge 라벨을 싣지 않는다. judge 라벨은 별도 키 파일에 보관.
15쌍은 난이도 축 dev 질의에서 judge 라벨 층화(Correct/Ambiguous/Incorrect 각 5)로
결정적 샘플링. 11 이하면 10쌍 추가 생성(--make --extra) 후 재채점,
그래도 미달이면 난이도 축 결론에 conclusive:false (measure_v2가 리포트에 반영).
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from jobrag.store import connect

from . import judge

EVAL_DIR = Path(__file__).parent
POOL_PATH = EVAL_DIR / "pool_v2.json"
SHEET = EVAL_DIR / "human_tasks" / "04_난이도앵커_15쌍.csv"
KEY = EVAL_DIR / "anchor" / "difficulty_key.json"
REPORT = EVAL_DIR / "anchor" / "difficulty_check_report.json"

judge.JUDGMENTS_PATH = EVAL_DIR / "judgments_v2.json"

DIFficulty_CATS = {"sparse_relax", "low_resource_role", "parser_trap",
                   "negative_signal", "freeform"}
PER_LABEL = 5
VALID = {"Correct", "Ambiguous", "Incorrect"}
GATE_MIN = 12


def _sample(pool, judgments, extra: bool) -> list[dict]:
    by_label = defaultdict(list)
    for qid, q in pool["queries"].items():
        if q["category"] not in DIFficulty_CATS:
            continue
        labels = judgments.get("queries", {}).get(qid, {}).get("labels", {})
        for uid, label in labels.items():
            if label in VALID:
                by_label[label].append({"qid": qid, "query": q["query"], "uid": uid,
                                        "judge": label})
    picked = []
    offset = PER_LABEL if extra else 0
    n_take = 4 if extra else PER_LABEL   # extra 회차는 10쌍(라벨당 3~4)
    for label in ("Correct", "Ambiguous", "Incorrect"):
        cands = sorted(by_label[label],
                       key=lambda r: hashlib.sha256(f"diff:{r['qid']}|{r['uid']}".encode())
                       .hexdigest())
        take = cands[offset:offset + (3 if extra and label == "Correct" else n_take)]
        picked.extend(take)
    return picked[:10] if extra else picked[:15]


def make(extra: bool = False):
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(judge.JUDGMENTS_PATH.read_text(encoding="utf-8"))
    picked = _sample(pool, judgments, extra)
    if len(picked) < (10 if extra else 15):
        print(f"[경고] 표본 부족: {len(picked)}쌍 — 난이도 질의 판정 분포 확인 필요")

    conn = connect()
    try:
        details = judge._fetch_posting_details(conn, [p["uid"] for p in picked])
    finally:
        conn.close()

    mode = "a" if extra and SHEET.exists() else "w"
    with open(SHEET, mode, encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if mode == "w":
            w.writerow(["no", "qid", "query", "uid", "회사", "제목", "기술",
                        "본문발췌", "사람라벨(Correct/Ambiguous/Incorrect)"])
        start = 16 if extra else 1
        for i, p in enumerate(picked, start):
            d = details.get(p["uid"], {})
            w.writerow([i, p["qid"], p["query"], p["uid"],
                        d.get("company", "?"), d.get("title", "?"),
                        ", ".join((d.get("tech") or [])[:8]),
                        (d.get("snippet") or "")[:400].replace("\n", " "), ""])

    key = json.loads(KEY.read_text(encoding="utf-8")) if (extra and KEY.exists()) else {}
    for p in picked:
        key[f"{p['qid']}|{p['uid']}"] = p["judge"]
    KEY.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"시트 생성: {SHEET} ({len(picked)}쌍{' 추가' if extra else ''})")
    print("사람 채점 후: python -m eval.difficulty_check --score")


def score():
    key = json.loads(KEY.read_text(encoding="utf-8"))
    rows = []
    with open(SHEET, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            human = r["사람라벨(Correct/Ambiguous/Incorrect)"].strip()
            # "Ambiguous,메모" 형태 허용 — 첫 토큰만 라벨로 취급
            human = human.split(",")[0].split("(")[0].strip()
            human = {"Ambigous": "Ambiguous"}.get(human, human)
            if not human:
                print(f"[미기입] no={r['no']} {r['qid']}|{r['uid']}")
                continue
            if human not in VALID:
                print(f"[비표준] no={r['no']}: '{human}'")
                continue
            j = key.get(f"{r['qid']}|{r['uid']}")
            rows.append((human, j, r["qid"], r["uid"]))

    n = len(rows)
    agree = sum(1 for h, j, *_ in rows if h == j)
    passed = agree >= GATE_MIN if n >= 15 else agree >= round(GATE_MIN / 15 * n)
    report = {
        "n_scored": n, "n_agree": agree, "gate_min": GATE_MIN, "passed": passed,
        "disagreements": [{"qid": q, "uid": u, "human": h, "judge": j}
                          for h, j, q, u in rows if h != j],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"일치 {agree}/{n} → 게이트 3b: {'PASS' if passed else 'FAIL'}")
    if not passed:
        print("11 이하 → --make --extra 로 10쌍 추가 후 재채점 (사전등록 §4-3b)")
    print(f"리포트: {REPORT}")


def main():
    if "--score" in sys.argv:
        score()
    else:
        make("--extra" in sys.argv)


if __name__ == "__main__":
    main()
