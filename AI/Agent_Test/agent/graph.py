"""Agent 루프 — LangGraph (D11 = B 아키텍처).

agent(LLM bind_tools) ⇄ tools(실행+State갱신) ─[조건엣지]─ analyze_gap&중/하 → auto_search → agent
                                                          └ 그외 → agent    → 툴없음 → END(=reply)
- 동적 라우팅(LLM 툴 선택) + 결정적 level 분기(조건엣지). max_steps 가드.
- profile/공고는 State 주입(LLM 인자 아님). 라이트 로깅(run_id + 노드별 1줄).
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

import tools as T  # load_posting, search_postings, analyze_gap (실제 구현)
from llm import get_llm
from schemas import GapResult, Meta, Posting, RunAgentResult, UserProfile

log = logging.getLogger("agent")
MAX_STEPS = 10


# --- LLM용 도구 스키마 (실행은 tools 노드가 함) ---
@tool
def load_posting(url: str) -> str:
    """공고 URL로 해당 공고 1건을 DB에서 조회한다. 사용자가 공고 URL을 제시하면 사용."""
    return ""


@tool
def search_postings(job_name: str = "") -> str:
    """관련 공고를 검색한다. job_name을 주면 그 직군의 공고, 비우면 사용자 이력서 기반 추천."""
    return ""


@tool
def analyze_gap() -> str:
    """사용자 이력서와 '방금 조회한 공고'의 지원 가능성을 상/중/하로 분석한다. load_posting 뒤에 사용."""
    return ""


_TOOLS = [load_posting, search_postings, analyze_gap]

SYSTEM = """당신은 커리어 코치 AI Agent입니다. 사용자의 이력서(프로필)는 이미 시스템에 있습니다.
도구:
- load_posting(url): 공고 URL로 공고 조회
- search_postings(job_name): 관련 공고 검색 (job_name 비우면 이력서 기반 추천)
- analyze_gap(): 방금 조회한 공고와 이력서의 지원 가능성(상/중/하) 분석 (load_posting 후)

