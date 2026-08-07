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

    public record PostingImportRequest(String sourceUrl) {
    }

    public record PostingImportWarning(String code, String message) {
    }

    public record PostingImportResponse(
            String finalUrl,
            String rawText,
            List<PostingImportWarning> warnings
    ) {
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
            String answerLabel,
            String inputType,
            String answerStatus,
            List<String> relatedRequirementIds,
            String absenceScope
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
            String inputType,
            List<AnalysisQuestionOption> options,
            List<String> relatedRequirementIds,
            String absenceScope
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
            CareerSummary career,
            ChatTaskContext task,
            JsonNode workspaceState
    ) {
        public ChatRequest(
                UUID conversationId,
                String displayName,
                List<ChatMessage> messages,
                CareerSummary career
        ) {
            this(
                    conversationId,
                    displayName,
                    messages,
                    career,
                    new ChatTaskContext("AUTO", List.of(), List.of()),
                    null
            );
        }
    }

    public record ChatMessage(String role, String content) {
    }

    public record CareerSummary(
            List<String> completedNodes,
            List<String> activeGoals,
            List<String> recentPostings,
            List<String> savedEvidence,
            List<StoredResume> resumes,
            List<StoredPosting> postings,
            JsonNode roadmap,
            JsonNode preferences,
            JsonNode facts,
            Integer preparationPeriodWeeks,
            Integer availableHoursPerWeek
    ) {
        // 확정 항목만 있고 수집 자산·선호·기간이 아직 없는 요약. ChatRequest와 같은 방식으로
        // 좁은 생성자를 함께 둬서, 계약이 넓어질 때 이 형태를 쓰는 호출부가 깨지지 않게 한다.
        // 없는 값은 빈 목록과 null로 명시한다 — 지어낸 기본값을 채우지 않는다.
        public CareerSummary(
                List<String> completedNodes,
                List<String> activeGoals,
                List<String> recentPostings,
                List<String> savedEvidence
        ) {
            this(
                    completedNodes,
                    activeGoals,
                    recentPostings,
                    savedEvidence,
                    List.of(),
                    List.of(),
                    null,
                    null,
                    null,
                    null,
                    null
            );
        }
    }

    public record StoredResume(
            UUID id,
            String title,
            String sourceType,
            String rawText,
            OffsetDateTime createdAt
    ) {
    }

    public record StoredPosting(
            UUID id,
            String sourceType,
            String sourceUrl,
            String rawText,
            JsonNode parsedData,
            JsonNode structuredPosting,
            OffsetDateTime createdAt
    ) {
    }

    public record ChatTaskContext(
            String mode,
            List<ChatPostingAsset> postings,
            List<ChatCareerSourceAsset> careerSources
    ) {
    }

    public record ChatPostingAsset(
            UUID id,
            String companyName,
            String roleTitle,
            String sourceUrl,
            String experienceText,
            String lifecycleStatus,
            String rawText,
            String analysisSummary
    ) {
    }

    public record ChatCareerSourceAsset(
            UUID id,
            String sourceType,
            String title,
            String sourceUrl,
            String summary,
            String rawText,
            List<ChatCareerFragment> fragments
    ) {
    }

    public record ChatCareerFragment(
            String kind,
            String title,
            String description
    ) {
    }

    public record ChatResponse(
            String message,
            String intent,
            boolean shouldRequestPosting,
            List<SuggestedAction> suggestedActions,
            List<ChatReplySource> replySources,
            List<AgentProgress> progress,
            List<ProposedAgentAction> proposedActions,
            PendingConfirmation pendingConfirmation,
            ChatArtifact artifact,
            ChatAgentPlan plan,
            BigDecimal confidence,
            String detailedStatus,
            List<ChatAgentWorkProduct> workProducts,
            List<ChatAgentWarning> warnings,
            List<ChatReplyAttribution> replyAttributions,
            JsonNode workspaceState,
            JsonNode collected
    ) {
    }

    public record ChatStreamEvent(
            String type,
            int sequence,
            OffsetDateTime occurredAt,
            String agentId,
            String label,
            String status,
            String message,
            ChatResponse result,
            ChatAgentPlan plan,
            String errorCode,
            String errorMessage
    ) {
    }

    public record SuggestedAction(String action, String label) {
    }

    public record ChatReplySource(
            String sourceType,
            UUID sourceId,
            String title,
            String excerpt
    ) {
    }

    public record AgentProgress(
            String agentId,
            String label,
            String status,
            String message
    ) {
    }

    public record ProposedAgentAction(
            String actionId,
            String actionType,
            String label,
            String description,
            boolean requiresConsent,
            JsonNode payload
    ) {
    }

    public record PendingConfirmation(
            String question,
            String reason,
            List<String> options
    ) {
    }

    public record ChatArtifact(
            String artifactType,
            String title,
            String summary,
            List<Map<String, Object>> sections
    ) {
    }

    public record ChatAgentPlan(
            String intent,
            BigDecimal confidence,
            List<PlannedChatAgent> agents,
            List<ChatPlanEdge> edges,
            List<UUID> selectedPostingIds,
            List<UUID> selectedCareerSourceIds,
            PendingConfirmation pendingConfirmation,
            boolean updatedDuringRun
    ) {
    }

    public record PlannedChatAgent(
            String runId,
            String agentId,
            String label,
            int groupIndex,
            int orderIndex,
            String reason,
            String status
    ) {
    }

    public record ChatPlanEdge(String fromRunId, String toRunId) {
    }

    public record ChatAgentWorkProduct(
            String agentId,
            String productType,
            String title,
            String reply,
            String summary,
            List<String> findings,
            List<String> recommendations,
            List<String> followUpQuestions,
            List<ChatReplySource> replySources,
            List<SuggestedAction> suggestedActions,
            List<ProposedAgentAction> proposedActions,
            PendingConfirmation pendingConfirmation,
            ChatArtifact artifact,
            JsonNode data
    ) {
    }

    public record ChatAgentWarning(
            String code,
            String message,
            String agentId,
            boolean recoverable
    ) {
    }

    public record ChatReplyAttribution(
            String agentId,
            String channel,
            String text
    ) {
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

    public record CompetencyLearningRequest(
            AssessmentCompetency competency,
            AssessmentTargetContext target
    ) {
    }

    public record CompetencyLearningResponse(
            String title,
            String summary,
            String scopeReminder,
            String targetContext,
            List<LearningModule> modules,
            List<String> recommendedResources,
            List<String> assessmentReadiness
    ) {
    }

    public record LearningModule(
            String title,
            String objective,
            List<String> concepts,
            String example,
            String practice,
            List<String> completionCriteria
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
