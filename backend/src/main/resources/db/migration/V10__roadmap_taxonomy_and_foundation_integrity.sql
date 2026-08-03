ALTER TABLE user_competencies
    ADD COLUMN roadmap_eligible boolean NOT NULL DEFAULT true,
    ADD COLUMN verification_method text;

ALTER TABLE posting_competency_requirements
    ADD COLUMN competency_title varchar(160),
    ADD COLUMN competency_kind varchar(40),
    ADD COLUMN roadmap_domain varchar(40),
    ADD COLUMN roadmap_stage varchar(40),
    ADD COLUMN roadmap_eligible boolean NOT NULL DEFAULT true,
    ADD COLUMN verification_method text;

UPDATE posting_competency_requirements r
SET
    competency_title = c.title,
    competency_kind = c.competency_kind,
    roadmap_domain = c.domain,
    roadmap_stage = c.default_stage,
    roadmap_eligible = c.roadmap_eligible,
    verification_method = c.verification_method
FROM user_competencies c
WHERE c.id = r.competency_id;

WITH proposal_competencies AS (
    SELECT
        g.analysis_job_id,
        competency
    FROM graph_change_sets g
    CROSS JOIN LATERAL jsonb_array_elements(
        coalesce(g.proposal -> 'competencies', '[]'::jsonb)
    ) AS competency
)
UPDATE posting_competency_requirements r
SET
    competency_title = coalesce(
        p.competency ->> 'title',
        r.competency_title
    ),
    competency_kind = coalesce(
        p.competency ->> 'kind',
        r.competency_kind
    ),
    roadmap_domain = coalesce(
        p.competency ->> 'domain',
        r.roadmap_domain
    ),
    roadmap_stage = coalesce(
        p.competency ->> 'stage',
        r.roadmap_stage
    ),
    roadmap_eligible = coalesce(
        (p.competency ->> 'roadmapEligible')::boolean,
        r.roadmap_eligible
    ),
    verification_method = coalesce(
        p.competency ->> 'verificationMethod',
        r.verification_method
    )
FROM proposal_competencies p, user_competencies c
WHERE p.analysis_job_id = r.analysis_job_id
  AND c.user_id = r.user_id
  AND c.id = r.competency_id
  AND p.competency ->> 'canonicalKey' = c.canonical_key;

UPDATE user_competencies
SET roadmap_eligible = false
WHERE canonical_key IN (
    'practice.collaboration',
    'practice.proactive-improvement',
    'practice.proactive-problem-solving',
    'practice.adaptability',
    'practice.language-adaptability'
);

UPDATE posting_competency_requirements r
SET roadmap_eligible = false
FROM user_competencies c
WHERE c.id = r.competency_id
  AND c.canonical_key IN (
      'practice.collaboration',
      'practice.proactive-improvement',
      'practice.proactive-problem-solving',
      'practice.adaptability',
      'practice.language-adaptability'
  );

UPDATE posting_target_projects project
SET
    required_competency_keys = coalesce(
        (
            SELECT jsonb_agg(value ORDER BY ordinal)
            FROM jsonb_array_elements_text(project.required_competency_keys)
                WITH ORDINALITY AS entry(value, ordinal)
            WHERE value NOT IN (
                'practice.collaboration',
                'practice.proactive-improvement',
                'practice.proactive-problem-solving',
                'practice.adaptability',
                'practice.language-adaptability'
            )
        ),
        '[]'::jsonb
    ),
    optional_competency_keys = coalesce(
        (
            SELECT jsonb_agg(value ORDER BY ordinal)
            FROM jsonb_array_elements_text(project.optional_competency_keys)
                WITH ORDINALITY AS entry(value, ordinal)
            WHERE value NOT IN (
                'practice.collaboration',
                'practice.proactive-improvement',
                'practice.proactive-problem-solving',
                'practice.adaptability',
                'practice.language-adaptability'
            )
        ),
        '[]'::jsonb
    );

