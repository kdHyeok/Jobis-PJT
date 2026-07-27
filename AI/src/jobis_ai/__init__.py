"""자비스(잡퀘스트) 취업 준비 멀티에이전트 AI 서버.

- LangGraph 오케스트레이터 + 역할별 LangChain 워커 에이전트 구조.
- 이 패키지는 우선 "전체가 도는 뼈대"(스켈레톤)를 제공한다.
  각 에이전트 노드는 현재 mock 데이터를 반환하며, 이후 실제 체인으로 교체한다.

설계 문서: `에이전트 설계/agent_tool_langchain_langgraph_plan.md`
"""

__version__ = "0.1.0"
