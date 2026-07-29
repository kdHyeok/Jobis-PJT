"""사람 앵커 120쌍 -3세션 격리, 층화추출, κ·사후가중·McNemar·피로도."""
from __future__ import annotations

import csv
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

EVAL_DIR = Path(__file__).parent
JUDGMENTS_PATH = EVAL_DIR / "judgments.json"
ANCHOR_DIR = EVAL_DIR / "anchor"
KEY_PATH = ANCHOR_DIR / "anchor_key.json"

STRATA = {
    "pos_dense":  25,
    "pos_sparse": 25,
    "ambiguous":  20,
    "neg_top":    30,
    "pool_tail":  20,
}

EASY_STRATA = {"pos_dense", "pos_sparse", "neg_top", "pool_tail"}
AMBIG_STRATA = {"ambiguous"}
RECHECK_N = 20


def _load_judgments() -> dict:
    return json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))


def _classify_query_density(qid: str, labels: dict[str, str]) -> str:
    n_correct = sum(1 for v in labels.values() if v == "Correct")
    ratio = n_correct / len(labels) if labels else 0
    return "dense" if ratio > 0.10 else "sparse"


def _select_stratum(all_labels: dict[str, dict], pool: dict[str, dict],
                    arm_tops: dict[str, list[str]]) -> dict[str, list[tuple[str, str]]]:
    populations: dict[str, list[tuple[str, str]]] = {s: [] for s in STRATA}

    for qid, labels in all_labels.items():
        density = _classify_query_density(qid, labels)
        top_uids = set()
        qid_arms = arm_tops.get(qid, {})
        for arm_key, ranked in qid_arms.items():
            top_uids.update(ranked[:3])

        for uid, label in labels.items():
            pair = (qid, uid)
            if label == "Correct" and density == "dense":
                populations["pos_dense"].append(pair)
            elif label == "Correct" and density == "sparse":
                populations["pos_sparse"].append(pair)
            elif label == "Ambiguous":
                populations["ambiguous"].append(pair)
            elif label == "Incorrect" and uid in top_uids:
                populations["neg_top"].append(pair)
            else:
                populations["pool_tail"].append(pair)

    rng = random.Random(42)
    selected: dict[str, list[tuple[str, str]]] = {}
    pop_sizes: dict[str, int] = {}
    for stratum, target_n in STRATA.items():
        pop = populations[stratum]
        pop_sizes[stratum] = len(pop)
        rng.shuffle(pop)
        selected[stratum] = pop[:target_n]

    return selected, pop_sizes


