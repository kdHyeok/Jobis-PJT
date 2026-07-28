"""LangGraph 그래프 조립 (설계 13.5 전체 흐름).

START
→ parse_job_posting → build_user_profile → check_profile_completeness → check_sufficiency
    ├─ insufficient → ask_user → assemble_output
    └─ sufficient   → analyze_gap → plan_roadmap
→ (optional) find_alternatives → verify_result
    ├─ retry → analyze_gap | plan_roadmap
    └─ pass  → assemble_output → END

MVP 범위(설계 13.6): 필수 경로 우선. 재시도 루프·추가 질문 분기는 1회 수준.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from jobis_ai.graph import nodes
from jobis_ai.graph.state import GraphState


def build_graph():
    """MVP 그래프를 구성해 컴파일된 앱을 반환한다."""

    g = StateGraph(GraphState)

    # --- 노드 등록 (설계 13.3) ---
    g.add_node("parse_job_posting", nodes.parse_job_posting)
    g.add_node("build_user_profile", nodes.build_user_profile)
    # defer=True: 병렬 분기(파싱 ∥ 프로필 빌드)의 **합류 지점** — 두 분기가 재시도 루프까지
    # 전부 끝난 뒤에 한 번만 실행된다. defer 없이는 먼저 끝난 분기가 이 노드를 조기 실행한다.
    g.add_node("check_profile_completeness", nodes.check_profile_completeness, defer=True)
    g.add_node("check_sufficiency", nodes.check_sufficiency)
    g.add_node("ask_user", nodes.ask_user)
    g.add_node("analyze_gap", nodes.analyze_gap)
    g.add_node("plan_roadmap", nodes.plan_roadmap)
    g.add_node("find_alternatives", nodes.find_alternatives)
    g.add_node("verify_result", nodes.verify_result)
    g.add_node("assemble_output", nodes.assemble_output)

    # --- 엣지 (설계 13.5) ---
    # 각 에이전트 뒤에 "산출물 검증 라우터"를 둔다: 생성 실패면 다음 에이전트로 넘어가지 않고
    # 같은 에이전트에게 다시 지시(재시도 예산 소진 시에만 진행). (설계 16.2)
    # 공고 파싱과 프로필 빌드는 상호 독립 — 팬아웃으로 **병렬 실행**한다 (LLM 직렬 2회 → 1회분 단축).
    # 각 분기는 자기 재시도 루프만 돌고, 성공하면 "inputs_ready" 신호로 합류 지점에 모인다.
    g.add_edge(START, "parse_job_posting")
    g.add_edge(START, "build_user_profile")
    g.add_conditional_edges(
        "parse_job_posting", nodes.route_after_parse,
        {"parse_job_posting": "parse_job_posting", "inputs_ready": "check_profile_completeness"},
    )
    g.add_conditional_edges(
        "build_user_profile", nodes.route_after_profile,
        {"build_user_profile": "build_user_profile", "inputs_ready": "check_profile_completeness"},
    )
    g.add_edge("check_profile_completeness", "check_sufficiency")

    # 정보 충분성 분기
    g.add_conditional_edges(
        "check_sufficiency",
        nodes.route_sufficiency,
        {"ask_user": "ask_user", "analyze_gap": "analyze_gap"},
    )
    g.add_edge("ask_user", "assemble_output")

    g.add_conditional_edges(
        "analyze_gap", nodes.route_after_gap,
        {"analyze_gap": "analyze_gap", "plan_roadmap": "plan_roadmap",
         # 상 등급이면 로드맵을 건너뛴다: 대안 요청이 있으면 find_alternatives, 없으면 바로 검증 (2026-07-21)
         "find_alternatives": "find_alternatives", "verify_result": "verify_result"},
    )

    # 로드맵 검증 + 대체 경로 조건부 실행 (통합)
    g.add_conditional_edges(
        "plan_roadmap",
        nodes.route_after_roadmap,
        {"plan_roadmap": "plan_roadmap", "find_alternatives": "find_alternatives",
         "verify_result": "verify_result"},
    )
    g.add_conditional_edges(
        "find_alternatives", nodes.route_after_alternatives,
        {"find_alternatives": "find_alternatives", "verify_result": "verify_result"},
    )

    # 검증 재시도 루프
    g.add_conditional_edges(
        "verify_result",
        nodes.route_verification,
        {
            "analyze_gap": "analyze_gap",
            "plan_roadmap": "plan_roadmap",
            "assemble_output": "assemble_output",
        },
    )
    g.add_edge("assemble_output", END)

    return g.compile()
