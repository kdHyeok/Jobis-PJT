package com.jobiss.activity;

import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class ActivityJobService {

    private final RlsTransactionExecutor rls;

    public ActivityJobService(RlsTransactionExecutor rls) {
        this.rls = rls;
    }

    public List<ActivityJobView> active(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select *
                        from (
                            select
                                job.id,
                                'CHAT'::text as job_type,
                                conversation.title,
                                job.stage_message as message,
                                job.status::text as status,
                                'CONVERSATION'::text as destination_type,
                                conversation.id as destination_id,
                                job.created_at
                            from chat_reply_jobs job
                            join conversations conversation
                              on conversation.id = job.conversation_id
                            where job.status in ('QUEUED', 'RUNNING')

                            union all

                            select
                                evidence.id,
                                'VERIFICATION'::text,
                                node.title,
                                case evidence.verification_status
                                    when 'PENDING' then '증거 검증 대기 중'
                                    else '제출한 증거를 검증하고 있습니다.'
                                end,
                                evidence.verification_status,
                                'ROADMAP_NODE'::text,
                                node.id,
                                evidence.created_at
                            from evidence
                            join career_nodes node on node.id = evidence.node_id
                            where evidence.verification_status in ('PENDING', 'RUNNING')

                            union all

                            select
                                analysis.id,
                                'ANALYSIS'::text,
                                coalesce(posting.company_name, '채용 공고') || ' · ' || coalesce(posting.role_title, '공고 분석'),
                                analysis.stage_message,
                                analysis.status::text,
                                'POSTING'::text,
                                posting.id,
                                analysis.created_at
                            from analysis_jobs analysis
                            join job_postings posting on posting.id = analysis.posting_id
                            where analysis.status in ('QUEUED', 'RUNNING')

                            union all

                            select
                                source.id,
                                'CAREER'::text,
                                source.title,
                                source.stage_message,
                                source.status,
                                'CAREER_SOURCE'::text,
                                source.id,
                                source.created_at
                            from career_sources source
                            where source.status in ('QUEUED', 'RUNNING')
                        ) active_job
                        order by active_job.created_at desc
                        limit 100
                        """)
                .query((rs, rowNum) -> new ActivityJobView(
                        rs.getObject("id", UUID.class),
                        rs.getString("job_type"),
                        rs.getString("title"),
                        rs.getString("message"),
                        rs.getString("status"),
                        rs.getString("destination_type"),
                        rs.getObject("destination_id", UUID.class),
                        rs.getObject("created_at", OffsetDateTime.class)
                ))
                .list());
    }

    public record ActivityJobView(
            UUID id,
            String type,
            String title,
            String message,
            String status,
            String destinationType,
            UUID destinationId,
            OffsetDateTime createdAt
    ) {
    }
}
