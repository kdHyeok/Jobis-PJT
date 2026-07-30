"""오케스트레이터 다중 실행 일관성 평가 — Agent_Test(tests/eval.py) 방식 이식.

케이스별 N회 실행해 **디스패치 궤적(어떤 에이전트가 어떤 순서로 돌았나)** 의 일관성을
집계한다. 구조·일관성만 본다 — 답변 품질 판정은 하지 않는다.

턴당 **LLM 콜 수·토큰**도 함께 집계한다(llm_usage) — "평균 몇 콜로 결론에 도달하는가"는
평가 리포트 §1-2 가 "말할 수 없다"고 적은 숫자이고, 풀턴을 도는 이 하네스가 재기에 맞는
자리다(플래너 + 에이전트 + 표현 계층이 전부 잡힌다).

사용: uv run python -m jobis_ai.eval.consistency [--runs N] [--save 경로]
      (기본 N=3. **실 GMS 를 다수 호출한다 — 크레딧 소모 큼.** 세션 저장은 memory 강제.)
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections import Counter
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
    """(이름, 발화, 첨부[(kind, value)], 기대판정(dispatched, reply) -> ok bool)"""

    return [
        ("S1 일상 위로", "요즘 취업 준비가 너무 힘들어. 위로해줘", [],
         lambda d, r: d == ["career_chat"]),
        ("S2 무관 거절", "오늘 서울 날씨 어때?", [],
         lambda d, r: d in ([], ["career_chat"]) and ("취업" in r)),
        ("S3 공고 제출→정리", "", [("job_posting", POSTING)],
         lambda d, r: "posting_analysis" in d),
        ("S4 이력서 제출→정리", "", [("resume", RESUME)],
         lambda d, r: "resume_diagnosis" in d),
        # ⚠️ KNOWN FAILURE (2026-07-29). 기대는 "무거운 파이프라인은 먼저 묻는다"인데 결과가
        # 갈린다: `resume_diagnosis`×2 / `fit_analysis>application_plan`×1.
        #   · 정리 먼저 — "제출 턴이면 자료를 읽어 보여준다"(07-27 정책)
        #   · 판정부터 — 플래너가 자소서의 전제로 fit_analysis 를 스스로 골라 실행(게이트 우회)
        # 두 번째가 **동의 게이트의 알려진 구멍**이다(router.validate_plan 주석 참고).
        # 기대값을 고쳐 덮지 않는다 — 구멍이 닫히기 전에 초록으로 만들면 그 사실이 사라진다.
        ("S5 갭분석 동의게이트", "자소서 써줘", [("resume", RESUME), ("job_posting", POSTING)],
         lambda d, r: d == [] and "진행할까요" in r),
        ("S6 슬롯 오배정 교정", "", [("job_posting", RESUME)],  # 이력서를 공고 슬롯에
         lambda d, r: "이력서로 등록했어요" in r),
        ("S7 공고 추천(실데이터)", "내 이력서로 갈 만한 공고 추천해줘", [("resume", RESUME)],
         lambda d, r: "job_recommend" in d),
    ]


def _run_case(query: str, attachments: list[tuple]) -> tuple[list[str], str, dict]:
    """1턴 실행 → (디스패치 궤적, reply, LLM 사용량 요약).

    handle_chat 이 턴마다 여는 수집기가 부모(여기)로도 전달하므로, 감싸기만 하면
    턴 안의 콜 전부가 잡힌다.
    """

    from jobis_ai import llm_usage
    from jobis_ai.contracts.api import ChatAttachment, ChatRequest
    from jobis_ai.orchestrator.chat import handle_chat

    with llm_usage.collecting() as usage:
        res = handle_chat(ChatRequest(
            sessionId=f"eval-{uuid.uuid4().hex[:8]}",
            message=query,
            attachments=[ChatAttachment(kind=k, sourceType="text", value=v)
                         for k, v in attachments],
        ))
    return list(res.dispatched), res.reply, usage.summary()


def main() -> None:
    parser = argparse.ArgumentParser(description="오케스트레이터 일관성 평가 (실 LLM)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--save", help="결과 JSON 저장 경로 — 콘솔에서 사라지는 수치는 baseline 이 못 된다")
    args = parser.parse_args()
    runs = args.runs

    from jobis_ai.eval import provenance

    meta = provenance(runs=runs)
    print(f"=== 오케스트레이터 일관성 평가 — {len(_cases())}케이스 × {runs}회 (실 LLM) ===")
    print(f"    provider={meta['provider']} model={meta['model']}\n")
    total_bad = 0
    case_reports: list[dict] = []
    grand_calls: list[int] = []
    grand_in: list[int] = []
    grand_out: list[int] = []
    for name, query, attachments, check in _cases():
        outcomes: list[tuple[bool, list[str]]] = []
        calls: list[int] = []
        input_tokens: list[int] = []
        output_tokens: list[int] = []
        unmetered = 0
        for _ in range(runs):
            try:
                dispatched, reply, llm = _run_case(query, attachments)
                outcomes.append((bool(check(dispatched, reply)), dispatched))
                calls.append(llm["calls"])
                unmetered += llm["unmeteredCalls"]
                if llm["inputTokens"] is not None:
                    input_tokens.append(llm["inputTokens"])
                    output_tokens.append(llm["outputTokens"] or 0)
            except Exception as exc:   # noqa: BLE001 — 평가는 크래시 자체가 결과다
                outcomes.append((False, [f"CRASH: {exc}"]))
        ok = sum(1 for good, _ in outcomes if good)
        total_bad += runs - ok
        mark = "✅" if ok == runs else "❌"
        calls_mean = sum(calls) / len(calls) if calls else 0
        tokens_note = (f"토큰 평균 {sum(input_tokens) / len(input_tokens):.0f}"
                       f"→{sum(output_tokens) / len(output_tokens):.0f}"
                       if input_tokens else "토큰 미계측")
        if unmetered:
            tokens_note += f" (미계측 콜 {unmetered}건)"
        print(f"[{name}] {mark} 일관성 {ok}/{runs}  턴당 콜 평균 {calls_mean:.1f}  {tokens_note}")
        for i, (good, dispatched) in enumerate(outcomes, 1):
            print(f"    run{i} {'ok ' if good else 'BAD'}: dispatched={dispatched}")
        print()
        grand_calls.extend(calls)
        grand_in.extend(input_tokens)
        grand_out.extend(output_tokens)
        case_reports.append({
            "name": name,
            "consistentOk": ok,
            "runs": runs,
            "outcomes": [{"ok": good, "dispatched": d} for good, d in outcomes],
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
        line = f"=== 턴당 콜 평균 {sum(grand_calls) / len(grand_calls):.1f}"
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
                    "callsMeanPerTurn": round(sum(grand_calls) / len(grand_calls), 2)
                                        if grand_calls else None,
                    "inputTokensMeanPerTurn": round(sum(grand_in) / len(grand_in))
                                              if grand_in else None,
                    "outputTokensMeanPerTurn": round(sum(grand_out) / len(grand_out))
                                               if grand_out else None,
                },
            },
            "cases": case_reports,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 저장: {args.save} ({meta['provider']}/{meta['model']}, {meta['measuredAt']})")


if __name__ == "__main__":
    main()