UPDATE graph_change_sets change_set
SET proposal = jsonb_set(
    jsonb_set(
        jsonb_set(
            change_set.proposal,
            '{competencies}',
            coalesce(
                (
                    SELECT jsonb_agg(
                        competency
                        || jsonb_build_object(
                            'roadmapEligible',
                            competency ->> 'canonicalKey' NOT IN (
                                'practice.collaboration',
                                'practice.proactive-improvement',
                                'practice.proactive-problem-solving',
                                'practice.adaptability',
                                'practice.language-adaptability'
                            ),
                            'verificationMethod',
                            CASE
                                WHEN competency ->> 'canonicalKey' IN (
                                    'practice.collaboration',
                                    'practice.proactive-improvement',
                                    'practice.proactive-problem-solving',
                                    'practice.adaptability',
                                    'practice.language-adaptability'
                                ) THEN null
                                ELSE coalesce(
                                    competency ->> 'verificationMethod',
                                    '코드, 문서, 경력 또는 자격 증거로 요구 범위를 확인'
                                )
                            END
                        )
                        ORDER BY ordinal
                    )
                    FROM jsonb_array_elements(
                        coalesce(
                            change_set.proposal -> 'competencies',
                            '[]'::jsonb
                        )
                    ) WITH ORDINALITY AS entry(competency, ordinal)
                ),
                '[]'::jsonb
            )
        ),
        '{targetProject,requiredCompetencyRefs}',
        coalesce(
            (
                SELECT jsonb_agg(value ORDER BY ordinal)
                FROM jsonb_array_elements_text(
                    coalesce(
                        change_set.proposal
                            -> 'targetProject'
                            -> 'requiredCompetencyRefs',
                        '[]'::jsonb
                    )
                ) WITH ORDINALITY AS entry(value, ordinal)
                WHERE value NOT IN (
                    SELECT competency ->> 'ref'
                    FROM jsonb_array_elements(
                        coalesce(
                            change_set.proposal -> 'competencies',
                            '[]'::jsonb
                        )
                    ) AS competency
                    WHERE competency ->> 'canonicalKey' IN (
                        'practice.collaboration',
                        'practice.proactive-improvement',
                        'practice.proactive-problem-solving',
                        'practice.adaptability',
                        'practice.language-adaptability'
                    )
                )
            ),
            '[]'::jsonb
        )
    ),
    '{targetProject,optionalCompetencyRefs}',
    coalesce(
        (
            SELECT jsonb_agg(value ORDER BY ordinal)
            FROM jsonb_array_elements_text(
                coalesce(
                    change_set.proposal
                        -> 'targetProject'
                        -> 'optionalCompetencyRefs',
                    '[]'::jsonb
                )
            ) WITH ORDINALITY AS entry(value, ordinal)
            WHERE value NOT IN (
                SELECT competency ->> 'ref'
                FROM jsonb_array_elements(
                    coalesce(
                        change_set.proposal -> 'competencies',
                        '[]'::jsonb
                    )
                ) AS competency
                WHERE competency ->> 'canonicalKey' IN (
                    'practice.collaboration',
                    'practice.proactive-improvement',
                    'practice.proactive-problem-solving',
                    'practice.adaptability',
                    'practice.language-adaptability'
                )
            )
        ),
        '[]'::jsonb
    )
);

UPDATE posting_competency_requirements r
SET roadmap_domain = CASE
    WHEN c.canonical_key IN (
        'foundation.programming',
        'foundation.git-terminal',
        'foundation.cs'
    ) THEN 'COMMON'
    WHEN r.roadmap_stage IN ('EXPERIENCE', 'CREDENTIAL') THEN 'CAREER'
    WHEN c.canonical_key = 'operations.cloud-platform' THEN 'CLOUD'
    WHEN r.roadmap_stage = 'OPERATIONS' THEN 'DEVOPS'
    WHEN c.canonical_key LIKE 'web.%'
        OR c.canonical_key LIKE 'frontend.%'
        OR c.canonical_key LIKE 'framework.frontend%'
        THEN 'FRONTEND'
    WHEN r.roadmap_stage = 'QUALITY'
        AND upper(coalesce(r.roadmap_domain, '')) = 'COMMON'
        THEN 'BACKEND'
    WHEN c.canonical_key = 'foundation.os-internals' THEN 'BACKEND'
    WHEN upper(coalesce(r.roadmap_domain, '')) IN (
        'COMMON',
        'BACKEND',
        'FRONTEND',
        'DATA',
        'DEVOPS',
        'CLOUD',
        'SECURITY',
        'AI',
        'MOBILE',
        'GAME',
        'DOMAIN',
        'CAREER'
    ) THEN upper(r.roadmap_domain)
    WHEN upper(coalesce(r.roadmap_domain, '')) IN ('PAYMENT', 'CONTENT')
        THEN 'DOMAIN'
    WHEN upper(coalesce(r.roadmap_domain, '')) = 'WEB' THEN 'FRONTEND'
    WHEN upper(coalesce(r.roadmap_domain, '')) = 'OPERATIONS' THEN 'DEVOPS'
    ELSE 'BACKEND'
