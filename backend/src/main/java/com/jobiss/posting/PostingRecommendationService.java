package com.jobiss.posting;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Service
public class PostingRecommendationService {

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;

    public PostingRecommendationService(
            RlsTransactionExecutor rls,
            ObjectMapper objectMapper
    ) {
        this.rls = rls;
        this.objectMapper = objectMapper;
    }

    public List<AlternativePosting> recommend(
            UUID userId,
            UUID sourcePostingId,
            int limit
    ) {
        int safeLimit = Math.max(1, Math.min(limit, 10));
        return rls.read(userId, jdbc -> {
            SourceTarget source = jdbc.sql("""
                            select
                                posting.company_name,
                                posting.role_title,
                                profile.primary_track
                            from job_postings posting
                            join posting_path_profiles profile
                              on profile.posting_id = posting.id
                            where posting.id = :postingId
                              and posting.archived_at is null
                            """)
                    .param("postingId", sourcePostingId)
                    .query((rs, rowNum) -> new SourceTarget(
                            rs.getString("company_name"),
                            rs.getString("role_title"),
                            rs.getString("primary_track")
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "ANALYZED_POSTING_NOT_FOUND",
                            "추천 기준이 될 분석 완료 공고를 찾을 수 없습니다."
                    ));

            int experienceMonths = jdbc.sql("""
                            select coalesce(max(
                                case
                                    when detail ->> 'months' ~ '^[0-9]{1,3}$'
                                    then (detail ->> 'months')::integer
                                    else 0
                                end
                            ), 0)
                            from career_fragments
                            where review_status = 'CONFIRMED'
                              and archived_at is null
                              and kind = 'EXPERIENCE'
                            """)
                    .query(Integer.class)
                    .single();

            List<CandidateRow> candidates = jdbc.sql("""
                            select
                                catalog.id,
                                catalog.company_name,
                                catalog.role_title,
                                catalog.source_url,
                                catalog.experience_text,
                                catalog.primary_track,
                                catalog.minimum_experience_months,
                                count(requirement.id)
                                    filter (
                                        where requirement.relation_kind =
                                            'REQUIRED'
                                    ) as required_total,
                                count(requirement.id)
                                    filter (
                                        where requirement.relation_kind =
                                            'REQUIRED'
                                          and competency.verified_level >=
                                              requirement.required_level
                                    ) as required_met,
                                count(requirement.id)
                                    filter (
                                        where requirement.relation_kind =
                                            'PREFERRED'
                                    ) as preferred_total,
                                count(requirement.id)
                                    filter (
                                        where requirement.relation_kind =
                                            'PREFERRED'
                                          and competency.verified_level >=
                                              requirement.required_level
                                    ) as preferred_met,
                                coalesce(
                                    jsonb_agg(
                                        distinct competency_catalog.title
                                        order by competency_catalog.title
                                    ) filter (
                                        where requirement.relation_kind =
                                            'REQUIRED'
                                          and coalesce(
                                              competency.verified_level,
                                              0
                                          ) < requirement.required_level
                                    ),
                                    '[]'::jsonb
                                )::text as gaps
                            from posting_catalog catalog
                            left join posting_catalog_requirements requirement
                              on requirement.posting_catalog_id = catalog.id
                            left join competency_catalog
                              on competency_catalog.id =
                                 requirement.catalog_competency_id
                            left join user_competencies competency
                              on competency.user_id = :userId
                             and competency.catalog_competency_id =
                                 requirement.catalog_competency_id
                            where catalog.active
                              and catalog.moderation_status = 'VERIFIED'
                              and catalog.lifecycle_status not in ('EXPIRED', 'CLOSED')
                              and (
                                catalog.closes_at is null
                                or catalog.closes_at > now()
                              )
                              and catalog.last_seen_at >=
                                  now() - interval '90 days'
                              and catalog.primary_track = :primaryTrack
                              and not exists (
                                select 1
                                from posting_catalog duplicate
                                where duplicate.id <> catalog.id
                                  and duplicate.active
                                  and duplicate.moderation_status = 'VERIFIED'
                                  and (
                                    (
                                      catalog.source_platform is not null
                                      and catalog.source_posting_key is not null
                                      and duplicate.source_platform =
                                          catalog.source_platform
                                      and duplicate.source_posting_key =
                                          catalog.source_posting_key
                                    )
                                    or (
                                      catalog.content_fingerprint is not null
                                      and duplicate.content_fingerprint =
                                          catalog.content_fingerprint
                                    )
                                  )
                                  and duplicate.first_seen_at <
                                      catalog.first_seen_at
                              )
                              and not (
                                  lower(catalog.company_name) =
                                      lower(coalesce(:companyName, ''))
                                  and lower(catalog.role_title) =
                                      lower(coalesce(:roleTitle, ''))
                              )
                            group by catalog.id
                            order by
                                (
                                    case
                                        when count(requirement.id)
                                            filter (
                                                where requirement.relation_kind =
                                                    'REQUIRED'
                                            ) = 0
                                        then 1.0
                                        else (
                                            count(requirement.id)
                                                filter (
                                                    where requirement.relation_kind =
                                                        'REQUIRED'
                                                      and competency.verified_level >=
                                                          requirement.required_level
                                                )
                                        )::numeric / nullif(
                                            count(requirement.id)
                                                filter (
                                                    where requirement.relation_kind =
                                                        'REQUIRED'
                                                ),
                                            0
                                        )
                                    end
                                ) desc,
                                case
                                    when catalog.minimum_experience_months <=
                                        :experienceMonths
                                    then 1
                                    else 0
                                end desc,
                                catalog.last_seen_at desc
                            limit :limit
                            """)
                    .param("userId", userId)
                    .param("primaryTrack", source.primaryTrack())
                    .param("companyName", source.companyName())
                    .param("roleTitle", source.roleTitle())
                    .param("experienceMonths", experienceMonths)
                    .param("limit", safeLimit)
                    .query((rs, rowNum) -> new CandidateRow(
                            rs.getObject("id", UUID.class),
                            rs.getString("company_name"),
                            rs.getString("role_title"),
                            rs.getString("source_url"),
                            rs.getString("experience_text"),
                            rs.getString("primary_track"),
                            rs.getInt("minimum_experience_months"),
                            rs.getInt("required_total"),
                            rs.getInt("required_met"),
                            rs.getInt("preferred_total"),
                            rs.getInt("preferred_met"),
                            readStrings(rs.getString("gaps"))
                    ))
                    .list();

            return candidates.stream()
                    .map(candidate -> toView(candidate, experienceMonths))
                    .sorted((left, right) ->
                            Integer.compare(right.matchScore(), left.matchScore()))
                    .toList();
        });
    }

