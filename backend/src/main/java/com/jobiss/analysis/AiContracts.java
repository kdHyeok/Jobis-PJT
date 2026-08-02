package com.jobiss.analysis;

import tools.jackson.databind.JsonNode;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

public final class AiContracts {

    private AiContracts() {
    }

    public record AnalysisRequest(
            UUID analysisJobId,
            Posting posting,
            CareerSnapshot career,
            int questionCount,
            List<AnalysisAnswer> answers
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
            List<ExistingCareerFragment> fragments
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
            ChangeProposal changeProposal
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
            JsonNode parsedData
    ) {
    }

    public record Evaluation(
            String verdict,
            String summary,
            List<String> reasons
    ) {
    }

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
            List<SuggestedAction> suggestedActions,
            List<ReplySource> replySources,
            List<ProgressStep> progress
    ) {
    }

    public record SuggestedAction(String action, String label) {
    }

    // message 를 구성한 문장별 화자 — 오라우팅 디버깅용. metadata 로 저장돼 프론트가 배지로 그린다.
    public record ReplySource(String agent, String channel, String text) {
    }

    // 턴 내부 진행 단계(플래너→실행 계획→에이전트별 실행→판정 노드) — 채팅 UI 의 "진행 과정".
    public record ProgressStep(String step, String label, String detail, Integer elapsedMs) {
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
