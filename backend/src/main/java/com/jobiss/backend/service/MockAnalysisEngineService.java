package com.jobiss.backend.service;

import com.jobiss.backend.domain.AnalysisRun;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * Mock 분석 엔진. AI 없이 고정된 질문 3개와 고정 결과(§B, cloudwave)를 반환한다.
 * 나중에 RuleBased / Ai(Python HTTP) 구현체로 교체 예정.
 */
@Service
public class MockAnalysisEngineService implements AnalysisEngineService {

    private final String resultJson;

    public MockAnalysisEngineService(@Value("classpath:mock/cloudwave-result.json") Resource resultResource) {
        try (InputStream in = resultResource.getInputStream()) {
            this.resultJson = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("mock 결과 JSON을 읽을 수 없습니다.", e);
        }
    }

    @Override
    public List<QuestionSpec> generateQuestions(AnalysisRun run) {
        return List.of(
                new QuestionSpec(1, "project_role",
                        "이 프로젝트에서 본인이 맡은 역할은 무엇인가요?",
                        "공고의 협업 경험 항목은 역할·의사결정 근거가 있어야 판정할 수 있습니다.",
                        "4인 팀에서 백엔드 파트를 맡아 게시판 API 설계와 DB 모델링, 코드 리뷰 규칙 정리를 담당했습니다.",
                        "협업 근거 1건 추가"),
                new QuestionSpec(2, "performance_metric",
                        "성능 개선으로 측정 가능한 수치가 있었나요?",
                        "공고 우대사항 \"성능 개선 경험\"은 수치 근거가 있어야 충족으로 판정합니다.",
                        "Postman 기준 목록 API 응답이 1.2초에서 180ms로 줄었고, 쿼리 수는 21개에서 3개가 되었습니다.",
                        "준비도 지표 +4"),
                new QuestionSpec(3, "cert_edu",
                        "배포 경험, 자격증, 교육 이력 중 추가로 입력할 내용이 있나요?",
                        "미입력 항목은 보완 계획 수립에 사용됩니다. 없어도 괜찮습니다.",
                        "자격증은 아직 없고 SSAFY(KDT) 지원을 준비 중입니다. 배포는 로컬 실행까지만 해봤습니다.",
                        "보완 과제 후보 등록")
        );
    }

    @Override
    public String generateResult(AnalysisRun run) {
        return resultJson;
    }
}
