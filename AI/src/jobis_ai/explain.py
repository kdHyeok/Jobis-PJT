"""오케스트레이터 자기설명 — **"이 상태에서 무엇이, 왜 실행되나"를 코드를 읽지 않고 답한다.**

왜 있나(비교 문서 §2-4): 프로토타입은 `agent/graph.py` 210줄 한 화면에 프롬프트·상태·툴 배선·
분기가 다 있어서 "왜 이게 돌았나"를 그 파일만 읽고 답할 수 있다. 우리는 같은 질문에
`planner.py`+`router.py`+`chat.py`+`agents/__init__.py`+`observe_rules.py` ≈ 1,400줄이 필요하고,
게다가 정책이 `AgentSpec` **선언 필드 8개의 상호작용**으로 결정된다 — 조합의 총 동작을 사람이
머릿속에서 시뮬레이션할 수는 없다.

줄 수는 기능(에이전트 10종·병렬·write-back·게이트)의 대가라 줄일 수 없다. 그래서 **읽고
시뮬레이션하는 대신 물어보게** 한다. 전부 결정론이고 LLM 을 부르지 않는다.

    uv run python -m jobis_ai.explain
    uv run python -m jobis_ai.explain --assets resume,job_posting
    uv run python -m jobis_ai.explain --assets resume --plan coverletter_draft

**값은 전부 코드에서 끌어온다**(레지스트리·validate_plan·observe_rules 상수). 설명을 따로 적어
두면 코드와 갈라지고, 그건 이 문제를 문서로 옮기는 것일 뿐이다.
"""

from __future__ import annotations

import argparse

from jobis_ai.agents import get_agent_registry
from jobis_ai.orchestrator import observe_rules
from jobis_ai.orchestrator.planner import CONFIDENCE_THRESHOLD
from jobis_ai.orchestrator.router import (
    FALLBACK_AGENT,
    agent_feasibility,
    asset_label,
    runnable_now,
    session_assets,
    validate_plan,
)


def _fmt(items) -> str:
    return ", ".join(items) if items else "—"


