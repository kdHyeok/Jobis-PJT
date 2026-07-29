package com.jobiss.backend.service.agent;

import com.jobiss.backend.domain.AnalysisEngine;
import com.jobiss.backend.domain.AnalysisRun;
import com.jobiss.backend.domain.Evidence;
import com.jobiss.backend.domain.JobPosting;
import com.jobiss.backend.domain.JobSourceType;
import com.jobiss.backend.domain.RunStatus;
import com.jobiss.backend.domain.User;
import com.jobiss.backend.dto.analysis.CustomAnalysisRequest;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.AnalysisRunRepository;
import com.jobiss.backend.repository.EvidenceRepository;
import com.jobiss.backend.repository.JobPostingRepository;
import com.jobiss.backend.repository.UserRepository;
import com.jobiss.backend.service.ConversationService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 가짜 AI 에이전트 기반 분석을 시작한다.
 * Run 생성(engine=AGENT, ANALYZING) → START 메시지 구성 → FakeAgentClient 세션 시작.
 * 이후 진행/질문/완료는 WebSocket 콜백에서 처리되고 브라우저로 중계된다.
 */
@Service
public class AgentRunService {

    private final UserRepository userRepository;
    private final JobPostingRepository jobPostingRepository;
    private final EvidenceRepository evidenceRepository;
    private final AnalysisRunRepository runRepository;
    private final FakeAgentClient agentClient;
    private final ConversationService conversationService;
    private final ObjectMapper om;

    public AgentRunService(UserRepository userRepository, JobPostingRepository jobPostingRepository,
                           EvidenceRepository evidenceRepository, AnalysisRunRepository runRepository,
                           FakeAgentClient agentClient, ConversationService conversationService,
                           ObjectMapper om) {
        this.userRepository = userRepository;
        this.jobPostingRepository = jobPostingRepository;
        this.evidenceRepository = evidenceRepository;
        this.runRepository = runRepository;
        this.agentClient = agentClient;
        this.conversationService = conversationService;
        this.om = om;
    }