    private AlternativePosting toView(CandidateRow row, int experienceMonths) {
        double requiredCoverage = row.requiredTotal() == 0
                ? 1
                : (double) row.requiredMet() / row.requiredTotal();
        double preferredCoverage = row.preferredTotal() == 0
                ? 1
                : (double) row.preferredMet() / row.preferredTotal();
        boolean experienceMatched =
                row.minimumExperienceMonths() <= experienceMonths;
        int score = (int) Math.round(
                requiredCoverage * 70
                        + preferredCoverage * 20
                        + (experienceMatched ? 10 : 0)
        );
        String reason;
        if (row.requiredMet() == row.requiredTotal() && experienceMatched) {
            reason = "현재 검증된 필수 역량과 경력 조건이 모두 맞습니다.";
        } else if (experienceMatched) {
            reason = "경력 조건은 맞으며, 부족한 필수 역량만 보강하면 됩니다.";
        } else {
            reason = "역량 유사도는 높지만 요구 경력까지 단계적인 준비가 필요합니다.";
        }
        return new AlternativePosting(
                row.id(),
                row.companyName(),
                row.roleTitle(),
                row.sourceUrl(),
                row.experienceText(),
                row.primaryTrack(),
                score,
                reason,
                experienceMatched,
                row.requiredMet(),
                row.requiredTotal(),
                row.preferredMet(),
                row.preferredTotal(),
                row.gaps()
        );
    }

    private List<String> readStrings(String value) {
        if (value == null) {
            return List.of();
        }
        JsonNode node = objectMapper.readTree(value);
        List<String> result = new ArrayList<>();
        node.forEach(item -> result.add(item.stringValue("")));
        return List.copyOf(result);
    }

    public record AlternativePosting(
            UUID id,
            String companyName,
            String roleTitle,
            String sourceUrl,
            String experienceText,
            String primaryTrack,
            int matchScore,
            String reason,
            boolean experienceMatched,
            int matchedRequired,
            int required,
            int matchedPreferred,
            int preferred,
            List<String> gaps
    ) {
    }

    private record SourceTarget(
            String companyName,
            String roleTitle,
            String primaryTrack
    ) {
    }

    private record CandidateRow(
            UUID id,
            String companyName,
            String roleTitle,
            String sourceUrl,
            String experienceText,
            String primaryTrack,
            int minimumExperienceMonths,
            int requiredTotal,
            int requiredMet,
            int preferredTotal,
            int preferredMet,
            List<String> gaps
    ) {
    }
}