지침:
- 공고 URL + 합격/지원 가능성 질문 → load_posting 후 analyze_gap 호출.
- 이력서 기반 공고 추천 → search_postings (job_name 없이).
- 특정 직군 공고 찾기 → search_postings(job_name).
- 취업과 무관한 질의 → "취업 관련 외 질의는 받지 않습니다"로 거절 (도구 안 씀).
- 일상 대화 → 공감하고, 이력서/공고를 주면 도울 수 있음을 안내 (도구 안 씀).
- **공고를 나열·추천할 때는 각 공고의 URL을 반드시 함께 제시**하세요 (사용자가 바로 갭분석에 쓸 수 있게).
도구가 더 필요 없으면 한국어로 최종 답변을 작성하세요."""


class AgentState(TypedDict):
    run_id: str
    messages: Annotated[list, add_messages]
    profile: Optional[UserProfile]
    current_posting: Optional[Posting]
    tools_called: list[str]
    level: Optional[str]
    step: int


def _agent_node(state: AgentState) -> dict:
    step = state.get("step", 0) + 1
    msgs = state["messages"]
    if not any(isinstance(m, SystemMessage) for m in msgs):
        msgs = [SystemMessage(content=SYSTEM), *msgs]
    resp = get_llm("cheap").bind_tools(_TOOLS).invoke(msgs)
    calls = [tc["name"] for tc in (resp.tool_calls or [])]
    log.info("[%s][step %d] node=agent tool_calls=%s", state["run_id"], step, calls)
    return {"messages": [resp], "step": step}


def _tools_node(state: AgentState) -> dict:
    last = state["messages"][-1]
    profile = state.get("profile")
    tools_called = list(state.get("tools_called", []))
    level = state.get("level")
    current_posting = state.get("current_posting")
    out: list = []
    for tc in last.tool_calls:
        name, args, tid = tc["name"], tc.get("args", {}), tc["id"]
        tools_called.append(name)
        if name == "load_posting":
            res = T.load_posting(args.get("url", ""))
            if isinstance(res, Posting):
                current_posting = res
                body = (res.detail_text or "").strip()
                excerpt = (body[:500] + "…") if len(body) > 500 else (body or "(본문 없음 — 이미지 공고)")
                summary = (f"공고 조회 OK — {res.company} | {res.title}\n"
                           f"경력:{res.experience} · 지역:{res.location} · 마감:{res.deadline}\n"
                           f"본문발췌: {excerpt}")
            else:
                summary = f"공고 조회 실패: {res.error} — {res.detail}"
        elif name == "search_postings":
            jn = (args.get("job_name") or "").strip()
            if jn:
                res = T.search_postings(jn)
            elif profile is not None:
                res = T.search_postings(profile)
            else:
                out.append(ToolMessage(content="이력서가 없어 추천할 수 없습니다.", tool_call_id=tid))
                log.info("[%s] node=tools tool=search_postings → 이력서 없음", state["run_id"])
                continue
            parts = []
            for p in res.postings[:3]:
                m = p.match_reason
                why = (m.matched_skills or m.matched_keywords)[:3]
                parts.append(f"{p.company} | {str(p.title)[:30]} | {p.url} (score {p.score}, 매칭 {why})")
            summary = (f"공고 {len(res.postings)}건:\n" + "\n".join(parts)) if res.postings else "관련 공고 없음"
        elif name == "analyze_gap":
            if current_posting is None:
                summary = "갭분석 불가: 조회된 공고가 없습니다 — 먼저 공고 URL을 알려주세요."
            elif profile is None:
                summary = "갭분석 불가: 이력서가 없습니다."
            else:
                res = T.analyze_gap(profile, current_posting)
                if isinstance(res, GapResult):
                    level = res.level
                    summary = (f"갭분석 결과 level={res.level} | 충족 {res.matched_required} | "
                               f"부족 {res.missing_required} | 판정불가 {len(res.uncertain)}")
                else:  # ToolError — 원인(detail)을 그대로 전달해 reply가 정확해지도록
                    summary = f"갭분석 불가: {res.detail}"
        else:
            summary = f"알 수 없는 도구: {name}"
        log.info("[%s] node=tools tool=%s → %s", state["run_id"], name, summary[:90])
        out.append(ToolMessage(content=summary, tool_call_id=tid))
    return {"messages": out, "tools_called": tools_called, "level": level, "current_posting": current_posting}


def _auto_search_node(state: AgentState) -> dict:
    profile = state.get("profile")
    skills = [s.name for s in profile.skills][:8] if profile else []
    alt = get_llm("cheap").invoke(
        f"아래 스킬을 가진 지원자가 갭이 커서 전직할 만한 대체 직군 하나를 "
        f"'직군명'만 (설명 없이) 출력하세요. 스킬: {skills}"
    ).content.strip().splitlines()[0].strip()
    res = T.search_postings(alt)
    lst = [f"{p.company} | {str(p.title)[:30]} | {p.url}" for p in res.postings[:3]]
    tools_called = list(state.get("tools_called", [])) + ["search_postings"]
    log.info("[%s] node=auto_search 대체직군=%r → %d건", state["run_id"], alt, len(res.postings))
    ctx = f"[시스템: 갭이 커서 대체직군 '{alt}' 공고 {len(res.postings)}건]\n" + "\n".join(lst)
    return {"messages": [HumanMessage(content=ctx)], "tools_called": tools_called}


def _route_after_agent(state: AgentState):
    if state.get("step", 0) >= MAX_STEPS:
        log.info("[%s] max_steps 도달 → END", state["run_id"])
        return END
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


def _route_after_tools(state: AgentState):
    tc = state.get("tools_called", [])
    if tc and tc[-1] == "analyze_gap" and state.get("level") in ("중", "하"):
        log.info("[%s] route_after_tools: level=%s → auto_search", state["run_id"], state["level"])
        return "auto_search"
    return "agent"


_GRAPH = None


def _graph():
    global _GRAPH
    if _GRAPH is None:
        g = StateGraph(AgentState)
        g.add_node("agent", _agent_node)
        g.add_node("tools", _tools_node)
        g.add_node("auto_search", _auto_search_node)
        g.set_entry_point("agent")
        g.add_conditional_edges("agent", _route_after_agent, {"tools": "tools", END: END})
        g.add_conditional_edges("tools", _route_after_tools, {"auto_search": "auto_search", "agent": "agent"})
        g.add_edge("auto_search", "agent")
        _GRAPH = g.compile()
    return _GRAPH


def run_agent(query: str, profile: UserProfile | dict | None = None) -> RunAgentResult:
    """자연어 쿼리 + (사전파싱) profile → RunAgentResult{reply, meta}. raise 안 함."""
    run_id = uuid.uuid4().hex[:8]
    if isinstance(profile, dict):
        profile = UserProfile(**profile)
    init: AgentState = {
        "run_id": run_id,
        "messages": [HumanMessage(content=query)],
        "profile": profile,
        "current_posting": None,
        "tools_called": [],
        "level": None,
        "step": 0,
    }
    final = _graph().invoke(init, {"recursion_limit": 4 * MAX_STEPS})
    reply = final["messages"][-1].content
    return RunAgentResult(
        reply=reply,
        meta=Meta(tools_called=final["tools_called"], level=final.get("level"), run_id=run_id),
    )
