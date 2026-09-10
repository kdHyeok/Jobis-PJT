"""RAGAS 4축 실행기 — 준비 완료본 (실행: python -m eval.ragas_run).

축 구성 (ragas 0.4 collections API):
1. context_precision : IDBasedContextPrecision — retrieved id vs reference id, 결정적(LLM 무관)
2. context_recall    : IDBasedContextRecall   — 동일하게 결정적
   + (옵션 --llm-context) LLM 판정판 ContextRecall/ContextPrecisionWithoutReference
3. faithfulness      : LLM — response의 주장들이 retrieved 본문에 근거하는가
4. answer_relevancy  : LLM+임베딩 — response가 질의에 답하는가

LLM은 GMS 게이트웨이의 gemini(judge와 동일 모델·경로), 임베딩은 파이프라인과
동일한 jobrag.embedding.embed_texts를 어댑터로 물린다 — 외부 신규 의존 없음.

response가 템플릿 스탠드인인 동안 3·4번 점수는 '하네스 검증값'이다.
Agent 실출력으로 ragas_dataset.json의 response를 교체한 뒤가 본 측정이다.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

EVAL_DIR = Path(__file__).parent
DATASET_PATH = EVAL_DIR / "ragas_dataset.json"
REPORT_PATH = EVAL_DIR / "ragas_report.json"

# GMS 게이트웨이는 429/503을 자주 낸다. ragas의 instructor 클라이언트는 재시도를
# 1회만 하고 백오프가 없어, 첫 실행에서 answer_relevancy가 15건 중 7건 유실됐다.
# 전송 계층 실패로 표본이 깎이면 평균이 '살아남은 샘플' 쪽으로 편향된다 —
# judge.py와 같은 정책(스로틀 + 지수 백오프)으로 되살린다.
# 구조화 출력 파싱 실패는 모델 능력 문제이므로 재시도하지 않고 그대로 skip한다.
MAX_RETRIES = 4
THROTTLE_SEC = 0.7
_TRANSIENT = ("429", "503", "500", "RESOURCE_EXHAUSTED", "UNAVAILABLE",
              "high demand", "Timeout", "Connection")
_last_call = 0.0


def _is_transient(msg: str) -> bool:
    return any(t in msg for t in _TRANSIENT)


async def _throttle() -> None:
    global _last_call
    import time
    wait = THROTTLE_SEC - (time.monotonic() - _last_call)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call = time.monotonic()


# ── GMS gemini LLM (instructor 어댑터) ─────────────────

def _gms_llm():
    """ragas 0.4 collections 지표는 await llm.agenerate()만 호출한다.

    llm_factory는 genai.Client를 instructor 동기 래퍼로 감싸므로 InstructorLLM.is_async가
    False가 되고, 첫 지표에서 'Cannot use agenerate() with a synchronous client'로 죽는다.
    AsyncInstructor(use_async=True)를 직접 물려 InstructorLLM을 구성한다.

    max_tokens는 ragas 기본 1024 -> 4096. 긴 한국어 공고 본문에서 statement 추출 결과가
    잘려 구조화 파싱이 깨지는 것을 막는다(ragas 문서 권고). 프롬프트는 손대지 않는다.
    """
    import instructor
    from google import genai
    from ragas.llms.base import InstructorLLM, InstructorModelArgs

    base = os.environ.get("GMS_BASE_URL",
                          "https://generativelanguage.googleapis.com")
    model = os.environ.get("GMS_MODEL", "gemini-2.5-flash-lite")
    client = genai.Client(api_key=os.environ["GMS_KEY"],
                          http_options={"base_url": base})
    return InstructorLLM(
        client=instructor.from_genai(client, use_async=True),
        model=model,
        provider="google",
        model_args=InstructorModelArgs(max_tokens=4096),
    )


# ── 파이프라인 임베딩 어댑터 ───────────────────────────

def _pipeline_embedding():
    """검색 파이프라인과 동일한 임베딩(jobrag.embedding)을 ragas 인터페이스로 —
    answer_relevancy의 유사도 공간이 실제 서비스와 일치한다."""
    from ragas.embeddings.base import BaseRagasEmbedding
    from jobrag.embedding import embed_texts

    class _Emb(BaseRagasEmbedding):
        def embed_text(self, text: str, **kwargs):
            [vec], _ = embed_texts([text])
            return list(vec)

        async def aembed_text(self, text: str, **kwargs):
            return await asyncio.to_thread(self.embed_text, text)

    return _Emb()


# ── 실행 ───────────────────────────────────────────────

async def run(llm_context: bool = False, dataset: str | None = None) -> dict:
    from ragas.dataset_schema import SingleTurnSample
    from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall
    from ragas.metrics.collections import (AnswerRelevancy, ContextRecall,
                                           ContextPrecisionWithoutReference,
                                           Faithfulness)

    # 생성기별 변형(ragas_dataset_<source>.json)을 각각 채점해 A/B 하려면 입력을 갈아야 한다.
    # 리포트도 같은 이름으로 분리해 서로 덮어쓰지 않게 한다.
    ds_path = (EVAL_DIR / dataset) if dataset else DATASET_PATH
    out_path = (EVAL_DIR / f"ragas_report_{ds_path.stem.removeprefix('ragas_dataset_')}.json"
                if dataset else REPORT_PATH)
    data = json.loads(ds_path.read_text(encoding="utf-8"))
    samples = data["samples"]

    llm = _gms_llm()
    emb = _pipeline_embedding()

    id_cp = IDBasedContextPrecision()
    id_cr = IDBasedContextRecall()
    faith = Faithfulness(llm=llm)
    relev = AnswerRelevancy(llm=llm, embeddings=emb)
    llm_cr = ContextRecall(llm=llm) if llm_context else None
    llm_cp = ContextPrecisionWithoutReference(llm=llm) if llm_context else None

    rows = []
    failures: list[dict] = []
    for s in samples:
        row = {"qid": s["qid"], "question": s["question"], "category": s["category"]}

        st = SingleTurnSample(
            user_input=s["question"],
            retrieved_context_ids=s["retrieved_context_ids"],
            reference_context_ids=s["reference_context_ids"],
        )
        row["context_precision_id"] = round(id_cp.single_turn_score(st), 4)
        row["context_recall_id"] = round(id_cr.single_turn_score(st), 4)

        if s["retrieved_contexts"] and s["response"]:
            # LLM 축은 샘플 단위로 격리한다. gemini-lite가 구조화 출력 형식을 깨는
            # 전례가 있어(PLAN_v5), 1건 실패로 전체 실행을 잃지 않도록 skip 후
            # n_failed에 기록한다. 프롬프트를 고쳐 억지로 통과시키지 않는다.
            async def _axis(name, coro_fn):
                for attempt in range(MAX_RETRIES):
                    try:
                        await _throttle()
                        r = await coro_fn()
                        row[name] = round(float(r.value), 4)
                        return
                    except Exception as e:
                        msg = f"{type(e).__name__}: {e}"
                        if _is_transient(msg) and attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(2 ** attempt + random.random())
                            continue
                        failures.append({"qid": s["qid"], "metric": name,
                                         "attempts": attempt + 1,
                                         "transient": _is_transient(msg),
                                         "error": msg[:200]})
                        return

            await _axis("faithfulness", lambda: faith.ascore(
                user_input=s["question"], response=s["response"],
                retrieved_contexts=s["retrieved_contexts"]))
            await _axis("answer_relevancy", lambda: relev.ascore(
                user_input=s["question"], response=s["response"]))
            if llm_cr is not None:
                await _axis("context_recall_llm", lambda: llm_cr.ascore(
                    user_input=s["question"],
                    retrieved_contexts=s["retrieved_contexts"],
                    reference=s["reference"]))
            if llm_cp is not None:
                await _axis("context_precision_llm", lambda: llm_cp.ascore(
                    user_input=s["question"], response=s["response"],
                    retrieved_contexts=s["retrieved_contexts"]))

        rows.append(row)
        print(f"  {s['qid']}: " + ", ".join(f"{k}={v}" for k, v in row.items()
                                            if k not in ("qid", "question", "category")))

    # 실패로 일부 행에 키가 빠질 수 있으므로 전 행의 합집합으로 축을 잡고,
    # 축마다 실제 성공 표본 수(n)를 함께 남긴다 — 평균의 분모를 감추지 않는다.
    metric_keys = [k for k in dict.fromkeys(k for r in rows for k in r)
                   if k not in ("qid", "question", "category")]
    summary, coverage = {}, {}
    for k in metric_keys:
        vals = [r[k] for r in rows if k in r]
        coverage[k] = f"{len(vals)}/{len(rows)}"
        if vals:
            summary[k] = round(sum(vals) / len(vals), 4)

    report = {
        "framework": "ragas 0.4",
        "llm_judge": os.environ.get("GMS_MODEL", "gemini-2.5-flash-lite"),
        "response_source": samples[0].get("response_source"),
        "caveat": [
            "reference는 gemini v3 judge 라벨 — 사람 채점 전까지 교차검증 기준",
            "faithfulness/answer_relevancy는 response가 템플릿 스탠드인인 동안 하네스 검증값",
        ],
        "dataset": ds_path.name,
        "response_generator": data.get("response_generator", "template 스탠드인"),
        "summary": summary,
        "n_samples": len(rows),
        "n_failed": len(failures),
        "scored_coverage": coverage,
        "failures": failures,
        "per_query": rows,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n요약: {summary}")
    print(f"리포트: {out_path}")
    return report


if __name__ == "__main__":
    _ds = None
    if "--dataset" in sys.argv:
        _ds = sys.argv[sys.argv.index("--dataset") + 1]
    asyncio.run(run(llm_context="--llm-context" in sys.argv, dataset=_ds))