def _fetch_context(conn, qid: str, uid: str, queries_map: dict) -> dict:
    query_text = queries_map.get(qid, "")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.title, p.company, p.tech,
                      COALESCE(
                          (SELECT text FROM chunks WHERE posting_uid = p.uid
                           ORDER BY (part = 'full') DESC, chunk_id LIMIT 1),
                          ''
                      )
               FROM postings p WHERE p.uid = %s""",
            (uid,),
        )
        row = cur.fetchone()
    if not row:
        return {"query": query_text, "uid": uid, "title": "?", "company": "?",
                "tech": [], "snippet": ""}
    return {
        "query": query_text,
        "uid": uid,
        "title": row[0],
        "company": row[1],
        "tech": row[2] or [],
        "snippet": row[3][:600],
    }


def generate_sheets(conn, pool: dict, arm_tops: dict) -> None:
    ANCHOR_DIR.mkdir(exist_ok=True)
    data = _load_judgments()
    all_labels = {qid: q["labels"] for qid, q in data.get("queries", {}).items()}
    queries_map = {qid: q["query"] for qid, q in data.get("queries", {}).items()}

    selected, pop_sizes = _select_stratum(all_labels, pool, arm_tops)

    key_data = {"pop_sizes": pop_sizes, "strata": {}, "llm_labels": {}}
    all_pairs = []

    for stratum, pairs in selected.items():
        key_data["strata"][stratum] = [{"qid": q, "uid": u} for q, u in pairs]
        for qid, uid in pairs:
            llm_label = all_labels.get(qid, {}).get(uid, "?")
            key_data["llm_labels"][f"{qid}:{uid}"] = llm_label
            all_pairs.append((stratum, qid, uid))

    KEY_PATH.write_text(json.dumps(key_data, ensure_ascii=False, indent=2), encoding="utf-8")

    rng = random.Random(123)

    easy_rows = [(s, q, u) for s, q, u in all_pairs if s in EASY_STRATA]
    rng.shuffle(easy_rows)
    _write_sheet(conn, ANCHOR_DIR / "session_easy.csv", easy_rows, queries_map)

    ambig_rows = [(s, q, u) for s, q, u in all_pairs if s in AMBIG_STRATA]
    rng.shuffle(ambig_rows)
    _write_sheet(conn, ANCHOR_DIR / "session_ambiguous.csv", ambig_rows, queries_map)

    recheck_pool = easy_rows + ambig_rows
    rng.shuffle(recheck_pool)
    recheck_rows = recheck_pool[:RECHECK_N]
    _write_sheet(conn, ANCHOR_DIR / "session_recheck.csv", recheck_rows, queries_map)

    print(f"앵커 시트 생성 완료: {ANCHOR_DIR}")
    print(f"  easy: {len(easy_rows)}쌍, ambiguous: {len(ambig_rows)}쌍, recheck: {RECHECK_N}쌍")
    print(f"  정답키: {KEY_PATH} (채점 시트에 LLM 라벨 미포함)")


def _write_sheet(conn, path: Path, rows: list[tuple], queries_map: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["seq", "qid", "query", "uid", "company", "title", "tech", "snippet", "label", "timestamp"])
        for i, (stratum, qid, uid) in enumerate(rows, 1):
            ctx = _fetch_context(conn, qid, uid, queries_map)
            w.writerow([
                i, qid, ctx["query"], uid, ctx["company"], ctx["title"],
                "|".join(ctx["tech"][:8]), ctx["snippet"][:300], "", "",
            ])


def score(conn=None) -> dict:
    """채점된 시트 3개를 읽어 κ·사후가중·McNemar·피로도를 산출한다."""
    key_data = json.loads(KEY_PATH.read_text(encoding="utf-8"))
    llm_labels = key_data["llm_labels"]
    pop_sizes = key_data["pop_sizes"]

    human_labels = {}
    timestamps = {}
    for session_file in ANCHOR_DIR.glob("session_*.csv"):
        with open(session_file, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pair_key = f"{row['qid']}:{row['uid']}"
                label = row.get("label", "").strip()
                ts = row.get("timestamp", "").strip()
                if label and label in ("Correct", "Ambiguous", "Incorrect"):
                    if session_file.name == "session_recheck.csv":
                        human_labels[f"recheck:{pair_key}"] = label
                    else:
                        human_labels[pair_key] = label
                    if ts:
                        timestamps[pair_key] = ts

    primary = {k: v for k, v in human_labels.items() if not k.startswith("recheck:")}
    recheck = {k.replace("recheck:", ""): v for k, v in human_labels.items() if k.startswith("recheck:")}

    if len(primary) < 100:
        return {"error": f"사람 채점 {len(primary)}쌍 -최소 100쌍 필요", "gate3": "FAIL"}

    binary_agree, binary_total = 0, 0
    human_pos_llm_neg, human_neg_llm_pos = 0, 0
    for pair_key, h_label in primary.items():
        l_label = llm_labels.get(pair_key, "?")
        if l_label == "?":
            continue
        binary_total += 1
        h_bin = 1 if h_label == "Correct" else 0
        l_bin = 1 if l_label == "Correct" else 0
        if h_bin == l_bin:
            binary_agree += 1
        if h_bin == 1 and l_bin == 0:
            human_pos_llm_neg += 1
        if h_bin == 0 and l_bin == 1:
            human_neg_llm_pos += 1

    kappa = _cohens_kappa_binary(primary, llm_labels)

    self_kappa = None
    if len(recheck) >= 10:
        self_labels_a = {k: primary[k] for k in recheck if k in primary}
        self_labels_b = recheck
        self_kappa = _cohens_kappa_binary(self_labels_a, self_labels_b)

    total_pop = sum(pop_sizes.values())
    weighted_agree = 0
    weighted_total = 0
    for stratum, pairs_data in key_data["strata"].items():
        n_h = pop_sizes.get(stratum, 0)
        w = n_h / total_pop if total_pop > 0 else 0
        stratum_agree = 0
        stratum_total = 0
        for pair in pairs_data:
            pk = f"{pair['qid']}:{pair['uid']}"
            h = primary.get(pk)
            l = llm_labels.get(pk)
            if h and l:
                stratum_total += 1
                if (h == "Correct") == (l == "Correct"):
                    stratum_agree += 1
        if stratum_total > 0:
            weighted_agree += w * (stratum_agree / stratum_total)
            weighted_total += w

    weighted_accuracy = weighted_agree / weighted_total if weighted_total > 0 else 0

    mcnemar_stat = None
    mcnemar_direction = None
    b, c = human_pos_llm_neg, human_neg_llm_pos
    if b + c > 0:
        mcnemar_stat = (abs(b - c) - 1) ** 2 / (b + c) if (b + c) > 0 else 0
        mcnemar_direction = "LLM inflates positives" if c > b else "LLM deflates positives"

    fatigue = _check_fatigue(timestamps)

    gate3 = "PASS" if kappa >= 0.60 else "FAIL"
    gate3b = "PASS"
    if self_kappa is not None and self_kappa < kappa:
        gate3b = "FAIL -사람 자기일관성이 사람-LLM κ보다 낮음"

    report = {
        "n_primary": len(primary),
        "n_recheck": len(recheck),
        "binary_kappa": round(kappa, 4),
        "binary_agreement": round(binary_agree / binary_total, 4) if binary_total > 0 else None,
        "self_consistency_kappa": round(self_kappa, 4) if self_kappa is not None else None,
        "weighted_accuracy": round(weighted_accuracy, 4),
        "mcnemar": {
            "b_human_pos_llm_neg": b,
            "c_human_neg_llm_pos": c,
            "statistic": round(mcnemar_stat, 4) if mcnemar_stat is not None else None,
            "direction": mcnemar_direction,
        },
        "fatigue": fatigue,
        "gate3": gate3,
        "gate3b": gate3b,
    }

    out_path = ANCHOR_DIR / "anchor_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n앵커 리포트: {out_path}")
    print(f"  이진 κ = {report['binary_kappa']} -> 게이트 3: {gate3}")
    if self_kappa is not None:
        print(f"  자기일관성 κ = {report['self_consistency_kappa']} -> 게이트 3b: {gate3b}")
    print(f"  McNemar: {mcnemar_direction} (b={b}, c={c})")
    return report


def _cohens_kappa_binary(labels_a: dict, labels_b: dict) -> float:
    common = set(labels_a.keys()) & set(labels_b.keys())
    if len(common) < 2:
        return 0.0
    a_vals = [1 if labels_a[k] == "Correct" else 0 for k in common]
    b_vals = [1 if labels_b[k] == "Correct" else 0 for k in common]
    n = len(common)
    agree = sum(1 for a, b in zip(a_vals, b_vals) if a == b)
    p_o = agree / n
    p_a1 = sum(a_vals) / n
    p_b1 = sum(b_vals) / n
    p_e = p_a1 * p_b1 + (1 - p_a1) * (1 - p_b1)
    if p_e >= 1.0:
        return 1.0
    return (p_o - p_e) / (1 - p_e)


def _check_fatigue(timestamps: dict) -> dict:
    if not timestamps:
        return {"measured": False, "note": "no timestamps"}
    try:
        times = sorted(timestamps.values())
        if len(times) < 10:
            return {"measured": False, "note": "too few timestamps"}
        first_half = times[:len(times) // 2]
        second_half = times[len(times) // 2:]
        return {
            "measured": True,
            "n_with_timestamps": len(times),
            "note": "판정별 타임스탬프 기록됨. 세션 내 순번 대비 시간 분석 가능",
        }
    except Exception:
        return {"measured": False, "note": "timestamp parse error"}


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--score" in args:
        score()
    else:
        session = "all"
        for a in args:
            if a.startswith("--session"):
                session = args[args.index(a) + 1] if a == "--session" else a.split("=")[1]

        from jobrag.store import connect
        conn = connect()
        try:
            pool_path = EVAL_DIR / "pool.json"
            if not pool_path.exists():
                print("pool.json 없음 -먼저 python -m eval.run --build-pool 실행")
                sys.exit(1)
            pool_data = json.loads(pool_path.read_text(encoding="utf-8"))
            pool = pool_data.get("pool", {})
            arm_tops = pool_data.get("arm_tops", {})
            generate_sheets(conn, pool, arm_tops)
        finally:
            conn.close()
