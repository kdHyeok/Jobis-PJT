package com.jobiss.analysis.v3;

import com.jobiss.analysis.AiServiceException;
import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.time.OffsetDateTime;
import java.util.UUID;

@Component
public class V3AnalysisJobProcessor {

    private final RlsTransactionExecutor rls;
    private final V3AnalysisRequestFactory requestFactory;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;

    public V3AnalysisJobProcessor(
            RlsTransactionExecutor rls,
            V3AnalysisRequestFactory requestFactory,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper
    ) {
        this.rls = rls;
        this.requestFactory = requestFactory;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    public boolean supports(UUID userId, UUID analysisJobId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select analysis_provider = 'UNIFIED'
                        from analysis_jobs
                        where id = :analysisJobId
                        """)
                .param("analysisJobId", analysisJobId)
                .query(Boolean.class)
                .optional()
                .orElse(false));
    }

    public void process(UUID userId, UUID analysisJobId, String workerId) {
        V3AnalysisRequestFactory.AnalysisContext context =
                requestFactory.create(userId, analysisJobId);
        boolean ownsStructureLease = prepareSharedStructure(
                userId,
                context,
                workerId
        );
        try {
            int runRevision = beginRun(userId, context, workerId);
            JsonNode result = aiClient.streamCareerPipeline(
                    context.request(),
                    event -> recordProgress(
                            userId,
                            context,
                            workerId,
                            runRevision,
                            event
                    )
            );
            String status = result.path("status").stringValue("");
            if ("AWAITING_CLARIFICATION".equals(status)) {
                pauseForQuestion(
                        userId,
                        context,
                        workerId,
                        runRevision,
                        result,
                        result.path("resolution").path("activeAmbiguity"),
                        false
                );
                return;
            }
            if ("AWAITING_POSTING_CONFIRMATION".equals(status)) {
                pauseForPostingConfirmation(
                        userId,
                        context,
                        workerId,
                        runRevision,
                        result
                );
                return;
            }
            if ("AWAITING_USER_EVIDENCE".equals(status)) {
                pauseForQuestion(
                        userId,
                        context,
                        workerId,
                        runRevision,
                        result,
                        result.path("fit").path("activeAmbiguity"),
                        true
                );
                return;
            }
            if (!"COMPLETED".equals(status)) {
                throw new AiServiceException(
                        "INVALID_AI_RESPONSE",
                        "커리어 분석 결과 상태가 올바르지 않습니다: " + status
                );
            }
            complete(userId, context, workerId, runRevision, result);
        } finally {
            if (ownsStructureLease) {
                releaseStructureLease(userId, context);
            }
        }
    }

    private boolean prepareSharedStructure(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context,
            String workerId
    ) {
        if (context.request().path("structuredPostingCheckpoint").isObject()) {
            return false;
        }
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.MINUTES.toNanos(5);
        boolean waitingMessageWritten = false;
        while (System.nanoTime() < deadline) {
            JsonNode cached = loadSharedStructure(userId, context.snapshotHash());
            if (cached != null) {
                ((ObjectNode) cached).put(
                        "verifiedSnapshotId",
                        context.request().path("verifiedSnapshot")
                                .path("verifiedSnapshotId").stringValue()
                );
                ((ObjectNode) context.request()).set("structuredPostingCheckpoint", cached);
                return false;
            }
            if (tryAcquireStructureLease(userId, context)) {
                return true;
            }
            if (!waitingMessageWritten) {
                rls.write(userId, jdbc -> {
                    jdbc.sql("""
                                    update analysis_jobs
                                    set
                                        stage = 'WAITING_FOR_SHARED_STRUCTURE',
                                        stage_message = '같은 공고의 공용 구조화를 기다리고 있어요'
                                    where id = :jobId
                                      and status = 'RUNNING'
                                      and worker_id = :workerId
                                    """)
                            .param("jobId", context.jobId())
                            .param("workerId", workerId)
                            .update();
                    return null;
                });
                waitingMessageWritten = true;
            }
            try {
                Thread.sleep(1000);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new AiServiceException(
                        "ANALYSIS_CANCELLED",
                        "사용자가 분석을 취소했습니다."
                );
            }
        }
        throw new AiServiceException(
                "SHARED_STRUCTURE_TIMEOUT",
                "같은 공고의 공용 구조화 결과를 기다리는 시간이 초과됐습니다."
        );
    }

    private JsonNode loadSharedStructure(UUID userId, String snapshotHash) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select structured_posting::text
                        from ai_v3_posting_structure_cache
                        where snapshot_hash = :snapshotHash
                          and contract_version = 'jobis.ai.v3alpha1'
                          and invalidated_at is null
                        """)
                .param("snapshotHash", snapshotHash)
                .query(String.class)
                .optional()
                .map(objectMapper::readTree)
                .orElse(null));
    }

    private boolean tryAcquireStructureLease(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context
    ) {
        return rls.write(userId, jdbc -> jdbc.sql("""
                        insert into ai_v3_posting_structure_leases (
                            snapshot_hash, owner_analysis_job_id, lease_until
                        ) values (
                            :snapshotHash, :jobId, now() + interval '5 minutes'
                        )
                        on conflict (snapshot_hash) do update set
                            owner_analysis_job_id = excluded.owner_analysis_job_id,
                            lease_until = excluded.lease_until
                        where ai_v3_posting_structure_leases.lease_until < now()
                        returning owner_analysis_job_id
                        """)
                .param("snapshotHash", context.snapshotHash())
                .param("jobId", context.jobId())
                .query(UUID.class)
                .optional()
                .map(context.jobId()::equals)
                .orElse(false));
    }

    private void releaseStructureLease(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context
    ) {
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            delete from ai_v3_posting_structure_leases
                            where snapshot_hash = :snapshotHash
                              and owner_analysis_job_id = :jobId
                            """)
                    .param("snapshotHash", context.snapshotHash())
                    .param("jobId", context.jobId())
                    .update();
            return null;
        });
    }

    private int beginRun(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context,
            String workerId
    ) {
        return rls.write(userId, jdbc -> {
            requireCurrentWorker(jdbc, context.jobId(), workerId);
            jdbc.sql("delete from analysis_agent_events where analysis_job_id = :jobId")
                    .param("jobId", context.jobId())
                    .update();
            return jdbc.sql("""
                            insert into ai_v3_analysis_runs (
                                analysis_job_id,
                                user_id,
                                source_id,
                                verified_snapshot_id,
                                common_analysis_id,
                                opportunity_id,
                                contract_version,
                                state,
                                based_on_roadmap_version,
                                request_data
                            )
                            values (
                                :jobId,
                                :userId,
                                :sourceId,
                                :snapshotId,
                                :commonAnalysisId,
                                :opportunityId,
                                'jobis.ai.v3alpha1',
                                'RUNNING',
                                :roadmapVersion,
                                cast(:requestData as jsonb)
                            )
                            on conflict (analysis_job_id)
                            do update set
                                run_revision = ai_v3_analysis_runs.run_revision + 1,
                                source_id = excluded.source_id,
                                verified_snapshot_id = excluded.verified_snapshot_id,
                                common_analysis_id = excluded.common_analysis_id,
                                opportunity_id = excluded.opportunity_id,
                                state = 'RUNNING',
                                based_on_roadmap_version = excluded.based_on_roadmap_version,
                                request_data = excluded.request_data,
                                result_data = null,
                                active_ambiguity = null,
                                completed_at = null,
                                updated_at = now()
                            returning run_revision
                            """)
                    .param("jobId", context.jobId())
                    .param("userId", userId)
                    .param("sourceId", context.sourceId())
                    .param("snapshotId", context.verifiedSnapshotId())
                    .param("commonAnalysisId", context.commonAnalysisId())
                    .param("opportunityId", context.opportunityId())
                    .param("roadmapVersion", context.basedOnRoadmapVersion())
                    .param("requestData", writeJson(context.request()))
                    .query(Integer.class)
                    .single();
        });
    }

    private void recordProgress(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context,
            String workerId,
            int runRevision,
            JsonNode event
    ) {
        if (!"PROGRESS".equals(event.path("type").stringValue(""))) {
            return;
        }
        JsonNode progress = event.path("progress");
        int sequence = requiredSequence(event);
        if (!context.jobId().toString().equals(progress.path("jobId").stringValue(""))) {
            throw new AiServiceException(
                    "ANALYSIS_STALE_RESULT",
                    "커리어 분석 진행 이벤트가 다른 작업을 참조합니다."
            );
        }
        rls.write(userId, jdbc -> {
            requireCurrentRun(jdbc, context.jobId(), workerId, runRevision);
            jdbc.sql("""
                            insert into analysis_agent_events (
                                user_id,
                                analysis_job_id,
                                sequence,
                                event_data,
                                occurred_at
                            )
                            values (
                                :userId,
                                :jobId,
                                :sequence,
                                cast(:eventData as jsonb),
                                :occurredAt
                            )
                            on conflict (analysis_job_id, sequence)
                            do nothing
                            """)
                    .param("userId", userId)
                    .param("jobId", context.jobId())
                    .param("sequence", sequence)
                    .param("eventData", writeJson(event))
                    .param("occurredAt", OffsetDateTime.parse(
                            progress.path("occurredAt").stringValue()
                    ))
                    .update();
            String stage = requiredText(progress, "stage");
            String label = requiredText(progress, "label");
            String detail = nullableText(progress, "detail");
            jdbc.sql("""
                            update analysis_jobs
                            set
                                stage = :stage,
                                stage_message = :message,
                                locked_until = now() + interval '15 minutes'
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("stage", stage)
                    .param("message", detail == null ? label : label + " · " + detail)
                    .param("jobId", context.jobId())
                    .param("workerId", workerId)
                    .update();
            return null;
        });
    }

    private void pauseForQuestion(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context,
            String workerId,
            int runRevision,
            JsonNode result,
            JsonNode ambiguity,
            boolean evidenceQuestion
    ) {
        pauseForQuestion(
                userId,
                context,
                workerId,
                runRevision,
                result,
                ambiguity,
                evidenceQuestion,
                null
        );
    }

    private void pauseForPostingConfirmation(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context,
            String workerId,
            int runRevision,
            JsonNode result
    ) {
        JsonNode review = requireObject(result, "postingReview");
        String reviewId = requiredText(review, "reviewId");
        ObjectNode ambiguity = objectMapper.createObjectNode();
        ambiguity.put("ambiguityId", reviewId);
        ambiguity.put("type", "POSTING_CONFIRMATION");
        ambiguity.put(
                "reason",
                "선택한 직무와 경력 기준에 해당하는 공고 범위를 확인한 뒤 프로젝트와 로드맵을 만듭니다."
        );
        ArrayNode candidateIds = ambiguity.putArray("candidateIds");
        candidateIds.add(requiredText(review, "selectedPositionId"));
        ObjectNode question = ambiguity.putObject("question");
        question.put("inputType", "CHOICE");
        question.put("text", "이 내용으로 회사 맞춤 프로젝트와 로드맵을 만들까요?");
        ArrayNode options = question.putArray("options");
        ObjectNode confirm = options.addObject();
        confirm.put("value", "CONFIRM");
        confirm.put("label", "이 내용으로 계속");
        confirm.put("description", "확인한 직무와 경력 범위로 프로젝트 설계를 시작합니다.");
        ObjectNode cancel = options.addObject();
        cancel.put("value", "CANCEL");
        cancel.put("label", "분석 취소");
        cancel.put("description", "현재 분석을 종료하고 공고 목록으로 돌아갑니다.");
        pauseForQuestion(
                userId,
                context,
                workerId,
                runRevision,
                result,
                ambiguity,
                false,
                "AWAITING_POSTING_CONFIRMATION"
        );
    }

    private void pauseForQuestion(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context,
            String workerId,
            int runRevision,
            JsonNode result,
            JsonNode ambiguity,
            boolean evidenceQuestion,
            String stageOverride
    ) {
        if (!ambiguity.isObject() || !ambiguity.path("question").isObject()) {
            throw new AiServiceException(
                    "INVALID_AI_RESPONSE",
                    "커리어 분석 대기 결과에 유효한 추가 질문이 없습니다."
            );
        }
        String ambiguityId = requiredText(ambiguity, "ambiguityId");
        String ambiguityType = requiredText(ambiguity, "type");
        JsonNode question = ambiguity.path("question");
        String inputType = requiredText(question, "inputType");
        if (!inputType.matches("CHOICE|TEXT")) {
            throw new AiServiceException(
                    "INVALID_AI_RESPONSE",
                    "커리어 분석 질문 입력 형식이 올바르지 않습니다."
            );
        }
        ArrayNode options = inputType.equals("TEXT")
                ? objectMapper.createArrayNode()
                : copyOptions(question.path("options"));
        if ("CHOICE".equals(inputType)
                && (options.size() < 2 || options.size() > 12)) {
            throw new AiServiceException(
                    "INVALID_AI_RESPONSE",
                    "커리어 분석 선택 질문은 2개 이상 12개 이하의 선택지가 필요합니다."
            );
        }
        if (context.questionCount() >= 10) {
            throw new AiServiceException(
                    "ANALYSIS_QUESTION_LIMIT",
                    "공고 분석 추가 질문 횟수를 초과했습니다."
            );
        }

        rls.write(userId, jdbc -> {
            requireCurrentRun(jdbc, context.jobId(), workerId, runRevision);
            int ordinal = jdbc.sql("""
                            select coalesce(max(ordinal), 0) + 1
                            from analysis_questions
                            where analysis_job_id = :jobId
                            """)
                    .param("jobId", context.jobId())
                    .query(Integer.class)
                    .single();
            int inserted = jdbc.sql("""
                            insert into analysis_questions (
                                user_id,
                                analysis_job_id,
                                question_key,
                                question_text,
                                reason,
                                input_type,
                                options,
                                ordinal,
                                related_requirement_ids,
                                absence_scope
                            )
                            values (
                                :userId,
                                :jobId,
                                :questionKey,
                                :questionText,
                                :reason,
                                :inputType,
                                cast(:options as jsonb),
                                :ordinal,
                                cast(:relatedRequirementIds as jsonb),
                                :absenceScope
                            )
                            on conflict (analysis_job_id, question_key)
                            do nothing
                            """)
                    .param("userId", userId)
                    .param("jobId", context.jobId())
                    .param("questionKey", ambiguityId)
                    .param("questionText", requiredText(question, "text"))
                    .param("reason", requiredText(ambiguity, "reason"))
                    .param("inputType", inputType)
                    .param("options", writeJson(options))
                    .param("ordinal", ordinal)
                    .param(
                            "relatedRequirementIds",
                            writeJson(arrayOrEmpty(ambiguity.path("candidateIds")))
                    )
                    .param("absenceScope", evidenceQuestion ? "REQUIREMENTS" : "NONE")
                    .update();
            if (inserted == 0) {
                throw new AiServiceException(
                        "AMBIGUITY_UNRESOLVED",
                        "이미 처리한 모호성 질문이 다시 반환되었습니다."
                );
            }
            jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'WAITING_FOR_INPUT',
                                question_count = question_count + 1,
                                stage = :stage,
                                stage_message = :message,
                                result_data = cast(:resultData as jsonb),
                                worker_id = null,
                                locked_until = null
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param(
                            "stage",
                            stageOverride != null
                                    ? stageOverride
                                    : evidenceQuestion
                                            ? "AWAITING_USER_EVIDENCE"
                                            : "AWAITING_CLARIFICATION"
                    )
                    .param("message", requiredText(question, "text"))
                    .param("resultData", writeJson(result))
                    .param("jobId", context.jobId())
                    .param("workerId", workerId)
                    .update();
            jdbc.sql("""
                            update ai_v3_analysis_runs
                            set
                                state = :state,
                                structured_posting = cast(:structuredPosting as jsonb),
                                fit_result = cast(:fitResult as jsonb),
                                result_data = cast(:resultData as jsonb),
                                active_ambiguity = cast(:ambiguity as jsonb),
                                evidence_question_count = evidence_question_count + :evidenceIncrement,
                                updated_at = now()
                            where analysis_job_id = :jobId
                              and run_revision = :runRevision
                            """)
                    .param("state", result.path("status").stringValue())
                    .param("structuredPosting", writeJson(result.path("structuredPosting")))
                    .param(
                            "fitResult",
                            result.path("fit").isObject()
                                    ? writeJson(result.path("fit"))
                                    : null
                    )
                    .param("resultData", writeJson(result))
                    .param("ambiguity", writeJson(ambiguity))
                    .param("evidenceIncrement", evidenceQuestion ? 1 : 0)
                    .param("jobId", context.jobId())
                    .param("runRevision", runRevision)
                    .update();
            storeSharedStructure(
                    jdbc,
                    context.snapshotHash(),
                    result.path("structuredPosting")
            );
            jdbc.sql("select finish_analysis_job(:jobId, :userId)")
                    .param("jobId", context.jobId())
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    private void complete(
            UUID userId,
            V3AnalysisRequestFactory.AnalysisContext context,
            String workerId,
            int runRevision,
            JsonNode result
    ) {
        JsonNode structured = requireObject(result, "structuredPosting");
        JsonNode fit = requireObject(result, "fit");
        JsonNode normalization = requireObject(result, "normalization");
        JsonNode proposal = requireObject(result, "roadmapProposal");
        long basedOnVersion = requiredLong(proposal, "basedOnRoadmapVersion");
        if (basedOnVersion != context.basedOnRoadmapVersion()) {
            throw new AiServiceException(
                    "ANALYSIS_STALE_RESULT",
                    "커리어 그래프 제안의 기준 버전이 현재 요청과 다릅니다."
            );
        }
        String proposalId = requiredText(proposal, "proposalId");
        String selectedPositionId = requiredText(result.path("resolution"), "selectedPositionId");
        JsonNode position = findPosition(structured, selectedPositionId);
        String companyName = structured.path("company").path("displayName")
                .stringValue("확인 필요");
        String roleTitle = position.path("sourceTitle").stringValue(
                structured.path("postingTitle").stringValue("채용 기회")
        );
        JsonNode experience = position.path("experience");

        rls.write(userId, jdbc -> {
            requireCurrentRun(jdbc, context.jobId(), workerId, runRevision);
            jdbc.sql("""
                            update ai_v3_analysis_runs
                            set
                                state = 'COMPLETED',
                                structured_posting = cast(:structuredPosting as jsonb),
                                fit_result = cast(:fitResult as jsonb),
                                normalization_result = cast(:normalizationResult as jsonb),
                                roadmap_proposal = cast(:roadmapProposal as jsonb),
                                result_data = cast(:resultData as jsonb),
                                active_ambiguity = null,
                                completed_at = now(),
                                updated_at = now()
                            where analysis_job_id = :jobId
                              and run_revision = :runRevision
                            """)
                    .param("structuredPosting", writeJson(structured))
                    .param("fitResult", writeJson(fit))
                    .param("normalizationResult", writeJson(normalization))
                    .param("roadmapProposal", writeJson(proposal))
                    .param("resultData", writeJson(result))
                    .param("jobId", context.jobId())
                    .param("runRevision", runRevision)
                    .update();
            storeSharedStructure(jdbc, context.snapshotHash(), structured);
            jdbc.sql("""
                            insert into ai_v3_roadmap_proposals (
                                user_id,
                                analysis_job_id,
                                proposal_id,
                                based_on_roadmap_version,
                                proposed_roadmap_version,
                                status,
                                proposal
                            )
                            values (
                                :userId,
                                :jobId,
                                :proposalId,
                                :basedOnVersion,
                                :proposedVersion,
                                'DRAFT',
                                cast(:proposal as jsonb)
                            )
                            on conflict (analysis_job_id)
                            do update set
                                proposal_id = excluded.proposal_id,
                                based_on_roadmap_version = excluded.based_on_roadmap_version,
                                proposed_roadmap_version = excluded.proposed_roadmap_version,
                                status = 'DRAFT',
                                proposal = excluded.proposal,
                                preview_snapshot = null,
                                applied_at = null,
                                cancelled_at = null,
                                updated_at = now()
                            """)
                    .param("userId", userId)
                    .param("jobId", context.jobId())
                    .param("proposalId", proposalId)
                    .param("basedOnVersion", basedOnVersion)
                    .param("proposedVersion", basedOnVersion + 1)
                    .param("proposal", writeJson(proposal))
                    .update();
            upsertCapabilityReviewCandidates(jdbc, userId, context.jobId(), normalization);
            upsertRoleReviewCandidates(jdbc, userId, context.jobId(), structured);
            jdbc.sql("""
                            update job_postings
                            set
                                company_name = :companyName,
                                role_title = :roleTitle,
                                experience_text = :experienceText,
                                parsed_data = cast(:parsedData as jsonb),
                                closes_at = case
                                    when :deadline = '' then null
                                    else cast(:deadline as date)::timestamptz
                                end,
                                lifecycle_status = case
                                    when :postingStatus = 'CLOSED' then 'CLOSED'
                                    when :postingStatus = 'ACTIVE' then 'ACTIVE'
                                    else 'UNKNOWN'
                                end
                            where id = :postingId
                            """)
                    .param("companyName", companyName)
                    .param("roleTitle", roleTitle)
                    .param("experienceText", experienceSummary(experience))
                    .param("parsedData", writeJson(structured))
                    .param("deadline", structured.path("applicationDeadline").stringValue(""))
                    .param("postingStatus", structured.path("postingStatus").stringValue("UNKNOWN"))
                    .param("postingId", context.postingId())
                    .update();
            int updated = jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'SUCCEEDED',
                                stage = 'SUCCEEDED',
                                stage_message = '공고 분석과 새 로드맵 초안이 준비됐어요',
                                result_data = cast(:resultData as jsonb),
                                worker_id = null,
                                locked_until = null,
                                error_code = null,
                                error_message = null,
                                completed_at = now()
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("resultData", writeJson(result))
                    .param("jobId", context.jobId())
                    .param("workerId", workerId)
                    .update();
            if (updated == 0) {
                throw new AiServiceException(
                        "ANALYSIS_STALE_RESULT",
                        "취소되거나 교체된 커리어 분석 결과를 폐기했습니다."
                );
            }
            jdbc.sql("select finish_analysis_job(:jobId, :userId)")
                    .param("jobId", context.jobId())
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            jdbc.sql("""
                            insert into notifications (
                                user_id,
                                notification_type,
                                title,
                                body,
                                payload
                            )
                            values (
                                :userId,
                                'ANALYSIS_COMPLETED',
                                '공고 분석이 완료됐어요',
                                :body,
                                jsonb_build_object(
                                    'analysisJobId', cast(:jobId as text),
                                    'postingId', cast(:postingId as text),
                                    'provider', 'UNIFIED',
                                    'proposalId', :proposalId
                                )
                            )
                            """)
                    .param("userId", userId)
                    .param("body", companyName + " " + roleTitle + " 분석 결과를 확인해 보세요.")
                    .param("jobId", context.jobId())
                    .param("postingId", context.postingId())
                    .param("proposalId", proposalId)
                    .update();
            return null;
        });
    }

    private void upsertCapabilityReviewCandidates(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID userId,
            UUID jobId,
            JsonNode normalization
    ) {
        jdbc.sql("""
                        insert into capability_review_candidates (
                            source_user_id,
                            analysis_job_id,
                            normalization_id,
                            requirement_id,
                            candidate_id,
                            decision_kind,
                            display_name,
                            proposed_kind,
                            scope_definition,
                            aliases,
                            evidence_ids,
                            match_candidates,
                            confidence,
                            reason
                        )
                        select
                            :userId,
                            :jobId,
                            :normalizationId,
                            item ->> 'requirementId',
                            coalesce(
                                item -> 'newCandidate' ->> 'candidateId',
                                left('review-' || (item ->> 'requirementId'), 160)
                            ),
                            item ->> 'decision',
                            coalesce(
                                item -> 'newCandidate' ->> 'displayName',
                                item ->> 'requirementId'
                            ),
                            item -> 'newCandidate' ->> 'proposedKind',
                            item -> 'newCandidate' ->> 'scopeDefinition',
                            coalesce(item -> 'newCandidate' -> 'aliases', '[]'::jsonb),
                            coalesce(item -> 'newCandidate' -> 'evidenceIds', item -> 'evidenceIds', '[]'::jsonb),
                            coalesce(item -> 'candidates', '[]'::jsonb),
                            case
                                when item -> 'newCandidate' ->> 'confidence' is null then null
                                else cast(item -> 'newCandidate' ->> 'confidence' as numeric)
                            end,
                            item ->> 'reason'
                        from jsonb_array_elements(
                            coalesce(cast(:normalization as jsonb) -> 'items', '[]'::jsonb)
                        ) item
                        where item ->> 'reviewStatus' = 'OPERATOR_REVIEW_REQUIRED'
                        on conflict (analysis_job_id, candidate_id)
                        do update set
                            display_name = excluded.display_name,
                            proposed_kind = excluded.proposed_kind,
                            scope_definition = excluded.scope_definition,
                            aliases = excluded.aliases,
                            evidence_ids = excluded.evidence_ids,
                            match_candidates = excluded.match_candidates,
                            confidence = excluded.confidence,
                            reason = excluded.reason
                        """)
                .param("userId", userId)
                .param("jobId", jobId)
                .param("normalizationId", normalization.path("normalizationId").stringValue("normalization-" + jobId))
                .param("normalization", writeJson(normalization))
                .update();
    }

    private void upsertRoleReviewCandidates(
            JdbcClient jdbc,
            UUID userId,
            UUID jobId,
            JsonNode structured
    ) {
        jdbc.sql("""
                        insert into role_review_candidates (
                            source_user_id,
                            analysis_job_id,
                            position_id,
                            source_title,
                            proposed_family,
                            proposed_specialization,
                            evidence_ids,
                            confidence
                        )
                        select
                            :userId,
                            :jobId,
                            position ->> 'positionId',
                            position ->> 'sourceTitle',
                            position -> 'role' ->> 'family',
                            position -> 'role' ->> 'specialization',
                            coalesce(position -> 'role' -> 'evidenceIds', '[]'::jsonb),
                            cast(position -> 'role' ->> 'confidence' as numeric)
                        from jsonb_array_elements(
                            coalesce(cast(:structured as jsonb) -> 'positions', '[]'::jsonb)
                        ) position
                        where position -> 'role' ->> 'status' = 'NEW_CANDIDATE'
                        on conflict (analysis_job_id, position_id)
                        do update set
                            source_title = excluded.source_title,
                            proposed_family = excluded.proposed_family,
                            proposed_specialization = excluded.proposed_specialization,
                            evidence_ids = excluded.evidence_ids,
                            confidence = excluded.confidence
                        """)
                .param("userId", userId)
                .param("jobId", jobId)
                .param("structured", writeJson(structured))
                .update();
    }

    private void storeSharedStructure(
            JdbcClient jdbc,
            String snapshotHash,
            JsonNode structured
    ) {
        if (structured == null || !structured.isObject()) {
            return;
        }
        jdbc.sql("""
                        insert into ai_v3_posting_structure_cache (
                            snapshot_hash,
                            contract_version,
                            analysis_version,
                            structured_posting
                        ) values (
                            :snapshotHash,
                            'jobis.ai.v3alpha1',
                            :analysisVersion,
                            cast(:structuredPosting as jsonb)
                        )
                        on conflict (snapshot_hash) do update set
                            contract_version = excluded.contract_version,
                            analysis_version = excluded.analysis_version,
                            structured_posting = excluded.structured_posting,
                            invalidated_at = null,
                            invalid_reason = null,
                            updated_at = now()
                        """)
                .param("snapshotHash", snapshotHash)
                .param(
                        "analysisVersion",
                        structured.path("analysisVersion").stringValue(null)
                )
                .param("structuredPosting", writeJson(structured))
                .update();
    }

    private void requireCurrentRun(
            JdbcClient jdbc,
            UUID jobId,
            String workerId,
            int runRevision
    ) {
        requireCurrentWorker(jdbc, jobId, workerId);
        boolean current = jdbc.sql("""
                        select exists (
                            select 1
                            from ai_v3_analysis_runs
                            where analysis_job_id = :jobId
                              and run_revision = :runRevision
                              and state = 'RUNNING'
                        )
                        """)
                .param("jobId", jobId)
                .param("runRevision", runRevision)
                .query(Boolean.class)
                .single();
        if (!current) {
            throw new AiServiceException(
                    "ANALYSIS_STALE_RESULT",
                    "커리어 분석 실행 revision이 더 이상 활성 상태가 아닙니다."
            );
        }
    }

    private void requireCurrentWorker(JdbcClient jdbc, UUID jobId, String workerId) {
        boolean current = jdbc.sql("""
                        select status = 'RUNNING' and worker_id = :workerId
                        from analysis_jobs
                        where id = :jobId
                        for update
                        """)
                .param("workerId", workerId)
                .param("jobId", jobId)
                .query(Boolean.class)
                .optional()
                .orElse(false);
        if (!current) {
            throw new AiServiceException(
                    "ANALYSIS_STALE_RESULT",
                    "커리어 분석 작업 소유권이 만료되었습니다."
            );
        }
    }

    private ArrayNode copyOptions(JsonNode source) {
        ArrayNode result = objectMapper.createArrayNode();
        if (!source.isArray()) {
            return result;
        }
        for (JsonNode item : source) {
            if (!item.isObject()) {
                continue;
            }
            String value = item.path("value").stringValue("");
            String label = item.path("label").stringValue("");
            if (!value.isBlank() && !label.isBlank()) {
                result.add(item);
            }
        }
        return result;
    }

    private ArrayNode arrayOrEmpty(JsonNode value) {
        if (value != null && value.isArray()) {
            return (ArrayNode) value;
        }
        return objectMapper.createArrayNode();
    }

    private static int requiredSequence(JsonNode event) {
        JsonNode value = event.path("sequence");
        if (!value.isIntegralNumber() || value.intValue() < 1 || value.intValue() > 10000) {
            throw new AiServiceException(
                    "INVALID_AI_RESPONSE",
                    "커리어 분석 진행 이벤트 순서가 올바르지 않습니다."
            );
        }
        return value.intValue();
    }

    private static JsonNode requireObject(JsonNode value, String field) {
        JsonNode result = value.path(field);
        if (!result.isObject()) {
            throw new AiServiceException(
                    "INVALID_AI_RESPONSE",
                    "커리어 분석 완료 결과에 " + field + " 항목이 없습니다."
            );
        }
        return result;
    }

    private static String requiredText(JsonNode node, String field) {
        String value = node.path(field).stringValue("");
        if (value.isBlank()) {
            throw new AiServiceException(
                    "INVALID_AI_RESPONSE",
                    "커리어 분석 응답에 " + field + " 값이 없습니다."
            );
        }
        return value;
    }

    private static String nullableText(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isNull() || value.isMissingNode() ? null : value.stringValue(null);
    }

    private static long requiredLong(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (!value.isIntegralNumber() || value.longValue() < 0) {
            throw new AiServiceException(
                    "INVALID_AI_RESPONSE",
                    "커리어 분석 응답에 올바른 " + field + " 값이 없습니다."
            );
        }
        return value.longValue();
    }

    private static JsonNode findPosition(JsonNode structured, String positionId) {
        for (JsonNode position : structured.path("positions")) {
            if (positionId.equals(position.path("positionId").stringValue(""))) {
                return position;
            }
        }
        throw new AiServiceException(
                "INVALID_AI_RESPONSE",
                "선택된 공고 직무가 구조화 결과에 없습니다."
        );
    }

    private static String experienceSummary(JsonNode experience) {
        String kind = experience.path("kind").stringValue("UNKNOWN");
        return switch (kind) {
            case "NEW_GRADUATE" -> "신입";
            case "NO_RESTRICTION" -> "경력 무관";
            case "NEW_GRADUATE_OR_EXPERIENCED" -> "신입 또는 경력";
            case "EXPERIENCE_REQUIRED", "RANGE" -> {
                int months = experience.path("minMonths").isIntegralNumber()
                        ? experience.path("minMonths").intValue()
                        : experience.path("experiencedMinMonths").intValue();
                yield months >= 12
                        ? "경력 " + (months / 12) + "년 이상"
                        : "경력 " + Math.max(1, months) + "개월 이상";
            }
            default -> "경력 조건 확인 필요";
        };
    }

    private String writeJson(JsonNode value) {
        return value == null || value.isMissingNode() || value.isNull()
                ? null
                : objectMapper.writeValueAsString(value);
    }
}
