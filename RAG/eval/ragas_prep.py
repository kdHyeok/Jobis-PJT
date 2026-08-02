"""RAGAS 평가 데이터셋 빌더 (준비 단계 — LLM 호출 없음).

기존 자산을 RAGAS 형식으로 변환한다:
- 질의: spec_anchor.SPEC_QUERIES (명세서 정규화 15종 — 직군+기술+연차 항상 포함)
- retrieved: pool_spec.json의 rrf_ce top-3 (실서비스 arm과 동일)
- reference: judgments_spec.json에서 judge=Correct 공고들
  ※ 이 reference는 gemini v3 판정 기준이다. 사람 채점 전까지 RAGAS 점수도
    "LLM 교차검증 기준"이라는 동일한 꼬리표를 단다 (PLAN_v5 §6.5).

4축 대응:
- context_precision / context_recall : retrieved vs reference — 지금 계산 가능
- faithfulness / answer_relevancy    : response(생성 답변) 필요.
  이 시스템은 생성이 없으므로 match_reason 기반 템플릿 response를 스탠드인으로
  넣어 하네스를 완성한다. Agent 실출력이 오면 response 필드만 교체하면 된다.

실행: python -m eval.ragas_prep  ->  eval/ragas_dataset.json
"""
from __future__ import annotations

import json
from pathlib import Path

from jobrag.store import connect

from .spec_anchor import POOL_SPEC_PATH, JUDGMENTS_SPEC_PATH

EVAL_DIR = Path(__file__).parent
DATASET_PATH = EVAL_DIR / "ragas_dataset.json"

TOP_K = 3
MAX_REFERENCE_CONTEXTS = 10   # Correct가 많은 질의도 reference 본문은 10건까지만

# 풀이 60질의로 확장됐지만 RAGAS는 **동결 15종(SA01~SA15)에서만** 돈다.
# 이유 두 가지:
#   1) 비교 가능성 — 이전 측정(ragas_report.json)이 이 15종이다. 질의를 갈아치우면
#      코퍼스 변화와 질의 변화가 섞여 축별 점수 변동을 해석할 수 없다.
#   2) 비용 — 축 4개 × 질의당 LLM 호출이고, 이전 실행에서 429/503 재시도가 잦았다.
#      60종은 4배가 되는데 얻는 정보는 IR 지표 쪽에서 이미 확보된다.
QID_SUBSET = tuple(f"SA{i:02d}" for i in range(1, 16))


def _fetch_texts(conn, uids: list[str]) -> dict[str, dict]:
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.uid, p.title, p.company, p.tech,
                      COALESCE((SELECT text FROM chunks WHERE posting_uid = p.uid
                                ORDER BY (part = 'full') DESC, chunk_id LIMIT 1), '')
               FROM postings p WHERE p.uid = ANY(%s)""",
            (uids,),
        )
        return {r[0]: {"title": r[1], "company": r[2], "tech": r[3] or [], "text": r[4]}
                for r in cur.fetchall()}


def _template_response(question: str, hits: list[tuple[str, dict]]) -> str:
    """생성부가 없는 동안의 스탠드인 response — 검색 결과를 그대로 서술한다.

    본문에 있는 사실만 담으므로 faithfulness의 상한 검증(harness sanity check)에
    쓰인다. Agent 실출력으로 교체 전까지 이 점수는 '생성 품질'이 아니다.
    """
    if not hits:
        return "조건에 맞는 공고를 찾지 못했습니다."
    lines = [f'"{question}" 조건에 맞는 추천 공고입니다.']
    for i, (uid, d) in enumerate(hits, 1):
        tech = ", ".join(d["tech"][:5]) if d["tech"] else ""
        tail = f" (주요 기술: {tech})" if tech else ""
        lines.append(f"{i}. {d['company']} - {d['title']}{tail}")
    return "\n".join(lines)


def _reference_answer(hits: list[tuple[str, dict]]) -> str:
    """LLM ContextRecall용 기준 답변 — judge=Correct 공고를 정답으로 서술."""
    if not hits:
        return "이 조건에 적합한 공고는 코퍼스에 없다."
    lines = ["이 질의에 적합한 공고는 다음과 같다."]
    for uid, d in hits:
        lines.append(f"- {d['company']} - {d['title']}")
    return "\n".join(lines)


def build() -> dict:
    pool_data = json.loads(POOL_SPEC_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(JUDGMENTS_SPEC_PATH.read_text(encoding="utf-8"))

    conn = connect()
    samples = []
    try:
        for qid, info in pool_data["pool"].items():
            if qid not in QID_SUBSET:
                continue
            question = info["query"]
            labels = judgments["queries"].get(qid, {}).get("labels", {})

            retrieved_ids = pool_data["arm_tops"][qid]["rrf_ce"][:TOP_K]
            correct_ids = sorted(u for u, l in labels.items() if l == "Correct")
            ref_ids_full = correct_ids
            ref_ids_text = correct_ids[:MAX_REFERENCE_CONTEXTS]

            texts = _fetch_texts(conn, list(set(retrieved_ids) | set(ref_ids_text)))
            retrieved_hits = [(u, texts[u]) for u in retrieved_ids if u in texts]
            ref_hits = [(u, texts[u]) for u in ref_ids_text if u in texts]

            samples.append({
                "qid": qid,
                "question": question,
                "category": info["category"],
                "retrieved_context_ids": retrieved_ids,
                "retrieved_contexts": [d["text"] for _, d in retrieved_hits],
                # reference: judge=Correct (gemini v3) — 사람 검증 아님
                "reference_context_ids": ref_ids_full,
                "reference_contexts": [d["text"] for _, d in ref_hits],
                "reference": _reference_answer(ref_hits),
                # response: 템플릿 스탠드인. Agent 실출력이 오면 여기만 교체
                "response": _template_response(question, retrieved_hits),
                "response_source": "template(top-3 검색결과 서술) — 생성부 부재 스탠드인",
            })
    finally:
        conn.close()

    dataset = {
        "built_from": {
            "queries": ("정규화 동결 15종 SA01~SA15 (풀은 60종이나 비교 가능성·비용상 "
                        "RAGAS는 동결분만 — ragas_prep.QID_SUBSET 주석 참고)"),
            "retrieved": "pool_spec.json rrf_ce top-3",
            "reference_labels": f"judgments_spec.json (judge=gemini {judgments and 'v3'})",
        },
        "caveat": "reference는 LLM judge 라벨 기준 — 사람 채점 전까지 점수는 교차검증 기준",
        "n_samples": len(samples),
        "samples": samples,
    }
    DATASET_PATH.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    n_ref = sum(len(s["reference_context_ids"]) for s in samples)
    print(f"RAGAS 데이터셋 저장: {DATASET_PATH}")
    print(f"  샘플 {len(samples)}건, retrieved {TOP_K}건/질의, reference 총 {n_ref}건")
    return dataset


if __name__ == "__main__":
    build()
