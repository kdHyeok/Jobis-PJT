-- SVG 기반 개발 경로에 QA·임베디드 트랙을 추가한다. 기존 10개 트랙은 그대로 유지하며
-- 공고 분석 계약이 새 트랙을 반환해도 저장 단계에서 거절되지 않게 한다.

ALTER TABLE posting_path_profiles
    DROP CONSTRAINT posting_path_profile_track_check,
    ADD CONSTRAINT posting_path_profile_track_check
        CHECK (
            primary_track IN (
                'BACKEND',
                'FRONTEND',
                'FULLSTACK',
                'DATA',
                'AI',
                'DEVOPS',
                'CLOUD',
                'SECURITY',
                'GAME',
                'MOBILE',
                'QA',
                'EMBEDDED'
            )
        );

ALTER TABLE posting_competency_requirements
    DROP CONSTRAINT posting_requirement_roadmap_domain_check,
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
                'QA',
                'EMBEDDED',
                'DOMAIN',
                'CAREER'
            )
        );
