"""판정자 신뢰도 — 사람 앵커 확장이 불가능한 상황에서 측정 가능한 것을 측정한다.

배경
----
게이트 3은 판정자 κ=0.5921 (95% CI [0.434, 0.736], n=118)로 사전등록 기준 0.60에
미달했으나 CI가 0.60을 포함해 **판정 불가**로 남았다. 이를 해소하는 정석은 사람
앵커를 250~300쌍으로 늘려 CI를 좁히는 것인데, 지금 사람 채점이 불가능하다.

그래서 사람이 필요 없는 두 가지를 대신 측정한다.

1. **판정자 자기일관성 (test-retest κ)**
   같은 프롬프트·같은 모델로 같은 쌍을 독립 호출해 다시 판정하고 자기 자신과의
   일치를 잰다. 이게 판정자의 **잡음 천장**이다. 사람의 잡음 천장 0.855에 대응하는
   값으로, "κ=0.5921이 낮은 것은 판정자가 사람과 다른 기준을 쓰기 때문인가,
   아니면 판정자가 그냥 불안정하기 때문인가"를 분리해준다.
   자기일관성이 낮으면 사람 대비 κ의 상한 자체가 낮으므로, 프롬프트 개선이 아니라
   **판정 안정화**(다수결·온도 조정)가 먼저다.

2. **사람 라벨 이전율 (transfer)**
   코퍼스가 1,172 -> 약 6,900건으로 커지면서 풀 구성이 바뀌었다. 기존 사람 라벨
   118쌍 중 신규 풀에 다시 등장하는 (qid, uid)만 재사용할 수 있다. 몇 쌍이
   살아남는지가 human-patched qrels의 실제 근거량이므로 명시한다.

실행: python -X utf8 -m eval.judge_reliability [--n 300] [--retest] [--measure]
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import anchor, judge
from .anchor_human import CANON, _bin, _kappa_ci

EVAL_DIR = Path(__file__).parent
ANCHOR_DIR = EVAL_DIR / "anchor"
POOL_PATH = EVAL_DIR / "pool_qtext.json"
JUDGMENTS_PATH = EVAL_DIR / "judgments_qtext.json"
RETEST_PATH = EVAL_DIR / "judgments_qtext_retest.json"
REPORT_PATH = EVAL_DIR / "judge_reliability.json"

RETEST_N = 300          # 층화 표본. κ CI 반폭 대략 ±0.09 — 자기일관성 판정에 충분
SEED = 20260730


def _human_labels() -> dict[str, str]:
    """사람 손수 라벨 (대소문자 정규화). anchor_human과 동일 규칙."""
    out = {}
    for name in ("session_easy.csv", "session_ambiguous.csv"):
        path = ANCHOR_DIR / name
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                lab = CANON.get((row.get("label") or "").strip().lower())
                if lab:
                    out[f"{row['qid']}:{row['uid']}"] = lab
    return out


def _judge_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {f"{qid}:{uid}": lab
            for qid, q in data.get("queries", {}).items()
            for uid, lab in q.get("labels", {}).items()}


# ── 1. 재판정 (자기일관성용) ────────────────────────────

def _sample_pairs(labels: dict[str, str], n: int) -> list[str]:
    """판정 라벨로 층화추출. 무작위로 뽑으면 Incorrect가 대부분이라
    Correct/Ambiguous 쪽 일관성을 거의 못 본다."""
    by_label: dict[str, list[str]] = {}
    for pk, lab in labels.items():
        by_label.setdefault(lab, []).append(pk)
    rng = random.Random(SEED)
    # Correct·Ambiguous를 각 40%까지 우선 채우고 나머지를 Incorrect로 메운다
    quota = {"Correct": int(n * 0.4), "Ambiguous": int(n * 0.2),
             "Incorrect": n - int(n * 0.4) - int(n * 0.2)}
    picked: list[str] = []
    for lab in ("Correct", "Ambiguous", "Incorrect"):
        pool = sorted(by_label.get(lab, []))
        rng.shuffle(pool)
        picked.extend(pool[:quota[lab]])
    # 어느 층이 모자라면 남은 쌍에서 보충
    if len(picked) < n:
        rest = sorted(set(labels) - set(picked))
        rng.shuffle(rest)
        picked.extend(rest[:n - len(picked)])
    return picked


def retest(conn, n: int = RETEST_N) -> None:
    """표본 쌍을 같은 프롬프트로 다시 판정해 RETEST_PATH에 저장."""
    pool_data = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    pool = pool_data["pool"]
    first = _judge_labels(JUDGMENTS_PATH)
    if not first:
        print(f"{JUDGMENTS_PATH.name} 없음 — query_text_ab --judge 먼저")
        return

    picked = _sample_pairs(first, n)
    by_qid: dict[str, list[str]] = {}
    for pk in picked:
        qid, uid = pk.split(":", 1)
        by_qid.setdefault(qid, []).append(uid)
    print(f"재판정 대상 {len(picked)}쌍 / {len(by_qid)}질의 "
          f"(층 분포 {dict(Counter(first[p] for p in picked).most_common())})")

    # 1차 판정 파일을 건드리지 않도록 저장 경로를 갈아끼운다
    judge.JUDGMENTS_PATH = RETEST_PATH
    if RETEST_PATH.exists():
        RETEST_PATH.unlink()       # 캐시가 남아 있으면 재판정이 아니라 재사용이 된다
    sub_pool = {qid: {**pool[qid], "uids": uids} for qid, uids in by_qid.items()}
    judge.judge_all(conn, sub_pool)
    print(f"재판정 저장: {RETEST_PATH.name}")


# ── 2. 측정 ────────────────────────────────────────────

def _agreement(a: dict[str, str], b: dict[str, str]) -> dict:
    keys = sorted(set(a) & set(b))
    if not keys:
        return {"n": 0}
    same3 = sum(1 for k in keys if a[k] == b[k])
    sameb = sum(1 for k in keys if _bin(a[k]) == _bin(b[k]))
    ta = {k: a[k] for k in keys}
    tb = {k: b[k] for k in keys}
    out = {"n": len(keys),
           "agreement_3class": round(same3 / len(keys), 4),
           "agreement_binary": round(sameb / len(keys), 4),
           "kappa_binary": round(anchor._cohens_kappa_binary(ta, tb), 4),
           "kappa_ci_95": _kappa_ci(tb, ta),
           "label_dist_run1": dict(Counter(ta.values()).most_common()),
           "label_dist_run2": dict(Counter(tb.values()).most_common())}
    # 라벨별로 어디서 흔들리는지 — Ambiguous가 불안정의 주 원인인지 확인
    per = {}
    for lab in ("Correct", "Ambiguous", "Incorrect"):
        sub = [k for k in keys if a[k] == lab]
        if sub:
            per[lab] = {"n": len(sub),
                        "held": round(sum(1 for k in sub if b[k] == lab) / len(sub), 4),
                        "moved_to": dict(Counter(b[k] for k in sub if b[k] != lab).most_common())}
    out["per_label_stability"] = per
    return out


def measure() -> dict:
    first = _judge_labels(JUDGMENTS_PATH)
    second = _judge_labels(RETEST_PATH)
    human = _human_labels()

    self_cons = _agreement(first, second)

    # 사람 라벨 이전율 — 신규 풀에 (qid, uid)가 다시 등장한 쌍만 쓸 수 있다
    transferred = {k: v for k, v in human.items() if k in first}
    vs_human = _agreement(transferred, {k: first[k] for k in transferred}) \
        if transferred else {"n": 0}

    # 자기일관성을 천장으로 본 상대 수준
    ceiling = self_cons.get("kappa_binary")
    attained = vs_human.get("kappa_binary")
    rel = round(attained / ceiling, 4) if (ceiling and attained) else None

    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "judge_prompt": judge.PROMPT_VERSION,
           "corpus_snapshot": json.loads(POOL_PATH.read_text(encoding="utf-8"))
                                  .get("corpus_snapshot"),
           "self_consistency": self_cons,
           "human_label_transfer": {
               "human_total": len(human),
               "transferred_to_new_pool": len(transferred),
               "transfer_rate": round(len(transferred) / len(human), 4) if human else 0.0,
               "note": ("코퍼스가 1,172 -> 약 6,900건으로 커져 풀 구성이 바뀌었다. "
                        "신규 풀에 다시 등장하는 (qid, uid)만 human-patched qrels의 "
                        "근거가 된다.")},
           "vs_human_on_transferred": vs_human,
           "relative_to_self_ceiling": rel,
           "interpretation": (
               "자기일관성 κ는 판정자의 잡음 천장이다. 사람 대비 κ가 이 천장에 가까우면 "
               "남은 격차는 '기준 차이'가 아니라 '판정 잡음'이므로, 프롬프트를 고치기보다 "
               "다수결 판정으로 안정화하는 것이 효과적이다. 반대로 천장이 높은데 사람 대비 "
               "κ가 낮으면 기준 차이가 실재하므로 판정 기준 문서화가 답이다."),
           "caveat": ("사람 라벨은 신규 라벨이 아니라 기존 118쌍의 이전분이다. "
                      "게이트 3의 '판정 불가' 상태는 이 측정으로 해소되지 않는다 — "
                      "표본 수가 늘지 않았기 때문이다.")}
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n판정자 자기일관성 (n={self_cons.get('n')})")
    if self_cons.get("n"):
        print(f"  3분류 일치 {self_cons['agreement_3class']:.4f} · "
              f"이진 일치 {self_cons['agreement_binary']:.4f} · "
              f"κ {self_cons['kappa_binary']:.4f} CI {self_cons['kappa_ci_95']}")
        for lab, s in self_cons["per_label_stability"].items():
            print(f"    {lab:10} n={s['n']:4} 유지율 {s['held']:.4f}  이동 {s['moved_to']}")
    t = out["human_label_transfer"]
    print(f"\n사람 라벨 이전: {t['transferred_to_new_pool']}/{t['human_total']} "
          f"({t['transfer_rate']:.1%})")
    if vs_human.get("n"):
        print(f"  이전분 기준 사람 대비 κ {vs_human['kappa_binary']:.4f} "
              f"CI {vs_human['kappa_ci_95']}")
    if rel:
        print(f"  자기 천장 대비 도달률 {rel:.1%}")
    print(f"\n리포트: {REPORT_PATH}")
    return out


def main():
    args = sys.argv[1:]
    n = RETEST_N
    for a in args:
        if a.startswith("--n"):
            n = int(a.split("=", 1)[1]) if "=" in a else n
    conn = None
    if "--retest" in args or "--all" in args:
        from jobrag.store import connect
        conn = connect()
    try:
        if "--retest" in args or "--all" in args:
            retest(conn, n)
        if "--measure" in args or "--all" in args:
            measure()
        if not args:
            print(__doc__)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