    /** 로그인한 사용자(userId)로 (샘플)공고 분석: 생성 후 즉시 시작(개발/데모 경로). */
    @Transactional
    public String startAgentRun(Long userId, String jobPostingCode, List<Long> evidenceIds) {
        User user = findUser(userId);
        JobPosting job = jobPostingRepository.findByCode(jobPostingCode)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "JOB_NOT_FOUND", "공고를 찾을 수 없습니다."));
        AnalysisRun run = createRun(user, job, evidenceIds, null);
        beginNow(run);
        return run.getAnalysisId();
    }

    /**
     * 자유 입력 공고로 분석 준비. 웹은 파싱하지 않고 원문(content)만 담아 JobPosting/Run만 만든다.
     * 실제 AI 세션은 브라우저가 구독을 마친 뒤 beginSession()으로 시작한다(JOB_CONTEXT 등 초기 신호 유실 방지).
     */
    @Transactional
    public Map<String, String> createCustomRun(Long userId, CustomAnalysisRequest req) {
        User user = findUser(userId);
        JobPosting job = jobPostingRepository.save(JobPosting.builder()
                .user(user)
                .sourceType(mapSource(req.sourceType()))
                .rawText(req.content())          // 원문 그대로 (파싱은 AI 몫)
                .build());
        AnalysisRun run = createRun(user, job, req.evidenceIds(), req.parentAnalysisId());
        // 분석은 언제나 어떤 대화 안에서 일어난다. 대화 밖(새 분석 화면)에서 시작했으면 대화를 만들어 담는다.
        var conversation = conversationService.attachAnalysis(
                userId, req.conversationId(), run.getAnalysisId(), conversationTitle(req.content()));
        run.attachConversation(conversation);
        // 화면이 그 대화로 자리를 옮길 수 있게 id를 함께 돌려준다
        return Map.of("analysisId", run.getAnalysisId(),
                "conversationId", conversation.getConversationId());
    }

    /** 대화 밖에서 시작한 분석의 대화 제목 — 아직 회사·직무를 모르므로 원문 앞머리로 둔다. */
    private static String conversationTitle(String content) {
        String t = content == null ? "" : content.replaceAll("\\s+", " ").trim();
        if (t.isEmpty()) return "새 분석";
        return "공고 분석 · " + (t.length() > 40 ? t.substring(0, 40) : t);
    }

    /** 브라우저가 구독을 마친 뒤 호출. 소유권 확인 후 AI 세션 시작(멱등: FakeAgentClient가 중복 방어). */
    @Transactional
    public void beginSession(Long userId, String analysisId) {
        AnalysisRun run = runRepository.findByAnalysisId(analysisId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "분석을 찾을 수 없습니다."));
        if (!run.getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "이 분석에 대한 권한이 없습니다.");
        }
        beginNow(run);
    }

    /** 자료 검증 → Run 생성(세션은 시작하지 않음). parentAnalysisId = 대체 재분석이면 원래 분석 id. */
    private AnalysisRun createRun(User user, JobPosting job, List<Long> evidenceIds, String parentAnalysisId) {
        List<Evidence> evidences;
        if (evidenceIds != null && !evidenceIds.isEmpty()) {
            evidences = evidenceRepository.findAllById(evidenceIds);
            boolean valid = evidences.size() == evidenceIds.size()
                    && evidences.stream().allMatch(e -> e.getUser().getId().equals(user.getId()));
            if (!valid) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_EVIDENCE", "선택한 자료가 올바르지 않습니다.");
            }
        } else {
            evidences = evidenceRepository.findByUserId(user.getId());
        }

        AnalysisRun run = AnalysisRun.builder()
                .analysisId(UUID.randomUUID().toString())
                .user(user)
                .jobPosting(job)
                .status(RunStatus.ANALYZING)
                .engine(AnalysisEngine.AGENT)
                .evidences(new HashSet<>(evidences))
                .parentAnalysisId(parentAnalysisId)
                .build();
        return runRepository.save(run);
    }

    /** Run의 공고·자료로 START를 구성해 AI 세션을 연다. */
    private void beginNow(AnalysisRun run) {
        List<Evidence> evidences = new ArrayList<>(run.getEvidences());
        String startJson = buildStartJson(run.getAnalysisId(), run.getJobPosting(), evidences);
        agentClient.startSession(run.getAnalysisId(), startJson);
    }

    private User findUser(Long userId) {
        return userRepository.findById(userId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다."));
    }

    private static JobSourceType mapSource(String s) {
        if (s == null) return JobSourceType.RAW;
        return switch (s.trim().toUpperCase()) {
            case "URL" -> JobSourceType.URL;
            case "FILE" -> JobSourceType.FILE;
            default -> JobSourceType.RAW;   // TEXT/RAW/그 외
        };
    }

    /** 개발용(인증 없이): 데모 사용자로 시작. DevController가 사용. */
    @Transactional
    public String startDemoRun(String jobPostingCode, List<Long> evidenceIds) {
        User demo = userRepository.findByEmail("junyoung.park@gmail.com")
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "NO_DEMO_USER", "데모 사용자가 없습니다."));
        return startAgentRun(demo.getId(), jobPostingCode, evidenceIds);
    }

    private String buildStartJson(String analysisId, JobPosting job, List<Evidence> evidences) {
        Map<String, Object> jp = new LinkedHashMap<>();
        jp.put("company", job.getCompany());
        jp.put("role", job.getRole());
        jp.put("career", job.getCareer());
        jp.put("rawText", job.getRawText());

        List<Map<String, Object>> evs = evidences.stream().map(e -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("kind", e.getKind().name());
            m.put("label", e.getLabel());
            m.put("description", e.getDescription());
            return m;
        }).toList();

        Map<String, Object> start = new LinkedHashMap<>();
        start.put("type", "START");
        start.put("analysisId", analysisId);
        start.put("jobPosting", jp);
        start.put("evidences", evs);
        return om.writeValueAsString(start);
    }
}
