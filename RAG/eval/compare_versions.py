"""v1 -> v2 판정 전이 분석.

프롬프트를 바꿨을 때 라벨이 어떻게 움직였는지, 그리고 그 변화가 앵커와의
일치도를 실제로 개선했는지 본다. 프롬프트 수정이 '앵커에 맞춘 과적합'인지
'실제 결함 수정'인지 구분하려면 전이 방향을 봐야 한다.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

EVAL_DIR = Path(__file__).parent
ANCHOR_DIR = EVAL_DIR / "anchor"
LABELS = ("Correct", "Ambiguous", "Incorrect")


def _flat(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for qid, q in data.get("queries", {}).items():
        for uid, label in q.get("labels", {}).items():
            out[f"{qid}:{uid}"] = label
    return out


def _anchor_primary() -> dict[str, str]:
    out = {}
    for name in ("session_easy_claude.csv", "session_ambiguous_claude.csv"):
        p = ANCHOR_DIR / name
        if not p.exists():
            continue
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            label = r.get("label", "").strip()
            if label in LABELS:
                out[f"{r['qid']}:{r['uid']}"] = label
    return out


def main() -> None:
    v1 = _flat(EVAL_DIR / "judgments_v1.json")
    v2 = _flat(EVAL_DIR / "judgments.json")
    anchor = _anchor_primary()

    common = set(v1) & set(v2)
    print(f"v1 {len(v1)}건, v2 {len(v2)}건, 공통 {len(common)}건\n")

    print("전이 행렬 (v1 -> v2):")
    trans = Counter((v1[k], v2[k]) for k in common)
    print("v1\\v2".rjust(12) + " " + " ".join(f"{x:>10}" for x in LABELS))
    for a in LABELS:
        print(f"{a:>12} " + " ".join(f"{trans[(a, b)]:>10}" for b in LABELS))

    print("\n라벨 분포:")
    for name, d in (("v1", v1), ("v2", v2)):
        c = Counter(d.values())
        tot = sum(c.values())
        parts = " ".join(f"{l}={c[l]} ({c[l]/tot*100:.0f}%)" for l in LABELS)
        print(f"  {name}: {parts}")

    # 앵커와의 일치도 비교 -핵심 질문
    print("\n앵커 대조 (앵커=Fable, 독립 모델):")
    for name, d in (("v1", v1), ("v2", v2)):
        pairs = [(k, anchor[k], d[k]) for k in anchor if k in d]
        if not pairs:
            print(f"  {name}: 겹치는 항목 없음")
            continue
        n = len(pairs)
        agree = sum(1 for _, h, j in pairs if (h == "Correct") == (j == "Correct"))
        b = sum(1 for _, h, j in pairs if h == "Correct" and j != "Correct")
        c = sum(1 for _, h, j in pairs if h != "Correct" and j == "Correct")
        kappa = _kappa([h for _, h, _ in pairs], [j for _, _, j in pairs])
        print(f"  {name}: n={n} κ={kappa:.4f} 일치={agree/n*100:.1f}% "
              f"(앵커+judge- = {b}, 앵커-judge+ = {c})")

        judged_correct = [(h) for _, h, j in pairs if j == "Correct"]
        if judged_correct:
            prec = sum(1 for h in judged_correct if h == "Correct") / len(judged_correct)
            print(f"       judge가 Correct라 한 {len(judged_correct)}건 중 앵커 동의 "
                  f"{prec*100:.0f}%")
        judged_not = [(h) for _, h, j in pairs if j == "Incorrect"]
        if judged_not:
            rec = sum(1 for h in judged_not if h != "Correct") / len(judged_not)
            print(f"       judge가 Incorrect라 한 {len(judged_not)}건 중 앵커 동의 "
                  f"{rec*100:.0f}%")

    # 전이가 앵커 기준으로 옳은 방향이었는지 -과적합 판별의 핵심
    moved = [k for k in common if v1[k] != v2[k] and k in anchor]
    if moved:
        print(f"\n라벨이 바뀐 앵커 항목 {len(moved)}건의 방향:")
        better = worse = neutral = 0
        for k in moved:
            h = anchor[k] == "Correct"
            a = v1[k] == "Correct"
            b_ = v2[k] == "Correct"
            if a == b_:
                neutral += 1
            elif b_ == h:
                better += 1
            else:
                worse += 1
        print(f"  앵커에 가까워짐 {better} / 멀어짐 {worse} / 이진 기준 변화 없음 {neutral}")


def _kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    av = [1 if x == "Correct" else 0 for x in a]
    bv = [1 if x == "Correct" else 0 for x in b]
    p_o = sum(1 for x, y in zip(av, bv) if x == y) / n
    p1, p2 = sum(av) / n, sum(bv) / n
    p_e = p1 * p2 + (1 - p1) * (1 - p2)
    return 1.0 if p_e >= 1.0 else (p_o - p_e) / (1 - p_e)


if __name__ == "__main__":
    main()
