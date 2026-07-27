package com.jobiss.backend.service;

import com.jobiss.backend.domain.AnalysisRun;

import java.util.List;

/**
 * 분석 "두뇌"의 계약. 구현체를 Mock -> Rule -> AI(Python 호출) 로 교체한다.
 * 백엔드의 나머지 코드는 이 인터페이스에만 의존하므로 교체해도 안 흔들린다.
 */
public interface AnalysisEngineService {

    /** 이 Run에 대해 사용자에게 물을 추가 질문들. */
    List<QuestionSpec> generateQuestions(AnalysisRun run);

    /** 최종 분석 결과(§B 계약) JSON 문자열. */
    String generateResult(AnalysisRun run);
}
