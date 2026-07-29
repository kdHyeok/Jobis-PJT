package com.jobiss.backend.service;

import com.jobiss.backend.domain.AnalysisAnswer;
import com.jobiss.backend.domain.AnalysisEngine;
import com.jobiss.backend.domain.AnalysisQuestion;
import com.jobiss.backend.domain.AnalysisResult;
import com.jobiss.backend.domain.AnalysisRun;
import com.jobiss.backend.domain.Evidence;
import com.jobiss.backend.domain.JobPosting;
import com.jobiss.backend.domain.RunStatus;
import com.jobiss.backend.domain.User;
import com.jobiss.backend.dto.analysis.AnalysisCreateRequest;
import com.jobiss.backend.dto.analysis.AnalysisStatusResponse;
import com.jobiss.backend.dto.analysis.AnalysisSummaryResponse;
import com.jobiss.backend.dto.analysis.AnswersRequest;
import com.jobiss.backend.dto.analysis.JobPostingBrief;
import com.jobiss.backend.dto.analysis.QuestionResponse;
import com.jobiss.backend.dto.analysis.ResultResponse;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.AnalysisAnswerRepository;
import com.jobiss.backend.repository.AnalysisQuestionRepository;
import com.jobiss.backend.repository.AnalysisResultRepository;
import com.jobiss.backend.repository.AnalysisRunRepository;
import com.jobiss.backend.repository.EvidenceRepository;
import com.jobiss.backend.repository.JobPostingRepository;
import com.jobiss.backend.repository.UserRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashSet;
import java.util.List;
import java.util.UUID;

@Service
public class AnalysisService {

    private final AnalysisRunRepository runRepository;
    private final JobPostingRepository jobPostingRepository;
    private final EvidenceRepository evidenceRepository;
    private final UserRepository userRepository;
    private final AnalysisQuestionRepository questionRepository;
    private final AnalysisAnswerRepository answerRepository;
    private final AnalysisResultRepository resultRepository;
    private final AnalysisEngineService engine;

    public AnalysisService(AnalysisRunRepository runRepository, JobPostingRepository jobPostingRepository,
                           EvidenceRepository evidenceRepository, UserRepository userRepository,
                           AnalysisQuestionRepository questionRepository, AnalysisAnswerRepository answerRepository,
                           AnalysisResultRepository resultRepository, AnalysisEngineService engine) {
        this.runRepository = runRepository;
        this.jobPostingRepository = jobPostingRepository;
        this.evidenceRepository = evidenceRepository;
        this.userRepository = userRepository;
        this.questionRepository = questionRepository;
        this.answerRepository = answerRepository;
        this.resultRepository = resultRepository;
        this.engine = engine;
    }

