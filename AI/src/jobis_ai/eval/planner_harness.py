"""플래너 평가 러너 — 발화 × 기대 실행 시퀀스 (llm-planner-design.md §4).

플래너 경로(plan_agents → validate_plan)의 끝단 결과를 기대값과 비교한다.
기대값은 "최종 실행 시퀀스"라서 플래너의 선택 실수가 검증기 보정으로 살아나는 것까지
포함해 측정한다 — 사용자에게 실제로 일어나는 일이 평가 대상.

    python -m jobis_ai.eval.planner_harness evals/planner_dataset.json
    python -m jobis_ai.eval.planner_harness evals/planner_dataset.json --runs 3 --save evals/planner_baseline.json

**정확도와 안정성을 따로 센다** (`--runs N`). 이 구분이 없으면 틀린 케이스를 볼 때
*일관되게 틀린 것*(명세·프롬프트 결함 — 재실행해도 안 낫는다)인지 *무작위로 틀린 것*(flaky —
온도·프롬프트 경화 대상)인지 알 수 없다. 이식해 온 Agent_Test `tests/eval.py` 는 "일관성 k/N"
하나로 둘을 섞었는데, 같은 run 데이터에서 공짜로 갈라 낼 수 있다:

  accuracy  = 기대와 일치한 run 비율
  stability = **최빈 결과**가 차지한 비율 (정답 여부와 무관)
  verdict   = stable-correct / stable-wrong / unstable

지표 로직 검증은 tests/test_planner_eval.py 가 담당.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from jobis_ai.orchestrator.planner import CONFIDENCE_THRESHOLD, plan_agents
from jobis_ai.orchestrator.router import FALLBACK_AGENT, validate_plan

_ROOT = Path(__file__).resolve().parents[3]

# 평가용 더미 세션 자산 — 존재 여부만 판정에 쓰이므로 내용은 최소로.
_DUMMY_ASSETS: dict[str, Any] = {
    "resume": {"sourceType": "text", "value": "Python Django 백엔드 3년"},
    "job_posting": {"sourceType": "text", "value": "백엔드 개발자 채용 공고"},
    "analysis": {"fitGrade": "중", "gaps": [{"requirementId": "r1"}]},
    "roadmap": {"roadmap": [{"title": "학습"}]},
    "preferences": {"roles": ["백엔드"], "companies": [], "domains": [], "turns": 1},
}


def build_session(assets: list[str]) -> dict[str, Any]:
    """케이스의 자산 이름 목록을 더미 세션으로 확장한다."""

    return {name: _DUMMY_ASSETS[name] for name in assets}


def dispatch_case(case: dict) -> dict[str, Any]:
    """한 케이스를 플래너 경로로 돌려 최종 실행 시퀀스를 얻는다.

    **`chat.handle_chat` 의 분기를 그대로 따라간다.** 그러지 않으면 프로덕션이 아닌 흐름을
    재게 된다 — 실제로 그랬다(2026-07-29 실측). 07-28 에 들어온 두 경로를 하네스가 모르고 있었다:

      · 확신이 낮으면 프로덕션은 **대화형 에이전트(career_chat)가 턴을 받아 대화한다.**
        하네스는 그걸 "되묻기(ASK)"로 뭉개서, 사실은 career_chat 이 도는 케이스가 오답으로 찍혔다.
      · 무거운 생산자 자동 삽입에는 **동의 게이트**가 걸린다(실행 없이 한 턴 묻는다).
        하네스는 `agents=()` + `asked=False` 로 기록해 어느 쪽도 아닌 빈 키가 됐다.

    되묻기(`asked=True`)의 정의는 **"실행 없이 사용자에게 되묻는다"** 다 — 동의 게이트가 여기
    해당하고, 저신뢰 폴백은 해당하지 않는다(에이전트가 실제로 돌아 말을 한다).
    """

    session = build_session(case.get("assets", []))
    message = case["message"]

    plan, _warnings = plan_agents(message, session)
    if plan is None:
        # LLM 미설정·실패 — 환경 문제라 정확도와 섞지 않고 따로 센다.
        return {"agents": (), "asked": True, "path": "llm_failed"}

    selected = list(plan.agents)
    if not plan.agents or plan.confidence < CONFIDENCE_THRESHOLD:
        # 프로덕션과 같다 — 대화형 에이전트가 턴을 받는다(고정 문구로 끝내지 않는다).
        return {"agents": (FALLBACK_AGENT,), "asked": False, "path": "fallback",
                "selected": selected, "confidence": plan.confidence}

    dispatch = validate_plan(plan.agents, session, plan.requestedAgents)
    if dispatch.ask:
        # 동의 게이트 — 이번 턴에는 실행하지 않고 묻는다.
        return {"agents": (), "asked": True, "path": "gate",
                "selected": selected, "confidence": plan.confidence}
    return {"agents": dispatch.agents, "asked": False, "path": "planner",
            "selected": selected, "confidence": plan.confidence}


def outcome_key(outcome: dict[str, Any]) -> str:
    """실행 결과를 비교 가능한 한 문자열로 — 되묻기면 "ASK", 실행이면 "a>b>c"."""

    return "ASK" if outcome["asked"] else ">".join(outcome["agents"])


def expected_key(case: dict) -> str:
    return "ASK" if case.get("expectAsk") else ">".join(case.get("expectedAgents", []))


def score_case(case: dict, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """N회 실행 결과 → 정확도·안정성·판정.

    정답 = (되묻기 일치) AND (실행이면 시퀀스 완전 일치) — outcome_key 비교가 이와 동치다.
    """

    runs = len(outcomes) or 1
    expect_ask = bool(case.get("expectAsk"))
    want = expected_key(case)

    keys = [outcome_key(o) for o in outcomes]
    correct = sum(1 for k in keys if k == want)
    ask_match = sum(1 for o in outcomes if o["asked"] == expect_ask)
    counts = Counter(keys)
    modal_count = counts.most_common(1)[0][1]

    accuracy = correct / runs
    stability = modal_count / runs
    # stability 가 1.0 이면 accuracy 는 0 또는 1 뿐이다(모든 run 이 같은 결과).
    verdict = ("stable-correct" if stability == 1.0 and accuracy == 1.0
               else "stable-wrong" if stability == 1.0
               else "unstable")

    return {
        "caseId": case.get("caseId", "?"),
        "runs": runs,
        # 1회 실행이면 예전 baseline 과 같은 값이 나온다(호환).
        "correct": accuracy == 1.0,
        "accuracy": round(accuracy, 4),
        "stability": round(stability, 4),
        "ask_accuracy": round(ask_match / runs, 4),
        "verdict": verdict,
        "expected": want,
        # 관측된 결과 전부 — 이탈을 덮지 않는다(Agent_Test 가 run 별 원문을 남긴 이유).
        "observed": dict(counts.most_common()),
        "llm_failed": sum(1 for o in outcomes if o["path"] == "llm_failed"),
        # **모델을 갈아 끼울 때 이 둘이 원인을 가른다.** 약한 모델의 알려진 실패 모드는
        # "에이전트는 맞게 고르면서 confidence 를 0.00 으로 채우는" 것이다(2026-07-28 gpt-4.1-nano
        # 실측). 그러면 임계값(0.6)에 걸려 전부 career_chat 으로 후퇴하는데, 결과만 보면
        # "라우팅을 못 한다"로 오진한다. path 분포와 confidence 를 함께 남겨야 구분된다.
        "paths": dict(Counter(o["path"] for o in outcomes).most_common()),
        "mean_confidence": round(
            sum(o.get("confidence") or 0.0 for o in outcomes) / runs, 3),
    }


def aggregate(results: list[dict]) -> dict[str, Any]:
    n = len(results) or 1
    return {
        "cases": len(results),
        "runs_per_case": results[0]["runs"] if results else 0,
        # 이름 유지 — 예전 baseline 과 같은 축으로 비교할 수 있게(1회 실행이면 값도 동일).
        "sequence_accuracy": round(sum(r["accuracy"] for r in results) / n, 4),
        "ask_accuracy": round(sum(r["ask_accuracy"] for r in results) / n, 4),
        "mean_stability": round(sum(r["stability"] for r in results) / n, 4),
        "stable_correct": sum(1 for r in results if r["verdict"] == "stable-correct"),
        "stable_wrong": sum(1 for r in results if r["verdict"] == "stable-wrong"),
        "unstable": sum(1 for r in results if r["verdict"] == "unstable"),
        "llm_failed": sum(r["llm_failed"] for r in results),
        # 저신뢰 폴백 비율 — 모델 교체 시 가장 먼저 보는 값(위 mean_confidence 주석 참고).
        "fallback_rate": round(
            sum(r["paths"].get("fallback", 0) for r in results)
            / max(1, sum(r["runs"] for r in results)), 4),
        "mean_confidence": round(
            sum(r["mean_confidence"] for r in results) / n, 3),
    }


# 오프라인 평가라 순서가 결과에 영향을 주지 않는다 — 벽시계를 줄이려고 몇 개를 동시에 던진다.
# 무한정 넓히지 않는 이유는 chat._MAX_PARALLEL 과 같다(동시 과금·레이트리밋).
_EVAL_WORKERS = 4


def run_dataset(path: str | Path, runs: int = 1) -> tuple[list[dict], dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data

    jobs = [(index, case) for index, case in enumerate(cases) for _ in range(runs)]
    outcomes: dict[int, list[dict]] = {index: [] for index in range(len(cases))}
    with ThreadPoolExecutor(max_workers=_EVAL_WORKERS) as pool:
        futures = {pool.submit(dispatch_case, case): index for index, case in jobs}
        for future in as_completed(futures):
            outcomes[futures[future]].append(future.result())

    results = [score_case(case, outcomes[index]) for index, case in enumerate(cases)]
    return results, aggregate(results)


_MARK = {"stable-correct": "O", "stable-wrong": "X", "unstable": "~"}


def _print_report(results: list[dict], summary: dict) -> None:
    print("\n===== 케이스별 (O 안정·정답 / X 안정·오답 / ~ 불안정) =====")
    for r in results:
        mark = _MARK[r["verdict"]]
        observed = " | ".join(f"{k or '(없음)'}×{v}" for k, v in r["observed"].items())
        print(f"  [{mark}] {r['caseId']:32} 정확 {r['accuracy']:.2f} 안정 {r['stability']:.2f}")
        if r["verdict"] != "stable-correct":
            print(f"        기대={r['expected'] or '(없음)'}  관측={observed}")
    print("\n===== 전체 요약 =====")
    for k, val in summary.items():
        print(f"  {k}: {val}")


def main() -> None:
    parser = argparse.ArgumentParser(description="플래너 평가 하네스 (llm-planner-design.md §4)")
    parser.add_argument("dataset", nargs="?", default=str(_ROOT / "evals" / "planner_dataset.json"))
    parser.add_argument("--save", help="baseline 리포트 저장 경로")
    parser.add_argument("--runs", type=int, default=1,
                        help="케이스당 실행 횟수. 2 이상이면 안정성(재현성)을 함께 센다.")
    args = parser.parse_args()

    from jobis_ai.eval import provenance

    mode = "플래너(실 LLM 호출)"
    # 이전에는 `settings.llm_model` 을 그대로 적어 Claude 로 돌린 결과에 GMS 모델명이 박혔다.
    # 모델명은 프로바이더 분기를 아는 곳(active_model) 한 군데서만 나온다.
    meta = provenance(mode=mode, runs=args.runs)
    print(f"플래너 평가 — {mode} 모드 / 케이스당 {args.runs}회 "
          f"/ provider={meta['provider']} model={meta['model']} temperature={meta['temperature']}")
    results, summary = run_dataset(args.dataset, args.runs)
    _print_report(results, summary)

    if args.save:
        Path(args.save).write_text(
            json.dumps({"meta": meta, "dataset": args.dataset,
                        "summary": summary, "cases": results},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nbaseline 저장: {args.save} ({meta['provider']}/{meta['model']}, {meta['measuredAt']})")


if __name__ == "__main__":
    main()
