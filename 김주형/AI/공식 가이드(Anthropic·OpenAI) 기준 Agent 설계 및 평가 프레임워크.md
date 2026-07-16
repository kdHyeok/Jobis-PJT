# 🤖 공식 가이드(Anthropic·OpenAI) 기준 Agent 설계 및 평가 프레임워크

Anthropic과 OpenAI의 공식 가이드를 바탕으로 정리한 AI Agent 설계 원칙, 평가 프레임워크, 그리고 유용한 레퍼런스 모음입니다.

---

## 🎯 Agent 작동 성공 판정 기준
> "이 Agent가 잘 동작한다"를 체크리스트 3~5개로 선언해야 구체적인 평가 셋을 구성할 수 있습니다.
> 💡 **작성 팁**: 각 항목은 예/아니오(Yes/No)로 대답 가능하도록 명확한 기준으로 작성합니다.

*   [ ] **경로 검증**: "요청 X에 대해 Tool A → Tool B 순서로 호출한다"
*   [ ] **예외 처리**: "Tool 호출 실패 시 재시도 또는 다른 tool로 fallback"
*   [ ] **결과 검증**: "최종 응답에 Tool 결과의 특정 필드가 포함된다"
*   [ ] **효율성**: "6 step 이내에 종료한다" (스텝 갯수 제한)
*   [ ] **일관성**: "같은 요청을 두 번 넣었을 때 경로가 과도하게 달라지지 않는다"

---

## 🔄 워크플로우 패턴 분류 (Non-Agent)
[AnthropicAI Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents) 가이드에서는 경로가 고정된 패턴을 **비-Agent(Workflow) 패턴**으로 분류합니다.(예시 아래)

*   **Prompt chaining**: 단계별 LLM 호출을 직렬로 연결
*   **Routing**: 입력을 분류한 후 전용 핸들러로 분기
*   **Parallelization**: 동일 입력을 여러 LLM에 병렬 처리 후 집계
*   **Orchestrator-workers**: 오케스트레이터가 서브태스크로 분배 (경로 고정)
*   **Evaluator-optimizer**: 생성 → 평가 → 재생성 루프

> ⚠️ **주의 (Orchestrator-workers 설계 방식)**
> *   **Workflow에 가까운 경우**: 오케스트레이터가 항상 고정된 순서와 고정된 역할로 작업을 분배할 때
> *   **Multi-Agent에 가까운 경우**: 요청에 따라 필요한 worker, 작업 순서, 반복 여부가 동적으로 달라질 때

---

## 📚 설계 축별 레퍼런스

| 축 | 레퍼런스 바로가기 |
| :--- | :--- |
| **Tool 설계** | [OpenAI — A Practical Guide to Building Agents (PDF)](https://cookbook.openai.com/examples/practical_guide_to_building_agents) |
| **System prompt** | [Anthropic — Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) |
| **종료 조건·Guardrails** | [OpenAI — A Practical Guide to Building Agents (PDF)](https://cookbook.openai.com/examples/practical_guide_to_building_agents) |
| **Agent 평가 (final/step/trajectory)** | [LangSmith — Agent Evaluation](https://docs.smith.langchain.com/) / [Anthropic — Demystifying evals for AI agents](https://www.anthropic.com/news/evals-for-ai-agents) |

---

## 🛠️ 프레임워크 및 도구 표준

| 프레임워크 | 레퍼런스 바로가기 |
| :--- | :--- |
| **LangChain** | [LangChain Concepts — Agents](https://python.langchain.com/v0.2/docs/concepts/#agents) |
| **LangGraph** | [LangGraph 공식](https://langchain-ai.github.io/langgraph/) |
| **CrewAI** | [CrewAI 공식](https://www.crewai.com/) |
| **AutoGen** | [AutoGen 공식](https://microsoft.github.io/autogen/) |
| **MCP (Tool 연결 표준)** | [MCP 공식](https://modelcontextprotocol.io/introduction) |