    /** 분석 시작: Run 생성 → (Mock) 질문 생성 → AWAITING_ANSWERS. */
    @Transactional
    public AnalysisStatusResponse createAnalysis(Long userId, AnalysisCreateRequest req) {
        JobPosting job = jobPostingRepository.findByCode(req.jobPostingCode())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "JOB_NOT_FOUND", "공고를 찾을 수 없습니다."));

        List<Evidence> evidences = evidenceRepository.findAllById(req.evidenceIds());
        boolean valid = evidences.size() == req.evidenceIds().size()
                && evidences.stream().allMatch(e -> e.getUser().getId().equals(userId));
        if (!valid) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_EVIDENCE", "선택한 자료가 올바르지 않습니다.");
        }

        User userRef = userRepository.getReferenceById(userId);
        AnalysisRun run = AnalysisRun.builder()
                .analysisId(UUID.randomUUID().toString())
                .user(userRef)
                .jobPosting(job)
                .status(RunStatus.ANALYZING)
                .engine(AnalysisEngine.MOCK)
                .evidences(new HashSet<>(evidences))
                .build();
        runRepository.save(run);

        // Mock: 질문을 즉시 생성하고 답변 대기 상태로.
        for (QuestionSpec spec : engine.generateQuestions(run)) {
            questionRepository.save(AnalysisQuestion.builder()
                    .run(run).seq(spec.seq()).field(spec.field()).title(spec.title())
                    .why(spec.why()).defaultAnswer(spec.defaultAnswer()).effect(spec.effect())
                    .build());
        }
        run.changeStatus(RunStatus.AWAITING_ANSWERS);

        return new AnalysisStatusResponse(run.getAnalysisId(), run.getStatus().name(),
                JobPostingBrief.from(job), "확인 질문이 준비되었습니다.", null, null, null);
    }

    @Transactional(readOnly = true)
    public AnalysisStatusResponse getStatus(Long userId, String analysisId) {
        AnalysisRun run = getOwnedRun(userId, analysisId);
        String parentId = run.getParentAnalysisId();
        String parentLabel = (parentId == null) ? null : runRepository.findByAnalysisId(parentId)
                .map(p -> {
                    JobPosting j = p.getJobPosting();
                    String c = j.getCompany() == null ? "" : j.getCompany();
                    String r = j.getRole() == null ? "" : j.getRole();
                    String label = (c + (r.isBlank() ? "" : " · " + r)).trim();
                    return label.isBlank() ? null : label;
                }).orElse(null);
        return new AnalysisStatusResponse(analysisId, run.getStatus().name(),
                JobPostingBrief.from(run.getJobPosting()), null, parentId, parentLabel, run.getSelectedRoute());
    }

    /** 경로 비교에서 주 경로 선택 저장(스펙 §11.3). 재선택 가능. */
    @Transactional
    public void selectRoute(Long userId, String analysisId, String routeId) {
        AnalysisRun run = getOwnedRun(userId, analysisId);
        String rid = (routeId != null && routeId.length() > 40) ? routeId.substring(0, 40) : routeId;
        run.selectRoute(rid);
    }

    @Transactional(readOnly = true)
    public List<QuestionResponse> getQuestions(Long userId, String analysisId) {
        AnalysisRun run = getOwnedRun(userId, analysisId);
        return questionRepository.findByRunIdOrderBySeqAsc(run.getId()).stream()
                .map(QuestionResponse::from)
                .toList();
    }

    /** 답변 제출 → (Mock) 결과 생성 → COMPLETED. */
    @Transactional
    public AnalysisStatusResponse submitAnswers(Long userId, String analysisId, AnswersRequest req) {
        AnalysisRun run = getOwnedRun(userId, analysisId);

        for (AnswersRequest.AnswerItem item : req.answers()) {
            AnalysisQuestion question = questionRepository.findById(item.questionId())
                    .orElseThrow(() -> new ApiException(HttpStatus.BAD_REQUEST, "QUESTION_NOT_FOUND", "질문을 찾을 수 없습니다."));
            if (!question.getRun().getId().equals(run.getId())) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "QUESTION_MISMATCH", "질문이 이 분석에 속하지 않습니다.");
            }
            if (answerRepository.existsByQuestionId(question.getId())) {
                continue; // 이미 답한 질문은 건너뜀
            }
            answerRepository.save(AnalysisAnswer.builder()
                    .run(run).question(question).answerText(item.answer()).build());
        }

        run.changeStatus(RunStatus.FINALIZING);
        String resultJson = engine.generateResult(run);
        resultRepository.save(AnalysisResult.builder().run(run).result(resultJson).build());
        run.changeStatus(RunStatus.COMPLETED);

        return new AnalysisStatusResponse(analysisId, run.getStatus().name(),
                JobPostingBrief.from(run.getJobPosting()), null, null, null, null);
    }

    @Transactional(readOnly = true)
    public ResultResponse getResult(Long userId, String analysisId) {
        AnalysisRun run = getOwnedRun(userId, analysisId);
        if (run.getStatus() != RunStatus.COMPLETED) {
            throw new ApiException(HttpStatus.CONFLICT, "RESULT_NOT_READY", "결과가 아직 준비되지 않았습니다.");
        }
        AnalysisResult result = resultRepository.findByRunId(run.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RESULT_NOT_FOUND", "결과를 찾을 수 없습니다."));
        return new ResultResponse(JobPostingBrief.from(run.getJobPosting()), result.getResult());
    }

    /** 사이드바 "최근 분석": 내 분석 목록(최신순). */
    @Transactional(readOnly = true)
    public List<AnalysisSummaryResponse> listForUser(Long userId) {
        return runRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
                .map(AnalysisSummaryResponse::from)
                .toList();
    }

    /** analysisId 로 Run 조회 + 소유자 확인(남의 분석 접근 차단). */
    private AnalysisRun getOwnedRun(Long userId, String analysisId) {
        AnalysisRun run = runRepository.findByAnalysisId(analysisId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "분석을 찾을 수 없습니다."));
        if (!run.getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }
        return run;
    }
}
