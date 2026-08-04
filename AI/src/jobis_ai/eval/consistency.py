"""오케스트레이터 다중 실행 일관성 평가 — Agent_Test(tests/eval.py) 방식 이식.

케이스별 N회 실행해 **디스패치 궤적(어떤 에이전트가 어떤 순서로 돌았나)** 의 일관성을
집계한다. 구조·일관성만 본다 — 답변 품질 판정은 하지 않는다.

**시나리오는 턴 시퀀스다(2026-07-31, D76).** 전에는 케이스마다 새 세션 1턴이라
"되묻기 → 접수 → 분석 → 종합"처럼 **턴 사이 상태(세션 자산)를 이어가는 흐름**을 잴 수
없었다 — 오케스트레이터의 존재 이유가 정확히 그 흐름인데 하네스가 못 봤다. 이제 한
시나리오가 같은 세션에서 여러 턴을 돌고, 턴마다 판정한다(S8·S9 가 멀티턴이다).

턴당 **LLM 콜 수·토큰**도 함께 집계한다(llm_usage) — "평균 몇 콜로 결론에 도달하는가"는
평가 리포트 §1-2 가 "말할 수 없다"고 적은 숫자이고, 풀턴을 도는 이 하네스가 재기에 맞는
자리다(플래너 + 에이전트 + 표현 계층이 전부 잡힌다).

사용: uv run python -m jobis_ai.eval.consistency [--runs N] [--save 경로]
      (기본 N=3. **실 LLM 을 다수 호출한다 — 크레딧 소모 큼.** 세션 저장은 memory 강제.)
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

os.environ.setdefault("SESSION_STORE", "memory")   # 평가가 sqlite 세션을 오염시키지 않게

RESUME = (
    "김지원. 프론트엔드 개발자. 기술 스택: JavaScript, TypeScript, React, Next.js, Zustand.\n"
    "프로젝트: MindConnect(React+TS, 드래그앤드롭 UI, 기여도 50%) / BookShare(WebSocket 채팅 UI, 60%).\n"
    "학력: OO대학교 컴퓨터공학과 졸업예정. 부트캠프 수료."
)
POSTING = (
    "[프론트엔드 개발자 채용] 담당업무: React 웹 서비스 UI 개발. "
    "자격요건: JavaScript/TypeScript, React 프로젝트 경험. 우대사항: Next.js, 상태관리. "
    "근무지: 서울. 고용형태: 정규직."
)


def _cases() -> list[tuple]:
    """(이름, 턴 시퀀스). 턴 = (발화, 첨부[(kind, value)], 판정(dispatched, reply, response)).

    시나리오의 모든 턴은 **같은 세션**에서 돈다 — 앞 턴이 쌓은 자산·기억(pendingRequest·
    pendingConsent)이 뒤 턴의 전제다. 1턴 케이스(S1~S7)는 턴 하나짜리 시퀀스다.
    """

    return [
        ("S1 일상 위로", [
            ("요즘 취업 준비가 너무 힘들어. 위로해줘", [],
             lambda d, r, res: d == ["career_chat"]),
        ]),
        ("S2 무관 거절", [
            ("오늘 서울 날씨 어때?", [],
             lambda d, r, res: d in ([], ["career_chat"]) and ("취업" in r)),
        ]),
        ("S3 공고 제출→정리", [
            ("", [("job_posting", POSTING)],
             lambda d, r, res: "posting_analysis" in d),
        ]),
        ("S4 이력서 제출→정리", [
            ("", [("resume", RESUME)],
             lambda d, r, res: "resume_diagnosis" in d),
        ]),
        # 갱신 (2026-08-04, 근거 D158). 이 술어는 원래 `d == []` 였다 — 게이트 턴에는 **아무
        # 담당도 돌지 않는다**를 못 박은 것이고, 07-29 KNOWN FAILURE(게이트 우회)를 감시하던
        # 자리다. D158 이 동작을 바꿨다: 게이트가 `Dispatch(())` 로 계획 **전체**를 막고 있어서
        # 공고를 붙인 턴에 판정이 게이트에 걸리면 **공고 정리까지 사라지고 질문만** 나갔다.
        # 이제 게이트 턴에도 `submission_review_inserts` 로 **이번 턴 제출물의 정리 단계만**
        # 돌고 질문이 뒤에 붙는다.
        #
        # 그래서 재는 대상을 바꾸지 않고 **정확히 재도록** 좁혔다 — 이 케이스가 지키려는 것은
        # "정리가 안 도는 것"이 아니라 **"무거운 판정이 묻기 전에 돌지 않는 것"** 이다.
        # `fit_analysis not in d` 가 07-29 구멍(플래너가 전제로 fit_analysis 를 끼워 실행)을
        # 그대로 감시한다. 관측에 맞춰 넓힌 것이 아니라, 결정(D158)이 정한 동작에 맞춘 것이다.
        ("S5 갭분석 동의게이트", [
            ("자소서 써줘", [("resume", RESUME), ("job_posting", POSTING)],
             lambda d, r, res: "fit_analysis" not in d and "진행할까요" in r),
        ]),
        ("S6 슬롯 오배정 교정", [
            ("", [("job_posting", RESUME)],   # 이력서를 공고 슬롯에
             lambda d, r, res: "이력서로 등록했어요" in r),
        ]),
        ("S7 공고 추천(실데이터)", [
            ("내 이력서로 갈 만한 공고 추천해줘", [("resume", RESUME)],
             lambda d, r, res: "job_recommend" in d),
        ]),
        # --- 멀티턴 (D76) — 턴 사이 상태를 잇는 흐름이 이 하네스의 존재 이유다 -----------
        # S8: 되묻기 → 접수 → 원요청 완수(D72). 턴1은 공고만 있어 적합도가 불가 — 이력서를
        # 청해야 하고(followUp), 턴2에 이력서가 오면 **플래너 선택과 무관하게** 적합도가
        # 이어져야 한다(pendingRequest 재큐 또는 플래너 규칙 2 — 어느 쪽이든 결과는 같아야 한다).
        ("S8 되묻기→접수→적합도 완수", [
            ("이 공고에 나 되는지 적합도 분석해줘", [("job_posting", POSTING)],
             lambda d, r, res: "fit_analysis" not in d
             and any(q.get("field") == "resume" for q in res.followUpQuestions)),
            ("", [("resume", RESUME)],
             lambda d, r, res: "fit_analysis" in d),
        ]),
        # S9: 동의 게이트 → 동의 → 실행(pendingConsent 소진). 턴1은 S5 와 같은 술어를 쓴다
        # (갱신 근거 D158 — 위 S5 주석 참고). 게이트가 안 걸린 run 은 턴2도 실패로 찍힌다.
        ("S9 동의→갭분석 실행", [
            ("자소서 써줘", [("resume", RESUME), ("job_posting", POSTING)],
             lambda d, r, res: "fit_analysis" not in d and "진행할까요" in r),
            ("응, 진행해줘", [],
             lambda d, r, res: "fit_analysis" in d),
        ]),
    ]


def _run_turn(session_id: str, query: str, attachments: list[tuple]) -> tuple:
    """같은 세션에서 1턴 실행 → (디스패치 궤적, reply, ChatResponse, LLM 사용량 요약).

    handle_chat 이 턴마다 여는 수집기가 부모(여기)로도 전달하므로, 감싸기만 하면
    턴 안의 콜 전부가 잡힌다.
    """

    from jobis_ai import llm_usage
    from jobis_ai.contracts.api import ChatAttachment, ChatRequest
    from jobis_ai.orchestrator.chat import handle_chat

    with llm_usage.collecting() as usage:
        res = handle_chat(ChatRequest(
            sessionId=session_id,
            message=query,
            attachments=[ChatAttachment(kind=k, sourceType="text", value=v)
                         for k, v in attachments],
        ))
    return list(res.dispatched), res.reply, res, usage.summary()


def _run_scenario(turns: list[tuple]) -> tuple[bool, str, dict]:
    """시나리오 1회 실행(새 세션) → (전 턴 통과 여부, 궤적 키, LLM 집계).

    궤적 키는 턴별 dispatched 를 ' || ' 로 이어 붙인다 — 멀티턴의 이탈이 어느 턴에서
    났는지가 키에 그대로 보인다.
    """

    session_id = f"eval-{uuid.uuid4().hex[:8]}"
    ok = True
    trajectory: list[str] = []
    calls = 0
    input_tokens = 0
    output_tokens = 0
    metered = True
    unmetered = 0
    for query, attachments, check in turns:
        dispatched, reply, res, llm = _run_turn(session_id, query, attachments)
        trajectory.append(">".join(dispatched) or "(없음)")
        ok = ok and bool(check(dispatched, reply, res))
        calls += llm["calls"]
        unmetered += llm["unmeteredCalls"]
        if llm["inputTokens"] is None:
            metered = False
        else:
            input_tokens += llm["inputTokens"]
            output_tokens += llm["outputTokens"] or 0
    return ok, " || ".join(trajectory), {
        "calls": calls, "unmetered": unmetered,
        "inputTokens": input_tokens if metered else None,
        "outputTokens": output_tokens if metered else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="오케스트레이터 일관성 평가 (실 LLM)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--save", help="결과 JSON 저장 경로 — 콘솔에서 사라지는 수치는 baseline 이 못 된다")
    args = parser.parse_args()
    runs = args.runs

    from jobis_ai.eval import provenance

    meta = provenance(runs=runs)
    print(f"=== 오케스트레이터 일관성 평가 — {len(_cases())}시나리오 × {runs}회 (실 LLM) ===")
    print(f"    provider={meta['provider']} model={meta['model']} "
          f"router={meta.get('modelRouter')}\n")
    total_bad = 0
    case_reports: list[dict] = []
    grand_calls: list[int] = []
    grand_in: list[int] = []
    grand_out: list[int] = []
    for name, turns in _cases():
        outcomes: list[tuple[bool, str]] = []
        calls: list[int] = []
        input_tokens: list[int] = []
        output_tokens: list[int] = []
        unmetered = 0
        for _ in range(runs):
            try:
                ok_run, trajectory, llm = _run_scenario(turns)
                outcomes.append((ok_run, trajectory))
                calls.append(llm["calls"])
                unmetered += llm["unmetered"]
                if llm["inputTokens"] is not None:
                    input_tokens.append(llm["inputTokens"])
                    output_tokens.append(llm["outputTokens"] or 0)
            except Exception as exc:   # noqa: BLE001 — 평가는 크래시 자체가 결과다
                outcomes.append((False, f"CRASH: {exc}"))
        ok = sum(1 for good, _ in outcomes if good)
        total_bad += runs - ok
        mark = "✅" if ok == runs else "❌"
        calls_mean = sum(calls) / len(calls) if calls else 0
        tokens_note = (f"토큰 평균 {sum(input_tokens) / len(input_tokens):.0f}"
                       f"→{sum(output_tokens) / len(output_tokens):.0f}"
                       if input_tokens else "토큰 미계측")
        if unmetered:
            tokens_note += f" (미계측 콜 {unmetered}건)"
        print(f"[{name}] {mark} 일관성 {ok}/{runs}  시나리오당 콜 평균 {calls_mean:.1f}  {tokens_note}")
        for i, (good, trajectory) in enumerate(outcomes, 1):
            print(f"    run{i} {'ok ' if good else 'BAD'}: {trajectory}")
        print()
        grand_calls.extend(calls)
        grand_in.extend(input_tokens)
        grand_out.extend(output_tokens)
        case_reports.append({
            "name": name,
            "turns": len(turns),
            "consistentOk": ok,
            "runs": runs,
            "outcomes": [{"ok": good, "trajectory": t} for good, t in outcomes],
            "llm": {
                "callsMean": round(calls_mean, 2),
                "inputTokensMean": round(sum(input_tokens) / len(input_tokens))
                                   if input_tokens else None,
                "outputTokensMean": round(sum(output_tokens) / len(output_tokens))
                                    if output_tokens else None,
                "unmeteredCalls": unmetered,
            },
        })
    print(f"=== 총 이탈 {total_bad}건 ===")
    if grand_calls:
        # "평균 몇 콜로 결론에 도달하는가" — 평가 리포트 §1-2 의 없던 숫자가 이 줄이다.
        line = f"=== 시나리오당 콜 평균 {sum(grand_calls) / len(grand_calls):.1f}"
        if grand_in:
            line += (f"  토큰 평균 {sum(grand_in) / len(grand_in):.0f}"
                     f"→{sum(grand_out) / len(grand_out):.0f}")
        print(line + " ===")

    if args.save:
        # meta 를 맨 앞에 둔다 — 파일을 열면 "무엇으로 잰 수치인가"가 첫 줄에 보여야 한다(D58).
        Path(args.save).write_text(json.dumps({
            "meta": meta,
            "totals": {
                "deviations": total_bad,
                "llm": {
                    "callsMeanPerScenario": round(sum(grand_calls) / len(grand_calls), 2)
                                            if grand_calls else None,
                    "inputTokensMeanPerScenario": round(sum(grand_in) / len(grand_in))
                                                  if grand_in else None,
                    "outputTokensMeanPerScenario": round(sum(grand_out) / len(grand_out))
                                                   if grand_out else None,
                },
            },
            "cases": case_reports,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 저장: {args.save} ({meta['provider']}/{meta['model']}, {meta['measuredAt']})")


if __name__ == "__main__":
    main()
