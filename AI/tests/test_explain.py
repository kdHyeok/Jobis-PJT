"""오케스트레이터 자기설명 (`jobis_ai.explain`).

이 모듈의 존재 이유는 "코드를 읽지 않고도 무엇이 왜 실행되나를 답한다"이므로, **설명이 코드와
갈라지지 않는 것**이 유일한 계약이다. 그래서 테스트는 출력 문구를 고정하지 않고 **출력이 실제
상수·레지스트리에서 나왔는지**를 검사한다 — 설명을 따로 적어 두면 문서 드리프트를 코드로
옮긴 것일 뿐이다(§2-4).
"""

from __future__ import annotations

from jobis_ai.agents import get_agent_registry
from jobis_ai.explain import (
    asset_state,
    flow_summary,
    observe_summary,
    plan_trace,
    registry_table,
)


def test_registry_table_lists_every_agent_and_its_kind():
    out = "\n".join(registry_table())
    registry = get_agent_registry()
    for name, spec in registry.items():
        assert name in out, f"{name} 이 표에 없다"
    assert "도구" in out and "에이전트" in out, "종류 구분이 보여야 한다"
    # 무거움·인자 같은 선언 필드도 표에 실린다(조합을 눈으로 보는 것이 목적).
    assert "무거움" in out and "인자" in out


def test_flow_summary_reads_the_real_constants():
    """상수를 베껴 적지 않는다 — 코드가 바뀌면 출력도 바뀐다."""

    from jobis_ai.orchestrator import chat
    from jobis_ai.orchestrator.planner import CONFIDENCE_THRESHOLD
    from jobis_ai.orchestrator.router import FALLBACK_AGENT

    out = "\n".join(flow_summary())
    assert str(CONFIDENCE_THRESHOLD) in out
    assert str(chat._MAX_AGENT_STEPS) in out
    assert str(chat._MAX_PARALLEL) in out
    assert FALLBACK_AGENT in out


def test_observe_summary_reads_the_real_rules():
    from jobis_ai.orchestrator import observe_rules

    out = "\n".join(observe_summary())
    for grade in observe_rules._WEAK_GRADES:
        assert grade in out
    for name in observe_rules._GRADE_DEPENDENT:
        assert name in out
    assert observe_rules._WEAK_GRADE_FALLBACK in out


def test_asset_state_separates_runnable_now_from_runnable_with_producer():
    """이 구분이 §2-4 의 핵심 — "지금 도나" 와 "생산자를 끼우면 도나" 는 다른 질문이다."""

    out = "\n".join(asset_state(["resume", "job_posting"]))
    lines = {line.split()[0]: line for line in out.splitlines() if line.startswith("  ")}
    # coverletter_draft 는 analysis 가 없어 지금은 못 돌지만, fit_analysis 를 끼우면 된다.
    row = next(line for key, line in lines.items() if key == "coverletter_draft")
    assert row.count("불가") == 1 and "가능" in row


def test_plan_trace_shows_the_consent_gate():
    """무거운 생산자 자동 삽입 → 실행 대신 묻는다. 그 사실이 설명에 드러나야 한다."""

    out = "\n".join(plan_trace(["coverletter_draft"], ["resume", "job_posting"]))
    assert "동의 게이트" in out
    assert "실행하지 않는다" in out


def test_plan_trace_shows_inserted_producer_when_not_heavy():
    """가벼운 생산자는 게이트 없이 앞에 끼워진다 — 무엇이 끼워졌는지 보여준다."""

    out = "\n".join(plan_trace(["job_recommend"], []))
    assert "preference_intake" in out, "선호 생산자가 끼워진 사실이 보여야 한다"


def test_plan_trace_marks_parallel_segments():
    """동시 실행 구간을 표기한다 — 순차로 읽으면 오해한다."""

    out = "\n".join(plan_trace(["posting_analysis", "resume_diagnosis"],
                               ["resume", "job_posting"]))
    assert "∥" in out and "동시 실행" in out
