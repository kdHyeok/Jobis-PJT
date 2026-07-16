package com.jobiss.backend.domain;

/** 분석을 수행한 엔진. mock -> agent(가짜 AI, WebSocket) -> ai(진짜) 로 교체된다. */
public enum AnalysisEngine {
    MOCK, RULE, AI, AGENT
}
