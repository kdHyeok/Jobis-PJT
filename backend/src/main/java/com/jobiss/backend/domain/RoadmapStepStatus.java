package com.jobiss.backend.domain;

/**
 * 로드맵 스텝 진행 상태.
 * VERIFIED   = 제출한 산출물에서 이 스텝의 요건 증거를 확인함(요건 매트릭스 → 확인).
 * NEEDS_WORK = 제출은 됐으나 요건 증거가 약해 보완이 필요함(요건 매트릭스 → 부분).
 * (제출 전 = 행 없음 = 미확인)
 */
public enum RoadmapStepStatus {
    VERIFIED, NEEDS_WORK
}
