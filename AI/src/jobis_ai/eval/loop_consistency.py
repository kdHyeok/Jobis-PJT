"""자기 루프 에이전트의 **궤적 안정성** 평가 (비교 문서 §2-1 의 마지막 미측정 표면).

플래너 안정성은 `planner_harness` 가, 풀턴 궤적은 `consistency.py` 가 잰다. 그러나
`agent_loop` 를 도는 세 에이전트(`interview_prep`·`coverletter_draft`·`preference_intake`)는
매 턴 **도구를 스스로 골라** 여러 스텝을 돈다 — 그 궤적이 얼마나 흔들리는지 아무도 재지
않았다. 프로토타입에서 배운 관점(같은 입력을 N회 돌려 궤적 불변식을 본다) 그대로다.

지표는 `planner_harness` 와 같은 갈래를 쓴다 — **정확도와 안정성을 섞지 않는다**:

  trajectory   도구 호출 순서를 한 문자열로 ("find_evidence>save_draft>check_draft")
  stability    최빈 궤적이 차지한 비율 (정답 여부와 무관)
  replied      검증 통과 문장을 만든 비율 (0 이면 결정론 폴백으로 나갔다는 뜻)
  steps        스텝 수 평균·최대 — 상한(agent_loop.DEFAULT_MAX_STEPS)에 닿는지
  warnings     경고 코드 분포 — **폴백 이유와 미해결 지적을 삼키지 않는다.**
               `llm_call_failed` 가 보이면 루프가 아예 안 돈 것이고(궤적이 빈 것과 구분된다),
               `coverletter_check_unresolved` 는 점검 지적을 남긴 채 답했다는 뜻이다.
  hand-off     에이전트 간 위임 **시도 / 성공 / 거부 사유**. 궤적 문자열에서 `ask_agent` 를
               사람이 눈으로 세던 것(0729 기록의 "1/5")을 여기서 집계로 바꾼다 —
               성공률의 분모가 없어 §1-1 이 ○ 였던 구멍이다. 출처는 trace
               (`delegate`/`delegate_refused`)이므로 도구 이름(`ask_agent`·`preview_postings`)이
               늘어도 이 집계는 그대로 맞는다.
  llm          run 당 **콜 수·토큰**(llm_usage) — "평균 몇 콜로 결론에 도달하는가"
               (평가 리포트 §1-2 의 없던 숫자). 토큰을 안 주는 공급자는 미계측으로 남는다.
  limit        `max_steps` **도달 횟수** — agent_loop 의 "실제 도달 빈도를 보고 다시
               조정한다"(DEFAULT_MAX_STEPS 주석)의 그 빈도. trace(action="limit")에서 센다.

**궤적에 "정답"은 두지 않는다.** 도구를 몇 개 쓸지는 발화·근거에 따라 달라지는 것이 정상이고
(0729 실측: 쓸 도구가 적으면 적게 돈다), 여기서 보려는 것은 *같은 입력에 같은 길을 가는지*다.
대신 **불변식**은 검사한다 — 예: 자소서는 저장 없이 답하지 않는다.

사용: uv run python -m jobis_ai.eval.loop_consistency [--runs N] [--save 경로]
      **실 LLM 을 여러 번 호출한다** (루프 1회 = 도구 호출 수만큼).
      `--save` 로 결과를 파일에 남긴다 — 콘솔에서 사라지는 수치는 baseline 이 못 된다.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

os.environ.setdefault("SESSION_STORE", "memory")   # 평가가 세션 파일을 오염시키지 않게

# --- 고정 입력 (모든 run 이 같은 것을 본다 — 흔들림의 출처를 모델로 한정한다) ----------
_PROFILE = {
    "skills": [{"name": "Java"}, {"name": "Spring Boot"}, {"name": "MySQL"}],
    "skillEvidence": {"Java": ["exp-1"], "Spring Boot": ["exp-1"]},
    "projects": [{
        "id": "p1", "title": "재고관리 API", "role": "백엔드",
        "techStack": ["Java", "Spring Boot", "MySQL"],
        "achievements": ["주문 처리 지연 1.2초 → 0.4초"],
        "summary": "주문·재고 도메인 API 를 설계하고 구현",
    }],
    "experiences": [], "education": [{"school": "OO대", "major": "컴퓨터공학"}],
    "certifications": [{"name": "정보처리기사"}], "languages": [], "awards": [],
}

_ANALYSIS = {
    "status": "completed", "fitGrade": "중", "overallScore": 0.55,
    "requirements": [
        {"requirementId": "r1", "text": "Java/Spring 실무 경험 2년 이상", "type": "required"},
        {"requirementId": "r2", "text": "Kafka 기반 이벤트 처리 경험", "type": "required"},
        {"requirementId": "r3", "text": "AWS 운영 경험", "type": "preferred"},
    ],
    "gaps": [
        {"requirementId": "r2", "severity": "high", "reason": "이력서에서 확인되지 않음",
         "missingSkills": ["Kafka"]},
        {"requirementId": "r3", "severity": "low", "reason": "기재 없음",
         "missingSkills": ["AWS"]},
    ],
    "strengths": [
        {"requirementId": "r1", "matchedSkills": ["Java", "Spring Boot"],
         "text": "재고관리 API 에서 Java/Spring 으로 주문 처리 구현"},
    ],
    "roadmap": [{"title": "Kafka 기초", "priority": "high"}],
}

_RESUME = {"sourceType": "text", "value": "Java Spring 백엔드 2년. 재고관리 API 프로젝트."}
_POSTING = {"sourceType": "text", "value": "백엔드 채용. 자격요건 Java/Spring 2년, Kafka."}


def _cases() -> list[tuple]:
    """(이름, 모듈, 세션, 불변식(steps, reply) -> bool | None)

    세션에 `profile` 을 미리 넣어 둔다 — 실사용의 세션 캐시와 같고, run 마다 프로필 추출 LLM
    호출이 반복되는 것을 막는다(재려는 것은 루프 궤적이지 추출이 아니다).
    """

    return [
        ("preference_intake", "preference_intake",
         {"last_message": "이력서는 없는데 백엔드 공고 추천받고 싶어"},
         # 선호를 말했으면 기록해야 한다 — 기록 없이 답하면 다음 턴이 아무것도 물려받지 못한다.
         lambda tools, reply: "record_preference" in tools),

        ("interview_prep", "interview_prep",
         {"profile": _PROFILE, "analysis": _ANALYSIS, "resume": _RESUME,
          "last_message": "면접 예상 질문 뽑아줘"},
         # 소재·근거는 도구만 준다 — 도구를 하나도 안 쓰고 질문을 지어내면 근거 제한 위반이다.
         lambda tools, reply: bool(tools)),

        ("coverletter_draft", "coverletter_draft",
         {"profile": _PROFILE, "analysis": _ANALYSIS, "resume": _RESUME,
          "job_posting": _POSTING, "last_message": "자소서 초안 써줘"},
         # 저장 없이 답하면 화면에 나갈 본문이 없다(초안은 save_draft 로만 기록된다).
         lambda tools, reply: "save_draft" in tools),
    ]


def _run_once(module: str, session: dict) -> dict:
    """루프 1회 → 관측 dict. 예외는 호출부가 크래시로 기록한다.

    위임 결과는 `"ok:<target>"` / `"<reason>:<target>"` 문자열이다 — trace 를 켜서 받는다
    (레코더가 없으면 emit 은 no-op 이라, 켜지 않으면 위임이 있었는지조차 알 수 없다).
    콜·토큰은 llm_usage 수집기로 같은 방식으로 받는다.
    """

    from importlib import import_module

    from jobis_ai import llm_usage, trace

    agent = import_module(f"jobis_ai.agents.{module}")
    with trace.recording() as recorder, llm_usage.collecting() as usage:
        result = agent.run(dict(session))
    steps = list(result.data.get("loopSteps") or [])
    return {
        "tools": [str(s.get("tool") or "") for s in steps],
        "reply": result.reply or "",
        "steps": len(steps),
        "codes": [str(w.get("code") or "") for w in result.warnings],
        "handoffs": [
            f"{'ok' if e['kind'] == 'delegate' else e['detail'].get('reason', '?')}"
            f":{e['detail'].get('target') or '(빈 이름)'}"
            for e in recorder.events if e["kind"] in ("delegate", "delegate_refused")
        ],
        "limit": any(e["kind"] == "agent_step" and e["detail"].get("action") == "limit"
                     for e in recorder.events),
        "llm": usage.summary(),
    }


def _llm_summary_line(calls: list[int], input_tokens: list[int], output_tokens: list[int],
                      unmetered: int) -> str:
    """run 별 콜·토큰 관측을 한 줄로. 토큰이 하나도 안 잡혔으면 '미계측'으로 정직하게 쓴다."""

    line = f"콜 평균 {sum(calls) / max(len(calls), 1):.1f}"
    if input_tokens:
        line += (f"  토큰 평균 {sum(input_tokens) / len(input_tokens):.0f}"
                 f"→{sum(output_tokens) / len(output_tokens):.0f}")
    else:
        line += "  토큰 미계측"
    if unmetered:
        line += f" (미계측 콜 {unmetered}건)"
    return line


def main() -> None:
    parser = argparse.ArgumentParser(description="자기 루프 궤적 안정성 평가 (실 LLM)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--save", help="결과 JSON 저장 경로 — 콘솔에서 사라지는 수치는 baseline 이 못 된다")
    args = parser.parse_args()
    runs = args.runs

    from jobis_ai.agents.agent_loop import DEFAULT_MAX_STEPS
    from jobis_ai.eval import provenance

    meta = provenance(runs=runs)
    print(f"=== 자기 루프 궤적 안정성 — {len(_cases())}케이스 × {runs}회 (실 LLM) ===")
    print(f"    provider={meta['provider']} model={meta['model']}"
          f" / 기본 스텝 상한={DEFAULT_MAX_STEPS}\n")

    broken = 0
    total_handoffs = 0
    total_handoff_ok = 0
    case_reports: list[dict] = []
    for name, module, session, invariant in _cases():
        trajectories: list[str] = []
        replied = 0
        step_counts: list[int] = []
        violations = 0
        limit_reached = 0
        warning_codes: Counter = Counter()
        handoff_results: Counter = Counter()
        runs_with_handoff = 0
        calls: list[int] = []
        input_tokens: list[int] = []
        output_tokens: list[int] = []
        unmetered = 0
        retries = 0
        for _ in range(runs):
            try:
                obs = _run_once(module, session)
            except Exception as exc:      # noqa: BLE001 — 크래시 자체가 결과다
                trajectories.append(f"CRASH: {type(exc).__name__}")
                step_counts.append(0)
                violations += 1
                continue
            trajectories.append(">".join(obs["tools"]) or "(도구 없음)")
            step_counts.append(obs["steps"])
            warning_codes.update(c for c in obs["codes"] if c)
            handoff_results.update(obs["handoffs"])
            if obs["handoffs"]:
                runs_with_handoff += 1
            if obs["reply"].strip():
                replied += 1
            if not invariant(obs["tools"], obs["reply"]):
                violations += 1
            if obs["limit"]:
                limit_reached += 1
            llm = obs["llm"]
            calls.append(llm["calls"])
            retries += llm["retries"]
            unmetered += llm["unmeteredCalls"]
            if llm["inputTokens"] is not None:
                input_tokens.append(llm["inputTokens"])
                output_tokens.append(llm["outputTokens"] or 0)

        counts = Counter(trajectories)
        stability = counts.most_common(1)[0][1] / runs
        broken += violations
        mark = "OK" if violations == 0 else "위반"
        print(f"[{name}] 안정 {stability:.2f}  답변 {replied}/{runs}  "
              f"스텝 평균 {sum(step_counts) / runs:.1f} 최대 {max(step_counts)}  불변식 {mark}")
        for trajectory, hits in counts.most_common():
            print(f"    {hits}/{runs}  {trajectory}")
        print("    " + _llm_summary_line(calls, input_tokens, output_tokens, unmetered)
              + (f"  재시도 {retries}" if retries else "")
              + (f"  상한도달 {limit_reached}/{runs}" if limit_reached else ""))
        if warning_codes:
            print("    경고: " + ", ".join(f"{code}×{n}"
                                          for code, n in warning_codes.most_common()))
        # 위임 통로가 없는 에이전트는 줄을 만들지 않는다 — 0/N 은 "실패"가 아니라 "해당 없음"이다.
        attempts = sum(handoff_results.values())
        ok = sum(n for key, n in handoff_results.items() if key.startswith("ok:"))
        if attempts:
            total_handoffs += attempts
            total_handoff_ok += ok
            print(f"    위임 {runs_with_handoff}/{runs} run  시도 {attempts}  성공 {ok}"
                  f" ({ok / attempts:.2f})  " + ", ".join(f"{key}×{n}"
                                                          for key, n in handoff_results.most_common()))
        print()
        case_reports.append({
            "name": name,
            "stability": round(stability, 4),
            "replied": replied,
            "invariantViolations": violations,
            "steps": {"mean": round(sum(step_counts) / runs, 2), "max": max(step_counts),
                      "limitReached": limit_reached},
            "trajectories": dict(counts),
            "warnings": dict(warning_codes),
            "handoff": {"attempts": attempts, "ok": ok, "results": dict(handoff_results)},
            "llm": {
                "callsMean": round(sum(calls) / max(len(calls), 1), 2),
                "retries": retries,
                "inputTokensMean": round(sum(input_tokens) / len(input_tokens))
                                   if input_tokens else None,
                "outputTokensMean": round(sum(output_tokens) / len(output_tokens))
                                    if output_tokens else None,
                "unmeteredCalls": unmetered,
            },
        })

    print(f"=== 불변식 위반 총 {broken}건 ===")
    # hand-off 성공률 — 이 줄이 §1-1 의 "성공률 지표가 없다"에 대한 답이다.
    # 시도 0 이면 비율을 인쇄하지 않는다: 0/0 을 0% 로 적으면 없는 실패를 만들어낸다.
    if total_handoffs:
        print(f"=== hand-off 시도 {total_handoffs}건 중 성공 {total_handoff_ok}건 "
              f"({total_handoff_ok / total_handoffs:.2f}) ===")
    else:
        print("=== hand-off 시도 0건 — 이번 실행에서 위임이 발동하지 않았다(성공률 미정의) ===")

    if args.save:
        # meta 를 맨 앞에 둔다 — 파일을 열면 "무엇으로 잰 수치인가"가 첫 줄에 보여야 한다(D58).
        Path(args.save).write_text(json.dumps({
            "meta": meta,
            "totals": {
                "invariantViolations": broken,
                "handoff": {"attempts": total_handoffs, "ok": total_handoff_ok,
                            "rate": round(total_handoff_ok / total_handoffs, 4)
                                    if total_handoffs else None},
            },
            "cases": case_reports,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 저장: {args.save} ({meta['provider']}/{meta['model']}, {meta['measuredAt']})")


if __name__ == "__main__":
    main()
