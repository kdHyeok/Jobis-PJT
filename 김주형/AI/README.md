# 📁 AI Agent 설계 참고 자료 모음

프로젝트에서 AI Agent를 설계하기 전에 참고할 자료 3종을 정리했습니다. 각 문서의 성격이 달라서 **상황에 맞게 골라 보시면** 됩니다.

---

## 1. `AI Agent 설계 가이드 - 프로젝트 참고 자료.md`
**한 줄 요약:** Agent 개념 자체를 처음부터 이해하기 위한 개론/입문 자료

- **내용:** Tool 개수 권장치, 사용자 시나리오 정의법, Agent vs Workflow 구분법, Anthropic이 제시한 3대 설계 원칙, Agent의 4대 구성요소(LLM/Planning/Tool/Memory)와 각 구성요소가 실제 개발 요소(System prompt, Memory, Tool, MCP)로 어떻게 매칭되는지 정리
- **언제 보면 좋은지:**
  - Agent 개발이 처음이거나, 팀원에게 개념부터 설명해야 할 때
  - "우리 이거 Agent로 만들어야 해, Workflow로 만들어야 해?" 판단이 필요할 때
  - Agent 실패 유형(판단 흐림, 무한 루프 등)의 원인을 축별로 진단하고 싶을 때
- **주요 특징:** 다이어그램(4대 구성요소 구조도) 포함, 개념 → 실제 개발 매칭까지 이어지는 흐름이라 온보딩용으로 적합

---

## 2. `AI AGENT 설계서 구조도.md`
**한 줄 요약:** 실제 Agent를 설계할 때 그대로 채워 쓰는 **템플릿/양식**

- **내용:** 개요·목적 → 사용자 시나리오 → 기능 요구사항 → Agent 패턴 선택 근거 → 동작 명세 → Tool 명세 → 데이터셋 → 성공 판정 기준까지 9개 섹션, 섹션마다 "💡 작성 요령" 포함. 마지막에 제출 전 자가 점검 체크리스트 포함
- **언제 보면 좋은지:**
  - 새 Agent 기획서/설계서를 처음부터 작성해야 할 때 (빈 문서 대신 이 템플릿 채우면 됨)
  - 설계 리뷰나 팀 공유 전에 "빠진 부분 없는지" 체크할 때
  - Tool 명세, 성공 판정 기준처럼 자주 놓치는 항목을 표준화하고 싶을 때
- **주요 특징:** *AI Agent Engineering* 도서를 참고해 작성한 실전형 템플릿이라, 이론이 아니라 바로 실무에 채워 넣을 수 있는 형태

---

## 3. `공식 가이드(Anthropic·OpenAI) 기준 Agent 설계 및 평가 프레임워크.md`
**한 줄 요약:** Anthropic·OpenAI **공식 문서 기반**의 평가 기준 + 레퍼런스 링크 모음

- **내용:** Agent 성공 판정 체크리스트, Workflow 패턴 5가지 분류(Prompt chaining, Routing, Parallelization, Orchestrator-workers, Evaluator-optimizer), Orchestrator-workers가 Workflow인지 Multi-Agent인지 구분하는 기준, 설계 축별(Tool/System prompt/종료조건/평가) 공식 레퍼런스 링크, 주요 프레임워크(LangChain, LangGraph, CrewAI, AutoGen, MCP) 공식 링크 표
- **언제 보면 좋은지:**
  - 우리 설계가 "이게 진짜 Agent가 맞나, Workflow인가"를 공식 기준으로 재확인하고 싶을 때
  - 평가 프레임워크나 특정 개념(예: Orchestrator-workers)의 1차 출처를 찾아야 할 때
  - 프레임워크(LangChain vs LangGraph vs CrewAI 등) 선택을 위해 공식 문서를 빠르게 찾아봐야 할 때
- **주요 특징:** 출처가 전부 Anthropic·OpenAI 공식 문서(Building Effective Agents, Practical Guide to Building Agents 등)라 신뢰도 있는 근거 자료로 인용하기 좋음

---

## 💡 요약: 상황별 추천

| 상황 | 참고 문서 |
|---|---|
| Agent 개념이 처음, 팀 온보딩 | 1번 (설계 가이드) |
| 실제 설계서 작성 시작 | 2번 (설계서 템플릿) |
| 공식 근거·출처 필요, 평가 기준 확인 | 3번 (공식 가이드 정리) |

세 문서를 순서대로 읽으면 **"개념 이해 → 설계서 작성 → 공식 기준으로 검증"** 흐름이 됩니다.