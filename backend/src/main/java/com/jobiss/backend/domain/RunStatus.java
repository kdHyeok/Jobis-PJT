package com.jobiss.backend.domain;

/** 분석 실행(Run)의 상태 머신. */
public enum RunStatus {
    PENDING, ANALYZING, AWAITING_ANSWERS, FINALIZING, COMPLETED, FAILED
}
