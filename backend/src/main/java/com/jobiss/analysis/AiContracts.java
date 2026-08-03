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
            List<String> savedEvidence
    ) {
    }

    public record ChatResponse(
            String message,
            String intent,
            boolean shouldRequestPosting,
            List<SuggestedAction> suggestedActions
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