END
FROM user_competencies c
WHERE c.id = r.competency_id;

UPDATE posting_competency_requirements r
SET roadmap_stage = 'QUALITY'
FROM user_competencies c
WHERE c.id = r.competency_id
  AND c.canonical_key = 'practice.technical-writing';

UPDATE posting_competency_requirements r
SET roadmap_domain = CASE
    WHEN r.roadmap_stage IN ('EXPERIENCE', 'CREDENTIAL') THEN 'CAREER'
    WHEN r.roadmap_stage = 'DATA' THEN 'DATA'
    WHEN r.roadmap_stage = 'OPERATIONS'
        AND c.canonical_key = 'operations.cloud-platform'
        THEN 'CLOUD'
    WHEN r.roadmap_stage = 'OPERATIONS' THEN 'DEVOPS'
    WHEN r.roadmap_stage = 'DOMAIN' THEN 'DOMAIN'
    WHEN r.roadmap_stage = 'WEB' THEN 'FRONTEND'
    WHEN r.roadmap_stage = 'QUALITY' THEN 'BACKEND'
    ELSE 'BACKEND'
END
FROM user_competencies c
WHERE c.id = r.competency_id
  AND r.roadmap_domain = 'COMMON'
  AND c.canonical_key NOT IN (
      'foundation.programming',
      'foundation.git-terminal',
      'foundation.cs'
  )
  AND r.roadmap_eligible;

UPDATE user_competencies c
SET
    catalog_competency_id = catalog.id,
    title = catalog.title,
    competency_kind = 'KNOWLEDGE',
    domain = catalog.domain,
    default_stage = 'FOUNDATION',
    scope_definition = catalog.scope_definition,
    roadmap_eligible = true,
    verification_method = '사용자가 기초 퀘스트 완료를 직접 확인'
FROM competency_catalog catalog
WHERE c.canonical_key = catalog.canonical_key
  AND c.canonical_key IN (
      'foundation.programming',
      'foundation.git-terminal',
      'foundation.cs'
  );

ALTER TABLE posting_competency_requirements
    ALTER COLUMN competency_title SET NOT NULL,
    ALTER COLUMN competency_kind SET NOT NULL,
    ALTER COLUMN roadmap_domain SET NOT NULL,
    ALTER COLUMN roadmap_stage SET NOT NULL,
    ADD CONSTRAINT posting_requirement_roadmap_domain_check
        CHECK (
            roadmap_domain IN (
                'COMMON',
                'BACKEND',
                'FRONTEND',
                'DATA',
                'DEVOPS',
                'CLOUD',
                'SECURITY',
                'AI',
                'MOBILE',
                'GAME',
                'DOMAIN',
                'CAREER'
            )
        ),
    ADD CONSTRAINT posting_requirement_roadmap_stage_check
        CHECK (
            roadmap_stage IN (
                'FOUNDATION',
                'WEB',
                'LANGUAGE',
                'FRAMEWORK',
                'DATA',
                'QUALITY',
                'OPERATIONS',
                'SCALE',
                'DOMAIN',
                'EXPERIENCE',
                'CREDENTIAL'
            )
        );

