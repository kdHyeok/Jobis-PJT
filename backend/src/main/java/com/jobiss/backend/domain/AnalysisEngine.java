package com.jobiss.backend.domain;

/**
 * 분석을 수행한 엔진. 지금 실제로 쓰이는 값은 AGENT 하나다 —
 * 진짜 에이전트(웹 브릿지, WebSocket)가 모든 분석을 수행한다.
 * MOCK/RULE/AI 는 과거·향후 값으로 남겨 둔 것이며 새 분석에는 기록되지 않는다.
 */
public enum AnalysisEngine {
    MOCK, RULE, AI, AGENT
}
