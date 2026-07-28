"""파싱 A/B 실험 — 하이브리드(현행: 룰 선추출 + LLM + 룰 덮어쓰기) vs LLM-only.

"파싱을 전부 LLM에 맡기면 더 정확한가?"를 실측으로 답한다 (2026-07-24 논의).

    PYTHONUTF8=1 uv run python scripts/ab_parse_experiment.py [--runs 3]

지표 (공고 6건 × 반복 N회 × 2변형, 실 LLM 호출):
- req_f1        : 필수+우대 요구사항 추출 F1 (eval.metrics.requirement_f1, 근사 매칭)
- stack_f1      : techStack F1 (구분자·대소문자 정규화 후 집합 비교)
- halluc        : 원문에 없는 스택 항목 수 (환각. 정규화 부분문자열 검사)
- seniority_ok  : 연차 사다리 키 정확도
- reproducible  : 반복 N회의 (요구사항·스택·연차) 출력이 완전 동일한 공고 비율

결과: 콘솔 표 + evals/ab_parse_results.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from pydantic import BaseModel, Field  # noqa: E402

from jobis_ai.contracts.domain import Requirement  # noqa: E402
from jobis_ai.eval.metrics import requirement_f1  # noqa: E402
from jobis_ai.graph.nodes import parse_job_posting  # noqa: E402
from jobis_ai.structured import run_structured  # noqa: E402

_SEP = re.compile(r"[.\s\-_/()]+")


def _norm(s: str) -> str:
    return _SEP.sub("", (s or "").strip().lower())


# --- LLM-only 변형 -------------------------------------------------------------
# 현행 스키마(_JobPostingRead)에는 seniority 가 없다(판단은 룰 소유). LLM-only 는
# "전부 LLM" 제안대로 seniority 까지 스키마에 포함해 LLM 이 직접 채우게 한다.
class _LlmOnlyRead(BaseModel):
    jobTitle: str = ""
    companyName: str = ""
    seniority: str = ""
    requiredRequirements: list[Requirement] = Field(default_factory=list)
    preferredRequirements: list[Requirement] = Field(default_factory=list)
    techStack: list[str] = Field(default_factory=list)
    domainKeywords: list[str] = Field(default_factory=list)


_LLM_ONLY_SYSTEM = """너는 채용공고에서 필드를 뽑아내는 추출기다. 공고 원문에 실제로 적힌 것만 뽑는다.
- requiredRequirements: 자격요건(필수). preferredRequirements: 우대사항. 한 문장 단위로 쪼갠다.
- techStack: 언급된 기술/언어/도구/플랫폼 이름 전부.
- seniority: 요구 연차를 intern / junior(0~2년·신입) / mid(3~6년) / senior(7~9년) / lead(10년 이상) 중 하나로. 표기가 없으면 빈 문자열.
- domainKeywords: 산업·서비스 도메인 키워드(예: 커머스, 핀테크)."""


def parse_hybrid(text: str) -> dict:
    state = {"jobPostingInput": {"sourceType": "text", "value": text}, "retryCount": {}}
    return parse_job_posting(state).get("normalizedJobPosting") or {}


def parse_llm_only(text: str) -> dict:
    read, _warnings = run_structured(_LlmOnlyRead, _LLM_ONLY_SYSTEM, text, node="ab_llm_only")
    return read.model_dump() if read is not None else {}


# --- 채점 ----------------------------------------------------------------------
def score(pred: dict, gold: dict, source: str) -> dict:
    req_pred = [r.get("text", "") for r in pred.get("requiredRequirements", [])] + \
               [r.get("text", "") for r in pred.get("preferredRequirements", [])]
    req_gold = gold["requiredRequirements"] + gold["preferredRequirements"]
    f1 = requirement_f1(req_pred, req_gold)["f1"]

    pred_stack = {_norm(s) for s in pred.get("techStack", []) if s}
    gold_stack = {_norm(s) for s in gold["techStack"]}
    tp = len(pred_stack & gold_stack)
    prec = tp / len(pred_stack) if pred_stack else 0.0
    rec = tp / len(gold_stack) if gold_stack else 1.0
    stack_f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    nsrc = _norm(source)
    halluc = [s for s in pred.get("techStack", []) if s and _norm(s) not in nsrc]

    return {
        "req_f1": round(f1, 3),
        "stack_f1": round(stack_f1, 3),
        "halluc": len(halluc),
        "halluc_items": halluc,
        "seniority_pred": pred.get("seniority", ""),
        "seniority_ok": pred.get("seniority", "") == gold["seniority"],
    }


def signature(pred: dict) -> str:
    """재현성 비교용 — 판정에 쓰이는 필드만의 표준 직렬화."""

    return json.dumps({
        "req": [r.get("text", "") for r in pred.get("requiredRequirements", [])],
        "pref": [r.get("text", "") for r in pred.get("preferredRequirements", [])],
        "stack": sorted(_norm(s) for s in pred.get("techStack", [])),
        "seniority": pred.get("seniority", ""),
    }, ensure_ascii=False, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="파싱 A/B 실험 (실 LLM 호출)")
    parser.add_argument("--runs", type=int, default=3, help="공고당 반복 횟수 (재현성 측정)")
    args = parser.parse_args()

    cases = json.loads((_ROOT / "evals" / "ab_parse_dataset.json").read_text(encoding="utf-8"))["cases"]
    variants = {"hybrid": parse_hybrid, "llm_only": parse_llm_only}
    total_calls = len(cases) * args.runs * len(variants)
    print(f"공고 {len(cases)}건 × {args.runs}회 × 2변형 = LLM 호출 {total_calls}회 실행…\n")

    report: dict = {"runs": args.runs, "variants": {}}
    for vname, fn in variants.items():
        case_rows = []
        for case in cases:
            runs = [fn(case["text"]) for _ in range(args.runs)]
            scores = [score(p, case["gold"], case["text"]) for p in runs]
            sigs = {signature(p) for p in runs}
            case_rows.append({
                "caseId": case["caseId"],
                "req_f1": round(sum(s["req_f1"] for s in scores) / len(scores), 3),
                "stack_f1": round(sum(s["stack_f1"] for s in scores) / len(scores), 3),
                "halluc": sum(s["halluc"] for s in scores),
                "halluc_items": sorted({h for s in scores for h in s["halluc_items"]}),
                "seniority_acc": round(sum(s["seniority_ok"] for s in scores) / len(scores), 3),
                "seniority_preds": sorted({s["seniority_pred"] for s in scores}),
                "distinct_outputs": len(sigs),
                "reproducible": len(sigs) == 1,
            })
            r = case_rows[-1]
            print(f"  [{vname:9}] {r['caseId']:28} reqF1={r['req_f1']:.2f} stackF1={r['stack_f1']:.2f} "
                  f"환각={r['halluc']} 연차={r['seniority_acc']:.2f} 동일출력={args.runs - r['distinct_outputs'] + 1}/{args.runs}")

        n = len(case_rows)
        report["variants"][vname] = {
            "cases": case_rows,
            "summary": {
                "avg_req_f1": round(sum(c["req_f1"] for c in case_rows) / n, 3),
                "avg_stack_f1": round(sum(c["stack_f1"] for c in case_rows) / n, 3),
                "total_halluc": sum(c["halluc"] for c in case_rows),
                "seniority_acc": round(sum(c["seniority_acc"] for c in case_rows) / n, 3),
                "reproducible_rate": round(sum(c["reproducible"] for c in case_rows) / n, 3),
            },
        }
        print()

    print("===== 요약 =====")
    header = f"{'지표':<22}" + "".join(f"{v:>12}" for v in variants)
    print(header)
    keys = ["avg_req_f1", "avg_stack_f1", "total_halluc", "seniority_acc", "reproducible_rate"]
    for k in keys:
        row = f"{k:<22}" + "".join(f"{report['variants'][v]['summary'][k]:>12}" for v in variants)
        print(row)

    out = _ROOT / "evals" / "ab_parse_results.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out}")


if __name__ == "__main__":
    main()