def registry_table() -> list[str]:
    """선언 필드를 한 표로 — 조합을 눈으로 보게 한다(머릿속 시뮬레이션 대체)."""

    registry = get_agent_registry()
    rows = [("이름", "종류", "전제(전부)", "전제(하나만)", "산출", "무거움", "인자")]
    for spec in registry.values():
        rows.append((
            spec.name,
            "도구" if spec.kind == "tool" else "에이전트",
            _fmt(spec.preconditions),
            _fmt(spec.preconditions_any),
            _fmt(spec.produces),
            "예" if spec.heavy else "—",
            _fmt([name for name, _ in spec.params]),
        ))
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    out = ["", "=== 에이전트 선언 (capability manifest) ==="]
    for index, row in enumerate(rows):
        out.append("  " + "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))
        if index == 0:
            out.append("  " + "  ".join("-" * w for w in widths))
    return out


def flow_summary() -> list[str]:
    """한 턴이 지나는 관문과 그 상수 — 어느 파일에 무엇이 있는지까지 적는다."""

    from jobis_ai.orchestrator import chat

    return [
        "",
        "=== 한 턴의 흐름 (관문 순서) ===",
        "  1. 첨부 저장      chat._apply_attachments  — 내용으로 kind 재분류(attachment_kind)",
        "                     이력서 갱신 시 파생 자산(profile·analysis) 무효화",
        f"  2. 플래너(LLM)    planner.plan_agents      — 확신 < {CONFIDENCE_THRESHOLD} 면 "
        f"{FALLBACK_AGENT} 가 턴을 받는다",
        "  3. 검증기         router.validate_plan     — 전제 생산자 자동 삽입 / 실행 불가 제외",
        "                     무거운 생산자가 **자동 삽입**되면 동의 게이트(실행 없이 한 턴 묻는다)",
        f"  4. 실행           chat.handle_chat 루프    — 스텝 상한 {chat._MAX_AGENT_STEPS}"
        f" / 동시 실행 상한 {chat._MAX_PARALLEL}",
        "                     서로 독립인 연속 구간은 동시에(chat.parallel_group)",
        "  5. 관찰(규칙)     observe_rules.observe    — 아래 규칙. **LLM 없음**",
        "  6. 저장           턴 끝에 한 번(write-back). 상태 전이는 sessionUpdates 로만",
    ]


def observe_summary() -> list[str]:
    """관찰 규칙 — 실행 뒤 계획이 바뀔 수 있는 경우 전부."""

    return [
        "",
        "=== 실행 뒤 계획을 바꾸는 규칙 (결정론) ===",
        f"  ① 약한 판정      fit_analysis 등급이 {_fmt(observe_rules._WEAK_GRADES)} 이고",
        f"                   큐에 {_fmt(observe_rules._GRADE_DEPENDENT)} 가 있으면",
        f"                   → 빼고 {observe_rules._WEAK_GRADE_FALLBACK} 를 넣는다",
        "                   (같은 턴에 판정이 난 경우만 — 다음 턴 재요청은 막지 않는다)",
        "  ② 전제 붕괴      남은 큐에서 지금 실행 불가한 항목을 뺀다(큐를 앞에서부터 시뮬레이션",
        "                   하므로 앞 단계가 만들어 줄 것은 남긴다). 전부 빠지면 턴 종료",
        "  그 밖            예정대로 계속",
    ]


def asset_state(assets: list[str]) -> list[str]:
    """주어진 자산에서 각 에이전트가 지금 도는지 / 무엇이 없어서 못 도는지."""

    from jobis_ai.eval.planner_harness import build_session

    session = build_session(assets)
    have = session_assets(session)
    registry = get_agent_registry()
    feasibility = agent_feasibility(session)

    out = ["", f"=== 자산 {_fmt(sorted(have))} 일 때 ==="]
    out.append("  에이전트                지금 실행  생산자 끼우면  결측")
    out.append("  " + "-" * 58)
    for name, spec in registry.items():
        now = "가능" if runnable_now(spec, have) else "불가"
        missing = feasibility[name]
        chained = "가능" if missing is None else "불가"
        out.append(f"  {name:22}  {now:8}  {chained:12}  "
                   f"{'—' if missing is None else asset_label(missing)}")
    return out


def plan_trace(plan: list[str], assets: list[str]) -> list[str]:
    """검증기가 이 계획을 어떻게 확정하는지 — 삽입·제외·게이트를 그대로 보여준다."""

    from jobis_ai.eval.planner_harness import build_session

    session = build_session(assets)
    dispatch = validate_plan(plan, session)

    out = ["", f"=== 플래너가 {plan} 을 골랐다면 ==="]
    if dispatch.ask:
        out.append("  → 실행하지 않는다. **동의 게이트**가 걸린다:")
        out.append(f'     "{dispatch.ask}"')
        out.append("     (무거운 생산자가 자동 삽입됐다 — 말없이 시작하지 않는다)")
        return out

    inserted = [n for n in dispatch.agents if n not in plan]
    dropped = [n for n in plan if n not in dispatch.agents]
    out.append(f"  확정 시퀀스: {_fmt(dispatch.agents)}")
    if inserted:
        out.append(f"  검증기가 앞에 끼운 것: {_fmt(inserted)} (전제를 만드는 생산자)")
    if dropped:
        out.append(f"  제외된 것: {_fmt(dropped)} (전제를 채울 수 없다)")
    if dispatch.note:
        out.append(f"  사용자에게 알릴 문구: {dispatch.note}")

    # 실행 루프가 이 시퀀스를 어떻게 쪼개는지 — 병렬 구간까지 보여준다.
    from jobis_ai.orchestrator.chat import parallel_group

    queue, dispatched, groups = list(dispatch.agents), [], []
    while queue:
        group = parallel_group(queue, dispatched, session)
        if len(group) > 1:
            groups.append(group)
            dispatched.extend(group)
            del queue[:len(group)]
        else:
            name = queue.pop(0)
            groups.append([name])
            dispatched.append(name)
    if any(len(g) > 1 for g in groups):
        out.append("  실행 방식: " + " → ".join(
            ("∥ ".join(g) if len(g) > 1 else g[0]) for g in groups)
            + "   (∥ = 동시 실행)")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="오케스트레이터 자기설명 — 무엇이 왜 실행되나 (LLM 없음)")
    parser.add_argument("--assets", default="",
                        help="쉼표로 구분한 세션 자산 "
                             "(resume, job_posting, analysis, roadmap, preferences)")
    parser.add_argument("--plan", default="",
                        help="쉼표로 구분한 에이전트 — 플래너가 이걸 골랐다고 가정한다")
    args = parser.parse_args()

    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    plan = [a.strip() for a in args.plan.split(",") if a.strip()]

    lines = registry_table() + flow_summary() + observe_summary()
    if assets or plan:
        lines += asset_state(assets)
    if plan:
        lines += plan_trace(plan, assets)
    lines.append("")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