CREATE TEMP TABLE foundation_node_merge AS
WITH ranked AS (
    SELECT
        n.id,
        first_value(n.id) OVER (
            PARTITION BY n.graph_id, n.canonical_key
            ORDER BY
                (n.competency_id IS NOT NULL) DESC,
                (n.detail ? 'selfConfirmable') DESC,
                n.created_at,
                n.id
        ) AS keep_id,
        row_number() OVER (
            PARTITION BY n.graph_id, n.canonical_key
            ORDER BY
                (n.competency_id IS NOT NULL) DESC,
                (n.detail ? 'selfConfirmable') DESC,
                n.created_at,
                n.id
        ) AS position
    FROM career_nodes n
    WHERE n.archived_at IS NULL
      AND n.kind = 'FOUNDATION'
      AND n.canonical_key IN (
          'foundation.programming',
          'foundation.git-terminal',
          'foundation.cs'
      )
)
SELECT id AS duplicate_id, keep_id
FROM ranked
WHERE position > 1;

UPDATE evidence e
SET node_id = m.keep_id
FROM foundation_node_merge m
WHERE e.node_id = m.duplicate_id;

INSERT INTO job_requirements (
    user_id,
    posting_id,
    node_id,
    requirement,
    source_text,
    confidence
)
SELECT
    r.user_id,
    r.posting_id,
    m.keep_id,
    r.requirement,
    r.source_text,
    r.confidence
FROM job_requirements r
JOIN foundation_node_merge m ON m.duplicate_id = r.node_id
ON CONFLICT (posting_id, node_id, requirement)
DO UPDATE SET
    source_text = coalesce(excluded.source_text, job_requirements.source_text),
    confidence = greatest(excluded.confidence, job_requirements.confidence);

DELETE FROM job_requirements r
USING foundation_node_merge m
WHERE r.node_id = m.duplicate_id;

INSERT INTO career_edges (
    user_id,
    graph_id,
    from_node_id,
    to_node_id,
    edge_kind
)
SELECT
    e.user_id,
    e.graph_id,
    coalesce(from_merge.keep_id, e.from_node_id),
    coalesce(to_merge.keep_id, e.to_node_id),
    e.edge_kind
FROM career_edges e
LEFT JOIN foundation_node_merge from_merge
  ON from_merge.duplicate_id = e.from_node_id
LEFT JOIN foundation_node_merge to_merge
  ON to_merge.duplicate_id = e.to_node_id
WHERE (from_merge.keep_id IS NOT NULL OR to_merge.keep_id IS NOT NULL)
  AND coalesce(from_merge.keep_id, e.from_node_id)
      <> coalesce(to_merge.keep_id, e.to_node_id)
ON CONFLICT (graph_id, from_node_id, to_node_id, edge_kind)
DO NOTHING;

DELETE FROM career_edges e
USING foundation_node_merge m
WHERE e.from_node_id = m.duplicate_id
   OR e.to_node_id = m.duplicate_id;

WITH progress_rollup AS (
    SELECT
        m.keep_id,
        bool_or(p.status = 'COMPLETED') AS completed,
        bool_or(p.status = 'IN_PROGRESS') AS in_progress,
        max(p.completed_at) AS completed_at,
        max(p.completion_method) FILTER (
            WHERE p.completion_method IS NOT NULL
        ) AS completion_method
    FROM foundation_node_merge m
    JOIN node_progress p
      ON p.node_id IN (m.duplicate_id, m.keep_id)
    GROUP BY m.keep_id
)
UPDATE node_progress keeper
SET
    status = CASE
        WHEN rollup.completed THEN 'COMPLETED'::progress_status
        WHEN rollup.in_progress THEN 'IN_PROGRESS'::progress_status
        ELSE keeper.status
    END,
    completion_method = coalesce(
        keeper.completion_method,
        rollup.completion_method
    ),
    completed_at = CASE
        WHEN rollup.completed
            THEN coalesce(keeper.completed_at, rollup.completed_at, now())
        ELSE keeper.completed_at
    END
FROM progress_rollup rollup
WHERE keeper.node_id = rollup.keep_id;

DELETE FROM node_progress p
USING foundation_node_merge m
WHERE p.node_id = m.duplicate_id;

UPDATE career_nodes n
SET archived_at = now()
FROM foundation_node_merge m
WHERE n.id = m.duplicate_id;

CREATE INDEX posting_requirements_roadmap_layout_idx
    ON posting_competency_requirements (
        posting_id,
        roadmap_eligible,
        roadmap_domain,
        roadmap_stage
    );

DROP TABLE foundation_node_merge;
