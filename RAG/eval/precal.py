# -*- coding: utf-8 -*-
"""앵커 사전캘리브레이션 — 사람 라벨 140쌍으로 새 judge(claude CLI)를 검증.

정본: eval/anchor/anchor_labeled.csv (easy 100 + ambiguous 20 + recheck 20).
judge 정확도는 easy+ambiguous의 유일쌍 120개 기준으로 잰다(recheck는 자기일관성용).

실행 (RAG 디렉토리에서):
    python -m eval.precal            # 판정 + 채점 (LLM 호출 ~9회, 재개형)
    python -m eval.precal --score    # 캐시된 판정으로 채점만

게이트(사전등록 §4-3a): 이진(strict) kappa >= 0.60.
산출: eval/anchor/precal_judgments.json, eval/anchor/precal_report.json
"""
from __future__ import annotations
import os

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from jobrag.store import connect

from . import judge

ANCHOR = Path(__file__).parent / "anchor"
LABELED = ANCHOR / "anchor_labeled.csv"
# 프롬프트 버전별 캐시/리포트 — v1 결과(FAIL, Ambiguous 과용)는 그대로 보존
# PRECAL_TAG: 같은 프롬프트의 재판정(judge 자기일관성 측정)용 접미사
_TAG = os.environ.get("PRECAL_TAG", "")
JUDGED = ANCHOR / f"precal_judgments_{judge.PROMPT_VERSION}{_TAG}.json"
REPORT = ANCHOR / f"precal_report_{judge.PROMPT_VERSION}{_TAG}.json"

VALID = ("Correct", "Ambiguous", "Incorrect")
GATE_KAPPA = 0.60


def load_pairs():
    """유일 (qid, uid) -> {query, human}. easy가 원본, recheck는 제외."""
    pairs = {}
    with open(LABELED, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["session"] == "recheck":
                continue
            k = (r["qid"], r["uid"])
            if k in pairs and pairs[k]["human"] != r["label"]:
                print(f"[경고] 세션 간 라벨 충돌 {k}: {pairs[k]['human']} vs {r['label']} — 먼저 나온 값 유지")
                continue
            pairs[k] = {"query": r["query"], "human": r["label"]}
    return pairs


def kappa(pairs_ab, classes):
    n = len(pairs_ab)
    if n == 0:
        return 0.0, 0.0
    po = sum(1 for a, b in pairs_ab if a == b) / n
    ca, cb = Counter(a for a, _ in pairs_ab), Counter(b for _, b in pairs_ab)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in classes)
    return po, (po - pe) / (1 - pe) if pe < 1 else 0.0


def run_judging(conn, pairs):
    judged = json.loads(JUDGED.read_text(encoding="utf-8")) if JUDGED.exists() else {}
    by_qid = defaultdict(list)
    for (qid, uid), v in pairs.items():
        if f"{qid}|{uid}" not in judged:
            by_qid[(qid, v["query"])].append(uid)

    total_pending = sum(len(v) for v in by_qid.values())
    print(f"판정 대상 {total_pending}쌍 (캐시 {len(judged)}쌍) / 백엔드: {judge.backend_id()}")

    for (qid, query), uids in sorted(by_qid.items()):
        details = judge._fetch_posting_details(conn, uids)
        missing = [u for u in uids if u not in details]
        for u in missing:
            judged[f"{qid}|{u}"] = "__MISSING__"  # DB에 없음 — 스냅샷 불일치로 기록
        present = [u for u in uids if u in details]
        for i in range(0, len(present), judge.BATCH_SIZE):
            batch = present[i:i + judge.BATCH_SIZE]
            id_map, parts = {}, []
            for j, uid in enumerate(batch, 1):
                sid = f"P{j}"
                id_map[sid] = uid
                d = details[uid]
                parts.append(judge._format_posting(sid, d["title"], d["company"],
                                                   d["tech"], d["snippet"]))
            prompt = judge.PROMPT.format(query=query, postings="\n\n".join(parts),
                                         n=len(batch))
            labels = judge._parse_response(judge._throttled_call(prompt), id_map)
            for uid in batch:
                judged[f"{qid}|{uid}"] = labels.get(uid, "__UNPARSED__")
            JUDGED.write_text(json.dumps(judged, ensure_ascii=False, indent=1),
                              encoding="utf-8")
            done = sum(1 for k in judged if not judged[k].startswith("__"))
            print(f"  {qid}: {len(batch)}쌍 판정 (누적 유효 {done})")
    return judged


def score(pairs, judged):
    rows, miss_db, unparsed = [], [], []
    for (qid, uid), v in pairs.items():
        j = judged.get(f"{qid}|{uid}")
        if j is None:
            continue
        if j == "__MISSING__":
            miss_db.append(f"{qid}|{uid}")
        elif j == "__UNPARSED__" or j not in VALID:
            unparsed.append(f"{qid}|{uid}")
        else:
            rows.append((v["human"], j))

    n = len(rows)
    po3, k3 = kappa(rows, VALID)
    brows = [("C" if a == "Correct" else "N", "C" if b == "Correct" else "N") for a, b in rows]
    po2, k2 = kappa(brows, ("C", "N"))
    conf = Counter(rows)

    gate = "PASS" if k2 >= GATE_KAPPA else "FAIL"
    report = {
        "backend": judge.backend_id(),
        "n_scored": n, "n_missing_in_db": len(miss_db), "n_unparsed": len(unparsed),
        "agreement_3class": round(po3, 4), "kappa_3class": round(k3, 4),
        "agreement_binary_strict": round(po2, 4), "kappa_binary_strict": round(k2, 4),
        "gate_3a": gate, "gate_threshold": GATE_KAPPA,
        "confusion_human_vs_judge": {f"{a}->{b}": c for (a, b), c in conf.most_common()},
        "missing_in_db": miss_db, "unparsed": unparsed,
        "note": "질의 분포가 직군형(SA)이라 골든셋 대비 대리 검증임 — 사전등록 §5",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n== 사전캘리브레이션 결과 (백엔드 {report['backend']}) ==")
    print(f"채점 {n}쌍 / DB 미존재 {len(miss_db)} / 파싱실패 {len(unparsed)}")
    print(f"3분류: 일치 {po3:.1%}, kappa={k3:.3f}")
    print(f"이진(strict): 일치 {po2:.1%}, kappa={k2:.3f}  -> 게이트 3a: {gate} (기준 {GATE_KAPPA})")
    if miss_db:
        print(f"[주의] DB에 없는 앵커 공고 {len(miss_db)}건 — 코퍼스가 갱신된 경우 라벨-본문 불일치 가능")
    print(f"리포트: {REPORT}")
    return report


def main():
    pairs = load_pairs()
    print(f"유일 앵커쌍 {len(pairs)}개 로드 (easy+ambiguous)")
    if "--score" in sys.argv:
        judged = json.loads(JUDGED.read_text(encoding="utf-8"))
    else:
        conn = connect()
        try:
            judged = run_judging(conn, pairs)
        finally:
            conn.close()
    score(pairs, judged)


if __name__ == "__main__":
    main()
