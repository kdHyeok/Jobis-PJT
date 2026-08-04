package com.jobiss.analysis;

import tools.jackson.databind.JsonNode;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public final class AiContracts {

    private AiContracts() {
    }

    public record AnalysisRequest(
            UUID analysisJobId,
            Posting posting,
            CareerSnapshot career,
            int questionCount,
            List<AnalysisAnswer> answers,
            SharedPostingAnalysis sharedAnalysis
    ) {
    }

    public record SharedPostingAnalysis(
            JobContext job,
            CompetencyProposal competencyProposal
    ) {
    }

    public record AnalysisAnswer(
            String questionKey,
            String questionText,
            String answerValue,
            String answerLabel
    ) {
    }

    public record Posting(
            UUID id,
            String sourceType,
            String sourceUrl,
            String rawText
    ) {
    }

    public record CareerSnapshot(
            UUID graphId,
            long version,
            List<ExistingNode> nodes,
            List<ExistingCareerFragment> fragments,
            CareerGoalContext goals
    ) {
    }

    public record CareerGoalContext(
            UUID currentPostingId,
            String currentCompanyName,
            String currentRoleTitle,
            String finalGoalText
    ) {
    }

    public record ExistingNode(
            UUID id,
            String canonicalKey,
            String title,
            String domain,
            String kind,
            String scopeDefinition,
            int level,
            String progressStatus
    ) {
    }

    public record ExistingCareerFragment(
            UUID id,
            String kind,
            String title,
            String description,
            JsonNode detail
    ) {
    }

    public record AnalysisResponse(
            String status,
            AnalysisQuestion question,
            JobContext job,
            Evaluation evaluation,
            CompetencyProposal competencyProposal
    ) {
    }

    public record AnalysisStageDefinition(
            String id,
            String label,
            String role,
            String message,
            String color
    ) {
    }

    public record AnalysisStageUpdate(
            String id,
            String status,
            String message
    ) {
    }

    public record AnalysisStreamEvent(
            String type,
            UUID runId,
            int sequence,
            OffsetDateTime occurredAt,
            List<AnalysisStageDefinition> stages,
            AnalysisStageUpdate stage,
            AnalysisResponse result,
            String errorCode,
            String errorMessage
    ) {
    }

    public record AnalysisQuestion(
            String key,
            String text,
            String reason,
            List<AnalysisQuestionOption> options
    ) {
    }

    public record AnalysisQuestionOption(
            String value,
            String label,
            String description
    ) {
    }

    public record JobContext(
            String companyName,
            String roleTitle,
            String employmentType,
            String experienceText,
            String primaryTrack,
            ExperienceRequirement experienceRequirement,
            OffsetDateTime closesAt,
            String lifecycleStatus,
            /**
             * URL 공고에서 AI 가 수집한 원문. 원문을 그대로 받은 공고에서는 null.
             *
             * <p>주소만 받은 공고는 {@code job_postings.raw_text} 에 주소가 자리표시로
             * 들어간다(NOT NULL + AI 계약 최소 1자). 이 값으로 되메우지 않으면 채용공고
             * 페이지의 "원문" 칸이 영영 주소로 남는다.
             */
            String sourceText,
            JsonNode parsedData
    ) {
    }

    public record ExperienceRequirement(
            String type,
            int minimumMonths,
            Integer maximumMonths,
            String sourceText
    ) {
    }

    public record Evaluation(
            String verdict,
            String summary,
            List<String> reasons
    ) {
    }

    public record CompetencyProposal(
            List<AnalyzedCompetency> competencies,
            List<AnalyzedRequirement> requirements,
            TargetProjectBrief targetProject
    ) {
    }

    public record AnalyzedCompetency(
            String ref,
            String canonicalKey,
            String title,
            String domain,
            String kind,
            String scopeDefinition,
            String stage,
            int requiredLevel,
            boolean roadmapEligible,
            String verificationMethod
    ) {
    }

    public record AnalyzedRequirement(
            String competencyRef,
            String relation,
            String sourceText,
            BigDecimal confidence
    ) {
    }

    public record TargetProjectBrief(
            String title,
            String objective,
            String domainContext,
            List<String> requiredCompetencyRefs,
            List<String> optionalCompetencyRefs,
            List<String> deliverables,
            List<String> acceptanceCriteria
    ) {
    }

    /*
     * Legacy graph proposal records remain readable while previously stored
     * analyses are retained. New analysis responses use CompetencyProposal
     * and never call the legacy graph merge path.
     */
    public record ChangeProposal(
            long baseGraphVersion,
            List<ProposedNode> nodes,
            List<ProposedEdge> edges,
            List<ProposedRequirement> requirements
    ) {
    }

    public record ProposedNode(
            String ref,
            String action,
            UUID existingNodeId,
            String canonicalKey,
            String title,
            String subtitle,
            String domain,
            String kind,
            String scopeDefinition,
            int level,
            int rank,
            JsonNode detail
    ) {
    }

    public record ProposedEdge(String fromRef, String toRef, String edgeKind) {
    }

    public record ProposedRequirement(
            String nodeRef,
            String kind,
            String sourceText,
            BigDecimal confidence
    ) {
    }

    public record ChatRequest(
            UUID conversationId,
            String displayName,
            List<ChatMessage> messages,
            CareerSummary career
    ) {
    }

    public record ChatMessage(String role, String content) {
    }

    public record CareerSummary(
            List<String> completedNodes,
            List<String> activeGoals,
            List<String> recentPostings,
            List<String> savedEvidence,
            /**
             * 등록된 이력서 원문(최신 우선, 최대 5건).
             *
             * <p>이력서는 이 서비스의 {@code career_sources} 가 진실의 출처다. 전에는 AI 세션
             * 파일에만 남아 있어서, 그 파일이 없으면 사용자가 올린 이력서가 대화에서 사라졌다.
             * 턴마다 실어 보내면 AI 는 저장소를 갖지 않아도 같은 대화를 이어갈 수 있다.
             */
            List<StoredResume> resumes,
            /**
             * 대화로 수집해 적재해 둔 공고 선호({@code user_goal_profiles.chat_preferences}).
             *
             * <p>올려 보내기만 하고 되돌려 주지 않으면 다음 턴이 AI 세션 파일에 의존한다.
             */
            JsonNode preferences,
            /** 사용자가 직접 말한 지속 사실({@code user_goal_profiles.chat_facts}). */
            List<String> facts,
            /**
             * 이 대화에서 다룬 공고들(최신 우선, 최대 5건).
             *
             * <p>{@code parsedData} 가 함께 가면 AI 가 다시 파싱하지 않는다 — 수십 초짜리
             * 파싱을 턴마다 반복하지 않게 하는 것이 이 칸의 목적이다.
             */
            List<StoredPosting> postings,
            /**
             * 도메인 자산이 아닌 잔여 세션 상태({@code agent_session_state.state}).
             *
             * <p>여러 턴에 걸친 약속(예: 자산이 없어 미뤄 둔 요청과 남은 턴 수)이 여기 담긴다 —
             * 대화 이력으로는 복원할 수 없는 값들이라 이 칸이 없으면 AI 가 세션 파일을 들고
             * 있어야 한다.
             */
            JsonNode sessionState,
            /** 여러 턴에 걸친 면접 진행 상태({@code interview_sessions.state}). */
            JsonNode interview
    ) {
    }

    public record StoredPosting(
            UUID id,
            String sourceType,
            String sourceUrl,
            String rawText,
            JsonNode parsedData,
            OffsetDateTime createdAt
    ) {
    }

    public record StoredResume(
            UUID id,
            String title,
            String sourceType,
            String rawText,
            OffsetDateTime createdAt
    ) {
    }

    public record ChatResponse(
            String message,
            String intent,
            boolean shouldRequestPosting,
            List<SuggestedAction> suggestedActions,
            List<ProgressStep> progress,
            List<ReplySource> replySources,
            /**
             * 이 답변이 AI 의 결정론 폴백이면 그 이유, 정상 답변이면 비어 있다.
             *
             * <p>폴백 문장이 그럴듯해 실패가 사용자에게 보이지 않았다 — 요약본을 분석
             * 결과로 읽게 된다. 백엔드는 판정하지 않고 AI 가 준 문구를 그대로 중계한다.
             */
            String degradedReason,
            /**
             * 이 턴에 대화로 확보한 자산 — 없으면 null.
             *
             * <p>AI 세션은 캐시이고 진실의 출처는 이 서비스의 테이블이다. 사용자가 채팅에
             * URL 을 붙이면 AI 는 수집·파싱까지 하는데, 그 결과를 받을 칸이 없어서 대화로
             * 준 공고는 채용공고 페이지에도 커리어지도에도 나타나지 않았다.
             */
            CollectedAssets collected
    ) {
    }

    public record CollectedAssets(
            CollectedPosting posting,
            CollectedResume resume,
            /** 이 턴에 에이전트가 만든 산출물 — V23 테이블들로 적재된다. */
            CollectedOutputs outputs,
            /** 대화로 수집한 공고 선호 — 이번 턴에 바뀐 경우만 온다. 전량 upsert. */
            JsonNode preferences,
            /** 사용자가 직접 말한 지속 사실 — 이번 턴에 늘어난 경우만 온다. 누적 전량. */
            List<String> facts
    ) {
    }

    /**
     * 대화로 확보한 공고. {@code rawText} 는 <b>주소가 아니라 원문</b>이다 — URL 로 받았으면
     * AI 가 수집한 본문이 들어온다.
     */
    public record CollectedPosting(
            String sourceType,
            String sourceUrl,
            String rawText
    ) {
    }

    public record CollectedResume(
            String sourceType,
            String title,
            String rawText
    ) {
    }

    /**
     * 대화가 만든 산출물. 전부 nullable — 그 턴에 만들어진 것만 온다.
     *
     * <p>전에는 이 값들이 AI 세션 파일에만 남아 있었다. 대화가 만든 것이 이 서비스의
     * 테이블에 남아야 화면·재개·통계가 성립한다.
     */
    public record CollectedOutputs(
            JsonNode analysis,
            JsonNode roadmap,
            JsonNode judgmentSummary,
            JsonNode profile,
            JsonNode recommendations,
            JsonNode coverletter,
            JsonNode interview,
            JsonNode applicationPlan,
            Integer preparationPeriodWeeks,
            Integer availableHoursPerWeek,
            JsonNode sessionState,
            /**
             * 대화가 쌓은 자산으로 만든 <b>지도 재료</b>.
             *
             * <p>전에는 이 재료를 만들 수 있는 곳이 공고 분석 작업 하나였고, 그 경로는 대화로
             * 모인 자산(선호·이력서 라이브러리)을 보지 못했다. 이 값이 오면 같은 공고의 공용
             * 분석으로 저장되고, 그 공고의 분석 작업이 <b>기존 재사용 경로</b>로 집어 적재한다 —
             * 적재 코드를 복제하지 않는다(writer 는 하나여야 한다).
             */
            CompetencyProposal competencyProposal,
            /**
             * 지도 재료의 짝 — 공고 맥락(경력 관문·트랙·마감). 공용 분석 캐시의 {@code job}
             * 칸을 이걸로 채운다. 없던 시절에는 아직 파싱 전인 {@code job_postings} 열로
             * 지어냈는데 {@code experienceRequirement}·{@code primaryTrack} 이 비어
             * 재사용 경로가 NPE 로 죽었다(실측 08-04).
             */
            JobContext jobContext
    ) {
    }

    /**
     * 최종 답변의 문장별 화자 — 어느 에이전트가 어느 채널로 쓴 문장인가.
     *
     * <p>AI 는 이 값을 전부터 보내고 있었지만 받을 칸이 없어 Jackson 이 버렸다. 대화창에서
     * 에이전트별로 말풍선을 나누는 근거가 이것이다 — 없으면 여러 담당이 만든 답변이
     * 화자 없는 한 덩어리로 합쳐진다.
     *
     * <p>{@code agent} 는 화면이 색·로고를 고르는 키이므로 문구가 아니라 키를 그대로 옮긴다.
     */
    public record ReplySource(String agent, String channel, String text) {
    }

    /**
     * 대화 한 턴에서 어떤 에이전트·도구가 무엇을 했는지.
     *
     * <p>AI 서버는 이 값을 전부터 보내고 있었지만 이 레코드에 받을 칸이 없어 Jackson 이
     * 조용히 버렸다. 공고를 채팅에 붙여넣는 흐름에서는 분석 작업(analysis job)이 생기지
     * 않으므로 진행 휠도 없다 — 그 경로에서 "어느 담당이 무슨 도구로 무엇을 하는지"를
     * 보여줄 유일한 통로가 이것이다.
     *
     * <p>{@code agent} 는 화자 키(에이전트 이름 또는 {@code orchestrator}) — 화면이 이 키로
     * 에이전트별 색·로고를 고른다. {@code step} 은 집계용 키(예:
     * {@code loop:coverletter_draft}), {@code label} 은 사람이 읽는 담당 이름,
     * {@code detail} 은 도구 호출·관찰 문구다.
     */
    public record ProgressStep(
            String agent,
            String step,
            String label,
            String detail,
            long elapsedMs,
            /**
             * 담당이 완성한 <b>사용자향 발화 본문</b>(D153) — 과정 라벨(detail)과 달리 내용이다.
             * 대화창이 담당 말풍선을 실시간으로 그리는 재료. 발화가 없는 단계는 빈 문자열.
             */
            String message
    ) {
    }

    public record SuggestedAction(String action, String label) {
    }

    public record EvidenceVerificationRequest(
            EvidencePayload evidence,
            EvidenceNode node
    ) {
    }

    public record EvidencePayload(
            UUID id,
            String evidenceType,
            String title,
            String sourceUrl,
            JsonNode content
    ) {
    }

    public record EvidenceNode(
            UUID id,
            String title,
            String domain,
            String kind,
            String scopeDefinition,
            int level
    ) {
    }

    public record EvidenceVerificationResponse(
            String verdict,
            BigDecimal confidence,
            String summary,
            List<String> strengths,
            List<String> gaps,
            List<String> nextActions
    ) {
    }

    public record CompetencyAssessmentRequest(
            UUID sessionId,
            AssessmentCompetency competency,
            AssessmentTargetContext target,
            List<AssessmentTurn> turns,
            Map<String, Integer> retainedScores,
            String requiredQuestionKind
    ) {
    }

    public record AssessmentCompetency(
            String canonicalKey,
            String title,
            String domain,
            String scopeDefinition,
            int requiredLevel,
            JsonNode levelDefinition,
            JsonNode assessmentBlueprint
    ) {
    }

    public record AssessmentTargetContext(
            String companyName,
            String roleTitle,
            String primaryTrack,
            String domainContext,
            String requirementSource,
            String currentGoal,
            String finalGoal
    ) {
    }

    public record AssessmentTurn(
            int ordinal,
            String questionKind,
            String prompt,
            String codeSnippet,
            String answerText,
            Integer score,
            String feedback
    ) {
    }

    public record CompetencyAssessmentResponse(
            AssessmentAnswerEvaluation answerEvaluation,
            AssessmentQuestion nextQuestion,
            String sessionSummary,
            List<String> strengths,
            List<String> gaps,
            List<String> nextActions
    ) {
    }

    public record AssessmentAnswerEvaluation(
            int score,
            String verdict,
            String feedback,
            List<String> coveredCriteria,
            List<String> gaps,
            List<String> futureExtensions
    ) {
    }

    public record AssessmentQuestion(
            String kind,
            String prompt,
            String codeSnippet,
            List<String> coreCriteria,
            List<String> futureExtensions
    ) {
    }

    public record CareerExtractionRequest(
            UUID sourceId,
            String sourceType,
            String title,
            String sourceUrl,
            String rawText
    ) {
    }

    public record CareerFragmentSuggestion(
            String kind,
            String title,
            String description,
            String canonicalKey,
            JsonNode detail
    ) {
    }

    public record CareerExtractionResponse(
            String summary,
            List<CareerFragmentSuggestion> fragments
    ) {
    }
}
