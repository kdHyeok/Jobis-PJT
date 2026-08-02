"""명세서 정규화 질의 기반 앵커셋 재구축.

RAG_입출력_명세서.md의 실입력은 정규화된 고정 형태다: 직군 + 기술스택 + 연차가
항상 채워져 들어온다 (spec_adapter가 profile에서 매핑; 지역 선호는 없음).
기존 앵커(자유 자연어 질의 표본)를 폐기하고, 이 정규화 형태 키워드가 항상
전부 포함된 질의로 RAG를 호출해 앵커셋을 다시 만든다.

- 검색용 QuerySpec: spec_adapter._spec_from_profile과 동일 형태로 직접 구성
  (text = 직군 + 기술, tech 리스트, exp_years, regions=[])
- judge/앵커 표시용 질의 문자열: 직군 + 기술 + 연차를 전부 명시
- 판정 저장은 judgments_spec.json (기존 자연어 트랙 judgments.json과 분리)

실행: python -m eval.spec_anchor --pool | --judge | --sheets | --all
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from jobrag.embedding import embed_texts
from jobrag.query_parser import QuerySpec
from jobrag.store import connect

from . import anchor, judge

EVAL_DIR = Path(__file__).parent
POOL_SPEC_PATH = EVAL_DIR / "pool_spec.json"
JUDGMENTS_SPEC_PATH = EVAL_DIR / "judgments_spec.json"

POOL_DEPTH = 10          # 앵커 후보 수집용 — 본평가(30)보다 얕게, 판정량 절약
ANCHOR_TARGET = 120

# 직군 12종 전부 + 연차대(신입/주니어/미들/시니어) 분산. 기술은 whitelist 표준명만.
# exp_years=None 은 신입(경력 없음) — spec_adapter._total_exp_years와 동일 의미.
SPEC_QUERIES = [
    {"id": "SA01", "role": "백엔드 개발자", "category": "backend",
     "tech": ["Java", "Spring Boot", "JPA", "MySQL"], "exp_years": 3},
    {"id": "SA02", "role": "백엔드 개발자", "category": "backend",
     "tech": ["Python", "Django", "PostgreSQL"], "exp_years": None},
    {"id": "SA03", "role": "백엔드 개발자", "category": "backend",
     "tech": ["Go", "Redis", "Kafka"], "exp_years": 7},
    {"id": "SA04", "role": "프론트엔드 개발자", "category": "frontend",
     "tech": ["React", "TypeScript", "Next.js"], "exp_years": 2},
    {"id": "SA05", "role": "프론트엔드 개발자", "category": "frontend",
     "tech": ["Vue", "JavaScript"], "exp_years": None},
    {"id": "SA06", "role": "풀스택 개발자", "category": "fullstack",
     "tech": ["React", "Node.js", "MySQL"], "exp_years": 4},
    {"id": "SA07", "role": "안드로이드 개발자", "category": "mobile",
     "tech": ["Kotlin", "Android"], "exp_years": 3},
    {"id": "SA08", "role": "DevOps 엔지니어", "category": "devops",
     "tech": ["Docker", "Kubernetes", "AWS", "Jenkins"], "exp_years": 5},
    {"id": "SA09", "role": "SRE 엔지니어", "category": "sre",
     "tech": ["Kubernetes", "Linux", "Terraform"], "exp_years": 4},
    {"id": "SA10", "role": "데이터 엔지니어", "category": "data_engineer",
     "tech": ["Python", "Kafka", "SQL"], "exp_years": 3},
    {"id": "SA11", "role": "데이터 사이언티스트", "category": "data_scientist",
     "tech": ["Python", "TensorFlow"], "exp_years": 2},
    {"id": "SA12", "role": "머신러닝 엔지니어", "category": "ml_engineer",
     "tech": ["Python", "PyTorch", "LLM"], "exp_years": 3},
    {"id": "SA13", "role": "데이터 분석가", "category": "data_analyst",
     "tech": ["SQL", "Python"], "exp_years": None},
    {"id": "SA14", "role": "QA 엔지니어", "category": "qa",
     "tech": ["Python", "Git"], "exp_years": 2},
    {"id": "SA15", "role": "보안 엔지니어", "category": "security",
     "tech": ["Linux"], "exp_years": 3},
]


def _retrieval_spec(q: dict) -> QuerySpec:
    """spec_adapter._spec_from_profile과 동일한 정규화 형태로 QuerySpec 구성.

    질의 텍스트 공식은 jobrag/query_text.py를 공유한다 — 여기서 따로 만들면
    사전등록 A/B(eval/PREREG_query_text.md)에서 채택한 구성과 갈린다.
    """
    from jobrag import query_text
    return QuerySpec(text=query_text.lexical_text(q["role"], q["tech"]),
                     dense_text=query_text.semantic_text(q["role"], q["tech"],
                                                         q["exp_years"]),
                     tech=list(q["tech"]), regions=[],
                     exp_years=q["exp_years"], role_category=q["category"])


def _display_query(q: dict) -> str:
    """judge·앵커 시트에 보여줄 질의 — 명세서 키워드(직군·기술·연차) 전부 포함."""
    exp = "신입" if q["exp_years"] is None else f"경력 {q['exp_years']}년"
    return f"{q['role']} {' '.join(q['tech'])} ({exp})"


# ── 풀 구성 ────────────────────────────────────────────

def build_pool(conn) -> dict:
    from .run import (_run_arm_bm25, _run_arm_dense, _run_arm_rrf,
                      _run_arm_rrf_ce, _run_arm_random)

    pool = {}
    arm_tops = {}
    for i, q in enumerate(SPEC_QUERIES, 1):
        spec = _retrieval_spec(q)
        disp = _display_query(q)
        print(f"[{i}/{len(SPEC_QUERIES)}] pool: {q['id']} - {disp}")
        [vec], _ = embed_texts([spec.semantic_text])

        arms = {
            "bm25": _run_arm_bm25(conn, spec, POOL_DEPTH),
            "dense": _run_arm_dense(conn, vec, spec, POOL_DEPTH),
            "rrf": _run_arm_rrf(conn, spec, POOL_DEPTH),
            "rrf_ce": _run_arm_rrf_ce(conn, spec, POOL_DEPTH),
            "random": _run_arm_random(conn, POOL_DEPTH),
        }
        all_uids = set()
        for uids in arms.values():
            all_uids.update(uids)

        pool[q["id"]] = {
            "query": disp,
            "category": q["category"],
            "spec": {"role": q["role"], "tech": q["tech"], "exp_years": q["exp_years"]},
            "uids": sorted(all_uids),
            "n_pool": len(all_uids),
        }
        arm_tops[q["id"]] = arms
        print(f"  풀 크기: {len(all_uids)}")

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_contract": "RAG_입출력_명세서.md — 정규화 고정형(직군+기술+연차, 지역 없음)",
        "n_queries": len(pool),
        "pool": pool,
        "arm_tops": arm_tops,
        "arms": ["bm25", "dense", "rrf", "rrf_ce", "random"],
    }
    POOL_SPEC_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(p["n_pool"] for p in pool.values())
    print(f"\n풀 저장: {POOL_SPEC_PATH} (판정 예정 {total}건)")
    return data


# ── 판정 (judgments_spec.json에 분리 저장) ─────────────

def judge_pool(conn) -> None:
    judge.JUDGMENTS_PATH = JUDGMENTS_SPEC_PATH   # 자연어 트랙 judgments.json 보호
    pool_data = json.loads(POOL_SPEC_PATH.read_text(encoding="utf-8"))
    judge.judge_all(conn, pool_data["pool"])


# ── 앵커 시트 생성 (층화추출 + 부족분 보충) ─────────────

def generate_sheets(conn) -> None:
    anchor.JUDGMENTS_PATH = JUDGMENTS_SPEC_PATH
    pool_data = json.loads(POOL_SPEC_PATH.read_text(encoding="utf-8"))
    pool = pool_data["pool"]
    arm_tops = pool_data["arm_tops"]

    data = json.loads(JUDGMENTS_SPEC_PATH.read_text(encoding="utf-8"))
    all_labels = {qid: q["labels"] for qid, q in data.get("queries", {}).items()}
    queries_map = {qid: q["query"] for qid, q in data.get("queries", {}).items()}

    selected, pop_sizes = anchor._select_stratum(all_labels, pool, arm_tops)

    # 소코퍼스·정규화 질의에서는 일부 계층(특히 ambiguous)이 목표에 못 미칠 수
    # 있다. 게이트 최소 표본(사람 채점 100쌍)을 지키기 위해 부족분은 모집단이
    # 남아 있는 계층에서 목표 비율대로 보충한다.
    total_sel = sum(len(pairs) for pairs in selected.values())
    if total_sel < ANCHOR_TARGET:
        rng = random.Random(777)
        chosen = {p for pairs in selected.values() for p in pairs}
        # 모집단 재구성 (선정분 제외)
        populations = {s: [] for s in anchor.STRATA}
        for qid, labels in all_labels.items():
            density = anchor._classify_query_density(qid, labels)
            top_uids = set()
            for ranked in arm_tops.get(qid, {}).values():
                top_uids.update(ranked[:3])
            for uid, label in labels.items():
                pair = (qid, uid)
                if pair in chosen:
                    continue
                if label == "Correct":
                    populations["pos_dense" if density == "dense" else "pos_sparse"].append(pair)
                elif label == "Ambiguous":
                    populations["ambiguous"].append(pair)
                elif uid in top_uids:
                    populations["neg_top"].append(pair)
                else:
                    populations["pool_tail"].append(pair)
        deficit = ANCHOR_TARGET - total_sel
        for stratum in ("pos_dense", "pos_sparse", "neg_top", "pool_tail", "ambiguous"):
            if deficit <= 0:
                break
            extra = populations[stratum]
            rng.shuffle(extra)
            take = extra[:deficit]
            selected[stratum].extend(take)
            deficit -= len(take)

    key_data = {"pop_sizes": pop_sizes, "strata": {}, "llm_labels": {},
                "input_contract": "spec 정규화 질의 (직군+기술+연차)"}
    all_pairs = []
    for stratum, pairs in selected.items():
        key_data["strata"][stratum] = [{"qid": q, "uid": u} for q, u in pairs]
        for qid, uid in pairs:
            key_data["llm_labels"][f"{qid}:{uid}"] = all_labels.get(qid, {}).get(uid, "?")
            all_pairs.append((stratum, qid, uid))

    anchor.ANCHOR_DIR.mkdir(exist_ok=True)
    anchor.KEY_PATH.write_text(json.dumps(key_data, ensure_ascii=False, indent=2),
                               encoding="utf-8")

    rng = random.Random(123)
    easy_rows = [(s, q, u) for s, q, u in all_pairs if s in anchor.EASY_STRATA]
    rng.shuffle(easy_rows)
    anchor._write_sheet(conn, anchor.ANCHOR_DIR / "session_easy.csv", easy_rows, queries_map)

    ambig_rows = [(s, q, u) for s, q, u in all_pairs if s in anchor.AMBIG_STRATA]
    rng.shuffle(ambig_rows)
    anchor._write_sheet(conn, anchor.ANCHOR_DIR / "session_ambiguous.csv", ambig_rows, queries_map)

    recheck_pool = easy_rows + ambig_rows
    rng.shuffle(recheck_pool)
    anchor._write_sheet(conn, anchor.ANCHOR_DIR / "session_recheck.csv",
                        recheck_pool[:anchor.RECHECK_N], queries_map)

    print(f"앵커 시트 생성: easy {len(easy_rows)} / ambiguous {len(ambig_rows)} / "
          f"recheck {anchor.RECHECK_N}")
    print(f"정답키: {anchor.KEY_PATH}")


def main():
    args = sys.argv[1:]
    conn = connect()
    try:
        if "--pool" in args or "--all" in args:
            build_pool(conn)
        if "--judge" in args or "--all" in args:
            judge_pool(conn)
        if "--sheets" in args or "--all" in args:
            generate_sheets(conn)
        if not args:
            print("사용법: python -m eval.spec_anchor --pool | --judge | --sheets | --all")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
