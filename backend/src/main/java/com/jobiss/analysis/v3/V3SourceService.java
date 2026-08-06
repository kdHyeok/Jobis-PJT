package com.jobiss.analysis.v3;

import com.jobiss.analysis.AiAnalysisClient;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.posting.JobPostingService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class V3SourceService {

    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final JobPostingService jobPostingService;

    public V3SourceService(
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper,
            JobPostingService jobPostingService
    ) {
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.jobPostingService = jobPostingService;
    }

    public SourceView acquire(UUID userId, AcquireCommand command) {
        String inputType = normalizeEnum(
                command.inputType(),
                "URL|IMAGE|TEXT",
                "지원하지 않는 공고 입력 형식입니다."
        );
        String entryPoint = normalizeEnum(
                command.entryPoint(),
                "CHAT|POSTINGS_PAGE|INTERNAL",
                "지원하지 않는 공고 진입 화면입니다."
        );
        requireMatchingPayload(inputType, command);
        if (command.postingId() != null) {
            rls.read(userId, jdbc -> {
                boolean owned = jdbc.sql("select exists(select 1 from job_postings where id = :id)")
                        .param("id", command.postingId())
                        .query(Boolean.class)
                        .single();
                if (!owned) {
                    throw notFound("연결할 채용 공고를 찾을 수 없습니다.");
                }
                return null;
            });
        }

        ObjectNode request = objectMapper.createObjectNode();
        request.put("inputType", inputType);
        request.put("entryPoint", entryPoint);
        request.put("extractionRevision", Math.max(1, command.extractionRevision()));
        putIfPresent(request, "text", command.text());
        putIfPresent(request, "url", command.url());
        putIfPresent(request, "imageBase64", command.imageBase64());
        putIfPresent(request, "imageMediaType", command.imageMediaType());
        putIfPresent(request, "originalFilename", command.originalFilename());

        JsonNode document = aiClient.acquireSource(request);
        String sourceDocumentId = requiredText(document, "sourceDocumentId");
        int revision = requiredPositiveInt(document, "extractionRevision");
        String status = requiredText(document, "status");
        String canonicalInputHash = requiredText(document, "canonicalInputHash");
        String contentHash = requiredText(document, "contentHash");

        UUID localId = rls.write(userId, jdbc -> jdbc.sql("""
                        insert into ai_v3_source_documents (
                            user_id,
                            posting_id,
                            source_document_id,
                            entry_point,
                            input_type,
                            extraction_revision,
                            status,
                            canonical_input_hash,
                            content_hash,
                            document
                        )
                        values (
                            :userId,
                            :postingId,
                            :sourceDocumentId,
                            :entryPoint,
                            :inputType,
                            :revision,
                            :status,
                            :canonicalInputHash,
                            :contentHash,
                            cast(:document as jsonb)
                        )
                        on conflict (user_id, source_document_id)
                        do update set
                            document = excluded.document,
                            status = excluded.status,
                            content_hash = excluded.content_hash,
                            updated_at = now()
                        where ai_v3_source_documents.user_id = excluded.user_id
                        returning id
                        """)
                .param("userId", userId)
                .param("postingId", command.postingId())
                .param("sourceDocumentId", sourceDocumentId)
                .param("entryPoint", entryPoint)
                .param("inputType", inputType)
                .param("revision", revision)
                .param("status", status)
                .param("canonicalInputHash", canonicalInputHash)
                .param("contentHash", contentHash)
                .param("document", writeJson(document))
                .query(UUID.class)
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.CONFLICT,
                        "V3_SOURCE_OWNERSHIP_CONFLICT",
                        "동일한 공고 원본이 다른 사용자 범위에 이미 존재합니다."
                )));
        return new SourceView(localId, command.postingId(), document, null, null);
    }

    public SourceView verify(
            UUID userId,
            UUID sourceId,
            VerifyCommand command
    ) {
        StoredSource stored = rls.read(userId, jdbc -> jdbc.sql("""
                        select id, posting_id, source_document_id, document::text
                        from ai_v3_source_documents
                        where id = :sourceId
                        """)
                .param("sourceId", sourceId)
                .query((rs, rowNum) -> new StoredSource(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        rs.getString("source_document_id"),
                        readJson(rs.getString("document"))
                ))
                .optional()
                .orElseThrow(() -> notFound("확인할 공고 원본을 찾을 수 없습니다.")));

        if (command.verifiedText() == null || command.verifiedText().isBlank()) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "V3_VERIFIED_TEXT_REQUIRED",
                    "확인한 공고 원문을 입력해 주세요."
            );
        }
        String verifiedBy = normalizeEnum(
                command.verifiedBy(),
                "USER|OPERATOR",
                "허용되지 않은 원문 확인 주체입니다."
        );
        ObjectNode request = objectMapper.createObjectNode();
        request.set("sourceDocument", stored.document());
        request.put("verifiedText", command.verifiedText().trim());
        request.set(
                "corrections",
                command.corrections() == null
                        ? objectMapper.createArrayNode()
                        : command.corrections()
        );
        request.put("verifiedBy", verifiedBy);
        if (command.previousSnapshotId() != null
                && !command.previousSnapshotId().isBlank()) {
            request.put("previousSnapshotId", command.previousSnapshotId().trim());
        }

        JsonNode result = aiClient.verifySource(stored.sourceDocumentId(), request);
        JsonNode document = result.path("sourceDocument");
        JsonNode snapshot = result.path("verifiedSnapshot");
        if (!document.isObject() || !snapshot.isObject()) {
            throw new IllegalStateException(
                    "공고 원문 검증이 필요한 계약 객체를 모두 반환하지 않았습니다."
            );
        }
        if (!stored.sourceDocumentId().equals(requiredText(document, "sourceDocumentId"))) {
            throw new IllegalStateException("공고 원문 검증 중 sourceDocumentId가 변경되었습니다.");
        }

        String verifiedSnapshotId = requiredText(snapshot, "verifiedSnapshotId");
        int sourceRevision = requiredPositiveInt(snapshot, "sourceRevision");
        String snapshotHash = requiredText(snapshot, "snapshotHash");
        UUID localSnapshotId = rls.write(userId, jdbc -> {
            jdbc.sql("""
                            update ai_v3_source_documents
                            set
                                document = cast(:document as jsonb),
                                status = :status,
                                content_hash = :contentHash,
                                updated_at = now()
                            where id = :sourceId
                            """)
                    .param("document", writeJson(document))
                    .param("status", requiredText(document, "status"))
                    .param("contentHash", requiredText(document, "contentHash"))
                    .param("sourceId", sourceId)
                    .update();
            return jdbc.sql("""
                            insert into ai_v3_verified_posting_snapshots (
                                user_id,
                                source_id,
                                verified_snapshot_id,
                                source_revision,
                                previous_snapshot_id,
                                snapshot_hash,
                                verified_by,
                                snapshot
                            )
                            values (
                                :userId,
                                :sourceId,
                                :verifiedSnapshotId,
                                :sourceRevision,
                                :previousSnapshotId,
                                :snapshotHash,
                                :verifiedBy,
                                cast(:snapshot as jsonb)
                            )
                            on conflict (user_id, verified_snapshot_id)
                            do update set snapshot = excluded.snapshot
                            returning id
                            """)
                    .param("userId", userId)
                    .param("sourceId", sourceId)
                    .param("verifiedSnapshotId", verifiedSnapshotId)
                    .param("sourceRevision", sourceRevision)
                    .param("previousSnapshotId", nullableText(snapshot, "previousSnapshotId"))
                    .param("snapshotHash", snapshotHash)
                    .param("verifiedBy", requiredText(snapshot, "verifiedBy"))
                    .param("snapshot", writeJson(snapshot))
                    .query(UUID.class)
                    .single();
        });
        return new SourceView(
                sourceId,
                stored.postingId(),
                document,
                localSnapshotId,
                snapshot
        );
    }

    public SourceView get(UUID userId, UUID sourceId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            source.id,
                            source.posting_id,
                            source.document::text,
                            snapshot.id as snapshot_id,
                            snapshot.snapshot::text
                        from ai_v3_source_documents source
                        left join lateral (
                            select id, snapshot
                            from ai_v3_verified_posting_snapshots
                            where source_id = source.id
                            order by created_at desc
                            limit 1
                        ) snapshot on true
                        where source.id = :sourceId
                        """)
                .param("sourceId", sourceId)
                .query((rs, rowNum) -> new SourceView(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        readJson(rs.getString("document")),
                        rs.getObject("snapshot_id", UUID.class),
                        readJson(rs.getString("snapshot"))
                ))
                .optional()
                .orElseThrow(() -> notFound("공고 원본을 찾을 수 없습니다.")));
    }

    public AnalysisStart startAnalysis(
            UUID userId,
            UUID sourceId,
            UUID conversationId
    ) {
        return rls.write(userId, jdbc -> {
            StartableSource source = jdbc.sql("""
                            select
                                source.id,
                                source.posting_id,
                                source.input_type,
                                source.document ->> 'canonicalUrl' as canonical_url,
                                snapshot.id as snapshot_id,
                                snapshot.snapshot ->> 'verifiedText' as verified_text
                            from ai_v3_source_documents source
                            join lateral (
                                select id, snapshot
                                from ai_v3_verified_posting_snapshots
                                where source_id = source.id
                                order by created_at desc
                                limit 1
                            ) snapshot on true
                            where source.id = :sourceId
                            for update of source
                            """)
                    .param("sourceId", sourceId)
                    .query((rs, rowNum) -> new StartableSource(
                            rs.getObject("id", UUID.class),
                            rs.getObject("posting_id", UUID.class),
                            rs.getString("input_type"),
                            rs.getString("canonical_url"),
                            rs.getObject("snapshot_id", UUID.class),
                            rs.getString("verified_text")
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.CONFLICT,
                            "V3_SOURCE_NOT_VERIFIED",
                            "공고 원문을 먼저 확인해 주세요."
                    ));

            if (conversationId != null) {
                boolean activeConversation = jdbc.sql("""
                                select exists (
                                    select 1
                                    from conversations
                                    where id = :conversationId
                                      and status = 'ACTIVE'
                                )
                                """)
                        .param("conversationId", conversationId)
                        .query(Boolean.class)
                        .single();
                if (!activeConversation) {
                    throw new ApiException(
                            HttpStatus.NOT_FOUND,
                            "CONVERSATION_NOT_FOUND",
                            "공고를 연결할 대화를 찾을 수 없습니다."
                    );
                }
            }

            if (source.postingId() != null) {
                AnalysisStart exact = jdbc.sql("""
                                select job.id, job.status::text
                                from analysis_jobs job
                                left join ai_v3_analysis_runs run
                                  on run.analysis_job_id = job.id
                                where job.posting_id = :postingId
                                  and job.analysis_provider = 'UNIFIED'
                                  and coalesce(job.v3_snapshot_id, run.verified_snapshot_id)
                                      = :snapshotId
                                order by job.created_at desc
                                limit 1
                                """)
                        .param("postingId", source.postingId())
                        .param("snapshotId", source.snapshotId())
                        .query((rs, rowNum) -> new AnalysisStart(
                                source.postingId(),
                                rs.getObject("id", UUID.class),
                                source.id(),
                                source.snapshotId(),
                                rs.getString("status"),
                                true,
                    "같은 확인본으로 시작한 분석을 이어서 보여드립니다."
                        ))
                        .optional()
                        .orElse(null);
                if (exact != null) {
                    return exact;
                }

                JobPostingService.CreatedPosting created =
                        jobPostingService.createV3AnalysisInTransaction(
                                jdbc,
                                userId,
                                source.postingId(),
                                source.canonicalUrl(),
                                source.verifiedText()
                        );
                bindV3SourceToJob(jdbc, created.analysisJobId(), source);
                appendConversationAnalysisMessages(
                        jdbc,
                        userId,
                        conversationId,
                        created,
                        source
                );
                return new AnalysisStart(
                        created.postingId(),
                        created.analysisJobId(),
                        source.id(),
                        source.snapshotId(),
                        created.status(),
                        false,
                        "수정해 확인한 새 공고 내용으로 분석을 시작합니다."
                );
            }

            String postingSource = "IMAGE".equals(source.inputType())
                    ? "FILE"
                    : source.inputType();
            JobPostingService.CreatedPosting created =
                    jobPostingService.createInTransaction(
                            jdbc,
                            userId,
                            new JobPostingService.CreatePosting(
                                    postingSource,
                                    source.canonicalUrl(),
                                    source.verifiedText(),
                                    conversationId
                            ),
                            false
                    );
            jdbc.sql("""
                            update ai_v3_source_documents
                            set posting_id = :postingId
                            where id = :sourceId
                            """)
                    .param("postingId", created.postingId())
                    .param("sourceId", sourceId)
                    .update();
            bindV3SourceToJob(jdbc, created.analysisJobId(), source);
            appendConversationAnalysisMessages(
                    jdbc,
                    userId,
                    conversationId,
                    created,
                    source
            );
            return new AnalysisStart(
                    created.postingId(),
                    created.analysisJobId(),
                    source.id(),
                    source.snapshotId(),
                    created.status(),
                    created.reusedAnalysis(),
                    created.reuseMessage()
            );
        });
    }

    public List<SourceSummary> list(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            source.id,
                            source.posting_id,
                            source.input_type,
                            source.entry_point,
                            source.status,
                            source.extraction_revision,
                            source.created_at,
                            exists (
                                select 1
                                from ai_v3_verified_posting_snapshots snapshot
                                where snapshot.source_id = source.id
                            ) as verified
                        from ai_v3_source_documents source
                        order by source.created_at desc
                        limit 100
                        """)
                .query((rs, rowNum) -> new SourceSummary(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        rs.getString("input_type"),
                        rs.getString("entry_point"),
                        rs.getString("status"),
                        rs.getInt("extraction_revision"),
                        rs.getBoolean("verified"),
                        rs.getObject("created_at", OffsetDateTime.class)
                ))
                .list());
    }

    private void bindV3SourceToJob(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID analysisJobId,
            StartableSource source
    ) {
        jdbc.sql("""
                        update analysis_jobs
                        set
                            analysis_provider = 'UNIFIED',
                            ai_contract_version = 'jobis.ai.v3alpha1',
                            v3_source_id = :sourceId,
                            v3_snapshot_id = :snapshotId
                        where id = :analysisJobId
                        """)
                .param("sourceId", source.id())
                .param("snapshotId", source.snapshotId())
                .param("analysisJobId", analysisJobId)
                .update();
    }

    private void appendConversationAnalysisMessages(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID userId,
            UUID conversationId,
            JobPostingService.CreatedPosting created,
            StartableSource source
    ) {
        if (conversationId == null) {
            return;
        }
        jdbc.sql("""
                        insert into conversation_messages (
                            user_id, conversation_id, role, kind, content,
                            posting_id, analysis_job_id, metadata
                        )
                        values (
                            :userId, :conversationId, 'USER', 'POSTING', :content,
                            :postingId, :analysisJobId,
                            jsonb_build_object(
                                'provider', 'UNIFIED',
                                'sourceId', cast(:sourceId as text),
                                'sourceVerified', true
                            )
                        )
                        """)
                .param("userId", userId)
                .param("conversationId", conversationId)
                .param("content", postingRequestMessage(source))
                .param("postingId", created.postingId())
                .param("analysisJobId", created.analysisJobId())
                .param("sourceId", source.id())
                .update();
        jdbc.sql("""
                        insert into conversation_messages (
                            user_id, conversation_id, role, kind, content,
                            posting_id, analysis_job_id, metadata
                        )
                        values (
                            :userId, :conversationId, 'ASSISTANT', 'ANALYSIS_STATUS',
                            '확인한 공고를 저장했고 JOBIS 분석을 시작했어요.',
                            :postingId, :analysisJobId,
                            jsonb_build_object(
                                'provider', 'UNIFIED',
                                'analysisJobId', cast(:analysisJobId as text),
                                'postingId', cast(:postingId as text),
                                'status', 'QUEUED'
                            )
                        )
                        """)
                .param("userId", userId)
                .param("conversationId", conversationId)
                .param("postingId", created.postingId())
                .param("analysisJobId", created.analysisJobId())
                .update();
    }

    private void requireMatchingPayload(String inputType, AcquireCommand command) {
        int supplied = countPresent(command.text())
                + countPresent(command.url())
                + countPresent(command.imageBase64());
        boolean matching = switch (inputType) {
            case "TEXT" -> present(command.text());
            case "URL" -> present(command.url());
            case "IMAGE" -> present(command.imageBase64())
                    && present(command.imageMediaType())
                    && present(command.originalFilename());
            default -> false;
        };
        if (!matching || supplied != 1) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "V3_SOURCE_PAYLOAD_MISMATCH",
                    "입력 형식과 일치하는 공고 원본 하나만 보내 주세요."
            );
        }
    }

    private String normalizeEnum(String value, String pattern, String message) {
        String normalized = value == null ? "" : value.trim().toUpperCase();
        if (!normalized.matches(pattern)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_V3_SOURCE", message);
        }
        return normalized;
    }

    private static int countPresent(String value) {
        return present(value) ? 1 : 0;
    }

    private static boolean present(String value) {
        return value != null && !value.isBlank();
    }

    private static String postingRequestMessage(StartableSource source) {
        if (present(source.canonicalUrl())) {
            return source.canonicalUrl() + "\n\n확인한 공고를 분석해 주세요.";
        }
        String firstLine = source.verifiedText().lines()
                .map(String::trim)
                .filter(line -> !line.isBlank())
                .findFirst()
                .orElse("채용 공고");
        if (firstLine.length() > 160) {
            firstLine = firstLine.substring(0, 160) + "…";
        }
        return firstLine + "\n\n확인한 공고를 분석해 주세요.";
    }

    private static void putIfPresent(ObjectNode node, String field, String value) {
        if (present(value)) {
            node.put(field, value.trim());
        }
    }

    private static String requiredText(JsonNode node, String field) {
        String value = node.path(field).stringValue("");
        if (value.isBlank()) {
            throw new IllegalStateException("공고 원문 응답에 " + field + " 항목이 없습니다.");
        }
        return value;
    }

    private static String nullableText(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() ? null : value.stringValue(null);
    }

    private static int requiredPositiveInt(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (!value.isIntegralNumber() || value.intValue() < 1) {
            throw new IllegalStateException("공고 원문 응답의 " + field + " 값이 올바르지 않습니다.");
        }
        return value.intValue();
    }

    private String writeJson(JsonNode value) {
        return objectMapper.writeValueAsString(value);
    }

    private JsonNode readJson(String value) {
        if (value == null) {
            return null;
        }
        return objectMapper.readTree(value);
    }

    private static ApiException notFound(String message) {
        return new ApiException(HttpStatus.NOT_FOUND, "V3_SOURCE_NOT_FOUND", message);
    }

    public record AcquireCommand(
            String inputType,
            String entryPoint,
            int extractionRevision,
            UUID postingId,
            String text,
            String url,
            String imageBase64,
            String imageMediaType,
            String originalFilename
    ) {
    }

    public record VerifyCommand(
            String verifiedText,
            ArrayNode corrections,
            String verifiedBy,
            String previousSnapshotId
    ) {
    }

    public record SourceView(
            UUID id,
            UUID postingId,
            JsonNode sourceDocument,
            UUID verifiedSnapshotId,
            JsonNode verifiedSnapshot
    ) {
    }

    public record SourceSummary(
            UUID id,
            UUID postingId,
            String inputType,
            String entryPoint,
            String status,
            int extractionRevision,
            boolean verified,
            OffsetDateTime createdAt
    ) {
    }

    public record AnalysisStart(
            UUID postingId,
            UUID analysisJobId,
            UUID sourceId,
            UUID verifiedSnapshotId,
            String status,
            boolean reusedAnalysis,
            String reuseMessage
    ) {
    }

    private record StoredSource(
            UUID id,
            UUID postingId,
            String sourceDocumentId,
            JsonNode document
    ) {
    }

    private record StartableSource(
            UUID id,
            UUID postingId,
            String inputType,
            String canonicalUrl,
            UUID snapshotId,
            String verifiedText
    ) {
    }
}
